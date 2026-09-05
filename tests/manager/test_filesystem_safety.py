"""Bounded failures, cache containment and failed-install preservation."""

from __future__ import annotations

import errno
import os
import sqlite3
from collections.abc import Callable
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


def patch_archive_open(
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
    replacement: Callable[..., Any],
) -> None:
    """Intercept only the exclusive open for one expected archive destination.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        target: Exact downloaded-archive path whose open should be intercepted.
        replacement: Callable used in place of ``Path.open`` for that one write.
    """
    original = Path.open

    def guarded(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        """Delegate every open except the selected exclusive archive write.

        Args:
            path: File being opened.
            mode: File mode requested by the caller.
            *args: Additional positional arguments accepted by ``Path.open``.
            **kwargs: Additional keyword arguments accepted by ``Path.open``.

        Returns:
            File object or test double produced by the selected implementation.
        """
        if path == target and mode == "xb":
            return replacement(path, mode, *args, **kwargs)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)


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
        patch_archive_open(
            monkeypatch, tmp_path / "download" / "chromedriver.zip", fail
        )
        action = lambda: archive()._save_file(tmp_path / "download")
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
        patch_archive_open(
            monkeypatch,
            tmp_path / "download" / "chromedriver.zip",
            flaky(Path.open),
        )
        assert archive()._save_file(tmp_path / "download").is_file()
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
        archive()._save_file(tmp_path)
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

    patch_archive_open(monkeypatch, destination, fail)
    with pytest.raises(errors.DriverManagerError):
        archive()._save_file(tmp_path)
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

    def partial_open(path: Path, mode: str, *args: Any, **kwargs: Any) -> PartialWriter:
        """Create the partial-writer double through the ``Path.open`` seam.

        Args:
            path: Archive destination opened by the implementation.
            mode: File mode requested by the implementation.
            *args: Additional positional arguments accepted by ``Path.open``.
            **kwargs: Additional keyword arguments accepted by ``Path.open``.

        Returns:
            Writer that persists a prefix before raising the synthetic failure.
        """
        return PartialWriter(path, mode)

    patch_archive_open(monkeypatch, tmp_path / "chromedriver.zip", partial_open)
    with pytest.raises(errors.DriverManagerError) as failure:
        archive()._save_file(tmp_path)
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


def test_checked_path_accepts_a_leaf_that_disappears_during_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retry when a volatile SQLite-style leaf disappears after ``lstat()``.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    root = tmp_path.resolve()
    leaf = root / "index.sqlite3-journal"
    leaf.touch()
    original = Path.lstat
    removed = False

    def disappearing(path: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        """Remove the selected leaf after returning its first observed status.

        Args:
            path: Path whose non-following status was requested.
            *args: Additional positional arguments accepted by ``Path.lstat``.
            **kwargs: Additional keyword arguments accepted by ``Path.lstat``.

        Returns:
            The status observed before the simulated concurrent removal.
        """
        nonlocal removed
        info = original(path, *args, **kwargs)
        if path == leaf and not removed:
            leaf.unlink()
            removed = True
        return info

    monkeypatch.setattr(Path, "lstat", disappearing)
    assert safety.checked_path(root, leaf) is leaf
    assert removed


def test_checked_path_does_not_resolve_a_stably_absent_leaf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Resolve the persistent ancestor instead of an absent volatile leaf.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    root = tmp_path.resolve()
    leaf = root / "index.sqlite3-wal"
    original = Path.resolve

    def guarded(path: Path, *args: Any, **kwargs: Any) -> Path:
        """Reject an unnecessary attempt to resolve the absent leaf itself.

        Args:
            path: Path selected for canonical resolution.
            *args: Additional positional arguments accepted by ``Path.resolve``.
            **kwargs: Additional keyword arguments accepted by ``Path.resolve``.

        Returns:
            Canonical path returned for an existing ancestor.
        """
        if path == leaf:
            pytest.fail("A volatile absent leaf must not be resolved")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", guarded)
    assert safety.checked_path(root, leaf) is leaf


def test_checked_path_rejects_a_reparse_leaf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject a Windows reparse leaf without following its target.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """

    class ReparseStat:
        """Represent the Windows reparse attribute returned by ``lstat()``."""

        st_mode = 0o100644
        st_file_attributes = 0x400

    root = tmp_path.resolve()
    leaf = root / "index.sqlite3-shm"
    original = Path.lstat

    def reparse(path: Path, *args: Any, **kwargs: Any) -> Any:
        """Return a synthetic reparse result only for the selected leaf.

        Args:
            path: Path whose non-following status was requested.
            *args: Additional positional arguments accepted by ``Path.lstat``.
            **kwargs: Additional keyword arguments accepted by ``Path.lstat``.

        Returns:
            A synthetic or native non-following status result.
        """
        if path == leaf:
            return ReparseStat()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="link/reparse"):
        safety.checked_path(root, leaf)


def test_checked_path_propagates_non_disappearance_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Do not classify permission failures as harmless leaf disappearance.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    root = tmp_path.resolve()
    leaf = root / "index.sqlite3-journal"
    original = Path.lstat

    def denied(path: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        """Raise the selected permission error and delegate all other paths.

        Args:
            path: Path whose non-following status was requested.
            *args: Additional positional arguments accepted by ``Path.lstat``.
            **kwargs: Additional keyword arguments accepted by ``Path.lstat``.

        Returns:
            Native status for paths other than the selected leaf.
        """
        if path == leaf:
            raise PermissionError(errno.EACCES, "synthetic access denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(PermissionError):
        safety.checked_path(root, leaf)


def test_checked_path_has_a_finite_redirection_retry_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fail closed after a stable resolution mismatch instead of looping.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    root = tmp_path.resolve()
    leaf = root / "index.sqlite3-journal"
    resolutions: list[Path] = []

    def redirected(path: Path, *, strict: bool = False) -> Path:
        """Return a stable foreign canonical spelling for the anchored root.

        Args:
            path: Path selected for canonical resolution.
            strict: Whether every component is required to exist.

        Returns:
            A different absolute path representing persistent redirection.
        """
        assert path == root
        assert strict
        resolutions.append(path)
        return root.parent / "redirected"

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(ValueError, match="changed while it was validated"):
        safety.checked_path(root, leaf)
    assert resolutions == [root] * safety.PATH_CHECK_ATTEMPTS


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
def test_checked_path_rejects_replacement_above_the_anchored_root(
    tmp_path: Path,
) -> None:
    """Detect a symlink swap in a parent above the retained canonical root.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    container = tmp_path / "container"
    root = container / "cache"
    root.mkdir(parents=True)
    anchored = root.resolve(strict=True)
    container.rename(tmp_path / "original-container")
    foreign = tmp_path / "foreign"
    (foreign / "cache").mkdir(parents=True)
    container.symlink_to(foreign, target_is_directory=True)

    with pytest.raises(ValueError, match="changed while it was validated"):
        safety.checked_path(anchored, anchored / "index.sqlite3-wal")


@pytest.mark.skipif(
    os.name == "nt", reason="Native Windows symlink privileges are not assumed"
)
def test_checked_path_rechecks_anchor_after_confirming_an_absent_leaf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject a parent replacement between canonical and absence checks.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    container = tmp_path / "container"
    root = container / "cache"
    root.mkdir(parents=True)
    anchored = root.resolve(strict=True)
    foreign = tmp_path / "foreign"
    (foreign / "cache").mkdir(parents=True)
    original = Path.resolve
    replaced = False

    def replace_after_resolution(path: Path, *args: Any, **kwargs: Any) -> Path:
        """Replace the root's parent immediately after its first resolution.

        Args:
            path: Path selected for canonical resolution.
            *args: Additional positional arguments accepted by ``Path.resolve``.
            **kwargs: Additional keyword arguments accepted by ``Path.resolve``.

        Returns:
            Canonical path observed before the simulated concurrent replacement.
        """
        nonlocal replaced
        resolved = original(path, *args, **kwargs)
        if path == anchored and not replaced:
            container.rename(tmp_path / "original-container")
            container.symlink_to(foreign, target_is_directory=True)
            replaced = True
        return resolved

    monkeypatch.setattr(Path, "resolve", replace_after_resolution)
    with pytest.raises(ValueError, match="changed while it was validated"):
        safety.checked_path(anchored, anchored / "index.sqlite3-shm")
    assert replaced


def test_checked_path_rejects_a_missing_leaf_that_reappears_as_reparse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Inspect a volatile leaf again when it appears during validation.

    Args:
        monkeypatch: Pytest fixture for reversible attribute patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """

    class ReparseStat:
        """Represent the Windows reparse attribute returned by ``lstat()``."""

        st_mode = 0o100644
        st_file_attributes = 0x400

    root = tmp_path.resolve()
    leaf = root / "index.sqlite3-journal"
    original = Path.lstat
    observations = 0

    def appear(path: Path, *args: Any, **kwargs: Any) -> Any:
        """Report one absence followed by a synthetic reparse point.

        Args:
            path: Path whose non-following status was requested.
            *args: Additional positional arguments accepted by ``Path.lstat``.
            **kwargs: Additional keyword arguments accepted by ``Path.lstat``.

        Returns:
            A synthetic or native non-following status result.
        """
        nonlocal observations
        if path != leaf:
            return original(path, *args, **kwargs)
        observations += 1
        if observations == 1:
            raise FileNotFoundError(leaf)
        return ReparseStat()

    monkeypatch.setattr(Path, "lstat", appear)
    with pytest.raises(ValueError, match="link/reparse"):
        safety.checked_path(root, leaf)
    assert observations == 2


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

    def partial_open(path: Path, mode: str, *args: Any, **kwargs: Any) -> PartialWriter:
        """Create the partial-writer double through the ``Path.open`` seam.

        Args:
            path: Archive destination opened by the implementation.
            mode: File mode requested by the implementation.
            *args: Additional positional arguments accepted by ``Path.open``.
            **kwargs: Additional keyword arguments accepted by ``Path.open``.

        Returns:
            Writer that persists a prefix before raising the synthetic failure.
        """
        return PartialWriter(path, mode)

    patch_archive_open(monkeypatch, tmp_path / "chromedriver.zip", partial_open)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(errors.DriverManagerError) as failure:
        archive()._save_file(tmp_path)
    assert failure.value.__cause__ is cause
    assert (tmp_path / "chromedriver.zip").read_bytes()
    assert "Partial downloaded archive retained" in caplog.text
