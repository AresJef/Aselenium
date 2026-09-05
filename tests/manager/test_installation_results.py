"""Immutable results, request-local state and acquisition handoff contracts."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aselenium import errors
from aselenium.chrome.options import ChromeOptions
from aselenium.manager import ChromeDriverManager, ChromiumVersion
from aselenium.manager._installation import owned_gather
from aselenium.webdriver import SessionContext


def prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Prepare.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    manager = ChromeDriverManager(str(tmp_path))
    browser = tmp_path / "fixture browser"
    browser.touch()
    monkeypatch.setattr(
        manager, "_detect_browser_version", lambda _: ChromiumVersion("120.0.1.1")
    )
    monkeypatch.setattr(manager, "_match_driver_executable", lambda *_: None)

    async def resolve(version: Any) -> Any:
        """Resolve.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return version

    async def download(version: Any) -> Any:
        """Download.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        await asyncio.sleep(0)
        manager._driver_version = ChromiumVersion(str(version))
        manager._driver_location = tmp_path / ("driver-" + str(version))
        return manager._driver_location

    monkeypatch.setattr(manager, "_request_driver_version", resolve)
    monkeypatch.setattr(manager, "_install_driver_executable", download)
    return manager, str(browser)


@pytest.mark.asyncio
async def test_result_is_immutable_and_does_not_change_after_later_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify result is immutable and does not change after later install.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = prepare(tmp_path, monkeypatch)
    first, second = await asyncio.gather(
        manager.install_result("120.0.1.1", binary=browser),
        manager.install_result("121.0.1.1", binary=browser),
    )
    assert first.driver_version == first.request.version == "120.0.1.1"
    assert second.driver_version == second.request.version == "121.0.1.1"
    assert first.driver_location != second.driver_location
    with pytest.raises(FrozenInstanceError):
        first.driver_version = "broken"
    with pytest.raises(FrozenInstanceError):
        first.request.version = "broken"
    manager.reset()
    assert manager.last_result is None
    assert first.driver_version == "120.0.1.1"


@pytest.mark.asyncio
async def test_failed_request_does_not_clear_another_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify failed request does not clear another success.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = prepare(tmp_path, monkeypatch)
    result = await manager.install_result("120.0.1.1", binary=browser)
    with pytest.raises(errors.BrowserBinaryNotDetectedError):
        await manager.install_result("121.0.1.1", binary=str(tmp_path / "missing"))
    assert manager.last_result == result
    assert manager.driver_location == result.driver_location


@pytest.mark.asyncio
async def test_inflight_target_fields_are_not_visible_in_an_unrelated_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify inflight target fields are not visible in an unrelated task.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = prepare(tmp_path, monkeypatch)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def download(version: Any) -> Any:
        """Download.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        entered.set()
        await release.wait()
        manager._driver_version = version
        return tmp_path / "driver"

    monkeypatch.setattr(manager, "_install_driver_executable", download)
    task = asyncio.create_task(manager.install_result("120.0.1.1", binary=browser))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert manager._target_version is None
        assert manager._browser_location is None
        assert manager.last_result is None
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_distinct_cache_roots_can_install_without_a_global_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify distinct cache roots can install without a global lock.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots:
        root.mkdir()
    instances = [prepare(root, monkeypatch) for root in roots]
    started = []
    both = asyncio.Event()

    async def download(version: Any) -> Any:
        """Download.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        started.append(1)
        if len(started) == 2:
            both.set()
        await both.wait()
        return tmp_path / "driver"

    for manager, _ in instances:
        monkeypatch.setattr(manager, "_install_driver_executable", download)
    await asyncio.wait_for(
        asyncio.gather(
            *(
                manager.install("120.0.1.1", binary=browser)
                for manager, browser in instances
            )
        ),
        2,
    )


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_owned_sibling_cleanup() -> None:
    """Verify repeated cancellation waits for owned sibling cleanup."""
    entered = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    children = []

    async def child() -> None:
        """Child."""
        children.append(asyncio.current_task())
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()

    parent = asyncio.create_task(owned_gather(child()))
    await entered.wait()
    parent.cancel()
    await cleanup_started.wait()
    parent.cancel()
    await asyncio.sleep(0)
    assert not parent.done()
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(parent, 2)
    assert all(child.done() for child in children)


@pytest.mark.asyncio
async def test_acquisition_consumes_its_result_even_after_a_later_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify acquisition consumes its result even after a later install.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = prepare(tmp_path, monkeypatch)
    result = await manager.install_result("120.0.1.1", binary=browser)
    later = await manager.install_result("121.0.1.1", binary=browser)

    async def delayed_result(*args: Any, **kwargs: Any) -> Any:
        """Delayed result.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return result

    monkeypatch.setattr(manager, "install_result", delayed_result)
    services = []

    def service(version: Any, path: Any, *args: Any, **kwargs: Any) -> Any:
        """Service.

        Args:
            version: Fixture or parametrized version input for this regression.
            path: Fixture or parametrized path input for this regression.
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        services.append((str(version), path))
        return SimpleNamespace()

    class Session:
        """Represent Session using the inherited implementation."""

        def __init__(self, options: Any, service: Any) -> None:
            """Initialize the instance with the supplied configuration.

            Args:
                options: Fixture or parametrized options input for this regression.
                service: Fixture or parametrized service input for this regression.
            """
            self.options = options

        async def start(self) -> None:
            """Start."""
            pass

        async def quit(self) -> None:
            """Quit."""
            pass

    options = ChromeOptions()
    context = SessionContext(manager, (), {}, service, 10, (), {}, options)
    context._SESSION_CLS = Session
    session = await context.start()
    try:
        assert services == [(result.driver_version, result.driver_location)]
        assert services[0][1] != later.driver_location
        assert str(session.options.browser_version) == result.browser_version
    finally:
        await context.quit()
