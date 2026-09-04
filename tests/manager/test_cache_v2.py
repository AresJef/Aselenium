"""SQLite, ownership, recovery and independent-process cache regressions."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import sqlite3
import threading
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import psutil
import pytest

from aselenium import errors
from aselenium._async import run_blocking
from aselenium.manager.file import ChromeDriverFile, ChromeFileManager
from aselenium.manager.version import ChromiumVersion


def archive() -> Any:
    """Archive.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    stream = BytesIO()
    with ZipFile(stream, "w") as output:
        output.writestr("chromedriver", b"fixture-never-executed")
    return ChromeDriverFile(
        "linux", "https://example.invalid/driver.zip", stream.getvalue()
    )


def install(base: Any, version: str = "120.0.1.1", crash: bool = False) -> Any:
    """Install.

    Args:
        base: Fixture or parametrized base input for this regression.
        version: Fixture or parametrized version input for this regression.
        crash: Fixture or parametrized crash input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    cache = ChromeFileManager(base).for_platform("linux", "64")
    if crash:
        cache._publish = lambda row: os._exit(17)
    return cache.cache_driver(ChromiumVersion(version), archive())


def test_independent_processes_publish_one_artifact(tmp_path: Path) -> None:
    """Verify independent processes publish one artifact.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    context = multiprocessing.get_context("spawn")
    jobs = [context.Process(target=install, args=(str(tmp_path),)) for _ in range(3)]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(15)
        if job.is_alive():
            job.kill()
            job.join(5)
            pytest.fail("Cache process exceeded deadline")
        assert job.exitcode == 0
    cache = ChromeFileManager(str(tmp_path)).for_platform("linux", "64")
    assert cache.cached_versions() == ["120.0.1.1"]
    assert len(list(Path(cache._directory).glob("*/artifact.json"))) == 1


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
