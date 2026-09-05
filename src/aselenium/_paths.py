"""Central filesystem-path parsing and validation for package internals.

Public entry points accept text and string-valued path-like objects. This module
normalizes those values at filesystem-workflow boundaries; downstream code
keeps :class:`pathlib.Path` objects. It deliberately does not call ``resolve()``
so symbolic-link names and ``..`` components retain the host operating system's
native traversal semantics.
"""

from __future__ import annotations

from collections.abc import Collection
from os import PathLike, fspath, scandir, stat_result
from pathlib import Path
from stat import S_ISDIR, S_ISLNK, S_ISREG
from typing import TypeAlias

from aselenium import errors

PathInput: TypeAlias = str | PathLike[str]


def _stat_is_link(info: stat_result) -> bool:
    """Classify a non-following status result as a link or reparse point.

    Args:
        info: Status returned by ``lstat()`` or by ``DirEntry.stat()`` with
            ``follow_symlinks=False``.

    Returns:
        ``True`` for a symbolic link, junction, or another Windows reparse
        point; otherwise ``False``.
    """
    return S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def is_link(path: Path) -> bool:
    """Return whether a retained path is a link or Windows reparse point.

    Args:
        path: Host-native path to inspect without following its final component.

    Returns:
        ``True`` for symbolic links, junctions, and other Windows reparse
        points; ``False`` for missing or ordinary entries.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return _stat_is_link(info)


def _regular_tree_files(
    root: Path, *, ignored_names: Collection[str] = ()
) -> list[Path]:
    """Collect regular files without following links or filesystem special entries.

    Args:
        root: Existing absolute directory retained by the calling workflow.
        ignored_names: Entry basenames to omit at every directory level.

    Returns:
        Regular files below ``root`` as retained host-native paths.

    Raises:
        ValueError: ``root`` is relative, is a link/reparse point, or contains
            a link/reparse point or non-regular filesystem entry.
        OSError: A directory entry cannot be inspected.
    """
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError("Filesystem tree root must be an absolute pathlib.Path")
    if is_link(root):
        raise ValueError("Filesystem tree root is a link/reparse point: %s" % root)
    pending = [root]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        if is_link(directory):
            raise ValueError(
                "Filesystem tree contains a link/reparse point: %s" % directory
            )
        with scandir(directory) as entries:
            for entry in entries:
                if entry.name in ignored_names:
                    continue
                path = directory / entry.name
                info = entry.stat(follow_symlinks=False)
                if _stat_is_link(info):
                    raise ValueError(
                        "Filesystem tree contains a link/reparse point: %s" % path
                    )
                if S_ISDIR(info.st_mode):
                    pending.append(path)
                elif S_ISREG(info.st_mode):
                    files.append(path)
                else:
                    raise ValueError(
                        "Filesystem tree contains a non-regular entry: %s" % path
                    )
    return files


def parse_path(path: PathInput) -> Path:
    """Convert one nonempty text path to an absolute, unresolved ``Path``.

    Args:
        path: Text path or string-valued path-like object. A leading user-home
            marker is expanded and relative paths are anchored to the current
            working directory.

    Returns:
        An absolute host-native ``Path``. Symbolic links and parent components
        are not resolved or lexically collapsed. An already absolute ``Path``
        is returned unchanged.

    Raises:
        errors.AseleniumInvalidPathError: The value is empty, byte-valued,
            contains a null character, is drive-relative, or cannot be converted
            to an unambiguous absolute path.

    Example:
        >>> parsed = parse_path("downloads/driver.zip")
        >>> parsed.is_absolute()
        True
    """
    try:
        if isinstance(path, Path):
            parsed = path
            if any("\x00" in part for part in parsed.parts):
                raise ValueError("Paths may not contain null characters")
            if parsed.is_absolute():
                return parsed
        else:
            value = fspath(path)
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError(
                    "Expected a nonempty text path without null characters"
                )
            parsed = Path(value)
        parsed = parsed.expanduser()
        if parsed.drive and not parsed.root:
            raise ValueError("Drive-relative paths are not unambiguously absolute")
        if not parsed.is_absolute():
            parsed = Path.cwd() / parsed
        return parsed
    except Exception as err:
        raise errors.AseleniumInvalidPathError(
            "Filesystem path {} {} is not valid.".format(repr(path), type(path))
        ) from err


def directory_path(path: PathInput) -> Path:
    """Validate an existing directory and return its parsed ``Path``.

    Args:
        path: Directory supplied as text or a string-valued path-like object.

    Returns:
        Absolute host-native path to the existing directory, without resolving
        symbolic links or collapsing parent components.

    Raises:
        errors.AseleniumInvalidPathError: The input cannot be parsed safely.
        errors.AseleniumDirectoryNotFoundError: The path is not an existing
            directory on the host filesystem.

    Example:
        >>> from pathlib import Path
        >>> directory_path(Path.cwd()) == Path.cwd()
        True
    """
    parsed = parse_path(path)
    if not parsed.is_dir():
        raise errors.AseleniumDirectoryNotFoundError(
            "Directory '{}' does not exist.".format(parsed)
        )
    return parsed


def file_path(path: PathInput) -> Path:
    """Validate an existing regular file and return its parsed ``Path``.

    Args:
        path: File supplied as text or a string-valued path-like object.

    Returns:
        Absolute host-native path to the existing regular file, without
        resolving symbolic links or collapsing parent components.

    Raises:
        errors.AseleniumInvalidPathError: The input cannot be parsed safely.
        errors.AseleniumFileNotFoundError: The path is not an existing regular
            file on the host filesystem.
    """
    parsed = parse_path(path)
    if not parsed.is_file():
        raise errors.AseleniumFileNotFoundError(
            "File '{}' does not exist.".format(parsed)
        )
    return parsed


def save_file_path(path: PathInput, file_ext: str) -> Path:
    """Validate an output destination and append its required suffix once.

    Args:
        path: Destination supplied as text or a string-valued path-like object.
        file_ext: Required case-sensitive filename suffix, such as ``.png``.

    Returns:
        Absolute host-native output path with ``file_ext`` appended when it was
        absent. Existing suffix case is preserved.

    Raises:
        errors.AseleniumInvalidPathError: The input cannot be parsed or the
            suffix is invalid, or the supplied or suffixed destination is an
            existing directory.
        errors.AseleniumDirectoryNotFoundError: The destination parent is not an
            existing directory.

    Example:
        >>> destination = save_file_path("capture", ".png")
        >>> destination.is_absolute() and destination.name == "capture.png"
        True
    """
    if not isinstance(file_ext, str) or not file_ext.startswith(".") or file_ext == ".":
        raise errors.AseleniumInvalidPathError(
            "Output filename suffix must start with '.' and contain a suffix"
        )
    parsed = parse_path(path)
    if parsed.is_dir():
        raise errors.AseleniumInvalidPathError(
            "Output path '{}' identifies a directory, not a file.".format(parsed)
        )
    if not parsed.parent.is_dir():
        raise errors.AseleniumDirectoryNotFoundError(
            "File directory '{}' does not exist.".format(parsed.parent)
        )
    if not parsed.name.endswith(file_ext):
        parsed = parsed.with_name(parsed.name + file_ext)
    if parsed.is_dir():
        raise errors.AseleniumInvalidPathError(
            "Output path '{}' identifies a directory, not a file.".format(parsed)
        )
    return parsed
