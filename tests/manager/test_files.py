"""Offline coverage of actual cache metadata and synthetic archive handling."""

from __future__ import annotations

import os
import sqlite3
import stat
import tarfile
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile, ZipInfo

import pytest

from aselenium import errors
from aselenium.manager import file as files
from aselenium.manager.version import ChromiumVersion, GeckoVersion

PAYLOAD = b"synthetic driver bytes; never execute"
RETRY_LIMIT = 3


class RetryBudgetExhausted(BaseException):
    """Escape production retry loops even when running pytest --runxfail."""


def zip_bytes(members: Any) -> Any:
    """Zip bytes.

    Args:
        members: Fixture or parametrized members input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            member = ZipInfo(name)
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(member, content)
    return buffer.getvalue()


def tar_bytes(members: Any, mode: str = "w:gz") -> Any:
    """Tar bytes.

    Args:
        members: Fixture or parametrized members input for this regression.
        mode: Fixture or parametrized mode input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for name, content in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            archive.addfile(member, BytesIO(content))
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def fake_archive_chmod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Record direct permission changes, confined to disposable test paths.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    calls = []
    original = files.chmod

    def chmod_without_subprocess(path: Any, mode: Any) -> None:
        """Chmod without subprocess.

        Args:
            path: Fixture or parametrized path input for this regression.
            mode: Fixture or parametrized mode input for this regression.
        """
        target = Path(path).resolve()
        target.relative_to(tmp_path.resolve())
        original(path, mode)
        calls.append(target)

    monkeypatch.setattr(files, "chmod", chmod_without_subprocess)
    return calls


@pytest.mark.parametrize(
    ("os_name", "executable"),
    [("win", "chromedriver.exe"), ("linux", "chromedriver"), ("mac", "chromedriver")],
)
def test_zip_unpack_finds_nested_driver(
    tmp_path: Path, fake_archive_chmod: Any, os_name: Any, executable: Any
) -> None:
    """Verify zip unpack finds nested driver.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_archive_chmod: Fixture or parametrized fake archive chmod input for this regression.
        os_name: Fixture or parametrized os name input for this regression.
        executable: Fixture or parametrized executable input for this regression.
    """
    archive = files.ChromeDriverFile(
        os_name,
        "https://downloads.invalid/chromedriver.zip",
        zip_bytes({f"nested/{executable}": PAYLOAD, "nested/LICENSE": b"fixture"}),
    )

    location = Path(archive.unpack(str(tmp_path / "download")))

    assert location == tmp_path / "download" / "extracted" / "nested" / executable
    assert location.read_bytes() == PAYLOAD
    assert archive._content is None
    if os_name != "win":
        assert [path.name for path in fake_archive_chmod] == [executable]
        if os.name != "nt":
            assert location.stat().st_mode & stat.S_IXUSR
    else:
        assert fake_archive_chmod == []


@pytest.mark.parametrize("compression", ["w:gz", "w:bz2"])
def test_tar_unpack_supports_gzip_and_existing_bzip_fallback(
    tmp_path: Path, compression: Any
) -> None:
    """Verify tar unpack supports gzip and existing bzip fallback.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        compression: Fixture or parametrized compression input for this regression.
    """
    archive = files.GeckoDriverFile(
        "win",
        "https://downloads.invalid/geckodriver.tar.gz",
        tar_bytes({"nested/geckodriver.exe": PAYLOAD}, mode=compression),
    )

    location = Path(archive.unpack(str(tmp_path / "download")))

    assert location.read_bytes() == PAYLOAD
    assert location.name == "geckodriver.exe"


@pytest.mark.parametrize(
    "content", [b"not a zip archive", zip_bytes({"LICENSE": b"no driver"})]
)
def test_invalid_or_missing_driver_archive_is_rejected(
    tmp_path: Path, content: Any
) -> None:
    """Verify invalid or missing driver archive is rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        content: Fixture or parametrized content input for this regression.
    """
    archive = files.ChromeDriverFile(
        "win", "https://downloads.invalid/driver.zip", content
    )

    with pytest.raises(errors.InvalidDownloadFileError):
        archive.unpack(str(tmp_path / "download"))


def test_file_type_rejects_unknown_extension() -> None:
    """Verify file type rejects unknown extension."""
    archive = files.ChromeDriverFile("win", "https://downloads.invalid/driver.txt", b"")

    with pytest.raises(errors.InvalidDownloadFileError):
        _ = archive.filetype


@pytest.mark.parametrize(
    ("manager_cls", "file_cls", "version_cls", "version", "executable"),
    [
        (
            files.ChromeFileManager,
            files.ChromeDriverFile,
            ChromiumVersion,
            "120.0.6000.1",
            "chromedriver.exe",
        ),
        (
            files.EdgeFileManager,
            files.EdgeDriverFile,
            ChromiumVersion,
            "120.0.6000.1",
            "msedgedriver.exe",
        ),
        (
            files.FirefoxFileManager,
            files.GeckoDriverFile,
            GeckoVersion,
            "0.34.0",
            "geckodriver.exe",
        ),
    ],
)
def test_driver_cache_round_trip_and_metadata_reload(
    tmp_path: Path,
    manager_cls: Any,
    file_cls: Any,
    version_cls: Any,
    version: Any,
    executable: Any,
) -> None:
    """Verify driver cache round trip and metadata reload.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        manager_cls: Fixture or parametrized manager cls input for this regression.
        file_cls: Fixture or parametrized file cls input for this regression.
        version_cls: Fixture or parametrized version cls input for this regression.
        version: Fixture or parametrized version input for this regression.
        executable: Fixture or parametrized executable input for this regression.
    """
    manager = manager_cls(str(tmp_path))
    expected_version = version_cls(version)
    download = file_cls(
        "win", "https://downloads.invalid/driver.zip", zip_bytes({executable: PAYLOAD})
    )

    cached = manager.cache_driver(expected_version, download)
    manager = manager_cls(str(tmp_path))
    matched = manager.match_driver(expected_version)

    assert matched == cached
    assert matched["version"].version == version
    assert Path(matched["location"]).read_bytes() == PAYLOAD
    assert Path(manager._database).is_file()
    assert len(manager.cached_versions()) == 1


def test_chrome_browser_binary_cache_round_trip(tmp_path: Path) -> None:
    """Verify chrome browser binary cache round trip.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = files.ChromeFileManager(str(tmp_path))
    version = ChromiumVersion("120.0.6000.1")
    archive = files.ChromeBinaryFile(
        "win",
        "https://downloads.invalid/chrome.zip",
        zip_bytes({"chrome/chrome.exe": PAYLOAD}),
    )

    cached = manager.cache_binary(version, archive)
    manager = files.ChromeFileManager(str(tmp_path))

    assert manager.match_binary(version) == cached
    assert Path(cached["location"]).read_bytes() == PAYLOAD


def test_chromium_cache_matches_latest_major_build_or_exact_patch(
    tmp_path: Path,
) -> None:
    """Verify chromium cache matches latest major build or exact patch.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = files.ChromeFileManager(str(tmp_path))
    for text in ["120.0.6000.1", "120.0.6000.5", "120.0.6001.2"]:
        manager.cache_driver(
            ChromiumVersion(text),
            files.ChromeDriverFile(
                "win",
                "https://downloads.invalid/driver.zip",
                zip_bytes({"chromedriver.exe": PAYLOAD}),
            ),
        )

    assert (
        manager.match_driver(ChromiumVersion("120"), "major")["version"].version
        == "120.0.6001.2"
    )
    assert (
        manager.match_driver(ChromiumVersion("120.0.6000"), "build")["version"].version
        == "120.0.6000.5"
    )
    assert (
        manager.match_driver(ChromiumVersion("120.0.6000.1"), "patch")[
            "version"
        ].version
        == "120.0.6000.1"
    )
    assert manager.match_driver(ChromiumVersion("121"), "major") is None


def test_missing_cached_executable_removes_stale_metadata(tmp_path: Path) -> None:
    """Verify missing cached executable removes stale metadata.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = files.ChromeFileManager(str(tmp_path))
    version = ChromiumVersion("120.0.6000.1")
    cached = manager.cache_driver(
        version,
        files.ChromeDriverFile(
            "win",
            "https://downloads.invalid/driver.zip",
            zip_bytes({"chromedriver.exe": PAYLOAD}),
        ),
    )
    location = Path(cached["location"])
    location.relative_to(tmp_path)
    location.unlink()

    assert manager.match_driver(version) is None
    # Corrupt bytes remain recoverable; they are never returned as a cache hit.
    assert location.parent.parent.exists()


def test_cache_release_keeps_newest_entry_and_removes_only_old_tmp_folder(
    tmp_path: Path,
) -> None:
    """Verify cache release keeps newest entry and removes only old tmp folder.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = files.ChromeFileManager(str(tmp_path))
    locations = {}
    for year, text in [(2020, "120.0.6000.1"), (2021, "121.0.6000.1")]:
        cached = manager.cache_driver(
            ChromiumVersion(text),
            files.ChromeDriverFile(
                "win",
                "https://downloads.invalid/driver.zip",
                zip_bytes({"chromedriver.exe": PAYLOAD}),
            ),
        )
        locations[text] = Path(cached["location"])
        with manager._db() as db:
            db.execute("UPDATE artifacts SET created=? WHERE version=?", (year, text))

    manager.prune(limit=1)

    assert manager.cached_versions() == ["121.0.6000.1"]
    assert locations["121.0.6000.1"].is_file()
    assert not locations["120.0.6000.1"].exists()


def test_file_manager_singleton_is_scoped_by_browser_and_cache_directory(
    tmp_path: Path,
) -> None:
    """Verify file manager singleton is scoped by browser and cache directory.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    other = tmp_path / "other"
    other.mkdir()
    manager = files.ChromeFileManager(str(tmp_path))

    assert files.ChromeFileManager(str(tmp_path))._database == manager._database
    assert files.ChromeFileManager(str(other)) is not manager
    assert files.EdgeFileManager(str(tmp_path)) is not manager


def test_unavailable_database_has_a_finite_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify unavailable database has a finite failure.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager = files.ChromeFileManager(str(tmp_path))
    attempts = []

    def fail(*args: Any, **kwargs: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        attempts.append(1)
        raise sqlite3.OperationalError("synthetic read/write denial")

    monkeypatch.setattr(sqlite3, "connect", fail)
    with pytest.raises(errors.DriverManagerError) as failure:
        manager.cached_versions()
    assert isinstance(failure.value.__cause__, sqlite3.OperationalError)
    assert len(attempts) == 1


@pytest.mark.regression
def test_tar_member_cannot_write_outside_extraction_directory(tmp_path: Path) -> None:
    """Verify tar member cannot write outside extraction directory.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    destination = tmp_path / "download"
    escaped = destination / "escaped.txt"
    archive = files.GeckoDriverFile(
        "win",
        "https://downloads.invalid/driver.tar.gz",
        tar_bytes({"geckodriver.exe": PAYLOAD, "../escaped.txt": b"must not escape"}),
    )

    try:
        archive.unpack(str(destination))
    except errors.InvalidDownloadFileError:
        # A safe extractor can reject the archive instead of skipping bad members.
        pass

    assert not escaped.exists(), (
        "archive escaped extracted/, but stayed inside tmp_path"
    )


@pytest.mark.regression
def test_executable_selection_cannot_return_a_foreign_sibling_file(
    tmp_path: Path,
) -> None:
    """Verify executable selection cannot return a foreign sibling file.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    foreign = tmp_path / "outside-extraction" / "chromedriver.exe"
    foreign.parent.mkdir()
    foreign.write_bytes(b"pre-existing synthetic file; never execute")
    archive = files.ChromeDriverFile("win", "https://downloads.invalid/driver.zip", b"")

    try:
        selected = archive._find_target_executable(
            str(extracted), ["../outside-extraction/chromedriver.exe"]
        )
    except (errors.InvalidDownloadFileError, ValueError):
        return

    assert selected is None or Path(selected).resolve().is_relative_to(
        extracted.resolve()
    ), "archive member selected a pre-existing file outside the extraction root"


@pytest.mark.regression
def test_cache_cleanup_cannot_delete_a_foreign_sibling_folder(tmp_path: Path) -> None:
    """Verify cache cleanup cannot delete a foreign sibling folder.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = files.ChromeFileManager(str(tmp_path))
    foreign = tmp_path / "outside-cache"
    foreign.mkdir()
    with pytest.raises(errors.DriverManagerError):
        manager._delete_folder(foreign)
    assert foreign.is_dir()


@pytest.mark.regression
def test_persistent_download_write_error_has_a_finite_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify persistent download write error has a finite retry budget.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    archive = files.ChromeDriverFile(
        "win", "https://downloads.invalid/driver.zip", PAYLOAD
    )
    attempts = 0

    def fail_open(*args: Any, **kwargs: Any) -> None:
        """Fail open.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        nonlocal attempts
        attempts += 1
        if attempts > RETRY_LIMIT:
            raise RetryBudgetExhausted
        raise PermissionError("synthetic download write denial")

    monkeypatch.setattr(files, "open", fail_open, raising=False)
    try:
        with pytest.raises((OSError, errors.DriverManagerError)):
            archive._save_file(str(tmp_path / "download"))
    except RetryBudgetExhausted:
        raise AssertionError("download write exceeded three failed attempts") from None
