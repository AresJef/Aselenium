"""Regressions found by the original 12-step second-pass audit."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from psutil import NoSuchProcess

from aselenium import _output, errors
from aselenium._wait import DEADLINE, poll
from aselenium.actions import Actions
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.connection import Connection
from aselenium.manager.version import ChromiumVersion
from aselenium.options import Proxy
from aselenium.safari.options import SafariOptions
from aselenium.service import ChromiumBaseService
from aselenium.session import Session
from aselenium.utils import Rectangle, validate_save_file_path
from aselenium.webdriver import SessionContext


def test_step02_invalid_rectangle_raises_package_error() -> None:
    """Verify step02 invalid rectangle raises package error."""
    with pytest.raises(errors.InvalidRectValueError):
        Rectangle(None, 10, 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, [], {}, {"sessionId": 1}, {"sessionId": ""}])
async def test_step04_new_session_requires_nonempty_string_id(value: Any) -> None:
    """Verify step04 new session requires nonempty string id.

    Args:
        value: Fixture or parametrized value input for this regression.
    """
    service = SimpleNamespace(
        _driver_version=None, _driver_location="fixture", url="fixture", running=True
    )
    session = Session(ChromeOptions(), service)
    session._conn = SimpleNamespace(execute=AsyncMock(return_value={"value": value}))
    with pytest.raises(errors.InvalidSessionError):
        await session._start_session()


@pytest.mark.asyncio
async def test_step09_new_session_capability_encoding_runs_off_loop() -> None:
    """Verify step09 new session capability encoding runs off loop."""
    main_thread = threading.get_ident()

    class CheckedOptions(ChromeOptions):
        """Represent CheckedOptions using the inherited implementation."""

        @property
        def capabilities(self) -> Any:
            """Capabilities.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            assert threading.get_ident() != main_thread
            return super().capabilities

    service = SimpleNamespace(
        _driver_version=None, _driver_location="fixture", url="fixture", running=True
    )
    session = Session(CheckedOptions(), service)
    session._conn = SimpleNamespace(
        execute=AsyncMock(return_value={"value": {"sessionId": "fixture"}})
    )
    session._active_window_handle = AsyncMock(return_value="window")
    await session._start_session()
    assert session.id == "fixture"


@pytest.mark.asyncio
async def test_step05_failed_start_cannot_overwrite_resources_before_quit() -> None:
    """Verify step05 failed start cannot overwrite resources before quit."""
    original = SimpleNamespace(
        quit=AsyncMock(side_effect=errors.ServiceProcessError("still owned"))
    )
    manager = SimpleNamespace(install_result=AsyncMock())
    context = SessionContext(manager, (), {}, object, 1, (), {}, SimpleNamespace())
    context._session = original
    context._state = "starting"
    with pytest.raises(errors.InvalidSessionError, match="quit"):
        await context.start()
    manager.install_result.assert_not_awaited()
    assert context._session is original
    original.quit.side_effect = None
    await context.quit()
    assert context._state == "closed"


def test_step05_child_ownership_survives_parent_exit(tmp_path: Path) -> None:
    """Verify step05 child ownership survives parent exit.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    path = tmp_path / "driver"
    path.touch()
    service = ChromiumBaseService(ChromiumVersion("120.0.1.1"), str(path))
    child = SimpleNamespace(
        children=lambda **kwargs: [],
        terminate=lambda: None,
        is_running=lambda: True,
        kill=lambda: None,
        wait=lambda **kw: None,
    )
    attempts = []

    def child_wait(**kwargs: Any) -> None:
        """Child wait.

        Args:
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError("temporary fixture")

    child.wait = child_wait
    parent_alive = [True]

    def children(**kwargs: Any) -> Any:
        """Children.

        Args:
            **kwargs: Fixture or parametrized kwargs input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        if not parent_alive[0]:
            raise NoSuchProcess(12345)
        return [child]

    def terminate() -> None:
        """Terminate."""
        parent_alive[0] = False

    service._process = SimpleNamespace(
        is_running=lambda: parent_alive[0],
        children=children,
        terminate=terminate,
        wait=lambda **kw: None,
        kill=lambda: None,
    )
    with pytest.raises(errors.ServiceProcessError):
        service._stop_process()
    service._stop_process()
    assert len(attempts) == 2
    assert service._process is None


@pytest.mark.parametrize(
    "name,expected", [("capture", "capture.png"), ("capture.png", "capture.png")]
)
def test_step02_relative_output_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: Any, expected: Any
) -> None:
    """Verify step02 relative output filename.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        name: Fixture or parametrized name input for this regression.
        expected: Fixture or parametrized expected input for this regression.
    """
    monkeypatch.chdir(tmp_path)
    assert validate_save_file_path(name, ".png") == str(tmp_path / expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_name", ["_command_lock", "_wire_lock"])
async def test_step04_command_deadline_includes_queueing(lock_name: Any) -> None:
    """Verify step04 command deadline includes queueing.

    Args:
        lock_name: Fixture or parametrized lock name input for this regression.
    """
    connection = Connection(SimpleNamespace(), 0.02)
    connection._execute = AsyncMock(return_value={"value": None})
    lock = getattr(connection, lock_name)
    await lock.acquire()
    try:
        with pytest.raises(errors.SessionTimeoutError):
            await asyncio.wait_for(
                connection.execute("/session/id", Command.GET_TITLE), 0.5
            )
        connection._execute.assert_not_awaited()
    finally:
        lock.release()
    assert await connection.execute("/session/id", Command.GET_TITLE) == {"value": None}


def test_step06_arguments_are_atomic_on_validation_failure() -> None:
    """Verify step06 arguments are atomic on validation failure."""
    options = ChromeOptions()
    before = options.capabilities
    with pytest.raises(errors.InvalidOptionsError):
        options.add_arguments("--valid", None)
    assert "--valid" not in options.arguments
    assert options.capabilities == before


def test_step06_extension_batch_is_atomic() -> None:
    """Verify step06 extension batch is atomic."""
    options = ChromeOptions()
    with pytest.raises(errors.InvalidExtensionError):
        options.add_extensions_base64("YQ==", None)
    assert options.extensions == []


def test_step06_proxy_mutation_is_reflected_in_future_capabilities() -> None:
    """Verify step06 proxy mutation is reflected in future capabilities."""
    options = ChromeOptions()
    options.proxy = Proxy(http_proxy="http://first.invalid:80")
    assert options.capabilities["proxy"]["httpProxy"] == "first.invalid:80"
    snapshot = options.snapshot()
    options.proxy.http_proxy = "http://second.invalid:80"
    assert options.capabilities["proxy"]["httpProxy"] == "second.invalid:80"
    assert snapshot.capabilities["proxy"]["httpProxy"] == "first.invalid:80"


def test_step06_returned_and_supplied_capabilities_are_independent() -> None:
    """Verify step06 returned and supplied capabilities are independent."""
    options = ChromeOptions()
    supplied = {"nested": [1]}
    options.set_capability("vendor:fixture", supplied)
    supplied["nested"].append(2)
    returned = options.capabilities
    returned["vendor:fixture"]["nested"].append(3)
    assert options.capabilities["vendor:fixture"] == {"nested": [1]}


def test_step06_proxy_bypass_uses_w3c_array_and_copies_it() -> None:
    """Verify step06 proxy bypass uses w3c array and copies it."""
    proxy = Proxy(no_proxy="localhost, .example.invalid")
    caps = proxy.to_capabilities()
    assert caps["noProxy"] == ["localhost", ".example.invalid"]
    caps["noProxy"].append("mutated")
    assert proxy.to_capabilities()["noProxy"] == ["localhost", ".example.invalid"]


def test_step06_autodetect_does_not_send_nonstandard_flag() -> None:
    """Verify step06 autodetect does not send nonstandard flag."""
    assert Proxy(auto_detect=True).to_capabilities() == {"proxyType": "autodetect"}


@pytest.mark.parametrize(
    "field,key",
    [
        ("automatic_inspection", "safari:automaticInspection"),
        ("automatic_profiling", "safari:automaticProfiling"),
        ("technology_preview", "browserName"),
    ],
)
def test_step11_safari_option_changes_invalidate_capabilities(
    field: Any, key: Any
) -> None:
    """Verify step11 safari option changes invalidate capabilities.

    Args:
        field: Fixture or parametrized field input for this regression.
        key: Fixture or parametrized key input for this regression.
    """
    options = SafariOptions()
    before = options.capabilities
    setattr(options, field, True)
    assert options.capabilities.get(key) != before.get(key)
    setattr(options, field, False)
    assert options.capabilities == before


@pytest.mark.parametrize("duration", [True, float("inf"), float("nan"), -1])
def test_step11_action_duration_rejects_invalid_values(duration: Any) -> None:
    """Verify step11 action duration rejects invalid values.

    Args:
        duration: Fixture or parametrized duration input for this regression.
    """
    with pytest.raises(errors.InvalidArgumentError):
        Actions(SimpleNamespace(), duration=duration)


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", [0, -1, True, float("nan"), float("inf")])
async def test_step10_invalid_poll_interval_fails_before_predicate(
    interval: Any,
) -> None:
    """Verify step10 invalid poll interval fails before predicate.

    Args:
        interval: Fixture or parametrized interval input for this regression.
    """
    check = AsyncMock(return_value=True)
    with pytest.raises(errors.InvalidArgumentError):
        await poll(check, 1, interval)
    check.assert_not_awaited()


@pytest.mark.asyncio
async def test_step10_nested_wait_cannot_extend_parent_deadline() -> None:
    """Verify step10 nested wait cannot extend parent deadline."""

    async def outer() -> Any:
        """Outer.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return await poll(AsyncMock(return_value=False), 60)

    assert not await asyncio.wait_for(poll(outer, 0.02), 0.5)
    assert DEADLINE.get() is None


@pytest.mark.asyncio
async def test_step09_output_failure_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify step09 output failure preserves previous file.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    path = tmp_path / "capture.png"
    path.write_bytes(b"previous")

    def fail(*args: Any) -> None:
        """Fail.

        Args:
            *args: Fixture or parametrized args input for this regression.
        """
        raise PermissionError("fixture")

    monkeypatch.setattr(_output.os, "replace", fail)
    assert not await _output.save_bytes(str(path), b"replacement")
    assert path.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.asyncio
async def test_step09_output_write_does_not_block_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify step09 output write does not block event loop.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    started, release = threading.Event(), threading.Event()
    original = _output._write_atomic

    def slow(*args: Any) -> None:
        """Slow.

        Args:
            *args: Fixture or parametrized args input for this regression.
        """
        started.set()
        assert release.wait(2)
        original(*args)

    monkeypatch.setattr(_output, "_write_atomic", slow)
    task = asyncio.create_task(
        _output.save_bytes(str(tmp_path / "capture.png"), b"fixture")
    )
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert (tmp_path / "capture.png").read_bytes() == b"fixture"
