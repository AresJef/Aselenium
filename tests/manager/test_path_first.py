"""Path-first contracts for cache and archive filesystem workflows."""

from __future__ import annotations

from io import BytesIO
from os import PathLike
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pytest

from aselenium import errors
from aselenium.manager.file import ChromeDriverFile, ChromeFileManager


class CountingPath(PathLike[str]):
    """Expose a text path-like value while counting boundary conversions."""

    def __init__(self, path: Path) -> None:
        """Store a path for later ``os.fspath`` conversion.

        Args:
            path: Filesystem path represented by this test value.
        """
        self.path = path
        self.calls = 0

    def __fspath__(self) -> str:
        """Return the represented text path and record one conversion.

        Returns:
            String form of the represented path.
        """
        self.calls += 1
        return str(self.path)


def driver_archive() -> ChromeDriverFile:
    """Build an in-memory ChromeDriver ZIP archive.

    Returns:
        Downloaded-file facade containing one inert driver executable.
    """
    stream = BytesIO()
    with ZipFile(stream, "w") as output:
        output.writestr("chromedriver", b"fixture-never-executed")
    return ChromeDriverFile(
        "linux", "https://example.invalid/chromedriver.zip", stream.getvalue()
    )


def test_cache_boundary_converts_pathlike_once_and_retains_paths(
    tmp_path: Path,
) -> None:
    """Keep ``Path`` values after the cache-parent boundary conversion.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    supplied = CountingPath(tmp_path)

    cache = ChromeFileManager(supplied)

    assert supplied.calls == 1
    assert cache._base_dir == tmp_path.resolve()
    assert isinstance(cache._base_dir, Path)
    assert isinstance(cache._directory, Path)
    assert isinstance(cache._database, Path)


def test_default_cache_boundary_uses_path_home(tmp_path: Path) -> None:
    """Anchor the default cache in the disposable platform home directory.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    cache = ChromeFileManager()

    assert cache._base_dir == tmp_path.resolve()


def test_default_cache_rejects_home_that_is_not_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a platform home value that names a regular file.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment changes.
    """
    home = tmp_path / "not-a-directory"
    home.touch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    with pytest.raises(errors.DriverManagerError, match="existing directory"):
        ChromeFileManager()


def test_default_cache_classifies_unresolvable_platform_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convert a platform home-discovery failure to the manager error contract.

    Args:
        monkeypatch: Pytest fixture replacing ``Path.home`` for this boundary.
    """

    def fail_home() -> Path:
        """Simulate a Windows service account without a discoverable home.

        Raises:
            RuntimeError: Always, matching ``Path.home`` failure semantics.
        """
        raise RuntimeError("synthetic unresolved home")

    monkeypatch.setattr(Path, "home", fail_home)

    with pytest.raises(errors.DriverManagerError, match="existing directory") as caught:
        ChromeFileManager()

    assert isinstance(caught.value.__cause__, RuntimeError)


def test_archive_boundary_converts_pathlike_once_and_returns_text(
    tmp_path: Path,
) -> None:
    """Parse a custom destination once while preserving the public text result.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    supplied = CountingPath(tmp_path / "published")

    result = driver_archive().unpack(supplied)

    assert supplied.calls == 1
    assert isinstance(result, str)
    assert Path(result).read_bytes() == b"fixture-never-executed"


def test_private_archive_helpers_exchange_paths(tmp_path: Path) -> None:
    """Keep private save and executable-selection results as ``Path`` objects.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    saved = driver_archive()._save_file(tmp_path / "download")
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    executable = extracted / "chromedriver.exe"
    executable.write_bytes(b"fixture-never-executed")
    selected = ChromeDriverFile(
        "win", "https://example.invalid/chromedriver.zip", b""
    )._find_target_executable(extracted, [PurePosixPath(executable.name)])

    assert isinstance(saved, Path)
    assert saved.is_file()
    assert selected == executable
    assert isinstance(selected, Path)


def test_archive_members_remain_parsed_between_private_stages(
    tmp_path: Path,
) -> None:
    """Retain each validated archive member as ``PurePosixPath`` internally.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    archive = driver_archive()
    saved = archive._save_file(tmp_path / "download")
    extracted = tmp_path / "extracted"

    members = archive._extract_zip_file(saved, extracted)
    selected = archive._find_target_executable(extracted, members)

    assert members == [PurePosixPath("chromedriver")]
    assert all(isinstance(member, PurePosixPath) for member in members)
    assert selected == extracted / "chromedriver"


def test_generated_archive_basename_uses_its_parsed_parts(tmp_path: Path) -> None:
    """Preserve a portable Unicode basename through the native ``Path`` join.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    archive = ChromeDriverFile(
        "linux", "https://example.invalid/chromedriver.zip", b"fixture"
    )
    archive._name = "driver package 驱动"

    saved = archive._save_file(tmp_path / "download")

    assert saved == tmp_path / "download" / "driver package 驱动.zip"
    assert saved.read_bytes() == b"fixture"
