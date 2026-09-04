"""Final manager regressions for exact provisioning and malformed vendor metadata."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from aselenium import errors
from aselenium.manager import ChromeDriverManager, FirefoxDriverManager
from aselenium.manager.file import ChromeBinaryFile, ChromeDriverFile
from aselenium.manager.version import ChromiumVersion, GeckoVersion


def chrome_manager(tmp_path: Path) -> ChromeDriverManager:
    """Create a cache-only manager with deterministic Windows artifact names.

    Args:
        tmp_path: Disposable cache parent supplied by pytest.

    Returns:
        A manager that does not probe or launch a browser.
    """
    manager = ChromeDriverManager(str(tmp_path))
    manager._DriverManager__os_name = "win"
    manager._DriverManager__os_arch = "64"
    manager._DriverManager__os_is_arm = False
    return manager


def cache_pair(manager: ChromeDriverManager) -> str:
    """Publish one complete synthetic CfT pair without executing its bytes.

    Args:
        manager: Manager whose disposable cache receives the fixture pair.

    Returns:
        The published driver executable path.
    """
    version = ChromiumVersion("120.0.6099.71")
    location = ""
    for kind, name, archive_class in (
        ("driver", "chromedriver.exe", ChromeDriverFile),
        ("binary", "chrome.exe", ChromeBinaryFile),
    ):
        stream = BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr(name, b"synthetic artifact; never execute")
        artifact = archive_class(
            "win", "https://fixture.invalid/artifact.zip", stream.getvalue()
        )
        result = getattr(manager._cache_view, "cache_" + kind)(version, artifact)
        if kind == "driver":
            location = result["location"]
    return location


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["120", "120.0.6099"])
@pytest.mark.parametrize("warm_cache", [False, True])
async def test_cft_exact_policy_rejects_partial_version_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
    warm_cache: bool,
) -> None:
    """An explicit exact policy must never silently choose a full version.

    Args:
        tmp_path: Disposable cache parent supplied by pytest.
        monkeypatch: Scoped patches for forbidden vendor resolution.
        selector: Incomplete numeric selector that cannot identify one artifact.
        warm_cache: Whether an otherwise matching complete pair is already cached.
    """
    manager = chrome_manager(tmp_path)
    if warm_cache:
        cache_pair(manager)
    network = AsyncMock(
        side_effect=AssertionError("Exact input must be rejected first")
    )
    monkeypatch.setattr(manager, "_request_cft_versions", network)
    with pytest.raises(errors.InvalidDriverVersionError, match="four numeric"):
        await manager.install_result(selector, channel="cft", policy="exact")
    network.assert_not_awaited()
    assert manager.last_result is None


@pytest.mark.asyncio
async def test_cft_exact_complete_version_retains_cached_pair_and_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rejecting partial exact input must preserve successful complete-version reuse.

    Args:
        tmp_path: Disposable cache parent supplied by pytest.
        monkeypatch: Scoped patches for forbidden vendor resolution.
    """
    manager = chrome_manager(tmp_path)
    location = cache_pair(manager)
    network = AsyncMock(side_effect=AssertionError("Cached exact pair is complete"))
    monkeypatch.setattr(manager, "_request_cft_versions", network)
    result = await manager.install_result(
        "120.0.6099.71", channel="cft", policy="exact"
    )
    assert result.driver_location == location
    assert result.driver_version == result.browser_version == "120.0.6099.71"
    with manager._cache_view._db() as database:
        assert [row[0] for row in database.execute("SELECT pinned FROM artifacts")] == [
            1,
            1,
        ]
    network.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [123, True, ["https://fixture.invalid"], {"url": "invalid"}, "https://[invalid/"],
)
async def test_cft_malformed_asset_url_is_a_classified_manager_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: Any
) -> None:
    """Malformed vendor fields must not escape as built-in type or URL errors.

    Args:
        tmp_path: Disposable cache parent supplied by pytest.
        monkeypatch: Scoped patches providing synthetic vendor JSON.
        url: Malformed URL field from an otherwise valid manifest.
    """
    manager = chrome_manager(tmp_path)
    metadata = {
        "version": "120.0.6099.71",
        "downloads": {"chromedriver": [{"platform": "win64", "url": url}]},
    }
    monkeypatch.setattr(
        manager, "_request_response_json", AsyncMock(return_value=metadata)
    )
    with pytest.raises(errors.DriverRequestFailedError, match="artifact URL"):
        await manager._cft_asset_url(ChromiumVersion("120.0.6099.71"), "chromedriver")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {},
        [],
        ["v0.37.1"],
        "v0.37.1",
        123,
        True,
        {"tag_name": None},
        {"tag_name": ""},
        {"tag_name": 123},
        {"tag_name": ["v0.37.1"]},
    ],
)
async def test_gecko_malformed_release_metadata_is_a_classified_manager_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: Any
) -> None:
    """Only a release object with a textual tag may proceed to version parsing.

    Args:
        tmp_path: Disposable cache parent supplied by pytest.
        monkeypatch: Scoped patches providing malformed vendor JSON.
        metadata: Structurally invalid GitHub release payload.
    """
    manager = FirefoxDriverManager(str(tmp_path))
    monkeypatch.setattr(
        manager, "_request_response_json", AsyncMock(return_value=metadata)
    )
    fallback = AsyncMock(
        side_effect=AssertionError("Malformed data is not a cache miss")
    )
    monkeypatch.setattr(manager, "_request_response_url", fallback)
    previous_maximum = manager._GECKODRIVER_MAX_VERSION
    with pytest.raises(errors.DriverRequestFailedError, match="release metadata"):
        await manager._request_driver_version(None)
    assert manager._GECKODRIVER_MAX_VERSION == previous_maximum
    fallback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, {"tag_name": "v0.37.1"}])
async def test_gecko_valid_release_metadata_and_missing_api_fallback_still_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, str] | None
) -> None:
    """Keep the successful API and genuine missing-resource fallback paths intact.

    Args:
        tmp_path: Disposable cache parent supplied by pytest.
        monkeypatch: Scoped patches providing vendor responses.
        metadata: Valid release object or the transport's missing-resource sentinel.
    """
    manager = FirefoxDriverManager(str(tmp_path))
    monkeypatch.setattr(
        manager, "_request_response_json", AsyncMock(return_value=metadata)
    )
    fallback = AsyncMock(return_value="v0.37.1")
    monkeypatch.setattr(manager, "_request_response_url", fallback)
    assert await manager._request_driver_version(None) == GeckoVersion("0.37.1")
    assert fallback.await_count == int(metadata is None)
