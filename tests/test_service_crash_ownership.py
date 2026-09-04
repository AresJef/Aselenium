"""Driver-crash cleanup regressions using identity-aware process boundaries."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from psutil import AccessDenied, NoSuchProcess, TimeoutExpired

from aselenium import errors
from aselenium import session as session_module
from aselenium.chrome.options import ChromeOptions
from aselenium.manager.version import ChromiumVersion
from aselenium.service import ChromiumBaseService
from aselenium.session import Session


class OwnedProcess:
    """Model process identity, ancestry, and exit without operating on real PIDs."""

    def __init__(self, pid: int) -> None:
        """Create a live, independently controlled process identity.

        Args:
            pid: Inert identifier used only in test assertions and exceptions.
        """
        self.pid = pid
        self.alive = True
        self.reused = False
        self.descendants: list[OwnedProcess] = []
        self.calls: list[str] = []
        self.query_error: Exception | None = None
        self.kill_error: Exception | None = None
        self.wait_error: Exception | None = None
        self.entered: threading.Event | None = None
        self.release: threading.Event | None = None

    def is_running(self) -> bool:
        """Check liveness and the original creation-time identity.

        Returns:
            Whether this original process, rather than a reused PID, survives.
        """
        return self.alive and not self.reused

    def children(self, recursive: bool = False) -> list[OwnedProcess]:
        """Enumerate only descendants of a still-matching process identity.

        Args:
            recursive: Whether to include descendants beyond direct children.

        Returns:
            Known live descendants, with recursive ancestry resolved when requested.

        Raises:
            NoSuchProcess: If the original process has exited or its PID was reused.
            Exception: If this fixture simulates an operating-system query failure.
        """
        self.calls.append("children")
        if self.entered is not None:
            self.entered.set()
        if self.release is not None and not self.release.wait(timeout=5):
            raise TimeoutError("Test did not release the process query")
        if not self.is_running():
            raise NoSuchProcess(self.pid)
        if self.query_error is not None:
            raise self.query_error
        result = [child for child in self.descendants if child.is_running()]
        if recursive:
            for child in tuple(result):
                result.extend(child._descendants())
        return result

    def _descendants(self) -> list[OwnedProcess]:
        """Resolve fixture ancestry without recording extra operating-system calls.

        Returns:
            Live descendants of this fixture process.
        """
        result: list[OwnedProcess] = []
        for child in self.descendants:
            if child.is_running():
                result.append(child)
                result.extend(child._descendants())
        return result

    def terminate(self) -> None:
        """Record a graceful signal for the original process only.

        Raises:
            NoSuchProcess: If this process has exited or its PID was reused.
        """
        if not self.is_running():
            raise NoSuchProcess(self.pid)
        self.calls.append("terminate")

    def kill(self) -> None:
        """Record a forced signal and exit unless a failure was requested.

        Raises:
            NoSuchProcess: If this process has exited or its PID was reused.
            Exception: If this fixture simulates a failed forced termination.
        """
        if not self.is_running():
            raise NoSuchProcess(self.pid)
        self.calls.append("kill")
        if self.kill_error is not None:
            raise self.kill_error
        self.alive = False

    def wait(self, timeout: float) -> None:
        """Record reaping, honoring the fixture's requested failure.

        Args:
            timeout: Positive bounded wait supplied by the service.

        Raises:
            Exception: If this fixture simulates an unreaped process.
        """
        assert timeout > 0
        self.calls.append("wait")
        if self.wait_error is not None:
            raise self.wait_error
        self.alive = False


@pytest.fixture
def owned_service(tmp_path: Path) -> ChromiumBaseService:
    """Create an actual service around a disposable, never-executed driver path.

    Args:
        tmp_path: Disposable directory supplied by pytest.

    Returns:
        Service with a synthetic driver and browser process tree.
    """
    executable = tmp_path / "driver"
    executable.touch()
    service = ChromiumBaseService(
        ChromiumVersion("120.0.1.1"), str(executable), timeout=0.1
    )
    driver = OwnedProcess(40001)
    driver.descendants = [OwnedProcess(40002)]
    service._process = driver
    service._popen = Mock()
    service._port = 41001
    return service


@pytest.fixture
def owned_session(
    owned_service: ChromiumBaseService, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Session]:
    """Retain actual session and cleanup logic while replacing transport and launch.

    Args:
        owned_service: Actual service containing inert owned process identities.
        monkeypatch: Fixture restoring the process-launch and HTTP boundaries.

    Yields:
        Session serving a successful W3C handshake and a default window.
    """
    options = ChromeOptions()
    connection = Mock()
    connection.execute = AsyncMock(
        side_effect=[
            {"value": {"sessionId": "owned-session"}},
            {"value": "owned-window"},
            {"value": None},
        ]
    )
    monkeypatch.setattr(session_module, "Connection", Mock(return_value=connection))
    monkeypatch.setattr(owned_service, "start", AsyncMock())
    monkeypatch.setattr(owned_service, "_ping_port", Mock(return_value=True))
    owned_service._session = Mock(closed=False, close=AsyncMock())
    session = Session(options, owned_service)
    try:
        yield session
    finally:
        options.close()


@pytest.mark.asyncio
async def test_driver_exit_after_start_retains_browser_ownership(
    owned_service: ChromiumBaseService, owned_session: Session
) -> None:
    """Clean up a browser after its driver crashes between startup and teardown.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    window = await owned_session.start()
    assert window.handle == "owned-window"
    driver.alive = False
    await owned_session.quit()
    assert not browser.alive
    assert browser.calls.count("terminate") == 1
    assert owned_service._owned_children == []
    assert owned_service._process is None


@pytest.mark.asyncio
async def test_late_renderer_is_discovered_from_surviving_browser(
    owned_service: ChromiumBaseService, owned_session: Session
) -> None:
    """Discover a renderer created after startup even after driver ancestry is lost.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    await owned_session.start()
    renderer = OwnedProcess(40003)
    browser.descendants.append(renderer)
    driver.alive = False
    await owned_session.quit()
    assert not browser.alive and not renderer.alive
    assert renderer.calls.count("terminate") == 1
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_late_renderer_is_captured_before_remote_quit_breaks_ancestry(
    owned_service: ChromiumBaseService, owned_session: Session
) -> None:
    """Retain late browser descendants before the protocol closes their parents.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    await owned_session.start()
    renderer = OwnedProcess(40003)
    browser.descendants.append(renderer)
    connection = session_module.Connection.return_value

    async def remote_quit(*args: object, **kwargs: object) -> dict[str, object]:
        """Simulate a protocol quit that exits parents before local teardown.

        Args:
            *args: Positional command values supplied by the session.
            **kwargs: Keyword command values supplied by the session.

        Returns:
            Successful W3C response after breaking the original ancestry.
        """
        driver.alive = False
        browser.alive = False
        return {"value": None}

    connection.execute.side_effect = remote_quit

    await owned_session.quit()

    assert not renderer.alive
    assert renderer.calls.count("terminate") == 1
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_failed_pre_quit_snapshot_retries_before_service_shutdown(
    owned_service: ChromiumBaseService,
    owned_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry process discovery before any fallback driver shutdown request.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
        monkeypatch: Fixture restoring the ordered teardown boundaries.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    await owned_session.start()
    renderer = OwnedProcess(40003)
    browser.descendants.append(renderer)
    events: list[str] = []

    async def failed_session_snapshot() -> None:
        """Simulate a transient operating-system process-query failure.

        Raises:
            ServiceProcessError: Always, before the session-level remote quit.
        """
        events.append("session-snapshot-failed")
        raise errors.ServiceProcessError("synthetic process inspection failure")

    original_capture = owned_service._capture_owned_children

    def service_snapshot() -> None:
        """Record and perform the service's authoritative local snapshot."""
        events.append("service-snapshot")
        original_capture()

    async def remote_shutdown() -> None:
        """Model shutdown severing parent ancestry after the safe retry."""
        events.append("remote-shutdown")
        driver.alive = False
        browser.alive = False

    monkeypatch.setattr(
        owned_service, "_capture_session_children", failed_session_snapshot
    )
    monkeypatch.setattr(owned_service, "_capture_owned_children", service_snapshot)
    monkeypatch.setattr(owned_service, "_shutdown_remote", remote_shutdown)

    await owned_session.quit()

    assert events[:3] == [
        "session-snapshot-failed",
        "service-snapshot",
        "remote-shutdown",
    ]
    assert not renderer.alive
    assert renderer.calls.count("terminate") == 1
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_failed_new_session_still_captures_created_browser(
    owned_service: ChromiumBaseService, owned_session: Session
) -> None:
    """Retain browser ownership when a driver launches it but returns bad session data.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    connection = session_module.Connection.return_value
    connection.execute.side_effect = [{"value": {}}]
    with pytest.raises(errors.InvalidSessionError):
        await owned_session.start()
    assert not browser.alive
    assert driver.calls.count("children") >= 2
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_handshake_failure_survives_failed_process_snapshot(
    owned_service: ChromiumBaseService,
    owned_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the primary transport failure when ownership inspection also fails.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
        monkeypatch: Fixture restoring the simulated inspection boundary.
    """
    primary = errors.SessionClientError("primary handshake failure")
    connection = session_module.Connection.return_value
    connection.execute.side_effect = primary
    capture = AsyncMock(
        side_effect=errors.ServiceProcessError("secondary process inspection failure")
    )
    monkeypatch.setattr(owned_service, "_capture_session_children", capture)
    monkeypatch.setattr(owned_service, "_shutdown_remote", AsyncMock())

    with pytest.raises(errors.SessionClientError) as captured:
        await owned_session.start()

    assert captured.value is primary
    assert capture.await_count == 2
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_valid_handshake_id_is_retained_before_process_snapshot_failure(
    owned_service: ChromiumBaseService,
    owned_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delete a valid remote session when its first ownership snapshot fails.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
        monkeypatch: Fixture restoring the simulated inspection boundary.
    """
    inspection_failure = errors.ServiceProcessError(
        "synthetic post-handshake inspection failure"
    )
    capture = AsyncMock(side_effect=[inspection_failure, None])
    monkeypatch.setattr(owned_service, "_capture_session_children", capture)
    connection = session_module.Connection.return_value

    with pytest.raises(errors.ServiceProcessError) as captured:
        await owned_session.start()

    assert captured.value is inspection_failure
    assert capture.await_count == 2
    assert connection.execute.await_args_list[1].args[:2] == (
        "/session/owned-session",
        session_module.Command.QUIT,
    )
    assert owned_service._owned_children == []


@pytest.mark.parametrize(
    "failure",
    [asyncio.CancelledError(), errors.SessionClientError("Handshake transport failed")],
)
@pytest.mark.asyncio
async def test_interrupted_handshake_captures_and_cleans_created_browser(
    owned_service: ChromiumBaseService,
    owned_session: Session,
    failure: BaseException,
) -> None:
    """Capture launched browsers even when the handshake transport never returns data.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
        failure: Transport cancellation or failure raised after browser creation.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    connection = session_module.Connection.return_value
    connection.execute.side_effect = [failure]
    with pytest.raises(type(failure)) as captured:
        await owned_session.start()
    assert captured.value is failure
    assert not browser.alive
    assert driver.calls.count("children") >= 2
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_lost_browser_root_does_not_hide_known_renderer_descendants(
    owned_service: ChromiumBaseService, owned_session: Session
) -> None:
    """Continue from a remembered renderer when both its driver and browser exit.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    renderer = OwnedProcess(40003)
    browser.descendants.append(renderer)
    await owned_session.start()
    worker = OwnedProcess(40004)
    renderer.descendants.append(worker)
    driver.alive = False
    browser.alive = False
    await owned_session.quit()
    assert not renderer.alive and not worker.alive
    assert renderer.calls.count("children") >= 2
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_started_browser_snapshot_does_not_block_event_loop(
    owned_service: ChromiumBaseService, owned_session: Session
) -> None:
    """Drain an in-flight ownership query before propagating startup cancellation.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    driver.entered = threading.Event()
    driver.release = threading.Event()
    task = asyncio.create_task(owned_session.start())

    async def wait_for_query() -> None:
        """Yield until the ownership query begins or startup finishes unexpectedly."""
        while not driver.entered.is_set() and not task.done():
            await asyncio.sleep(0.001)

    try:
        await asyncio.wait_for(wait_for_query(), timeout=2)
        assert driver.entered.is_set(), "Startup must capture owned browser processes"
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done(), "Cancellation must wait for the ownership query"
    finally:
        driver.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert not browser.alive
    assert owned_service._owned_children == []


@pytest.mark.asyncio
async def test_cancelled_teardown_drains_ownership_refresh_before_signalling(
    owned_service: ChromiumBaseService,
) -> None:
    """Finish owned cleanup despite repeated cancellation during a blocked tree query.

    Args:
        owned_service: Actual service with inert process boundaries.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    owned_service._owned_children = [browser]
    driver.alive = False
    browser.entered = threading.Event()
    browser.release = threading.Event()
    task = asyncio.create_task(owned_service.stop())

    async def wait_for_query() -> None:
        """Yield until the teardown ownership query starts or finishes unexpectedly."""
        while not browser.entered.is_set() and not task.done():
            await asyncio.sleep(0.001)

    try:
        await asyncio.wait_for(wait_for_query(), timeout=2)
        assert browser.entered.is_set()
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and browser.alive
    finally:
        browser.release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert not browser.alive
    assert owned_service._owned_children == []
    assert owned_service._process is None and owned_service._popen is None


@pytest.mark.parametrize("parent_present", [True, False])
def test_remembered_children_are_cleaned_without_a_live_parent(
    owned_service: ChromiumBaseService, parent_present: bool
) -> None:
    """Keep retained descendants actionable even without a driver process handle.

    Args:
        owned_service: Actual service with inert process boundaries.
        parent_present: Whether the original, now-exited driver handle is retained.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    renderer = OwnedProcess(40003)
    browser.descendants.append(renderer)
    owned_service._owned_children = [browser]
    driver.alive = False
    if not parent_present:
        owned_service._process = None
        owned_service._popen = None
    owned_service._stop_process()
    assert not browser.alive and not renderer.alive
    assert owned_service._owned_children == []


@pytest.mark.parametrize("reused", ["driver", "browser", "both"])
def test_reused_pids_are_neither_queried_nor_signalled(
    owned_service: ChromiumBaseService, reused: str
) -> None:
    """Never traverse or terminate an unrelated process that inherited an old PID.

    Args:
        owned_service: Actual service with inert process boundaries.
        reused: Which original process identities have been replaced.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    unrelated = OwnedProcess(40999)
    owned_service._owned_children = [browser]
    if reused in {"driver", "both"}:
        driver.reused = True
        driver.descendants = [unrelated]
    if reused in {"browser", "both"}:
        browser.reused = True
        browser.descendants = [unrelated]
    owned_service._stop_process()
    assert unrelated.calls == [] and unrelated.alive
    if driver.reused:
        assert driver.calls == []
    if browser.reused:
        assert browser.calls == []
    assert owned_service._owned_children == []


def test_failed_orphan_kill_preserves_original_identity_for_retry(
    owned_service: ChromiumBaseService,
) -> None:
    """Retain a failed browser termination and clean up newly created children later.

    Args:
        owned_service: Actual service with inert process boundaries.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    owned_service._owned_children = [browser]
    driver.alive = False
    browser.kill_error = AccessDenied(browser.pid)
    with pytest.raises(errors.ServiceProcessError, match="ownership retained"):
        owned_service._stop_process()
    assert owned_service._owned_children == [browser]
    assert owned_service._process is driver
    assert owned_service._popen is not None
    renderer = OwnedProcess(40003)
    browser.descendants.append(renderer)
    browser.kill_error = None
    owned_service._stop_process()
    assert not browser.alive and not renderer.alive
    assert owned_service._owned_children == []
    assert owned_service._process is None and owned_service._popen is None


def test_descendant_query_failure_keeps_ownership_and_can_be_retried(
    owned_service: ChromiumBaseService,
) -> None:
    """Do not report successful teardown when owned descendants cannot be enumerated.

    Args:
        owned_service: Actual service with inert process boundaries.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    owned_service._owned_children = [browser]
    driver.alive = False
    browser.query_error = AccessDenied(browser.pid)
    with pytest.raises(errors.ServiceProcessError, match="ownership retained"):
        owned_service._stop_process()
    assert owned_service._owned_children == [browser]
    assert browser.alive
    browser.query_error = None
    owned_service._stop_process()
    assert not browser.alive and owned_service._owned_children == []


@pytest.mark.asyncio
async def test_startup_snapshot_failure_retains_service_until_cleanup_succeeds(
    owned_service: ChromiumBaseService, owned_session: Session
) -> None:
    """Surface snapshot failure and retain the live service for a later cleanup retry.

    Args:
        owned_service: Actual service with inert process boundaries.
        owned_session: Actual session with an independently specified handshake.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    driver.query_error = AccessDenied(driver.pid)
    with pytest.raises(errors.ServiceProcessError, match="ownership retained"):
        await owned_session.start()
    assert owned_service._process is driver and browser.alive
    driver.query_error = None
    await owned_session.quit()
    assert owned_service._process is None and not browser.alive


def test_living_driver_refresh_queries_tree_once(
    owned_service: ChromiumBaseService,
) -> None:
    """Avoid redundant recursive scans when a live driver covers known descendants.

    Args:
        owned_service: Actual service with inert process boundaries.
    """
    driver = owned_service._process
    browser = driver.descendants[0]
    renderer = OwnedProcess(40003)
    browser.descendants.append(renderer)
    owned_service._owned_children = [browser, renderer]
    owned_service._stop_process()
    assert driver.calls.count("children") == 1
    assert browser.calls.count("children") == 0
    assert renderer.calls.count("children") == 0


def test_driver_termination_timeout_still_escalates(
    owned_service: ChromiumBaseService,
) -> None:
    """Retain the established terminate-then-kill contract after ownership refresh.

    Args:
        owned_service: Actual service with inert process boundaries.
    """
    driver = owned_service._process
    driver.wait_error = TimeoutExpired(0.01, pid=driver.pid)
    with pytest.raises(errors.ServiceProcessError, match="ownership retained"):
        owned_service._stop_process()
    assert driver.calls.count("terminate") == 1
    assert driver.calls.count("kill") == 1
    assert owned_service._process is driver
    driver.wait_error = None
    owned_service._stop_process()
    assert owned_service._process is None
