"""Safari metadata/path contracts exercised entirely in disposable app bundles."""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from xml.parsers.expat import ExpatError

import pytest

from aselenium import Safari, SafariVersion, errors
from aselenium.manager import driver as drivers
from aselenium.safari.session import SafariSession
from aselenium.utils import load_plist_file

MALFORMED_PLISTS = [
    pytest.param(b"not a plist", plistlib.InvalidFileException, id="unknown-format"),
    pytest.param(
        b"bplist00truncated", plistlib.InvalidFileException, id="truncated-binary"
    ),
    pytest.param(
        b'<?xml version="1.0"?><plist version="1.0"><dict>'
        b"<key>CFBundleShortVersionString</key><string>17.4.1</dict></plist>",
        ExpatError,
        id="malformed-xml",
    ),
]


@pytest.mark.parametrize("method", ["_parse_browser_version", "_parse_driver_version"])
@pytest.mark.parametrize("value", ["26.6.2", "18.0", SafariVersion("17.4.1")])
def test_safari_result_versions_are_reconstructed(
    tmp_path: Path, method: str, value: str | SafariVersion
) -> None:
    """Reconstruct typed versions when an immutable result starts a session.

    Args:
        tmp_path: Disposable manager directory.
        method: Browser or driver version parser used by session acquisition.
        value: Valid version string or existing Safari version value.
    """
    manager = drivers.SafariDriverManager(directory=str(tmp_path))
    parsed = getattr(manager, method)(value)
    assert isinstance(parsed, SafariVersion)
    assert str(parsed) == str(value)


@pytest.mark.parametrize(
    ("method", "error"),
    [
        ("_parse_browser_version", errors.InvalidBrowserVersionError),
        ("_parse_driver_version", errors.InvalidDriverVersionError),
    ],
)
@pytest.mark.parametrize("value", [None, "", "not-a-version", False, 26, {}])
def test_safari_result_versions_reject_invalid_values(
    tmp_path: Path, method: str, error: type[Exception], value: Any
) -> None:
    """Expose the appropriate package error for malformed result versions.

    Args:
        tmp_path: Disposable manager directory.
        method: Parser under test.
        error: Expected browser-specific or driver-specific version error.
        value: Malformed value that cannot represent a Safari version.
    """
    manager = drivers.SafariDriverManager(directory=str(tmp_path))
    with pytest.raises(error):
        getattr(manager, method)(value)


@pytest.mark.asyncio
async def test_safari_acquisition_consumes_real_discovery_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise discovery-to-session handoff without launching an installed browser.

    Args:
        tmp_path: Directory containing a synthetic Safari application bundle.
        monkeypatch: Override only remote session startup and teardown.
    """
    browser, _ = make_bundle(tmp_path)
    started = AsyncMock()
    stopped = AsyncMock()
    monkeypatch.setattr(SafariSession, "start", started)
    monkeypatch.setattr(SafariSession, "quit", stopped)
    facade = Safari()
    try:
        context = facade.acquire(binary=str(browser))
        async with context as session:
            assert isinstance(session, SafariSession)
            assert context._options.browser_version == "17.4.1"
            assert str(context._service.driver_version) == "17.4.1"
            assert context._installation.browser_location == str(browser)
        started.assert_awaited_once()
        stopped.assert_awaited_once()
        assert context._state == "closed"
    finally:
        facade.options.close()


@pytest.fixture(autouse=True)
def synthetic_safari_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    # Error formatting must not ask platform.architecture() to run `file` either.
    """Synthetic safari platform.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    monkeypatch.setattr(drivers, "system", lambda: "Darwin")
    monkeypatch.setattr(drivers, "architecture", lambda: ("64bit", ""))
    monkeypatch.setattr(drivers, "machine", lambda: "arm64")
    default_driver = tmp_path / "synthetic-system" / "safaridriver"
    monkeypatch.setattr(
        drivers.SafariDriverManager, "_MAC_DRIVER_DEFAULT_PATH", str(default_driver)
    )
    return default_driver


def make_bundle(
    root: Any,
    name: str = "Safari Démo 日本語 'quoted' ; safe.app",
    with_driver: bool = True,
) -> Any:
    """Make bundle.

    Args:
        root: Fixture or parametrized root input for this regression.
        name: Fixture or parametrized name input for this regression.
        with_driver: Fixture or parametrized with driver input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    contents = root / name / "Contents"
    browser = contents / "MacOS" / "Safari"
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"synthetic browser; never execute")
    (contents / "version.plist").write_bytes(
        plistlib.dumps({"CFBundleShortVersionString": "17.4.1"})
    )
    driver = browser.parent / "safaridriver"
    if with_driver:
        driver.write_bytes(b"synthetic driver; never execute")
    return browser, driver


@pytest.mark.parametrize("plist_format", [plistlib.FMT_XML, plistlib.FMT_BINARY])
@pytest.mark.parametrize("as_path_object", [False, True])
def test_load_plist_supports_xml_binary_and_unicode_paths(
    tmp_path: Path, plist_format: Any, as_path_object: Any
) -> None:
    """Verify load plist supports xml binary and unicode paths.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        plist_format: Fixture or parametrized plist format input for this regression.
        as_path_object: Fixture or parametrized as path object input for this regression.
    """
    path = tmp_path / "metadata 日本語 with spaces.plist"
    expected = {"CFBundleShortVersionString": "17.4.1", "label": "Démo 日本語"}
    path.write_bytes(plistlib.dumps(expected, fmt=plist_format))

    actual = load_plist_file(path if as_path_object else str(path))

    assert actual == expected


def test_load_plist_preserves_missing_file_error(tmp_path: Path) -> None:
    """Verify load plist preserves missing file error.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    missing = tmp_path / "missing.plist"

    with pytest.raises(FileNotFoundError) as caught:
        load_plist_file(str(missing))

    assert caught.value.filename == str(missing)


@pytest.mark.parametrize(("content", "cause_type"), MALFORMED_PLISTS)
def test_load_plist_rejects_malformed_metadata(
    tmp_path: Path, content: Any, cause_type: Any
) -> None:
    """Verify load plist rejects malformed metadata.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        content: Fixture or parametrized content input for this regression.
        cause_type: Fixture or parametrized cause type input for this regression.
    """
    path = tmp_path / "malformed.plist"
    path.write_bytes(content)

    with pytest.raises(cause_type):
        load_plist_file(str(path))


def test_safari_version_uses_own_bundle_when_parent_contains_contents_macos(
    tmp_path: Path,
) -> None:
    """Verify safari version uses own bundle when parent contains contents macos.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    browser, _ = make_bundle(tmp_path / "Contents" / "MacOS" / "outer directory")
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    assert manager._detect_browser_version(str(browser)).version == "17.4.1"


def test_safari_prefers_version_plist_when_both_metadata_files_exist(
    tmp_path: Path,
) -> None:
    """Verify safari prefers version plist when both metadata files exist.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    browser, _ = make_bundle(tmp_path)
    (browser.parent.parent / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleShortVersionString": "19.0"}, fmt=plistlib.FMT_BINARY)
    )
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    assert manager._detect_browser_version(str(browser)).version == "17.4.1"


def test_safari_missing_metadata_preserves_info_plist_failure_cause(
    tmp_path: Path,
) -> None:
    """Verify safari missing metadata preserves info plist failure cause.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    browser, _ = make_bundle(tmp_path)
    (browser.parent.parent / "version.plist").unlink()
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.BrowserBinaryNotDetectedError) as caught:
        manager._detect_browser_version(str(browser))

    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert caught.value.__cause__.filename == str(browser.parent.parent / "Info.plist")


@pytest.mark.parametrize(("content", "cause_type"), MALFORMED_PLISTS)
def test_safari_malformed_version_plist_does_not_hide_error_with_info_fallback(
    tmp_path: Path, content: Any, cause_type: Any
) -> None:
    """Verify safari malformed version plist does not hide error with info fallback.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        content: Fixture or parametrized content input for this regression.
        cause_type: Fixture or parametrized cause type input for this regression.
    """
    browser, _ = make_bundle(tmp_path)
    contents = browser.parent.parent
    (contents / "version.plist").write_bytes(content)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleShortVersionString": "19.0"})
    )
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.BrowserBinaryNotDetectedError) as caught:
        manager._detect_browser_version(str(browser))

    assert isinstance(caught.value.__cause__, cause_type)


@pytest.mark.parametrize(
    ("metadata", "cause_type"),
    [
        ({}, KeyError),
        ({"CFBundleShortVersionString": "not-a-version"}, errors.InvalidVersionError),
    ],
)
def test_safari_invalid_version_metadata_preserves_original_cause(
    tmp_path: Path, metadata: Any, cause_type: Any
) -> None:
    """Verify safari invalid version metadata preserves original cause.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        metadata: Fixture or parametrized metadata input for this regression.
        cause_type: Fixture or parametrized cause type input for this regression.
    """
    browser, _ = make_bundle(tmp_path)
    (browser.parent.parent / "version.plist").write_bytes(plistlib.dumps(metadata))
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.BrowserBinaryNotDetectedError) as caught:
        manager._detect_browser_version(str(browser))

    assert isinstance(caught.value.__cause__, cause_type)


def test_safari_permission_error_does_not_trigger_info_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify safari permission error does not trigger info fallback.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    browser, _ = make_bundle(tmp_path)
    attempted = []

    def denied(path: Any) -> None:
        """Denied.

        Args:
            path: Fixture or parametrized path input for this regression.
        """
        attempted.append(path)
        raise PermissionError("synthetic metadata denial")

    monkeypatch.setattr(drivers, "load_plist_file", denied)
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.BrowserBinaryNotDetectedError) as caught:
        manager._detect_browser_version(str(browser))

    assert isinstance(caught.value.__cause__, PermissionError)
    assert attempted == [str(browser.parent.parent / "version.plist")]


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["stable", "dev"])
@pytest.mark.parametrize("as_path_object", [False, True])
async def test_safari_install_accepts_explicit_paths_and_returns_absolute_strings(
    tmp_path: Path, channel: Any, as_path_object: Any
) -> None:
    """Verify safari install accepts explicit paths and returns absolute strings.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        channel: Fixture or parametrized channel input for this regression.
        as_path_object: Fixture or parametrized as path object input for this regression.
    """
    browser, driver = make_bundle(tmp_path)
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    installed = await manager.install(
        channel=channel,
        binary=browser if as_path_object else str(browser),
        driver=driver if as_path_object else str(driver),
    )

    assert installed == str(driver.absolute())
    assert isinstance(installed, str)
    assert manager.driver_location == installed
    assert manager.browser_location == str(browser.absolute())
    assert manager.browser_version.version == "17.4.1"
    assert manager.driver_version.version == "17.4.1"


@pytest.mark.asyncio
async def test_safari_install_normalizes_relative_explicit_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify safari install normalizes relative explicit paths.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    browser, driver = make_bundle(tmp_path)
    monkeypatch.chdir(tmp_path)
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    installed = await manager.install(
        binary=str(browser.relative_to(tmp_path)),
        driver=str(driver.relative_to(tmp_path)),
    )

    assert installed == str(driver.absolute())
    assert manager.browser_location == str(browser.absolute())


@pytest.mark.parametrize(
    "name", ["prefix-safaridriver", "safaridriver.txt", "not-safaridriver"]
)
def test_safari_explicit_driver_requires_exact_basename(
    tmp_path: Path, name: Any
) -> None:
    """Verify safari explicit driver requires exact basename.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        name: Fixture or parametrized name input for this regression.
    """
    driver = tmp_path / name
    driver.write_bytes(b"synthetic file")
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.DriverExecutableNotDetectedError):
        manager._parse_target_driver(str(driver))


def test_safari_explicit_driver_rejects_directory_with_correct_name(
    tmp_path: Path,
) -> None:
    """Verify safari explicit driver rejects directory with correct name.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    driver = tmp_path / "safaridriver"
    driver.mkdir()
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.DriverExecutableNotDetectedError):
        manager._parse_target_driver(str(driver))


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["beta", "unknown"])
async def test_safari_rejects_unsupported_channel_even_with_explicit_paths(
    tmp_path: Path, channel: Any
) -> None:
    """Verify safari rejects unsupported channel even with explicit paths.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        channel: Fixture or parametrized channel input for this regression.
    """
    browser, driver = make_bundle(tmp_path)
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.DriverManagerError):
        await manager.install(channel=channel, binary=str(browser), driver=str(driver))


@pytest.mark.asyncio
async def test_safari_install_uses_existing_default_if_explicit_bundle_has_no_driver(
    tmp_path: Path, synthetic_safari_platform: Any
) -> None:
    """Verify safari install uses existing default if explicit bundle has no driver.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        synthetic_safari_platform: Fixture or parametrized synthetic safari platform input for this regression.
    """
    browser, _ = make_bundle(tmp_path, with_driver=False)
    default = synthetic_safari_platform
    default.parent.mkdir()
    default.write_bytes(b"synthetic default driver")
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    assert await manager.install(binary=str(browser)) == str(default)


@pytest.mark.asyncio
async def test_safari_install_never_returns_nonexistent_default_driver(
    tmp_path: Path,
) -> None:
    """Verify safari install never returns nonexistent default driver.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    browser, _ = make_bundle(tmp_path, with_driver=False)
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    with pytest.raises(errors.DriverExecutableNotDetectedError):
        await manager.install(binary=str(browser))

    assert manager._driver_location is None
    assert manager._browser_location is None


def test_safari_driver_discovery_finds_nested_bundle_executable(tmp_path: Path) -> None:
    """Verify safari driver discovery finds nested bundle executable.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    browser, _ = make_bundle(tmp_path, with_driver=False)
    driver = browser.parent.parent / "Resources" / "nested" / "safaridriver"
    driver.parent.mkdir(parents=True)
    driver.write_bytes(b"synthetic nested driver")
    manager = drivers.SafariDriverManager(directory=str(tmp_path))
    manager._channel = "dev"
    manager._browser_location = str(browser)
    manager._target_binary = str(browser)

    assert manager._detect_driver_location() == str(driver)


def test_safari_driver_discovery_revalidates_walk_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify safari driver discovery revalidates walk results.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    browser, _ = make_bundle(tmp_path, with_driver=False)
    stale_folder = browser.parent.parent / "Resources"
    stale_folder.mkdir()
    monkeypatch.setattr(
        drivers, "walk_path", lambda root: [(str(stale_folder), [], ["safaridriver"])]
    )
    manager = drivers.SafariDriverManager(directory=str(tmp_path))
    manager._channel = "dev"
    manager._browser_location = str(browser)
    manager._target_binary = str(browser)

    with pytest.raises(errors.DriverExecutableNotDetectedError):
        manager._detect_driver_location()
