"""Contracts for the package's single-conversion ``Path`` boundary."""

from __future__ import annotations

from os import PathLike
from os import name as os_name
from pathlib import Path
from typing import Any

import pytest

from aselenium import Firefox, errors
from aselenium._paths import directory_path, file_path, parse_path, save_file_path
from aselenium.firefox.service import FirefoxService
from aselenium.manager.version import GeckoVersion


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


def test_firefox_profile_root_is_parsed_once_and_retained_as_path(
    tmp_path: Path,
) -> None:
    """Keep the Firefox profile root as a Path until command serialization.

    Args:
        tmp_path: Existing profile root and inert GeckoDriver executable parent.
    """
    executable = tmp_path / "geckodriver"
    executable.touch()
    profile_root = tmp_path / "shared-profiles"
    profile_root.mkdir()
    supplied = CountingTextPath(str(profile_root))

    service = FirefoxService(GeckoVersion("0.32.0"), executable, profile_root=supplied)
    service._port = 41001
    service._port_str = "41001"
    service._cdp_port = 41002
    service._cdp_port_str = "41002"

    assert supplied.calls == 1
    assert service._profile_root == profile_root
    assert isinstance(service._profile_root, Path)
    assert service.port_args == [
        "--port=41001",
        "--websocket-port",
        "41002",
        "--profile-root",
        str(profile_root),
    ]
    assert supplied.calls == 1


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_firefox_profile_root_requires_an_existing_directory(
    tmp_path: Path, kind: str
) -> None:
    """Reject profile roots that GeckoDriver cannot use as directory parents.

    Args:
        tmp_path: Parent for the valid executable and invalid profile-root input.
        kind: Whether the rejected input is absent or a regular file.
    """
    executable = tmp_path / "geckodriver"
    executable.touch()
    profile_root = tmp_path / kind
    if kind == "file":
        profile_root.touch()

    with pytest.raises(errors.AseleniumDirectoryNotFoundError):
        FirefoxService(GeckoVersion("0.37.1"), executable, profile_root=profile_root)


@pytest.mark.parametrize(
    "manual",
    [
        ("--profile-root", "manual-root"),
        ("--profile-root=manual-root",),
        (Path("--profile-root"), Path("manual-root")),
        (Path("--profile-root=manual-root"),),
        (b"--profile-root", b"manual-root"),
        (b"--profile-root=manual-root",),
    ],
)
def test_firefox_profile_root_rejects_ambiguous_manual_flag(
    tmp_path: Path, manual: tuple[object, ...]
) -> None:
    """Reject two competing ways to configure GeckoDriver's profile root.

    Args:
        tmp_path: Parent for the valid executable and profile-root directory.
        manual: Raw GeckoDriver spelling that conflicts with the typed option.
    """
    executable = tmp_path / "geckodriver"
    executable.touch()

    with pytest.raises(errors.InvalidArgumentError, match="cannot be combined"):
        FirefoxService(
            GeckoVersion("0.37.1"),
            executable,
            10,
            *manual,
            profile_root=tmp_path,
        )


@pytest.mark.parametrize("version", ["0.30.0", "0.31.0"])
def test_firefox_profile_root_rejects_unsupported_geckodriver(
    tmp_path: Path, version: str
) -> None:
    """Fail before launch when GeckoDriver predates its profile-root flag.

    Args:
        tmp_path: Parent for the valid executable and profile-root directory.
        version: Unsupported legacy GeckoDriver version without ``--profile-root``.
    """
    executable = tmp_path / "geckodriver"
    executable.touch()

    with pytest.raises(errors.InvalidArgumentError, match="0.32.0 or newer"):
        FirefoxService(GeckoVersion(version), executable, profile_root=tmp_path)


def test_firefox_facade_defers_profile_root_parsing_to_service(
    tmp_path: Path,
) -> None:
    """Preserve flexible path-like input until the Firefox service boundary.

    Args:
        tmp_path: Dedicated cache parent and existing profile-root directory.
    """
    profile_root = tmp_path / "shared-profiles"
    profile_root.mkdir()
    supplied = CountingTextPath(str(profile_root))
    driver = Firefox(directory=tmp_path, profile_root=supplied)
    try:
        context = driver.acquire()
        assert supplied.calls == 0
        assert driver._service_kwargs["profile_root"] is supplied
        assert context._service_kwargs["profile_root"] is supplied
    finally:
        driver.options.close()
