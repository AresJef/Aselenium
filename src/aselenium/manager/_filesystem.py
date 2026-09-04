"""Private, cross-version filesystem boundaries for driver provisioning.

Archive contents are untrusted. No extractall(), archive-supplied ownership, or
archive-supplied special permission bits are used. Cross-process coordination is
deliberately separate from these validation and bounded-I/O helpers.
"""

from __future__ import annotations

import errno
import os
import stat
import unicodedata
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from time import sleep
from typing import (
    IO,
    TypeVar,
)

from aselenium import errors

T = TypeVar("T")

IO_ATTEMPTS = 3
MAX_MEMBERS = 50_000
MAX_MEMBER_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_PATH_DEPTH = 128
MAX_LINK_BYTES = 4096
COPY_CHUNK_BYTES = 1024 * 1024


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


def is_link(path: Path) -> bool:
    """Include Windows junctions/reparse points on Python versions before 3.12.

    Args:
        path: Filesystem path to inspect or operate on.

    Returns:
        True when the checked condition is satisfied; otherwise False.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def checked_path(root: Path, value: Path, *, allow_root: bool = False) -> Path:
    """Require a lexical descendant with no existing link/reparse ancestors.

    Args:
        root: Absolute ``Path`` anchoring the managed filesystem operation.
        value: Absolute ``Path`` expected to remain beneath ``root``.
        allow_root: Whether the anchored root itself is accepted as the checked path.

    Returns:
        The absolute path after containment and link/reparse checks succeed.
    """
    if not root.is_absolute() or not value.is_absolute():
        raise ValueError("Managed filesystem paths must be absolute")
    if ".." in root.parts or ".." in value.parts:
        raise ValueError("Parent traversal is not allowed: %s" % value)
    relative = value.relative_to(root)
    if not relative.parts and not allow_root:
        raise ValueError("The managed root itself is not an entry: %s" % root)
    current = root
    if is_link(current):
        raise ValueError("Managed root is a link/reparse point: %s" % current)
    for part in relative.parts:
        current = current / part
        if is_link(current):
            raise ValueError("Managed path contains a link/reparse point: %s" % current)
    # Also catch replacement of a parent of the anchored root with a link.
    if value.resolve(strict=False) != value:
        raise ValueError(
            "Managed path no longer resolves to its anchored location: %s" % value
        )
    return value


def member_path(name: str) -> PurePosixPath:
    """Normalize portable archive names; reject ambiguous Windows aliases too.

    Args:
        name: Name identifying the requested item.

    Returns:
        A normalized portable relative archive path.
    """
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("Invalid archive member name: %r" % name)
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or len(path.parts) > MAX_PATH_DEPTH:
        raise ValueError("Unsafe archive member path: %r" % name)
    for part in path.parts:
        stem = part.split(".", 1)[0].upper()
        if (
            ":" in part
            or part.endswith((" ", "."))
            or any(ord(char) < 32 for char in part)
            or stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
            or stem in {"COM" + c for c in "123456789¹²³"}
            or stem in {"LPT" + c for c in "123456789¹²³"}
        ):
            raise ValueError("Non-portable archive member path: %r" % name)
    return path


class ArchiveWriter:
    """Write into a new private extraction directory with finite expansion limits."""

    def __init__(self, root: Path) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            root: Absolute private extraction directory that does not yet exist.
        """
        self.root = root
        checked_path(self.root.parent.resolve(strict=True), self.root)
        self.root.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.names: list[str] = []
        self.kinds: dict[str, str] = {}
        self.parent_names: set[str] = set()
        self.count = 0
        self.total = 0
        self.links: list[tuple[Path, str, str]] = []

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
            name: Name identifying the requested item.
            kind: Operation or artifact kind selected by the caller.
            size: Declared member size in bytes.
            mode: Archive permission bits; unsafe write and special bits are discarded.
            source: Binary member stream, or None for entries without streamed file data.
            link: Relative link target when supplied by archive metadata.
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
        self.names.append(str(relative))
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
            if (
                not isinstance(link, str)
                or not link
                or len(link.encode("utf-8")) > MAX_LINK_BYTES
            ):
                raise ValueError("Invalid archive link target")
            if (
                "\\" in link
                or "\0" in link
                or ":" in link
                or PurePosixPath(link).is_absolute()
            ):
                raise ValueError("Unsafe archive link target: %r" % link)
            self.links.append((target, link, kind))
        else:
            raise ValueError("Archive special files are not permitted: %s" % name)

    def finish(self) -> list[str]:
        # Never extract data through a link. Create links only after all regular
        # files, and only to existing targets contained within this private tree.
        """Create deferred safe links and return the extracted member names.

        Returns:
            Names of the validated extracted members, after all deferred links are created.
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
                source = (origin / link).resolve(strict=False)
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
                    target.symlink_to(link, target_is_directory=source.is_dir())
            if len(deferred) == len(pending):
                raise ValueError("Archive contains dangling or cyclic links")
            pending = deferred
        raise ValueError("Archive link-depth limit exceeded")
