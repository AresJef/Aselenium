"""Private, cross-version filesystem boundaries for driver provisioning.

Archive contents are untrusted. No extractall(), archive-supplied ownership, or
archive-supplied special permission bits are used. Cross-process coordination is
deliberately separate from these validation and bounded-I/O helpers.
"""

from __future__ import annotations

import errno
import os
import unicodedata
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from time import sleep
from typing import (
    IO,
    TypeVar,
)

from aselenium import errors
from aselenium._paths import _stat_is_link

T = TypeVar("T")

IO_ATTEMPTS = 3
PATH_CHECK_ATTEMPTS = 3
MAX_MEMBERS = 50_000
MAX_MEMBER_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_PATH_DEPTH = 128
MAX_LINK_BYTES = 4096
COPY_CHUNK_BYTES = 1024 * 1024
_WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *("COM" + suffix for suffix in "123456789¹²³"),
    *("LPT" + suffix for suffix in "123456789¹²³"),
}


def filesystem_operation(operation: Callable[[], T], description: str) -> T:
    """Retry only transient OS failures, with at most three total attempts.

    Args:
        operation: Operation performed by this helper; its result or failure is propagated.
        description: Human-readable operation context included in a classified failure.

    Returns:
        The value returned by the successful filesystem operation.
    """
    for attempt in range(IO_ATTEMPTS):
        try:
            return operation()
        except OSError as cause:
            transient = cause.errno in {
                errno.EINTR,
                errno.EAGAIN,
                errno.EBUSY,
                errno.ETXTBSY,
            } or getattr(cause, "winerror", None) in {32, 33}
            if not transient or attempt + 1 == IO_ATTEMPTS:
                raise errors.DriverManagerError(
                    "%s failed after %d attempt(s): %s"
                    % (description, attempt + 1, cause)
                ) from cause
            sleep(0.05 * (attempt + 1))
    raise AssertionError("Filesystem retry budget must contain at least one attempt")


def checked_path(root: Path, value: Path, *, allow_root: bool = False) -> Path:
    """Require a stable lexical descendant without link/reparse ancestors.

    Args:
        root: Absolute ``Path`` anchoring the managed filesystem operation.
        value: Absolute ``Path`` expected to remain beneath ``root``.
        allow_root: Whether the anchored root itself is accepted as the checked path.

    Returns:
        The absolute path after containment and link/reparse checks succeed.

    Raises:
        ValueError: Either path is relative, contains parent traversal, escapes
            the root, traverses a link/reparse point, or changes repeatedly
            while it is being validated.
    """
    if not root.is_absolute() or not value.is_absolute():
        raise ValueError("Managed filesystem paths must be absolute")
    if ".." in root.parts or ".." in value.parts:
        raise ValueError("Parent traversal is not allowed: %s" % value)
    relative = value.relative_to(root)
    if not relative.parts and not allow_root:
        raise ValueError("The managed root itself is not an entry: %s" % root)
    for _ in range(PATH_CHECK_ATTEMPTS):
        current = root
        deepest: Path | None = None
        missing: Path | None = None
        components = (None, *relative.parts)
        try:
            for part in components:
                if part is not None:
                    current = current / part
                try:
                    info = current.lstat()
                except FileNotFoundError:
                    missing = current
                    break
                if _stat_is_link(info):
                    subject = "root" if current == root else "path"
                    raise ValueError(
                        "Managed %s contains a link/reparse point: %s"
                        % (subject, current)
                    )
                deepest = current

            # The root is an existing, canonical anchor at every call site. If
            # it or an existing descendant vanishes while being checked, start
            # a new bounded pass rather than treating the race as redirection.
            if deepest is None:
                continue
            if deepest.resolve(strict=True) != deepest:
                # On Windows an ordinary file can disappear between the two
                # native calls used by Path.resolve(), leaving a transient
                # ``\\?\`` spelling. A fresh pass distinguishes that race from
                # a stable symlink or junction without normalizing path text.
                continue

            if missing is not None:
                try:
                    appeared = missing.lstat()
                except FileNotFoundError:
                    # The parent chain may have been replaced after the first
                    # resolution and before the absence check. Revalidate the
                    # persistent anchor at the last possible point before an
                    # absent volatile leaf is accepted.
                    if deepest.resolve(strict=True) != deepest:
                        continue
                    return value
                if _stat_is_link(appeared):
                    raise ValueError(
                        "Managed path contains a link/reparse point: %s" % missing
                    )
                # A formerly absent component appeared. Validate it and every
                # descendant together on the next pass.
                continue
            return value
        except FileNotFoundError:
            # ``deepest`` disappeared during strict resolution. This is normal
            # for SQLite sidecars shared by independent cache processes.
            continue
        except RuntimeError as cause:
            raise ValueError(
                "Managed path could not be resolved safely: %s" % value
            ) from cause
    raise ValueError("Managed path changed while it was validated: %s" % value)


def _validate_portable_part(part: str, source: str) -> None:
    """Reject a path component that is unsafe on supported host filesystems.

    Args:
        part: One non-navigation component from an archive path.
        source: Original archive value included in validation diagnostics.

    Raises:
        ValueError: The component is a Windows device alias, contains a stream
            separator or control character, or has an ambiguous trailing suffix.
    """
    stem = part.split(".", 1)[0].upper()
    if (
        ":" in part
        or part.endswith((" ", "."))
        or any(ord(char) < 32 for char in part)
        or stem in _WINDOWS_DEVICE_NAMES
    ):
        raise ValueError("Non-portable archive path: %r" % source)


def member_path(name: str) -> PurePosixPath:
    """Parse a portable, relative archive member name.

    Args:
        name: Raw POSIX member name from ZIP or TAR metadata.

    Returns:
        A normalized portable relative archive path.

    Raises:
        ValueError: The name is empty, absolute, traverses a parent, exceeds the
            depth limit, or is unsafe on a supported host filesystem.
    """
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("Invalid archive member name: %r" % name)
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or len(path.parts) > MAX_PATH_DEPTH:
        raise ValueError("Unsafe archive member path: %r" % name)
    for part in path.parts:
        _validate_portable_part(part, name)
    return path


def link_path(name: str, origin: PurePosixPath) -> PurePosixPath:
    """Parse a portable archive link target contained beneath its origin.

    Symbolic-link targets are relative to the link's parent member, while TAR
    hard-link targets are relative to the archive root. Callers express that
    distinction through ``origin``. Parent components are retained in the
    returned path because they are meaningful link metadata, but their lexical
    application may not escape the archive root.

    Args:
        name: Raw POSIX link target supplied by the archive.
        origin: Validated archive-relative directory from which the target is resolved.

    Returns:
        Validated relative link target as a ``PurePosixPath``.

    Raises:
        ValueError: The target is empty, absolute, too long or deep, non-portable,
            or its parent traversal escapes the archive root.
    """
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("Invalid archive link target: %r" % name)
    try:
        encoded_size = len(name.encode("utf-8"))
    except UnicodeEncodeError as cause:
        raise ValueError("Invalid archive link target: %r" % name) from cause
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or encoded_size > MAX_LINK_BYTES
        or len(path.parts) > MAX_PATH_DEPTH
    ):
        raise ValueError("Unsafe archive link target: %r" % name)

    destination = list(origin.parts)
    for part in path.parts:
        if part == "..":
            if not destination:
                raise ValueError("Archive link escapes extraction root: %r" % name)
            destination.pop()
            continue
        _validate_portable_part(part, name)
        destination.append(part)
    if len(destination) > MAX_PATH_DEPTH:
        raise ValueError("Archive link target depth limit exceeded: %r" % name)
    return path


class ArchiveWriter:
    """Write into a new private extraction directory with finite expansion limits."""

    def __init__(self, root: Path) -> None:
        """Create a new private extraction root for validated archive members.

        Args:
            root: Absolute private extraction directory that does not yet exist.

        Raises:
            ValueError: ``root`` is not a safe child of its existing parent.
            OSError: The private extraction directory cannot be created.
        """
        self.root = root
        checked_path(self.root.parent.resolve(strict=True), self.root)
        self.root.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.names: list[PurePosixPath] = []
        self.kinds: dict[str, str] = {}
        self.parent_names: set[str] = set()
        self.count = 0
        self.total = 0
        self.links: list[tuple[Path, PurePosixPath, str]] = []

    def add(
        self,
        name: str,
        kind: str,
        size: int,
        mode: int,
        source: IO[bytes] | None = None,
        link: str | None = None,
    ) -> None:
        """Validate and stage one archive member without extracting through links.

        Args:
            name: Raw POSIX member name from archive metadata.
            kind: Member type: ``file``, ``dir``, ``symlink``, or ``hardlink``.
            size: Declared member size in bytes.
            mode: Archive permission bits; unsafe write and special bits are discarded.
            source: Binary member stream, or None for entries without streamed file data.
            link: POSIX link target supplied by archive metadata. Symbolic-link
                targets are relative to the member's parent; hard-link targets
                are relative to the archive root.

        Raises:
            ValueError: The member metadata, expansion, path, type, or link target
                violates the extraction safety policy.
        """
        self.count += 1
        if self.count > MAX_MEMBERS:
            raise ValueError("Archive member-count limit exceeded")
        relative = member_path(name)
        if not relative.parts:
            if kind == "dir":
                return
            raise ValueError("An archive file cannot replace the extraction root")
        if size < 0 or size > MAX_MEMBER_BYTES or self.total + size > MAX_TOTAL_BYTES:
            raise ValueError("Archive expansion limit exceeded")
        self.total += size
        key = unicodedata.normalize("NFC", str(relative)).casefold()
        if key in self.kinds:
            raise ValueError("Duplicate or aliased archive member: %s" % name)
        for parent in relative.parents:
            if not parent.parts:
                continue
            parent_key = unicodedata.normalize("NFC", str(parent)).casefold()
            if self.kinds.get(parent_key, "dir") != "dir":
                raise ValueError(
                    "Archive member has a non-directory ancestor: %s" % name
                )
        if kind != "dir" and key in self.parent_names:
            raise ValueError(
                "Archive member would replace a parent directory: %s" % name
            )
        self.parent_names.update(
            unicodedata.normalize("NFC", str(parent)).casefold()
            for parent in relative.parents
            if parent.parts
        )
        self.kinds[key] = kind
        target = checked_path(self.root, self.root.joinpath(*relative.parts))
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.names.append(relative)
        if kind == "dir":
            target.mkdir(mode=0o700, exist_ok=True)
        elif kind == "file":
            if source is None:
                raise ValueError("Missing file data: %s" % name)
            remaining = size
            with target.open("xb") as output:
                while remaining:
                    chunk = source.read(min(COPY_CHUNK_BYTES, remaining))
                    if not chunk or len(chunk) > remaining:
                        raise ValueError("Invalid expanded file size: %s" % name)
                    output.write(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise ValueError("File exceeds declared expanded size: %s" % name)
            # Keep helper executables executable, but never preserve setuid,
            # setgid, sticky bits or group/world write permissions.
            target.chmod(0o600 | (mode & 0o111))
        elif kind in {"symlink", "hardlink"}:
            if source is not None:
                if size > MAX_LINK_BYTES:
                    raise ValueError("Archive link target is too long")
                link = source.read(MAX_LINK_BYTES + 1).decode("utf-8")
            if not isinstance(link, str):
                raise ValueError("Invalid archive link target")
            origin = relative.parent if kind == "symlink" else PurePosixPath()
            self.links.append((target, link_path(link, origin), kind))
        else:
            raise ValueError("Archive special files are not permitted: %s" % name)

    def finish(self) -> list[PurePosixPath]:
        # Never extract data through a link. Create links only after all regular
        # files, and only to existing targets contained within this private tree.
        """Create deferred safe links and return the extracted member names.

        Returns:
            Parsed names of the validated extracted members after all deferred
            links are created.
        """
        pending = self.links
        for _ in range(MAX_PATH_DEPTH):
            if not pending:
                # A later link can change how an earlier target containing '..'
                # resolves. Recheck the completed graph before publication.
                for target, _, _ in self.links:
                    resolved = target.resolve(strict=True)
                    resolved.relative_to(self.root)
                    if resolved == self.root or resolved in target.parents:
                        raise ValueError(
                            "Archive link resolves to an ancestor directory"
                        )
                return self.names
            deferred = []
            for target, link, kind in pending:
                origin = target.parent if kind == "symlink" else self.root
                source = origin.joinpath(*link.parts).resolve(strict=False)
                source.relative_to(self.root)
                if source == self.root or source in target.parents:
                    raise ValueError("Archive link points to an ancestor directory")
                if not source.exists():
                    deferred.append((target, link, kind))
                    continue
                if kind == "hardlink":
                    if not source.is_file():
                        raise ValueError("Hard links must refer to a regular file")
                    os.link(source, target)
                else:
                    # Convert the validated archive path to a native path only at
                    # the operating-system symlink boundary.
                    target.symlink_to(
                        Path(*link.parts), target_is_directory=source.is_dir()
                    )
            if len(deferred) == len(pending):
                raise ValueError("Archive contains dangling or cyclic links")
            pending = deferred
        raise ValueError("Archive link-depth limit exceeded")
