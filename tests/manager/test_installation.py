"""Driver installation contracts exercised without browsers or network access.

Strict xfails document confirmed defects, not unsupported environments. All fake
downloads are cooperative and bounded, including when pytest uses --runxfail.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aselenium.manager.driver import (
    ChromeDriverManager,
    ChromiumDriverManager,
    EdgeDriverManager,
    FirefoxDriverManager,
)
from aselenium.manager.version import ChromiumVersion, FirefoxVersion, GeckoVersion

_TIMEOUT = 3.0
_CHROMIUM_MANAGERS = [
    pytest.param(ChromeDriverManager, False, id="chrome"),
    pytest.param(ChromiumDriverManager, False, id="chromium"),
    pytest.param(EdgeDriverManager, False, id="edge"),
    pytest.param(ChromeDriverManager, True, id="chrome-for-testing"),
]
_ALL_MANAGERS = [
    *_CHROMIUM_MANAGERS,
    pytest.param(FirefoxDriverManager, False, id="firefox"),
]


def _manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any
) -> Any:
    """Use actual construction/cache metadata, but never execute a browser.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    manager = manager_class(directory=str(tmp_path))
    browser = tmp_path / "synthetic browser"
    browser.touch()
    browser_version = (
        FirefoxVersion("120.0")
        if isinstance(manager, FirefoxDriverManager)
        else ChromiumVersion("120.0.6099.71")
    )
    monkeypatch.setattr(
        manager, "_detect_browser_version", lambda _path: browser_version
    )
    return manager, browser


def _cache_miss(manager: Any, monkeypatch: pytest.MonkeyPatch, cft: bool) -> None:
    """Cache miss.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        cft: Fixture or parametrized cft input for this regression.
    """
    monkeypatch.setattr(manager, "_match_driver_executable", lambda *_args: None)
    if cft:
        monkeypatch.setattr(
            manager, "_match_cft_driver_and_binary", lambda *_args: None
        )


async def _install(manager: Any, version: str, browser: Path, cft: bool) -> Any:
    """Install.

    Args:
        manager: Fixture or parametrized manager input for this regression.
        version: Fixture or parametrized version input for this regression.
        browser: Fixture or parametrized browser input for this regression.
        cft: Fixture or parametrized cft input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    if cft:
        return await manager.install(version, channel="cft")
    return await manager.install(version, binary=browser)


async def _drain(tasks: Any) -> None:
    """Cancel and consume every explicitly owned task, even after assertions.

    Args:
        tasks: Fixture or parametrized tasks input for this regression.
    """
    owned = set(tasks)
    for task in owned:
        if not task.done():
            task.cancel()
    if owned:
        await asyncio.wait_for(asyncio.gather(*owned, return_exceptions=True), _TIMEOUT)


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_class,cft", _CHROMIUM_MANAGERS)
@pytest.mark.regression
async def test_exact_version_pin_is_preserved_on_cache_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any, cft: Any
) -> None:
    """Verify exact version pin is preserved on cache miss.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        cft: Fixture or parametrized cft input for this regression.
    """
    manager, browser = _manager(tmp_path, monkeypatch, manager_class)
    _cache_miss(manager, monkeypatch, cft)
    pinned = "120.0.6099.71"
    latest = "120.0.6099.109"
    monkeypatch.setattr(
        manager, "_request_response_text", AsyncMock(return_value=latest)
    )

    async def download(version: Any) -> Any:
        """Download.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return tmp_path / str(version)

    monkeypatch.setattr(manager, "_install_driver_executable", download)
    if cft:
        monkeypatch.setattr(manager, "_install_browser_binary", download)

    installed = await asyncio.wait_for(
        _install(manager, pinned, browser, cft), _TIMEOUT
    )

    assert installed == tmp_path / pinned, (
        "A full version pin must not depend on cache contents."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_class,cft", _ALL_MANAGERS)
@pytest.mark.regression
async def test_concurrent_installs_keep_request_versions_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any, cft: Any
) -> None:
    """Verify concurrent installs keep request versions isolated.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        cft: Fixture or parametrized cft input for this regression.
    """
    manager, browser = _manager(tmp_path, monkeypatch, manager_class)
    _cache_miss(manager, monkeypatch, cft)
    versions = (
        ["0.30.0", "0.31.0", "0.32.0"]
        if isinstance(manager, FirefoxDriverManager)
        else ["120.0.1.1", "121.0.1.1", "122.0.1.1"]
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    downloads = []
    owned = []

    async def resolve(version: Any) -> Any:
        """Resolve.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return version

    async def resolve_pair(version: Any) -> Any:
        """Resolve pair.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return version, version

    async def download(version: Any) -> Any:
        """Download.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        owned.append(asyncio.current_task())
        downloads.append(str(version))
        if len(downloads) == 1:
            entered.set()
            await release.wait()
        return tmp_path / str(version)

    monkeypatch.setattr(manager, "_request_driver_version", resolve)
    monkeypatch.setattr(manager, "_install_driver_executable", download)
    if cft:
        monkeypatch.setattr(manager, "_request_cft_versions", resolve_pair)
        monkeypatch.setattr(
            manager, "_install_browser_binary", AsyncMock(return_value=browser)
        )

    requests = []
    try:
        requests.append(
            asyncio.create_task(_install(manager, versions[0], browser, cft))
        )
        await asyncio.wait_for(entered.wait(), _TIMEOUT)
        for version in versions[1:]:
            requests.append(
                asyncio.create_task(_install(manager, version, browser, cft))
            )
            # Deterministically let this request reach the occupied installation lock.
            await asyncio.sleep(0)
        release.set()
        installed = await asyncio.wait_for(asyncio.gather(*requests), _TIMEOUT)
        assert installed == [tmp_path / version for version in versions]
    finally:
        release.set()
        await _drain([*requests, *owned])


@pytest.mark.regression
def test_installations_work_across_sequential_event_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify installations work across sequential event loops.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    managers = [_manager(tmp_path, monkeypatch, ChromeDriverManager) for _ in range(2)]

    async def resolve(version: Any) -> Any:
        # Yield with the installation lock held so the second request contends.
        """Resolve.

        Args:
            version: Fixture or parametrized version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        await asyncio.sleep(0)
        return version

    for manager, _browser in managers:
        _cache_miss(manager, monkeypatch, False)
        monkeypatch.setattr(manager, "_request_driver_version", resolve)
        monkeypatch.setattr(
            manager,
            "_install_driver_executable",
            AsyncMock(return_value=tmp_path / "driver"),
        )

    async def install_pair() -> Any:
        """Install pair.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        tasks = [
            asyncio.create_task(_install(manager, "120.0.1.1", browser, False))
            for manager, browser in managers
        ]
        try:
            return await asyncio.wait_for(asyncio.gather(*tasks), _TIMEOUT)
        finally:
            await _drain(tasks)

    assert asyncio.run(install_pair()) == [tmp_path / "driver", tmp_path / "driver"]
    try:
        result = asyncio.run(install_pair())
    except RuntimeError as error:
        if "bound to a different event loop" not in str(error):
            raise
        raise AssertionError(
            "A new event loop must not reuse a loop-bound install lock."
        ) from error
    assert result == [tmp_path / "driver", tmp_path / "driver"]


class _SyntheticDownloadFailure(Exception):
    """Only this deliberate failure is accepted by the sibling-cleanup test."""


def _contains_synthetic_failure(error: BaseException) -> bool:
    """Contains synthetic failure.

    Args:
        error: Fixture or parametrized error input for this regression.

    Returns:
        True when the described condition holds; otherwise False.
    """
    if isinstance(error, _SyntheticDownloadFailure):
        return True
    children = getattr(error, "exceptions", ())
    # A grouped failure must not hide an unrelated exception beside our fixture.
    return bool(children) and all(
        _contains_synthetic_failure(child) for child in children
    )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_failed_cft_install_drains_sibling_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify failed cft install drains sibling before return.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = _manager(tmp_path, monkeypatch, ChromeDriverManager)
    _cache_miss(manager, monkeypatch, True)
    version = ChromiumVersion("120.0.1.1")
    monkeypatch.setattr(
        manager, "_request_cft_versions", AsyncMock(return_value=(version, version))
    )
    sibling_started = asyncio.Event()
    sibling_finished = asyncio.Event()
    release_sibling = asyncio.Event()
    completed_after_failure = False
    owned = []

    async def fail_driver(_version: Any) -> None:
        """Fail driver.

        Args:
            _version: Fixture or parametrized  version input for this regression.
        """
        owned.append(asyncio.current_task())
        await sibling_started.wait()
        raise _SyntheticDownloadFailure("synthetic driver download failure")

    async def download_browser(_version: Any) -> Any:
        """Download browser.

        Args:
            _version: Fixture or parametrized  version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        nonlocal completed_after_failure
        owned.append(asyncio.current_task())
        sibling_started.set()
        try:
            await release_sibling.wait()
            completed_after_failure = True
            manager._browser_location = browser
            return browser
        finally:
            sibling_finished.set()

    monkeypatch.setattr(manager, "_install_driver_executable", fail_driver)
    monkeypatch.setattr(manager, "_install_browser_binary", download_browser)
    try:
        try:
            await asyncio.wait_for(
                _install(manager, str(version), browser, True), _TIMEOUT
            )
        except Exception as error:
            if not _contains_synthetic_failure(error):
                raise
        else:
            raise AssertionError(
                "The synthetic driver download must fail installation."
            )
        release_sibling.set()
        await asyncio.wait_for(sibling_finished.wait(), _TIMEOUT)
        assert not completed_after_failure, (
            "A failed installation must cancel its sibling download."
        )
        assert manager._browser_location is None
    finally:
        release_sibling.set()
        await _drain(owned)


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_class,cft", _ALL_MANAGERS)
async def test_exact_cache_hit_avoids_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any, cft: Any
) -> None:
    """Verify exact cache hit avoids download.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        cft: Fixture or parametrized cft input for this regression.
    """
    manager, browser = _manager(tmp_path, monkeypatch, manager_class)
    pinned = (
        GeckoVersion("0.33.0")
        if isinstance(manager, FirefoxDriverManager)
        else ChromiumVersion("120.0.1.1")
    )
    expected = tmp_path / "cached driver"
    calls = []

    def match(version: Any, match_method: Any) -> Any:
        """Match.

        Args:
            version: Fixture or parametrized version input for this regression.
            match_method: Fixture or parametrized match method input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        calls.append((version, match_method))
        manager._driver_version = pinned
        manager._driver_location = expected
        return expected

    monkeypatch.setattr(manager, "_match_driver_executable", match)
    if cft:
        monkeypatch.setattr(manager, "_match_browser_binary", lambda *_args: browser)
    downloader = AsyncMock(side_effect=AssertionError("A cache hit must not download."))
    monkeypatch.setattr(manager, "_install_driver_executable", downloader)

    installed = await asyncio.wait_for(
        _install(manager, str(pinned), browser, cft), _TIMEOUT
    )

    assert installed == expected
    assert manager.driver_version == pinned
    assert manager.driver_location == expected
    assert calls == [(pinned, "patch")]
    downloader.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelling_cft_install_drains_both_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify cancelling cft install drains both downloads.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = _manager(tmp_path, monkeypatch, ChromeDriverManager)
    _cache_miss(manager, monkeypatch, True)
    version = ChromiumVersion("120.0.1.1")
    monkeypatch.setattr(
        manager, "_request_cft_versions", AsyncMock(return_value=(version, version))
    )
    both_started = asyncio.Event()
    release = asyncio.Event()
    owned = []

    async def download(_version: Any) -> Any:
        """Download.

        Args:
            _version: Fixture or parametrized  version input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        owned.append(asyncio.current_task())
        if len(owned) == 2:
            both_started.set()
        await release.wait()
        return browser

    monkeypatch.setattr(manager, "_install_driver_executable", download)
    monkeypatch.setattr(manager, "_install_browser_binary", download)
    installation = asyncio.create_task(_install(manager, str(version), browser, True))
    try:
        await asyncio.wait_for(both_started.wait(), _TIMEOUT)
        installation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(installation, _TIMEOUT)
        assert len(owned) == 2
        assert all(task.done() for task in owned)
        assert manager._driver_location is None
        assert manager._browser_location is None
    finally:
        release.set()
        await _drain([installation, *owned])
