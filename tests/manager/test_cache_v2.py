"""SQLite, ownership, recovery and independent-process cache regressions."""

from __future__ import annotations

import asyncio
import errno
import json
import multiprocessing
import os
import sqlite3
import threading
from io import BytesIO
from pathlib import Path
from traceback import format_exc
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import psutil
import pytest

from aselenium import errors
from aselenium._async import run_blocking
from aselenium._paths import PathInput
from aselenium.manager import _cache as cache_module
from aselenium.manager._cache import CacheEntry, artifact_lock
from aselenium.manager.file import ChromeDriverFile, ChromeFileManager
from aselenium.manager.version import ChromiumVersion


def archive() -> ChromeDriverFile:
    """Build a minimal ChromeDriver archive without external I/O.

    Returns:
        In-memory archive accepted by the real cache publication workflow.
    """
    stream = BytesIO()
    with ZipFile(stream, "w") as output:
        output.writestr("chromedriver", b"fixture-never-executed")
    return ChromeDriverFile(
        "linux", "https://example.invalid/driver.zip", stream.getvalue()
    )


def install(
    base: PathInput, version: str = "120.0.1.1", crash: bool = False
) -> CacheEntry:
    """Publish one archive through an independently constructed cache manager.

    Args:
        base: Existing cache parent directory.
        version: Driver version recorded in the artifact manifest.
        crash: Whether to terminate after publication and before index commit.

    Returns:
        Validated cache entry returned by the publication workflow.
    """
    cache = ChromeFileManager(base).for_platform("linux", "64")
    if crash:
        cache._publish = lambda row: os._exit(17)
    return cache.cache_driver(ChromiumVersion(version), archive())


def install_with_report(base: PathInput, report_directory: Path) -> None:
    """Run one cache publication and preserve a child traceback for the parent.

    Args:
        base: Existing cache parent directory shared by all child processes.
        report_directory: Existing directory receiving this child's diagnostic file.
    """
    report = report_directory / (str(os.getpid()) + ".json")
    try:
        entry = install(base)
    except BaseException as cause:
        detail = format_exc()
        try:
            write_child_report(report, "error", detail)
        except Exception as report_error:
            # Exception notes were added in Python 3.11; retain the package's
            # Python 3.10 test compatibility without replacing the root cause.
            add_note = getattr(cause, "add_note", None)
            if add_note is not None:
                add_note("Unable to publish child diagnostic: %s" % report_error)
        raise
    write_child_report(report, "ok", str(entry["location"]))


def write_child_report(report: Path, status: str, detail: str) -> None:
    """Atomically publish a child diagnostic with a direct-write fallback.

    Args:
        report: Final per-process JSON report path.
        status: Short outcome category consumed by the parent process.
        detail: Cache location or formatted child traceback.

    Raises:
        RuntimeError: Both the atomic publication and fallback write failed.
    """
    payload = {"status": status, "detail": detail}
    temporary = report.with_suffix(report.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(payload))
        temporary.replace(report)
    except OSError as atomic_error:
        payload["report_error"] = str(atomic_error)
        try:
            report.write_text(json.dumps(payload))
        except OSError as fallback_error:
            message = "Unable to publish child diagnostic for %s: %s" % (
                status,
                detail,
            )
            raise RuntimeError(message) from fallback_error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def collect_child_reports(
    report_directory: Path,
) -> dict[int, tuple[str, str]]:
    """Read child reports without hiding a pre-target spawn failure.

    Args:
        report_directory: Directory populated by cache-publication children.

    Returns:
        Reports keyed by operating-system process identifier.
    """
    outcomes: dict[int, tuple[str, str]] = {}
    for report in report_directory.glob("*.json"):
        payload = json.loads(report.read_text())
        outcomes[int(report.stem)] = (payload["status"], payload["detail"])
    return outcomes


def test_independent_processes_publish_one_artifact(tmp_path: Path) -> None:
    """Verify independent processes publish one artifact.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    context = multiprocessing.get_context("spawn")
    report_directory = tmp_path / "child-reports"
    report_directory.mkdir()
    jobs = [
        context.Process(target=install_with_report, args=(tmp_path, report_directory))
        for _ in range(3)
    ]
    started: list[multiprocessing.Process] = []
    timed_out: list[int | None] = []
    cleanup_errors: list[str] = []
    try:
        for job in jobs:
            job.start()
            started.append(job)
        for job in started:
            job.join(15)
            if job.is_alive():
                timed_out.append(job.pid)
    finally:
        for job in started:
            if not job.is_alive():
                continue
            try:
                job.kill()
            except OSError as cause:
                cleanup_errors.append("%s: %s" % (job.pid, cause))
        for job in started:
            if job.is_alive():
                job.join(5)
    survivors = [job.pid for job in started if job.is_alive()]
    if timed_out or cleanup_errors or survivors:
        pytest.fail(
            "Cache process cleanup failed; timed out=%r, kill errors=%r, survivors=%r"
            % (timed_out, cleanup_errors, survivors)
        )
    outcomes = collect_child_reports(report_directory)
    for job in jobs:
        status, detail = outcomes.get(
            job.pid or -1,
            ("missing", "Child exited before it could publish a diagnostic report"),
        )
        assert job.exitcode == 0, (
            f"Cache child {job.pid} exited with {job.exitcode}; {status}:\n{detail}"
        )
        assert status == "ok", f"Cache child {job.pid} reported {status}:\n{detail}"
    assert len(outcomes) == len(jobs), "One or more cache children did not report"
    cache = ChromeFileManager(tmp_path).for_platform("linux", "64")
    assert cache.cached_versions() == ["120.0.1.1"]
    assert len(list(cache._directory.glob("*/artifact.json"))) == 1


def test_windows_generic_lock_contention_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry a generic Windows ``OSError`` carrying a contention error code.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible attribute patches.
    """

    class WindowsLock:
        """Simulate the narrow acquisition and release contract of ``msvcrt``."""

        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            """Initialize acquisition and release counters."""
            self.acquisitions = 0
            self.releases = 0
            self.calls: list[tuple[int, int, int]] = []

        def locking(self, descriptor: int, mode: int, size: int) -> None:
            """Fail the first acquisition with a generic contention error.

            Args:
                descriptor: Open lock-file descriptor.
                mode: Nonblocking acquisition or release mode.
                size: Number of bytes in the locked region.
            """
            assert descriptor >= 0
            assert size == 1
            self.calls.append(
                (
                    mode,
                    os.lseek(descriptor, 0, os.SEEK_CUR),
                    os.fstat(descriptor).st_size,
                )
            )
            if mode == self.LK_UNLCK:
                self.releases += 1
                return
            self.acquisitions += 1
            if self.acquisitions == 1:
                cause = OSError("synthetic generic Windows lock contention")
                cause.errno = errno.EDEADLK
                raise cause

    backend = WindowsLock()
    waits: list[float] = []
    monkeypatch.setattr(cache_module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(cache_module, "msvcrt", backend, raising=False)
    monkeypatch.setattr(cache_module.time, "sleep", waits.append)

    with artifact_lock(tmp_path, "a" * 64):
        assert (tmp_path / ("a" * 64 + ".lock")).read_bytes() == b"\0"

    assert backend.acquisitions == 2
    assert backend.releases == 1
    assert backend.calls == [
        (backend.LK_NBLCK, 0, 1),
        (backend.LK_NBLCK, 0, 1),
        (backend.LK_UNLCK, 0, 1),
    ]
    assert waits == [0.05]


@pytest.mark.parametrize("body_fails", [False, True], ids=["clean-body", "body-error"])
def test_windows_unlock_failure_preserves_error_taxonomy_and_body_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    body_fails: bool,
) -> None:
    """Classify unlock failures without replacing an active body exception.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible attribute patches.
        caplog: Pytest fixture capturing release-failure diagnostics.
        body_fails: Whether the protected critical section raises first.
    """

    class WindowsLock:
        """Simulate successful acquisition followed by failed release."""

        LK_NBLCK = 1
        LK_UNLCK = 2

        def locking(self, descriptor: int, mode: int, size: int) -> None:
            """Raise only while releasing the synthetic Windows lock.

            Args:
                descriptor: Open lock-file descriptor.
                mode: Nonblocking acquisition or release mode.
                size: Number of bytes in the locked region.
            """
            assert descriptor >= 0
            assert size == 1
            if mode == self.LK_UNLCK:
                raise OSError("synthetic unlock failure")

    monkeypatch.setattr(cache_module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(cache_module, "msvcrt", WindowsLock(), raising=False)

    if body_fails:
        with pytest.raises(LookupError, match="critical-section failure") as captured:
            with artifact_lock(tmp_path, "b" * 64):
                raise LookupError("critical-section failure")
        assert str(captured.value) == "critical-section failure"
        assert "Unable to release cache artifact lock" in caplog.text
        assert "synthetic unlock failure" in caplog.text
    else:
        with pytest.raises(
            errors.DriverManagerError, match="Unable to release cache artifact lock"
        ):
            with artifact_lock(tmp_path, "b" * 64):
                pass


def test_child_report_falls_back_when_atomic_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain diagnostics when an atomic report replacement is unavailable.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible attribute patches.
    """
    report = tmp_path / "child.json"
    original_replace = Path.replace

    def replace(path: Path, target: Path) -> Path:
        """Reject only the target replacement exercised by this regression.

        Args:
            path: Temporary diagnostic path.
            target: Requested final diagnostic path.

        Returns:
            Result delegated to the original method for unrelated paths.

        Raises:
            OSError: The target diagnostic replacement is deliberately rejected.
        """
        if path == report.with_suffix(".json.tmp") and target == report:
            raise OSError("synthetic sharing failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    write_child_report(report, "error", "child traceback")

    assert json.loads(report.read_text()) == {
        "status": "error",
        "detail": "child traceback",
        "report_error": "synthetic sharing failure",
    }
    assert not report.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize(
    "relative",
    [
        Path(),
        Path("not-an-artifact") / "driver",
        Path("A" * 64) / "driver",
        Path("a" * 64) / ".." / "other" / "driver",
    ],
    ids=["cache-root", "malformed-key", "uppercase-key", "parent-traversal"],
)
def test_lease_ignores_paths_without_a_canonical_artifact_key(
    tmp_path: Path, relative: Path
) -> None:
    """Return no lease for the cache root or a malformed artifact directory.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        relative: Candidate path relative to the platform cache root.
    """
    cache = ChromeFileManager(tmp_path).for_platform("linux", "64")
    candidate = cache._directory / relative
    locks_before = set(cache._directory.glob("*.lock"))

    assert cache.lease(candidate) is None
    assert set(cache._directory.glob("*.lock")) == locks_before


def test_recovery_after_process_dies_between_publish_and_commit(tmp_path: Path) -> None:
    """Verify recovery after process dies between publish and commit.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    process = multiprocessing.get_context("spawn").Process(
        target=install, args=(str(tmp_path), "120.0.1.1", True)
    )
    process.start()
    process.join(15)
    if process.is_alive():
        process.kill()
        process.join(5)
        pytest.fail("Crash fixture exceeded deadline")
    assert process.exitcode == 17
    recovered = install(str(tmp_path))
    assert Path(recovered["location"]).read_bytes() == b"fixture-never-executed"


def test_platform_and_artifact_identity_are_isolated(tmp_path: Path) -> None:
    """Verify platform and artifact identity are isolated.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    install(str(tmp_path))
    cache = ChromeFileManager(str(tmp_path))
    version = ChromiumVersion("120.0.1.1")
    assert cache.for_platform("linux", "64").match_driver(version)
    assert cache.for_platform("linux", "64", True).match_driver(version) is None
    assert cache.for_platform("win", "64").match_driver(version) is None
    assert cache.for_platform("linux", "64").match_binary(version) is None


def test_lease_queries_use_artifact_index(tmp_path: Path) -> None:
    """Verify lease queries use artifact index.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    cache = ChromeFileManager(str(tmp_path))
    with cache._db() as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM leases WHERE key=?", ("fixture",)
        ).fetchall()
    assert any("lease_artifact_lookup" in row[3] for row in plan)


def test_lease_requires_the_exact_indexed_executable(tmp_path: Path) -> None:
    """Do not lease an artifact merely because a path shares its cache-key folder.

    Args:
        tmp_path: Isolated cache parent directory supplied by pytest.
    """
    entry = install(tmp_path)
    cache = ChromeFileManager(tmp_path).for_platform("linux", "64")
    unrelated = entry["location"].with_name("unrelated-file")
    unrelated.write_bytes(b"not the indexed executable")

    assert cache.lease(unrelated) is None


@pytest.mark.parametrize("protection", ["pin", "lease"])
def test_pruning_respects_pins_and_live_leases(tmp_path: Path, protection: Any) -> None:
    """Verify pruning respects pins and live leases.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        protection: Fixture or parametrized protection input for this regression.
    """
    first = install(str(tmp_path))
    cache = ChromeFileManager(str(tmp_path)).for_platform("linux", "64")
    if protection == "pin":
        cache.pin(ChromiumVersion("120.0.1.1"))
    else:
        token = cache.lease(first["location"])
    install(str(tmp_path), "121.0.1.1")
    cache.prune(limit=1)
    assert Path(first["location"]).exists()
    if protection == "pin":
        cache.pin(ChromiumVersion("120.0.1.1"), pinned=False)
    else:
        cache.release(token)
    cache.prune(limit=1)
    assert not Path(first["location"]).exists()


def test_checksum_change_is_not_a_cache_hit(tmp_path: Path) -> None:
    """Verify checksum change is not a cache hit.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    entry = install(str(tmp_path))
    Path(entry["location"]).write_bytes(b"changed fixture")
    cache = ChromeFileManager(str(tmp_path)).for_platform("linux", "64")
    assert cache.match_driver(ChromiumVersion("120.0.1.1")) is None
    with pytest.raises(errors.DriverManagerError, match="preserved"):
        install(str(tmp_path))


@pytest.mark.parametrize("corruption", ["schema", "bytes"])
def test_unknown_or_corrupt_database_is_preserved(
    tmp_path: Path, corruption: Any
) -> None:
    """Verify unknown or corrupt database is preserved.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        corruption: Fixture or parametrized corruption input for this regression.
    """
    cache = ChromeFileManager(str(tmp_path))
    path = Path(cache._database)
    if corruption == "schema":
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=99")
    else:
        path.write_bytes(b"not sqlite")
    previous = path.read_bytes()
    with pytest.raises(errors.DriverManagerError):
        ChromeFileManager(str(tmp_path))
    assert path.read_bytes() == previous


def test_legacy_cache_is_not_implicitly_read_or_changed(tmp_path: Path) -> None:
    """Verify legacy cache is not implicitly read or changed.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    root = tmp_path / ".aselenium"
    root.mkdir()
    legacy = root / "chrome_driver_metadata.feather"
    legacy.write_bytes(b"legacy fixture, deliberately not a valid feather")
    install(str(tmp_path))
    assert legacy.read_bytes() == b"legacy fixture, deliberately not a valid feather"


def test_stale_prune_keep_key_cannot_evict_everything(tmp_path: Path) -> None:
    """Verify stale prune keep key cannot evict everything.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    entry = install(str(tmp_path))
    cache = ChromeFileManager(str(tmp_path)).for_platform("linux", "64")
    cache.prune(limit=1, keep="f" * 64)
    assert Path(entry["location"]).exists()


@pytest.mark.asyncio
async def test_cancellation_waits_for_owned_worker(tmp_path: Path) -> None:
    """Verify cancellation waits for owned worker.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    started, release = threading.Event(), threading.Event()
    path = tmp_path / "worker-finished"

    def worker() -> None:
        """Run one owned worker operation for the enclosing workflow."""
        started.set()
        assert release.wait(5)
        path.touch()

    task = asyncio.create_task(run_blocking(worker))
    while not started.is_set():
        await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert path.exists()


def test_garbage_collection_preserves_unmarked_and_live_staging(tmp_path: Path) -> None:
    """Verify garbage collection preserves unmarked and live staging.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    cache = ChromeFileManager(str(tmp_path))
    unmarked = Path(cache._directory) / ".aselenium-stage-unknown"
    unmarked.mkdir()
    live = Path(cache._directory) / ".aselenium-stage-live"
    live.mkdir()
    owner = dict(key="0" * 64, pid=os.getpid(), started=psutil.Process().create_time())
    (live / "ownership.json").write_text(json.dumps(owner))
    dead = Path(cache._directory) / ".aselenium-stage-dead"
    dead.mkdir()
    owner["started"] = -1  # PID reuse/identity mismatch, not a living owner.
    (dead / "ownership.json").write_text(json.dumps(owner))
    assert cache.clean_staging() == 1
    assert live.exists() and unmarked.exists()
    assert not dead.exists()
