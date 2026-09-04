"""Discovery tests use synthetic browser paths and fake process probes only."""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

import pytest

from aselenium.manager import driver as drivers


@pytest.fixture
def fake_probe(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fake probe.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    calls = []

    class Probe:
        """Represent Probe using the inherited implementation."""

        returncode = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Initialize the instance with the supplied configuration.

            Args:
                *args: Fixture or parametrized args input for this regression.
                **kwargs: Fixture or parametrized kwargs input for this regression.
            """
            calls.append((args, kwargs))

        def __enter__(self) -> Probe:
            """Enter the context and return its managed value.

            Returns:
                The Probe value produced by this operation.
            """
            return self

        def __exit__(self, *args: Any) -> Any:
            """Release resources when leaving the synchronous context.

            Args:
                *args: Fixture or parametrized args input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return False

        def communicate(self, *args: Any, **kwargs: Any) -> Any:
            """Communicate.

            Args:
                *args: Fixture or parametrized args input for this regression.
                **kwargs: Fixture or parametrized kwargs input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return b"Google Chrome 120.0.6000.1\n", b""

    monkeypatch.setattr(drivers, "Popen", Probe)
    return calls


def test_browser_version_is_parsed_from_fake_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_probe: Any
) -> None:
    """Verify browser version is parsed from fake probe.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        fake_probe: Fixture or parametrized fake probe input for this regression.
    """
    monkeypatch.setattr(drivers, "system", lambda: "Linux")
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    browser = tmp_path / "browser with spaces"
    browser.write_bytes(b"not executable")

    version = manager._detect_browser_version(str(browser))

    assert version.version == "120.0.6000.1"
    assert len(fake_probe) == 1


@pytest.mark.regression
def test_browser_probe_passes_path_as_literal_argv_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_probe: Any
) -> None:
    """Verify browser probe passes path as literal argv without shell.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        fake_probe: Fixture or parametrized fake probe input for this regression.
    """
    monkeypatch.setattr(drivers, "system", lambda: "Linux")
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    browser = tmp_path / "browser;NEVER_EXECUTE_THIS"
    browser.write_bytes(b"synthetic; all process calls are intercepted")

    assert manager._detect_browser_version(str(browser)).version == "120.0.6000.1"
    assert len(fake_probe) == 1
    args, kwargs = fake_probe[0]
    assert kwargs.get("shell", False) is False, (
        "probe must not evaluate browser paths in a shell"
    )
    assert list(args[0]) == [str(browser), "--version"]


def test_windows_location_discovery_uses_synthetic_environment_path(
    tmp_path: Path,
) -> None:
    """Verify windows location discovery uses synthetic environment path.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = drivers.DriverManager("fixture", None, None, None)
    manager._DriverManager__environ_paths = [tmp_path]
    browser = tmp_path / "Vendor" / "Browser" / "browser.exe"
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"synthetic browser")

    relative = str(browser.relative_to(tmp_path))
    assert manager._find_win_browser_location(relative) == browser


def test_mac_discovery_finds_synthetic_environment_path(
    tmp_path: Path,
) -> None:
    """Verify Mac discovery joins a relative bundle path to a Path root.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = drivers.DriverManager("fixture", None, None, None)
    manager._DriverManager__environ_paths = [tmp_path]
    relative = f"{tmp_path.name} Fixture.app/Contents/MacOS/Fixture"
    expected = tmp_path / relative
    expected.parent.mkdir(parents=True)
    expected.touch()

    assert manager._find_mac_browser_location(relative) == expected


@pytest.mark.parametrize("plist_name", ["version.plist", "Info.plist"])
@pytest.mark.parametrize("plist_format", [plistlib.FMT_XML, plistlib.FMT_BINARY])
@pytest.mark.regression
def test_safari_version_discovery_reads_real_synthetic_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plist_name: Any, plist_format: Any
) -> None:
    """Verify safari version discovery reads real synthetic plist.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        plist_name: Fixture or parametrized plist name input for this regression.
        plist_format: Fixture or parametrized plist format input for this regression.
    """
    monkeypatch.setattr(drivers, "system", lambda: "Darwin")
    monkeypatch.setattr(drivers, "architecture", lambda: ("64bit", ""))
    monkeypatch.setattr(drivers, "machine", lambda: "arm64")
    contents = tmp_path / "Fixture Safari.app" / "Contents"
    executable = contents / "MacOS" / "Safari"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic Safari; never executed")
    (contents / plist_name).write_bytes(
        plistlib.dumps({"CFBundleShortVersionString": "17.4.1"}, fmt=plist_format)
    )
    manager = drivers.SafariDriverManager(directory=str(tmp_path))

    assert manager._detect_browser_version(executable).version == "17.4.1"


def test_safari_driver_discovery_finds_executable_beside_browser(
    tmp_path: Path,
) -> None:
    """Verify safari driver discovery finds executable beside browser.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    folder = tmp_path / "Fixture Safari.app" / "Contents" / "MacOS"
    folder.mkdir(parents=True)
    browser = folder / "Safari"
    driver = folder / "safaridriver"
    browser.write_bytes(b"synthetic browser")
    driver.write_bytes(b"synthetic driver")
    manager = drivers.SafariDriverManager(directory=str(tmp_path))
    manager._channel = "dev"
    manager._browser_location = str(browser)

    assert manager._detect_driver_location(browser) == driver
