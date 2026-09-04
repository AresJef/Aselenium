"""Central filesystem-path parsing and validation for package internals.

Public entry points may accept text or string-valued path-like objects.  This
module converts that input exactly once and keeps :class:`pathlib.Path` values
through the rest of each filesystem workflow.  It deliberately does not call
``resolve()`` so symbolic-link names and ``..`` components retain the host
operating system's native traversal semantics.
"""

from __future__ import annotations

from os import PathLike, fspath
from pathlib import Path
from typing import TypeAlias

from aselenium import errors

PathInput: TypeAlias = str | PathLike[str]


def parse_path(path: PathInput) -> Path:
    """Convert one nonempty text path to an absolute, un-resolved ``Path``.

    Args:
        path: Text path or string-valued path-like object. A leading user-home
            marker is expanded and relative paths are anchored to the current
            working directory.

    Returns:
        An absolute ``Path``. Symbolic links and parent components are not
        resolved or lexically collapsed.

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
        Absolute path to the existing directory.

    Raises:
        errors.AseleniumInvalidPathError: The input cannot be parsed safely.
        errors.AseleniumDirectoryNotFoundError: The path is not an existing
            directory on the host filesystem.
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
        Absolute path to the existing regular file.

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
        Absolute output path with ``file_ext`` appended when it was absent.

    Raises:
        errors.AseleniumInvalidPathError: The input cannot be parsed or the
            supplied or suffixed destination is an existing directory.
        errors.AseleniumDirectoryNotFoundError: The destination parent is not an
            existing directory.

    Example:
        >>> destination = save_file_path("capture", ".png")
        >>> destination.is_absolute() and destination.name == "capture.png"
        True
    """
    parsed = parse_path(path)
    if parsed.is_dir():
        raise errors.AseleniumInvalidPathError(
            "Output path '{}' identifies a directory, not a file.".format(parsed)
        )
    if not parsed.parent.is_dir():
        raise errors.AseleniumDirectoryNotFoundError(
            "File directory '{}' does not exist.".format(parsed)
        )
    if not parsed.name.endswith(file_ext):
        parsed = parsed.with_name(parsed.name + file_ext)
    if parsed.is_dir():
        raise errors.AseleniumInvalidPathError(
            "Output path '{}' identifies a directory, not a file.".format(parsed)
        )
    return parsed
