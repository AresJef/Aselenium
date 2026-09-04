"""Contracts for the package's single-conversion ``Path`` boundary."""

from __future__ import annotations

from os import PathLike
from os import name as os_name
from pathlib import Path
from typing import Any

import pytest

from aselenium import errors
from aselenium._paths import directory_path, file_path, parse_path, save_file_path


class CountingTextPath:
    """Expose path text while recording filesystem-protocol conversions."""

    def __init__(self, value: str) -> None:
        """Store one path value.

        Args:
            value: Text returned through the filesystem protocol.
        """
        self.value = value
        self.calls = 0

    def __fspath__(self) -> str:
        """Return the path text and record the boundary conversion.

        Returns:
            Configured path text.
        """
        self.calls += 1
        return self.value


class BytesPath:
    """Represent an unsupported byte-valued filesystem path."""

    def __fspath__(self) -> bytes:
        """Return byte-valued path data.

        Returns:
            Unsupported byte path used by the negative-control test.
        """
        return b"fixture"


def test_parse_path_converts_pathlike_once_and_preserves_parent_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anchor one path-like conversion without resolving its ``..`` component.

    Args:
        tmp_path: Isolated working directory used as the absolute anchor.
        monkeypatch: Fixture restoring the process working directory.
    """
    monkeypatch.chdir(tmp_path)
    supplied = CountingTextPath("folder/../target")

    parsed = parse_path(supplied)

    assert parsed == tmp_path / "folder" / ".." / "target"
    assert parsed.is_absolute() and ".." in parsed.parts
    assert supplied.calls == 1


@pytest.mark.parametrize(
    "invalid", [None, "", b"fixture", BytesPath(), Path("\x00"), object()]
)
def test_parse_path_rejects_nontext_or_empty_values(invalid: Any) -> None:
    """Map every malformed boundary value to the package path error.

    Args:
        invalid: Empty, byte-valued, or non-path input.
    """
    with pytest.raises(errors.AseleniumInvalidPathError):
        parse_path(invalid)


def test_parse_path_reuses_owned_absolute_path(tmp_path: Path) -> None:
    """Return an absolute ``Path`` unchanged for an established workflow.

    Args:
        tmp_path: Absolute fixture path representing an internally owned value.
    """
    assert parse_path(tmp_path) is tmp_path


@pytest.mark.skipif(os_name != "nt", reason="Windows drive-relative syntax")
def test_parse_path_rejects_ambiguous_drive_relative_input() -> None:
    """Reject a drive-qualified path that is relative to hidden drive state."""
    with pytest.raises(errors.AseleniumInvalidPathError):
        parse_path("C:relative\\driver.exe")


def test_core_validators_return_paths_without_reparsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep ``Path`` values throughout file, directory, and output validation.

    Args:
        tmp_path: Isolated directory containing all validation fixtures.
        monkeypatch: Fixture restoring the process working directory.
    """
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("fixture", encoding="utf-8")
    directory_input = CountingTextPath(".")
    file_input = CountingTextPath("source.txt")
    output_input = CountingTextPath("capture")

    directory = directory_path(directory_input)
    file = file_path(file_input)
    output = save_file_path(output_input, ".png")

    assert directory == tmp_path and isinstance(directory, Path)
    assert file == source and isinstance(file, Path)
    assert output == tmp_path / "capture.png" and isinstance(output, Path)
    assert directory_input.calls == file_input.calls == output_input.calls == 1


def test_save_file_path_rejects_directory_and_missing_parent(tmp_path: Path) -> None:
    """Reject destinations that cannot safely identify an output file.

    Args:
        tmp_path: Isolated directory containing invalid destinations.
    """
    with pytest.raises(errors.AseleniumInvalidPathError):
        save_file_path(tmp_path, ".png")
    with pytest.raises(errors.AseleniumDirectoryNotFoundError):
        save_file_path(tmp_path / "missing" / "capture", ".png")


def test_path_input_alias_accepts_standard_pathlike(tmp_path: Path) -> None:
    """Keep the boundary compatible with standard string path-like objects.

    Args:
        tmp_path: Existing directory supplied through the filesystem protocol.
    """
    supplied: PathLike[str] = tmp_path
    assert directory_path(supplied) == tmp_path
