"""Transactional SQLite cache on a local filesystem.

SQLite owns the index; immutable artifact directories own the bytes. A publication
manifest permits recovery after rename but before the index transaction commits.
No SQLite transaction is held while extracting an archive.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import logging
import os
import platform
import shutil
import sqlite3
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from math import isfinite
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    TypedDict,
    TypeVar,
)

import psutil

from aselenium import errors
from aselenium._paths import PathInput, directory_path, parse_path
from aselenium.manager._filesystem import checked_path, filesystem_operation
from aselenium.manager.version import ChromiumVersion, GeckoVersion, Version

if TYPE_CHECKING:
    from aselenium.manager.file import File
F = TypeVar("F", bound="FileManager")


class CacheEntry(TypedDict):
    """Validated executable location and parsed version returned by cache lookups."""

    location: str
    version: Version


LOG = logging.getLogger(__name__)

# These modules are mutually exclusive OS backends, selected once at import time.
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


def _is_lock_contention(cause: OSError) -> bool:
    """Return whether an OS lock failure represents temporary contention.

    Args:
        cause: Failure raised by the platform's nonblocking file-lock API.

    Returns:
        True for POSIX and Windows lock-contention error codes.
    """
    return (
        isinstance(cause, (BlockingIOError, PermissionError))
        or cause.errno
        in {
            errno.EACCES,
            errno.EAGAIN,
            errno.EBUSY,
            errno.EDEADLK,
        }
        or getattr(cause, "winerror", None) in {32, 33}
    )


@contextmanager
def artifact_lock(root: Path, key: str, timeout: float = 30) -> Iterator[None]:
    """Kernel-released process lock; never unlink a lock another waiter opened.

    Args:
        root: Absolute, validated cache directory retained by the file manager.
        key: Lookup key used by the current operation.
        timeout: Finite nonnegative wait budget in seconds. Zero attempts the lock once.

    Yields:
        None while this process holds the exclusive artifact lock.

    Raises:
        errors.DriverManagerError: The key, managed path, or timeout is invalid,
            or contention lasts beyond the wait budget.
    """
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not isfinite(timeout)
        or timeout < 0
    ):
        raise errors.DriverManagerError(
            "Artifact lock timeout must be finite and nonnegative"
        )
    try:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid artifact key")
        path = checked_path(root, root / (key + ".lock"))
    except ValueError as cause:
        raise errors.DriverManagerError("Unsafe artifact lock path") from cause
    handle = filesystem_operation(lambda: path.open("a+b"), "Open cache artifact lock")
    with handle:
        # ``msvcrt.locking`` coordinates a byte range rather than the whole
        # file. Materialize byte zero before asking the Windows CRT to lock it,
        # and explicitly seek before every acquisition attempt below.
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as cause:
                if not _is_lock_contention(cause):
                    raise errors.DriverManagerError(
                        "Unable to acquire cache artifact lock"
                    ) from cause
                if time.monotonic() >= deadline:
                    raise errors.DriverManagerError(
                        "Timed out acquiring cache artifact lock"
                    ) from cause
                time.sleep(0.05)
        body_error: BaseException | None = None
        try:
            yield
        except BaseException as cause:
            body_error = cause
            raise
        finally:
            try:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError as cause:
                message = "Unable to release cache artifact lock"
                if body_error is not None:
                    LOG.error(
                        "%s while propagating %s",
                        message,
                        type(body_error).__name__,
                        exc_info=True,
                    )
                else:
                    raise errors.DriverManagerError(message) from cause


def digest(path: Path) -> str:
    """Calculate the SHA-256 of a file using bounded-size reads.

    Args:
        path: Absolute, validated file whose contents are hashed.

    Returns:
        Lowercase hexadecimal SHA-256 digest of the file contents.

    Example:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as temporary:
        ...     executable = Path(temporary) / "chromedriver"
        ...     _ = executable.write_bytes(b"driver")
        ...     checksum = digest(executable)
        >>> len(checksum)
        64
    """
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


class FileManager:
    """Maintain a transactional, integrity-checked cache on a local filesystem."""

    product = "generic"
    version_class: type[Version] = ChromiumVersion

    def __init__(self, base_dir: PathInput | None = None) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            base_dir: Existing cache parent directory; None selects the current user home.
        """
        try:
            base = (
                directory_path(Path.home()).resolve(strict=True)
                if base_dir is None
                else directory_path(base_dir).resolve(strict=True)
            )
        except (
            errors.AseleniumDirectoryNotFoundError,
            errors.AseleniumInvalidPathError,
            OSError,
            RuntimeError,
        ) as cause:
            raise errors.DriverManagerError(
                "Cache base must be an existing directory"
            ) from cause
        self._base_dir: Path = base
        try:
            cache_root = checked_path(base, base / ".aselenium")
        except ValueError as cause:
            raise errors.DriverManagerError("Unsafe cache root") from cause
        cache_root.mkdir(mode=0o700, exist_ok=True)
        self._directory: Path = checked_path(cache_root, cache_root / "v2")
        self._directory.mkdir(mode=0o700, exist_ok=True)
        self.platform = (
            {"Darwin": "mac", "Windows": "win"}.get(platform.system(), "linux"),
            platform.machine().lower(),
        )
        self._database: Path = self._managed_path(self._directory / "index.sqlite3")
        schema_key = hashlib.sha256(b"aselenium-v2-schema").hexdigest()
        with artifact_lock(self._directory, schema_key), self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            schema = db.execute("PRAGMA user_version").fetchone()[0]
            if schema not in (0, 2):
                raise errors.DriverManagerError(
                    "Unsupported cache schema; existing database preserved"
                )
            db.execute(
                "CREATE TABLE IF NOT EXISTS artifacts (key TEXT PRIMARY KEY, product TEXT NOT NULL, platform TEXT NOT NULL, kind TEXT NOT NULL, version TEXT NOT NULL, executable TEXT NOT NULL, sha256 TEXT NOT NULL, created REAL NOT NULL, pinned INTEGER NOT NULL DEFAULT 0)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS artifact_lookup ON artifacts(product,platform,kind,version)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS leases (token TEXT PRIMARY KEY, key TEXT NOT NULL, pid INTEGER NOT NULL, process_started REAL NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS lease_artifact_lookup ON leases(key)"
            )
            db.execute("PRAGMA user_version=2")

    def for_platform(self: F, os_name: str, architecture: str, arm: bool = False) -> F:
        """Return a shallow cache view scoped to the requested platform.

        Args:
            os_name: Operating-system identifier used by the driver vendor.
            architecture: Architecture width used to scope the cache view.
            arm: Whether the target architecture belongs to the ARM family.

        Returns:
            A shallow cache view scoped to the requested platform.
        """
        view = copy.copy(self)
        view.platform = (os_name, ("arm" if arm else "x") + str(architecture))
        return view

    @property
    def _platform(self) -> str:
        """Return the product-independent platform key used by the SQLite index.

        Returns:
            The product-independent platform key used by the sqlite index.
        """
        return ":".join(self.platform)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """Open a checked SQLite connection and commit or roll back its transaction.

        Yields:
            The resource managed by this context; cleanup runs when the context exits.
        """
        db = None
        try:
            self._managed_path(self._database)
            for suffix in ("-journal", "-wal", "-shm"):
                self._managed_path(
                    self._database.with_name(self._database.name + suffix)
                )
            db = sqlite3.connect(self._database, timeout=5)
            db.row_factory = sqlite3.Row
            with db:
                yield db
        except sqlite3.Error as cause:
            raise errors.DriverManagerError(
                "Cache database unavailable; database and artifacts preserved"
            ) from cause
        finally:
            if db is not None:
                db.close()

    def _managed_path(self, path: Path) -> Path:
        """Validate a cache-owned path without following link or reparse ancestors.

        Args:
            path: Absolute path already derived from this manager's cache root.

        Returns:
            An absolute, validated path under the anchored cache root.
        """
        try:
            return checked_path(self._directory, path)
        except (OSError, ValueError) as cause:
            raise errors.DriverManagerError("Unsafe cache path") from cause

    def _delete_folder(self, folder: Path) -> None:
        """Delete one validated cache artifact directory with bounded retries.

        Args:
            folder: Absolute artifact directory already derived from the cache root.
        """
        path = self._managed_path(folder)
        if path.exists():
            filesystem_operation(
                lambda: shutil.rmtree(self._managed_path(path)), "Remove cache artifact"
            )

    def _key(self, kind: str, version: Version | str) -> str:
        """Hash the product, platform, artifact kind, and version into a cache key.

        Args:
            kind: Operation or artifact kind selected by the caller.
            version: Version object or version selector for this operation.

        Returns:
            The lowercase SHA-256 key of the artifact identity.
        """
        return hashlib.sha256(
            json.dumps([self.product, self._platform, kind, str(version)]).encode()
        ).hexdigest()

    def cached_versions(self, artifact: str = "driver") -> list[str]:
        """List indexed versions for this product, platform, and artifact kind.

        Args:
            artifact: Artifact kind: driver or binary.

        Returns:
            Indexed version strings for the selected product, platform, and artifact kind.
        """
        with self._db() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT version FROM artifacts WHERE product=? AND platform=? AND kind=?",
                    (self.product, self._platform, artifact),
                )
            ]

    def _valid(self, row: Mapping[str, Any] | sqlite3.Row) -> bool:
        """Verify an indexed artifact identity, executable path, and SHA-256.

        Args:
            row: Artifact metadata from the index or its recovery manifest.

        Returns:
            True when the checked condition is satisfied; otherwise False.
        """
        expected = hashlib.sha256(
            json.dumps(
                [row["product"], row["platform"], row["kind"], row["version"]]
            ).encode()
        ).hexdigest()
        if row["key"] != expected:
            raise errors.DriverManagerError("Invalid cache artifact identity")
        folder = self._managed_path(self._directory / row["key"])
        try:
            path = checked_path(folder, folder / row["executable"])
        except ValueError as cause:
            raise errors.DriverManagerError("Unsafe cache executable path") from cause
        return path.is_file() and digest(path) == row["sha256"]

    def _result(self, row: Mapping[str, Any] | sqlite3.Row) -> CacheEntry:
        """Convert a validated cache row to its executable location and parsed version.

        Args:
            row: Artifact metadata from the index or its recovery manifest.

        Returns:
            A cache entry with an executable location and parsed Version.
        """
        return {
            "location": str(self._directory / row["key"] / row["executable"]),
            "version": self.version_class(row["version"]),
        }

    def _match(
        self, kind: str, version: Version | str, match_method: str
    ) -> CacheEntry | None:
        """Find the newest integrity-checked artifact matching the requested version prefix.

        Args:
            kind: Operation or artifact kind selected by the caller.
            version: Version object or version selector for this operation.
            match_method: Version match granularity: major, build, or patch.

        Returns:
            Validated executable location and version, or None when no entry matches.
        """
        if match_method not in {"major", "build", "patch"}:
            raise ValueError("Unknown version matching method")
        parts = str(version).split(".")
        count = (
            1
            if match_method == "major"
            else min(len(parts), 2 if self.version_class is GeckoVersion else 3)
            if match_method == "build"
            else len(parts)
        )
        full = 3 if self.version_class is GeckoVersion else 4
        exact = count == full
        with self._db() as db:
            query = "SELECT * FROM artifacts WHERE product=? AND platform=? AND kind=?"
            params: tuple[str, ...] = (self.product, self._platform, kind)
            if exact:
                query += " AND version=?"
                params += (str(version),)
            else:
                query += " AND (version=? OR version LIKE ?)"
                prefix = ".".join(parts[:count])
                params += (prefix, prefix + ".%")
            rows = db.execute(query, params).fetchall()
        if not rows and exact:
            row = self._recover_key(self._key(kind, version))
            if row is not None:
                return self._result(row)
        for row in sorted(
            rows, key=lambda r: tuple(map(int, r["version"].split("."))), reverse=True
        ):
            if row["version"].split(".")[:count] != parts[:count]:
                continue
            with artifact_lock(self._directory, row["key"]):
                if self._valid(row):
                    return self._result(row)
        return None

    def _recover_key(self, key: str) -> dict[str, Any] | None:
        """Reindex a validated orphan publication for one artifact key.

        Args:
            key: Lookup key used by the current operation.

        Returns:
            Recovered artifact metadata, or None if no valid publication can be recovered.
        """
        folder = self._managed_path(self._directory / key)
        if not folder.is_dir():
            return None
        with artifact_lock(self._directory, key):
            try:
                marker = self._managed_path(folder / "artifact.json")
                row = json.loads(marker.read_text())
                if (
                    row["key"] != key
                    or row["product"] != self.product
                    or row["platform"] != self._platform
                ):
                    return None
                if self._valid(row):
                    self._publish(row)
                    return row
            except (OSError, ValueError, KeyError, TypeError):
                return None
        return None

    def recover(self) -> int:
        """Explicitly reindex validated orphan publications for this platform.

        Returns:
            Number of validated orphan publications reindexed.
        """
        count = 0
        for folder in self._directory.iterdir():
            if len(folder.name) == 64 and all(
                c in "0123456789abcdef" for c in folder.name
            ):
                count += self._recover_key(folder.name) is not None
        return count

    def clean_staging(self) -> int:
        """Remove only marked extraction staging owned by a dead process.

        Unknown or malformed directories are left for manual inspection.

        Returns:
            Number of marked, abandoned staging directories removed.
        """
        count = 0
        for folder in self._directory.glob(".aselenium-stage-*"):
            try:
                folder = self._managed_path(folder)
                marker = self._managed_path(folder / "ownership.json")
                owner = json.loads(marker.read_text())
                try:
                    alive = (
                        psutil.Process(owner["pid"]).create_time() == owner["started"]
                    )
                except psutil.NoSuchProcess:
                    alive = False
                except psutil.AccessDenied:
                    alive = True
                if alive:
                    continue
                with artifact_lock(self._directory, owner["key"]):
                    self._delete_folder(folder)
                    count += 1
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                errors.DriverManagerError,
            ):
                LOG.warning("Unverified staging directory preserved")
        return count

    def match_driver(
        self, version: Version | str, match_method: str = "patch"
    ) -> CacheEntry | None:
        """Find an integrity-checked cached driver for the requested version.

        Args:
            version: Version object or version selector for this operation.
            match_method: Version match granularity: major, build, or patch.

        Returns:
            Validated driver location and version, or None when no entry matches.
        """
        return self._match("driver", version, match_method)

    def match_binary(
        self, version: Version | str, match_method: str = "patch"
    ) -> CacheEntry | None:
        """Find an integrity-checked cached browser binary for the requested version.

        Args:
            version: Version object or version selector for this operation.
            match_method: Version match granularity: major, build, or patch.

        Returns:
            Validated browser location and version, or None when no entry matches.
        """
        return self._match("binary", version, match_method)

    @staticmethod
    def _validate_cache_limit(limit: int | None) -> None:
        """Reject cache limits other than a positive integer or None.

        Args:
            limit: Maximum retained artifact count; None leaves retention unbounded.
        """
        if limit is not None and (type(limit) is not int or limit < 1):
            raise errors.DriverManagerError(
                "max_cache_size must be a positive integer or None"
            )

    def _publish(self, row: Mapping[str, Any]) -> None:
        """Insert an artifact manifest into the SQLite index without replacing existing rows.

        Args:
            row: Artifact metadata from the index or its recovery manifest.
        """
        with self._db() as db:
            db.execute(
                "INSERT OR IGNORE INTO artifacts (key, product, platform, kind, version, executable, sha256, created) VALUES (:key,:product,:platform,:kind,:version,:executable,:sha256,:created)",
                row,
            )

    def _cache(
        self, kind: str, version: Version | str, archive: File, limit: int | None
    ) -> CacheEntry:
        """Validate or atomically publish an artifact, then apply scoped cache retention.

        Args:
            kind: Operation or artifact kind selected by the caller.
            version: Version object or version selector for this operation.
            archive: Downloaded archive whose contents will be validated before publication.
            limit: Maximum retained artifact count; None leaves retention unbounded.

        Returns:
            The published or reused artifact's executable location and parsed version.
        """
        self._validate_cache_limit(limit)
        key = self._key(kind, version)
        folder = self._managed_path(self._directory / key)
        with artifact_lock(self._directory, key):
            if folder.exists():
                marker = self._managed_path(folder / "artifact.json")
                try:
                    row = json.loads(marker.read_text())
                    expected = (key, self.product, self._platform, kind, str(version))
                    if tuple(
                        row[k]
                        for k in ("key", "product", "platform", "kind", "version")
                    ) != expected or not self._valid(row):
                        raise ValueError("Artifact identity or checksum mismatch")
                except (OSError, ValueError, KeyError, TypeError) as cause:
                    raise errors.DriverManagerError(
                        "Invalid existing artifact preserved; move it aside before retrying"
                    ) from cause
            else:
                row = dict(
                    key=key,
                    product=self.product,
                    platform=self._platform,
                    kind=kind,
                    version=str(version),
                    created=time.time(),
                )

                def before_publish(staging: Path, executable: Path) -> None:
                    """Write and flush the recovery manifest before the artifact directory is published.

                    Args:
                        staging: Private staging directory that has not yet been published.
                        executable: Validated executable path inside the staging directory.
                    """
                    row.update(
                        executable=str(executable.relative_to(staging)),
                        sha256=digest(executable),
                    )
                    with (staging / "artifact.json").open("x") as stream:
                        json.dump(row, stream)
                        stream.flush()
                        os.fsync(stream.fileno())

                archive.unpack(folder, _before_publish=before_publish, _owner_key=key)
            self._publish(row)
        self.prune(kind, limit, keep=key)
        return self._result(row)

    def cache_driver(
        self, version: Version | str, driver: File, max_cache_size: int | None = None
    ) -> CacheEntry:
        """Publish a downloaded driver archive and return its validated cache entry.

        Args:
            version: Version object or version selector for this operation.
            driver: Driver object or downloaded driver artifact required by this operation.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.

        Returns:
            Validated driver location and parsed version.
        """
        return self._cache("driver", version, driver, max_cache_size)

    def cache_binary(
        self, version: Version | str, binary: File, max_cache_size: int | None = None
    ) -> CacheEntry:
        """Publish a downloaded browser archive and return its validated cache entry.

        Args:
            version: Version object or version selector for this operation.
            binary: Browser executable or downloaded browser artifact required by this operation.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.

        Returns:
            Validated browser location and parsed version.
        """
        return self._cache("binary", version, binary, max_cache_size)

    def pin(
        self, version: Version | str, kind: str = "driver", pinned: bool = True
    ) -> None:
        """Set or clear eviction protection for an indexed artifact.

        Args:
            version: Version object or version selector for this operation.
            kind: Operation or artifact kind selected by the caller.
            pinned: Whether the indexed artifact is protected from automatic eviction.
        """
        key = self._key(kind, version)
        with artifact_lock(self._directory, key), self._db() as db:
            db.execute("UPDATE artifacts SET pinned=? WHERE key=?", (int(pinned), key))

    def lease(self, location: PathInput) -> str | None:
        """Protect an indexed artifact while its owning process/session is alive.

        Args:
            location: Executable path whose indexed artifact should be leased.

        Returns:
            A lease token, or None if the location is outside this cache.
        """
        path = parse_path(location)
        try:
            relative = path.relative_to(self._directory)
        except ValueError:
            return None
        if not relative.parts or ".." in relative.parts:
            return None
        key = relative.parts[0]
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            return None
        with artifact_lock(self._directory, key), self._db() as db:
            row = db.execute("SELECT * FROM artifacts WHERE key=?", (key,)).fetchone()
            if row is None or not self._valid(row):
                raise errors.DriverManagerError(
                    "Cached artifact disappeared before acquisition; retry installation"
                )
            token = uuid.uuid4().hex
            db.execute(
                "INSERT INTO leases VALUES (?,?,?,?)",
                (token, key, os.getpid(), psutil.Process().create_time()),
            )
            return token

    def release(self, token: str) -> None:
        """Remove a cache lease after the owning session has finished teardown.

        Args:
            token: Lease token returned by the corresponding acquisition.
        """
        with self._db() as db:
            db.execute("DELETE FROM leases WHERE token=?", (token,))

    def prune(
        self, kind: str = "driver", limit: int | None = None, keep: str | None = None
    ) -> None:
        """Evict eligible old artifacts while preserving pins, leases, and the keep key.

        Args:
            kind: Operation or artifact kind selected by the caller.
            limit: Maximum retained artifact count; None leaves retention unbounded.
            keep: Artifact key that this pruning operation must preserve, or None.
        """
        self._validate_cache_limit(limit)
        if limit is None:
            return
        key = hashlib.sha256(
            json.dumps(["prune", self.product, self._platform, kind]).encode()
        ).hexdigest()
        with artifact_lock(self._directory, key):
            self._prune_locked(kind, limit, keep)

    def _prune_locked(self, kind: str, limit: int, keep: str | None) -> None:
        """Apply the retention limit while the caller owns the product pruning lock.

        Args:
            kind: Operation or artifact kind selected by the caller.
            limit: Maximum retained artifact count; None leaves retention unbounded.
            keep: Artifact key that this pruning operation must preserve, or None.
        """
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM artifacts WHERE product=? AND platform=? AND kind=? ORDER BY created DESC",
                (self.product, self._platform, kind),
            ).fetchall()
        # A stale caller's keep key may already be absent. Never count an
        # absent artifact against the retention budget and evict everything.
        retained = int(any(row["key"] == keep for row in rows))
        for row in rows:
            if row["key"] == keep:
                continue
            if retained < limit or row["pinned"]:
                retained += 1
                continue
            try:
                with artifact_lock(self._directory, row["key"]), self._db() as db:
                    current = db.execute(
                        "SELECT pinned FROM artifacts WHERE key=?", (row["key"],)
                    ).fetchone()
                    if current is None or current["pinned"]:
                        continue
                    active = False
                    for lease in db.execute(
                        "SELECT * FROM leases WHERE key=?", (row["key"],)
                    ).fetchall():
                        try:
                            alive = (
                                psutil.Process(lease["pid"]).create_time()
                                == lease["process_started"]
                            )
                        except psutil.NoSuchProcess:
                            alive = False
                        except psutil.AccessDenied:
                            alive = True
                        if alive:
                            active = True
                        else:
                            db.execute(
                                "DELETE FROM leases WHERE token=?", (lease["token"],)
                            )
                    if active:
                        continue
                    self._delete_folder(self._directory / row["key"])
                    db.execute("DELETE FROM artifacts WHERE key=?", (row["key"],))
            except (errors.DriverManagerError, OSError):
                LOG.warning("Cache eviction deferred", exc_info=False)


class ChromiumBaseFileManager(FileManager):
    """Share Chromium cache behavior with product-specific subclasses."""

    pass


class ChromeFileManager(ChromiumBaseFileManager):
    """Scope the SQLite artifact cache to Chrome drivers and browser binaries."""

    product = "chrome"


class EdgeFileManager(ChromiumBaseFileManager):
    """Scope the SQLite artifact cache to Microsoft Edge."""

    product = "edge"


class FirefoxFileManager(FileManager):
    """Scope the SQLite artifact cache to GeckoDriver versions."""

    product = "firefox"
    version_class = GeckoVersion
