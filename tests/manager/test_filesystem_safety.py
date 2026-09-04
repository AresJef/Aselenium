"""Bounded failures, cache containment and failed-install preservation."""

from __future__ import annotations

import errno
import os
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from aselenium import errors
from aselenium.manager import _cache as cache_module
from aselenium.manager import _filesystem as safety
from aselenium.manager import file as files
from aselenium.manager.version import ChromiumVersion, GeckoVersion


@pytest.fixture(autouse=True)
def record_backoff(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Record backoff.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    waits = []
    monkeypatch.setattr(safety, "sleep", waits.append)
    return waits


@pytest.fixture
def manager(tmp_path: Path) -> Any:
    """Manager.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    return files.ChromeFileManager(str(tmp_path))


def archive(
    file_class: Any = files.ChromeDriverFile, executable: str = "chromedriver.exe"
) -> Any:
    """Archive.

    Args:
        file_class: Fixture or parametrized file class input for this regression.
        executable: Fixture or parametrized executable input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    buffer = BytesIO()
    with ZipFile(buffer, "w") as output:
        output.writestr(executable, b"synthetic bytes; never executed")
    return file_class("win", "https://offline.invalid/driver.zip", buffer.getvalue())


@pytest.mark.parametrize("operation", ["read", "write", "delete", "archive"])
@pytest.mark.parametrize(
    "code",
    [errno.EACCES, errno.ENOSPC, errno.EROFS, errno.EAGAIN, errno.EBUSY, errno.EINTR],
)
def test_filesystem_failures_have_classified_finite_attempts(
    manager: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_backoff: Any,
    operation: Any,
    code: Any,
) -> None:
    """Verify filesystem failures have classified finite attempts.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        record_backoff: Fixture or parametrized record backoff input for this regression.
        operation: Fixture or parametrized operation input for this regression.
        code: Fixture or parametrized code input for this regression.
    """
    attempts = []
    cause = OSError(code, "synthetic I/O failure")

    def fail(*args: Any, **kwargs: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        attempts.append(1)
        if len(attempts) > 3:
            pytest.fail("Retry budget exceeded")
        raise cause

    if operation == "read":
        action = lambda: safety.filesystem_operation(fail, "read fixture")
    elif operation == "write":
        action = lambda: safety.filesystem_operation(fail, "write fixture")
    elif operation == "delete":
        folder = Path(manager._directory) / "entry"
        folder.mkdir()
        monkeypatch.setattr(cache_module.shutil, "rmtree", fail)
        action = lambda: manager._delete_folder(folder)
    else:
        monkeypatch.setattr(files, "open", fail, raising=False)
        action = lambda: archive()._save_file(str(tmp_path / "download"))
    with pytest.raises(errors.DriverManagerError) as failure:
        action()
    assert failure.value.__cause__ is cause
    transient = code in {errno.EAGAIN, errno.EBUSY, errno.EINTR}
    assert len(attempts) == (3 if transient else 1)
    assert record_backoff == ([0.05, 0.1] if transient else [])


@pytest.mark.parametrize("operation", ["read", "write", "delete", "archive"])
def test_transient_failure_can_recover_within_budget(
    manager: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_backoff: Any,
    operation: Any,
) -> None:
    """Verify transient failure can recover within budget.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        record_backoff: Fixture or parametrized record backoff input for this regression.
        operation: Fixture or parametrized operation input for this regression.
    """
    attempts = []

    def flaky(original: Any) -> Any:
        """Flaky.

        Args:
            original: Fixture or parametrized original input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Wrapper.

            Args:
                *args: Fixture or parametrized args input for this regression.
                **kwargs: Fixture or parametrized kwargs input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError(errno.EBUSY, "synthetic busy file")
            return original(*args, **kwargs)

        return wrapper

    if operation == "read":
        assert safety.filesystem_operation(flaky(lambda: True), "read fixture")
    elif operation == "write":
        assert safety.filesystem_operation(flaky(lambda: True), "write fixture")
    elif operation == "delete":
        folder = Path(manager._directory) / "entry"
        folder.mkdir()
        monkeypatch.setattr(
            cache_module.shutil, "rmtree", flaky(cache_module.shutil.rmtree)
        )
        manager._delete_folder(folder)
        assert not folder.exists()
    else:
        monkeypatch.setattr(files, "open", flaky(open), raising=False)
        assert Path(archive()._save_file(str(tmp_path / "download"))).is_file()
    assert len(attempts) == 3
    assert record_backoff == [0.05, 0.1]


@pytest.mark.parametrize("winerror", [32, 33])
def test_windows_sharing_violations_are_bounded_transient_errors(
    winerror: Any, record_backoff: Any
) -> None:
    """Verify windows sharing violations are bounded transient errors.

    Args:
        winerror: Fixture or parametrized winerror input for this regression.
        record_backoff: Fixture or parametrized record backoff input for this regression.
    """
    cause = PermissionError(errno.EACCES, "synthetic Windows lock")
    cause.winerror = winerror
    attempts = []

    def fail() -> None:
        """Fail."""
        attempts.append(1)
        raise cause

    with pytest.raises(errors.DriverManagerError) as failure:
        safety.filesystem_operation(fail, "Windows sharing violation")
    assert failure.value.__cause__ is cause
    assert len(attempts) == 3
    assert record_backoff == [0.05, 0.1]


@pytest.mark.parametrize(
    "target", ["root", "outside", "sibling-prefix", "parent-traversal"]
)
@pytest.mark.parametrize("operation", ["read", "write", "delete"])
def test_managed_operations_reject_foreign_and_root_paths(
    manager: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: Any,
    operation: Any,
) -> None:
    """Verify managed operations reject foreign and root paths.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        target: Fixture or parametrized target input for this regression.
        operation: Fixture or parametrized operation input for this regression.
    """
    root = Path(manager._directory)
    paths = {
        "root": root,
        "outside": tmp_path / "foreign",
        "sibling-prefix": tmp_path / ".aselenium-foreign",
        "parent-traversal": root / "inside" / ".." / "victim",
    }

    def forbidden(*args: Any, **kwargs: Any) -> None:
        """Forbidden.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        pytest.fail("Unsafe target reached a filesystem operation")

    monkeypatch.setattr(cache_module.shutil, "rmtree", forbidden)
    with pytest.raises(errors.DriverManagerError, match="Unsafe"):
        if operation == "read":
            manager._managed_path(paths[target])
        elif operation == "write":
            manager._managed_path(paths[target])
        else:
            manager._delete_folder(paths[target])


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
@pytest.mark.parametrize("target", ["leaf", "ancestor", "cache-root"])
def test_cleanup_refuses_symlink_and_replaced_root(
    manager: Any, tmp_path: Path, target: Any
) -> None:
    """Verify cleanup refuses symlink and replaced root.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        target: Fixture or parametrized target input for this regression.
    """
    root = Path(manager._directory)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    sentinel = foreign / "sentinel"
    sentinel.write_text("preserve")
    if target == "cache-root":
        root.rename(tmp_path / "original-cache")
        root.symlink_to(foreign, target_is_directory=True)
        path = root / "entry"
    else:
        (root / "link").symlink_to(foreign, target_is_directory=True)
        path = root / "link" if target == "leaf" else root / "link/entry"
    with pytest.raises(errors.DriverManagerError):
        manager._delete_folder(path)
    assert sentinel.read_text() == "preserve"


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
def test_cache_root_symlink_is_refused_at_construction(tmp_path: Path) -> None:
    """Verify cache root symlink is refused at construction.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (tmp_path / ".aselenium").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(errors.DriverManagerError):
        files.ChromeFileManager(str(tmp_path))
    assert list(foreign.iterdir()) == []


def test_atomic_database_failure_preserves_previous_disk_file(manager: Any) -> None:
    """Verify atomic database failure preserves previous disk file.

    Args:
        manager: Fixture or parametrized manager input for this regression.
    """
    with manager._db() as db:
        db.execute(
            "INSERT INTO artifacts VALUES ('fixture','chrome','test','driver','1','exe','digest',0,0)"
        )
    with pytest.raises(errors.DriverManagerError):
        with manager._db() as db:
            db.execute("DELETE FROM artifacts")
            raise sqlite3.OperationalError("synthetic failed transaction")
    with manager._db() as db:
        assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("manager_class", "file_class", "version_class", "versions", "executable", "kind"),
    [
        (
            files.ChromeFileManager,
            files.ChromeDriverFile,
            ChromiumVersion,
            ["120.0.6000.1", "121.0.6000.1"],
            "chromedriver.exe",
            "driver",
        ),
        (
            files.EdgeFileManager,
            files.EdgeDriverFile,
            ChromiumVersion,
            ["120.0.6000.1", "121.0.6000.1"],
            "msedgedriver.exe",
            "driver",
        ),
        (
            files.FirefoxFileManager,
            files.GeckoDriverFile,
            GeckoVersion,
            ["0.34.0", "0.35.0"],
            "geckodriver.exe",
            "driver",
        ),
        (
            files.ChromeFileManager,
            files.ChromeBinaryFile,
            ChromiumVersion,
            ["120.0.6000.1", "121.0.6000.1"],
            "chrome.exe",
            "binary",
        ),
    ],
)
def test_failed_metadata_commit_does_not_evict_valid_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manager_class: Any,
    file_class: Any,
    version_class: Any,
    versions: Any,
    executable: Any,
    kind: Any,
) -> None:
    """Verify failed metadata commit does not evict valid cache.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        file_class: Fixture or parametrized file class input for this regression.
        version_class: Fixture or parametrized version class input for this regression.
        versions: Fixture or parametrized versions input for this regression.
        executable: Fixture or parametrized executable input for this regression.
        kind: Fixture or parametrized kind input for this regression.
    """
    manager = manager_class(str(tmp_path))
    cache = getattr(manager, "cache_" + kind)
    old = cache(
        version_class(versions[0]), archive(file_class, executable), max_cache_size=1
    )
    index_path = Path(manager._database)
    old_bytes = index_path.read_bytes()
    original = manager._publish

    def fail(*args: Any, **kwargs: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        raise errors.DriverManagerError("synthetic commit failure")

    monkeypatch.setattr(manager, "_publish", fail)
    with pytest.raises(errors.DriverManagerError):
        cache(
            version_class(versions[1]),
            archive(file_class, executable),
            max_cache_size=1,
        )
    assert Path(old["location"]).is_file()
    assert index_path.read_bytes() == old_bytes
    # Published bytes have a recovery manifest; retry adopts them without unpacking.
    monkeypatch.setattr(manager, "_publish", original)
    recovered = cache(version_class(versions[1]), archive(file_class, executable))
    assert Path(recovered["location"]).is_file()


def test_failed_extraction_cannot_evict_a_valid_cache(manager: Any) -> None:
    """Verify failed extraction cannot evict a valid cache.

    Args:
        manager: Fixture or parametrized manager input for this regression.
    """
    old = manager.cache_driver(
        ChromiumVersion("120.0.6000.1"), archive(), max_cache_size=1
    )
    index = Path(manager._database).read_bytes()
    bad = files.ChromeDriverFile(
        "win", "https://offline.invalid/driver.zip", b"invalid archive"
    )
    with pytest.raises(errors.InvalidDownloadFileError):
        manager.cache_driver(ChromiumVersion("121.0.6000.1"), bad, max_cache_size=1)
    assert Path(old["location"]).is_file()
    assert Path(manager._database).read_bytes() == index


def test_eviction_failure_is_reported_after_successful_commit(
    manager: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify eviction failure is reported after successful commit.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        caplog: Pytest fixture capturing log records emitted by the operation.
    """
    old = manager.cache_driver(
        ChromiumVersion("120.0.6000.1"), archive(), max_cache_size=1
    )
    with manager._db() as db:
        db.execute("UPDATE artifacts SET created=0")

    def fail(*args: Any, **kwargs: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        raise PermissionError(errno.EACCES, "synthetic locked old entry")

    monkeypatch.setattr(cache_module.shutil, "rmtree", fail)
    new = manager.cache_driver(
        ChromiumVersion("121.0.6000.1"), archive(), max_cache_size=1
    )
    assert Path(new["location"]).is_file()
    assert Path(old["location"]).is_file()
    assert "121.0.6000.1" in manager.cached_versions()
    assert "eviction deferred" in caplog.text


@pytest.mark.parametrize("field", ["key", "executable"])
def test_cache_hits_cannot_select_foreign_files(
    manager: Any, tmp_path: Path, field: Any
) -> None:
    """Verify cache hits cannot select foreign files.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        field: Fixture or parametrized field input for this regression.
    """
    version = ChromiumVersion("120.0.6000.1")
    manager.cache_driver(version, archive())
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    executable = foreign / "chromedriver.exe"
    executable.write_text("preserve")
    with manager._db() as db:
        db.execute(
            "UPDATE artifacts SET " + field + "=?",
            (str(foreign if field == "key" else executable),),
        )
    with pytest.raises(errors.DriverManagerError):
        manager.match_driver(version)
    assert executable.read_text() == "preserve"


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_invalid_cache_limits_fail_before_extraction(manager: Any, limit: Any) -> None:
    """Verify invalid cache limits fail before extraction.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        limit: Fixture or parametrized limit input for this regression.
    """
    before = set(Path(manager._directory).iterdir())
    with pytest.raises(errors.DriverManagerError, match="max_cache_size"):
        manager.cache_driver(
            ChromiumVersion("120.0.6000.1"), archive(), max_cache_size=limit
        )
    assert set(Path(manager._directory).iterdir()) == before


def test_download_save_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    """Verify download save refuses to overwrite existing file.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    destination = tmp_path / "chromedriver.zip"
    destination.write_bytes(b"previous download")
    with pytest.raises(errors.DriverManagerError):
        archive()._save_file(str(tmp_path))
    assert destination.read_bytes() == b"previous download"


def test_future_old_timestamp_cannot_evict_just_installed_entry(manager: Any) -> None:
    """Verify future old timestamp cannot evict just installed entry.

    Args:
        manager: Fixture or parametrized manager input for this regression.
    """
    old = manager.cache_driver(ChromiumVersion("120.0.6000.1"), archive())
    with manager._db() as db:
        db.execute("UPDATE artifacts SET created=9999999999")
    new = manager.cache_driver(
        ChromiumVersion("121.0.6000.1"), archive(), max_cache_size=1
    )
    assert Path(new["location"]).is_file()
    assert not Path(old["location"]).exists()
    assert manager.cached_versions() == ["121.0.6000.1"]


def test_absent_cache_entry_cleanup_is_idempotent(manager: Any) -> None:
    """Verify absent cache entry cleanup is idempotent.

    Args:
        manager: Fixture or parametrized manager input for this regression.
    """
    manager._delete_folder(Path(manager._directory) / "already-absent")


def test_download_permission_error_cannot_remove_preexisting_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify download permission error cannot remove preexisting file.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    destination = tmp_path / "chromedriver.zip"
    destination.write_bytes(b"preserve")

    def fail(*args: Any, **kwargs: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        raise PermissionError(errno.EACCES, "synthetic denial before open")

    monkeypatch.setattr(files, "open", fail, raising=False)
    with pytest.raises(errors.DriverManagerError):
        archive()._save_file(str(tmp_path))
    assert destination.read_bytes() == b"preserve"


def test_partial_archive_write_is_removed_before_transient_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_backoff: Any
) -> None:
    """Verify partial archive write is removed before transient retry.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        record_backoff: Fixture or parametrized record backoff input for this regression.
    """
    attempts = []
    cause = OSError(errno.EBUSY, "synthetic interrupted archive write")

    class PartialWriter:
        """Represent PartialWriter using the inherited implementation."""

        def __init__(self, path: Any, mode: Any) -> None:
            """Initialize the instance with the supplied configuration.

            Args:
                path: Fixture or parametrized path input for this regression.
                mode: Fixture or parametrized mode input for this regression.
            """
            attempts.append(1)
            self.stream = open(path, mode)

        def __enter__(self) -> PartialWriter:
            """Enter the context and return its managed value.

            Returns:
                The PartialWriter value produced by this operation.
            """
            return self

        def __exit__(self, *args: Any) -> None:
            """Release resources when leaving the synchronous context.

            Args:
                *args: Fixture or parametrized args input for this regression.
            """
            self.stream.close()

        def write(self, content: Any) -> None:
            """Write.

            Args:
                content: Fixture or parametrized content input for this regression.
            """
            self.stream.write(content[:2])
            raise cause

    monkeypatch.setattr(files, "open", PartialWriter, raising=False)
    with pytest.raises(errors.DriverManagerError) as failure:
        archive()._save_file(str(tmp_path))
    assert failure.value.__cause__ is cause
    assert len(attempts) == 3
    assert not (tmp_path / "chromedriver.zip").exists()
    assert record_backoff == [0.05, 0.1]


def test_publication_lock_failure_is_bounded_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_backoff: Any
) -> None:
    """Verify publication lock failure is bounded and cleans staging.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        record_backoff: Fixture or parametrized record backoff input for this regression.
    """
    attempts = []

    def fail(*args: Any, **kwargs: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        attempts.append(1)
        raise OSError(errno.EBUSY, "synthetic publication lock")

    monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(errors.InvalidDownloadFileError):
        archive().unpack(str(tmp_path / "entry"))
    assert len(attempts) == 3
    assert not (tmp_path / "entry").exists()
    assert not list(tmp_path.glob(".aselenium-stage-*"))
    assert record_backoff == [0.05, 0.1]


def test_failed_commit_preserves_primary_failure_and_recoverable_bytes(
    manager: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify failed commit preserves primary failure and recoverable bytes.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    old = manager.cache_driver(ChromiumVersion("120.0.6000.1"), archive())
    cause = errors.DriverManagerError("synthetic full disk")

    def fail(*args: Any, **kwargs: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        raise cause

    monkeypatch.setattr(manager, "_publish", fail)
    with pytest.raises(errors.DriverManagerError) as failure:
        manager.cache_driver(
            ChromiumVersion("121.0.6000.1"), archive(), max_cache_size=1
        )
    assert failure.value is cause
    assert Path(old["location"]).is_file()
    assert len(list(Path(manager._directory).glob("*/artifact.json"))) == 2


def test_windows_reparse_attribute_is_treated_as_a_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify windows reparse attribute is treated as a link.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """

    class ReparseStat:
        """Represent ReparseStat using the inherited implementation."""

        st_mode = 0o40755
        st_file_attributes = 0x400

    monkeypatch.setattr(Path, "lstat", lambda self: ReparseStat())
    assert safety.is_link(tmp_path / "junction")


def test_partial_archive_cleanup_preserves_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify partial archive cleanup preserves write failure.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        caplog: Pytest fixture capturing log records emitted by the operation.
    """
    cause = OSError(errno.ENOSPC, "synthetic write failure")

    class PartialWriter:
        """Represent PartialWriter using the inherited implementation."""

        def __init__(self, path: Any, mode: Any) -> None:
            """Initialize the instance with the supplied configuration.

            Args:
                path: Fixture or parametrized path input for this regression.
                mode: Fixture or parametrized mode input for this regression.
            """
            self.stream = open(path, mode)

        def __enter__(self) -> PartialWriter:
            """Enter the context and return its managed value.

            Returns:
                The PartialWriter value produced by this operation.
            """
            return self

        def __exit__(self, *args: Any) -> None:
            """Release resources when leaving the synchronous context.

            Args:
                *args: Fixture or parametrized args input for this regression.
            """
            self.stream.close()

        def write(self, content: Any) -> None:
            """Write.

            Args:
                content: Fixture or parametrized content input for this regression.
            """
            self.stream.write(content[:2])
            raise cause

    def fail_cleanup(*args: Any, **kwargs: Any) -> None:
        """Fail cleanup.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        raise PermissionError(errno.EACCES, "synthetic cleanup failure")

    monkeypatch.setattr(files, "open", PartialWriter, raising=False)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(errors.DriverManagerError) as failure:
        archive()._save_file(str(tmp_path))
    assert failure.value.__cause__ is cause
    assert (tmp_path / "chromedriver.zip").read_bytes()
    assert "Partial downloaded archive retained" in caplog.text
