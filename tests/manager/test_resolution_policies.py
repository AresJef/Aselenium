"""Vendor-shaped fixtures exercise resolution without external requests."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from aselenium import errors
from aselenium.manager import (
    ChromeDriverManager,
    ChromiumDriverManager,
    EdgeDriverManager,
    FirefoxDriverManager,
)
from aselenium.manager.file import ChromeBinaryFile, ChromeDriverFile, GeckoDriverFile
from aselenium.manager.version import ChromiumVersion, FirefoxVersion, GeckoVersion


def make_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cls: type[Any] = ChromeDriverManager,
    browser_version: str = "120.0.6099.71",
) -> Any:
    """Make manager.

    Args:
        cls: Patched class or instance used by this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        browser_version: Fixture or parametrized browser version input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    manager = cls(str(tmp_path))
    manager._DriverManager__os_name = "win"
    manager._DriverManager__os_arch = "64"
    manager._DriverManager__os_is_arm = False
    browser = tmp_path / "browser.exe"
    browser.touch()
    version_type = FirefoxVersion if cls is FirefoxDriverManager else ChromiumVersion
    monkeypatch.setattr(
        manager, "_detect_browser_version", lambda _: version_type(browser_version)
    )
    return manager, str(browser)


def archive(cls: type[Any], name: Any) -> Any:
    """Archive.

    Args:
        cls: Patched class or instance used by this regression.
        name: Fixture or parametrized name input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    output = BytesIO()
    with ZipFile(output, "w") as writer:
        writer.writestr(name, b"fixture bytes; never executed")
    return cls("win", "https://offline.invalid/fixture.zip", output.getvalue())


@pytest.mark.parametrize(
    "cls",
    [
        ChromeDriverManager,
        ChromiumDriverManager,
        EdgeDriverManager,
        FirefoxDriverManager,
    ],
)
@pytest.mark.parametrize(
    "selector",
    [
        "v120.0.1",
        "120.0.1.trailing",
        "120..1",
        "120.0.1.2.3",
        " 120.0.1",
        "120.0.1 ",
        "00120.0.1",
        "120.0.",
    ],
)
def test_user_selectors_are_strict_not_browser_output_parsers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls: type[Any], selector: Any
) -> None:
    """Verify user selectors are strict not browser output parsers.

    Args:
        cls: Patched class or instance used by this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        selector: Fixture or parametrized selector input for this regression.
    """
    manager, _ = make_manager(tmp_path, monkeypatch, cls)
    with pytest.raises(errors.InvalidDriverVersionError):
        manager._parse_target_version(selector)


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["offline", "120.0.6099.71"])
async def test_chrome_offline_cache_hit_never_requests_vendor_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selector: Any
) -> None:
    """Verify chrome offline cache hit never requests vendor data.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        selector: Fixture or parametrized selector input for this regression.
    """
    manager, browser = make_manager(tmp_path, monkeypatch)
    cached = manager._cache_view.cache_driver(
        ChromiumVersion("120.0.6099.71"), archive(ChromeDriverFile, "chromedriver.exe")
    )
    network = AsyncMock(
        side_effect=AssertionError("offline must not request metadata or downloads")
    )
    for name in (
        "_request_driver_version",
        "_request_response_file",
        "_request_response_json",
    ):
        monkeypatch.setattr(manager, name, network)
    result = await manager.install_result(selector, binary=browser, policy="offline")
    assert result.driver_location == cached["location"]
    assert result.request.policy == "offline"
    network.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cls",
    [
        ChromeDriverManager,
        EdgeDriverManager,
        ChromiumDriverManager,
        FirefoxDriverManager,
    ],
)
async def test_offline_miss_is_actionable_and_does_not_request_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls: type[Any]
) -> None:
    """Verify offline miss is actionable and does not request network.

    Args:
        cls: Patched class or instance used by this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = make_manager(tmp_path, monkeypatch, cls, "120.0.1")
    with pytest.raises(
        errors.DriverExecutableNotDetectedError, match="Provision it online first"
    ):
        await manager.install_result(binary=browser, policy="offline")


@pytest.mark.asyncio
async def test_cft_offline_chooses_an_older_complete_pair_over_newer_driver_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify cft offline chooses an older complete pair over newer driver only.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, _ = make_manager(tmp_path, monkeypatch)
    cache = manager._cache_view
    for text in ("120.0.6099.71", "120.0.6099.109"):
        cache.cache_driver(
            ChromiumVersion(text), archive(ChromeDriverFile, "chromedriver.exe")
        )
    browser = cache.cache_binary(
        ChromiumVersion("120.0.6099.71"), archive(ChromeBinaryFile, "chrome.exe")
    )
    result = await manager.install_result("120", channel="cft", policy="offline")
    assert result.driver_version == result.browser_version == "120.0.6099.71"
    assert result.browser_location == browser["location"]


@pytest.mark.asyncio
async def test_latest_compatible_refreshes_resolution_even_with_warm_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify latest compatible refreshes resolution even with warm cache.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = make_manager(tmp_path, monkeypatch)
    cache = manager._cache_view
    for text in ("120.0.6099.71", "120.0.6099.109"):
        cache.cache_driver(
            ChromiumVersion(text), archive(ChromeDriverFile, "chromedriver.exe")
        )
    resolve = AsyncMock(return_value=ChromiumVersion("120.0.6099.109"))
    monkeypatch.setattr(manager, "_request_driver_version", resolve)
    result = await manager.install_result(binary=browser, policy="latest-compatible")
    assert result.driver_version == "120.0.6099.109"
    resolve.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [ChromeDriverManager, EdgeDriverManager])
async def test_automatic_build_policy_rejects_a_vendor_major_only_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls: type[Any]
) -> None:
    """Verify automatic build policy rejects a vendor major only match.

    Args:
        cls: Patched class or instance used by this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = make_manager(tmp_path, monkeypatch, cls)
    monkeypatch.setattr(
        manager,
        "_request_driver_version",
        AsyncMock(return_value=ChromiumVersion("120.0.9999.1")),
    )
    with pytest.raises(
        errors.InvalidDriverVersionError, match="incompatible driver build"
    ):
        await manager.install(binary=browser)


@pytest.mark.asyncio
async def test_explicit_pin_can_prewarm_but_strict_acquisition_rejects_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify explicit pin can prewarm but strict acquisition rejects mismatch.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = make_manager(tmp_path, monkeypatch)
    cached = manager._cache_view.cache_driver(
        ChromiumVersion("121.0.1.1"), archive(ChromeDriverFile, "chromedriver.exe")
    )
    assert await manager.install("121.0.1.1", binary=browser) == cached["location"]
    with pytest.raises(errors.InvalidDriverVersionError, match="incompatible"):
        await manager.install_result(
            "121.0.1.1", binary=browser, validate_compatibility=True
        )


@pytest.mark.parametrize(
    ("browser", "expected"),
    [
        ("78", "0.30.0"),
        ("90.99", "0.30.0"),
        ("91", "0.31.0"),
        ("102", "0.33.0"),
        ("114", "0.33.0"),
        ("115", "0.37.1"),
        ("152", "0.37.1"),
    ],
)
def test_firefox_compatibility_selection_checks_the_entire_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, browser: Any, expected: Any
) -> None:
    """Verify firefox compatibility selection checks the entire range.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        browser: Fixture or parametrized browser input for this regression.
        expected: Fixture or parametrized expected input for this regression.
    """
    manager, _ = make_manager(tmp_path, monkeypatch, FirefoxDriverManager, browser)
    assert (
        str(manager._compatible_gecko_versions(FirefoxVersion(browser))[0]) == expected
    )


@pytest.mark.parametrize(
    ("driver", "browser"), [("0.33.0", "121"), ("0.34.0", "114"), ("0.99.0", "152")]
)
def test_unknown_or_incompatible_gecko_pair_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver: Any, browser: Any
) -> None:
    """Verify unknown or incompatible gecko pair is rejected.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        driver: Fixture or parametrized driver input for this regression.
        browser: Fixture or parametrized browser input for this regression.
    """
    manager, _ = make_manager(tmp_path, monkeypatch, FirefoxDriverManager, browser)
    with pytest.raises(errors.InvalidDriverVersionError):
        manager._validate_gecko_pair(GeckoVersion(driver), FirefoxVersion(browser))


@pytest.mark.asyncio
async def test_firefox_offline_can_use_an_older_compatible_cached_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify firefox offline can use an older compatible cached driver.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = make_manager(tmp_path, monkeypatch, FirefoxDriverManager, "120")
    cached = manager._cache_view.cache_driver(
        GeckoVersion("0.33.0"), archive(GeckoDriverFile, "geckodriver.exe")
    )
    result = await manager.install_result(binary=browser, policy="offline")
    assert result.driver_version == "0.33.0"
    assert result.driver_location == cached["location"]


@pytest.mark.asyncio
async def test_firefox_unknown_latest_release_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify firefox unknown latest release fails closed.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, browser = make_manager(tmp_path, monkeypatch, FirefoxDriverManager, "120")
    monkeypatch.setattr(
        manager,
        "_request_driver_version",
        AsyncMock(return_value=GeckoVersion("0.99.0")),
    )
    with pytest.raises(errors.InvalidDriverVersionError, match="No recorded"):
        await manager.install(binary=browser)


def manifest(
    version: Any, platform: str = "win64", artifact: str = "chromedriver"
) -> Any:
    """Manifest.

    Args:
        version: Fixture or parametrized version input for this regression.
        platform: Fixture or parametrized platform input for this regression.
        artifact: Fixture or parametrized artifact input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    url = "https://storage.googleapis.com/chrome-for-testing-public/%s/%s/%s-%s.zip" % (
        version,
        platform,
        artifact,
        platform,
    )
    return {
        "version": version,
        "downloads": {artifact: [{"platform": platform, "url": url}]},
    }, url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("os_name", "arm", "platform"),
    [
        ("win", False, "win64"),
        ("mac", True, "mac-arm64"),
        ("mac", False, "mac-x64"),
        ("linux", False, "linux64"),
        ("linux", True, "linux-arm64"),
    ],
)
async def test_cft_selects_exact_asset_from_verified_manifest_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    os_name: Any,
    arm: Any,
    platform: Any,
) -> None:
    """Verify cft selects exact asset from verified manifest schema.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        os_name: Fixture or parametrized os name input for this regression.
        arm: Fixture or parametrized arm input for this regression.
        platform: Fixture or parametrized platform input for this regression.
    """
    manager, _ = make_manager(tmp_path, monkeypatch)
    manager._DriverManager__os_name = os_name
    manager._DriverManager__os_is_arm = arm
    data, url = manifest("154.0.1.1", platform)
    metadata = AsyncMock(return_value=data)
    monkeypatch.setattr(manager, "_request_response_json", metadata)
    assert (
        await manager._cft_asset_url(ChromiumVersion("154.0.1.1"), "chromedriver")
        == url
    )
    metadata.assert_awaited_once_with(
        "https://googlechromelabs.github.io/chrome-for-testing/154.0.1.1.json"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "wrong-version",
        "wrong-arch",
        "http",
        "foreign-host",
        "wrong-path",
        "query",
        "bad-downloads",
        "bad-asset",
    ],
)
async def test_cft_rejects_malformed_or_unavailable_exact_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: Any
) -> None:
    """Verify cft rejects malformed or unavailable exact assets.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        change: Fixture or parametrized change input for this regression.
    """
    manager, _ = make_manager(tmp_path, monkeypatch)
    data, url = manifest("120.0.6099.71")
    asset = data["downloads"]["chromedriver"][0]
    if change == "wrong-version":
        data["version"] = "120.0.6099.109"
    elif change == "wrong-arch":
        asset["platform"] = "mac-arm64"
    elif change == "bad-downloads":
        data["downloads"] = None
    elif change == "bad-asset":
        data["downloads"]["chromedriver"] = [None]
    else:
        asset["url"] = {
            "http": url.replace("https:", "http:"),
            "foreign-host": url.replace("storage.googleapis.com", "attacker.invalid"),
            "wrong-path": url.replace("120.0.6099.71", "121.0.1.1"),
            "query": url + "?token=secret",
        }[change]
    monkeypatch.setattr(manager, "_request_response_json", AsyncMock(return_value=data))
    with pytest.raises(errors.DriverManagerError):
        await manager._cft_asset_url(ChromiumVersion("120.0.6099.71"), "chromedriver")


def test_edge_linux_arm_is_not_mislabeled_as_linux_x64(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify edge linux arm is not mislabeled as linux x64.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, _ = make_manager(tmp_path, monkeypatch, EdgeDriverManager)
    manager._DriverManager__os_name = "linux"
    manager._DriverManager__os_is_arm = True
    with pytest.raises(errors.UnsupportedPlatformError):
        manager._generate_azureedge_arch()


@pytest.mark.asyncio
async def test_unknown_policy_is_rejected_before_browser_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify unknown policy is rejected before browser discovery.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager, _ = make_manager(tmp_path, monkeypatch)
    with pytest.raises(errors.InvalidArgumentError):
        await manager.install_result(policy="invented")
