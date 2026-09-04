"""Step 2 path/discovery contracts, with no real browser or process probes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from aselenium import errors
from aselenium.manager import driver as drivers
from aselenium.manager.version import ChromiumVersion, FirefoxVersion

_MANAGERS = [
    pytest.param(drivers.ChromeDriverManager, id="chrome"),
    pytest.param(drivers.ChromiumDriverManager, id="chromium"),
    pytest.param(drivers.EdgeDriverManager, id="edge"),
    pytest.param(drivers.FirefoxDriverManager, id="firefox"),
]


class _CountingTextPath(os.PathLike[str]):
    """Expose a text path while recording filesystem-boundary conversion."""

    def __init__(self, path: Path) -> None:
        """Store the represented path.

        Args:
            path: Concrete filesystem path returned by ``__fspath__``.
        """
        self.path = path
        self.calls = 0

    def __fspath__(self) -> str:
        """Return the represented path and record the conversion.

        Returns:
            Text path accepted by the package path boundary.
        """
        self.calls += 1
        return str(self.path)

    def __str__(self) -> str:
        """Prove path handling never depends on an arbitrary text conversion.

        Raises:
            AssertionError: Always; valid path-like values must use ``__fspath__``.
        """
        raise AssertionError("PathLike.__str__ must not be used for path parsing")


def _manager(
    tmp_path: Path,
    manager_class: Any = drivers.ChromeDriverManager,
    os_name: str = "linux",
) -> Any:
    """Manager.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        manager_class: Fixture or parametrized manager class input for this regression.
        os_name: Fixture or parametrized os name input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    manager = manager_class(directory=str(tmp_path))
    manager._DriverManager__os_name = os_name
    manager._DriverManager__os_arch = "64"
    manager._DriverManager__os_is_arm = False
    manager._channel = (
        "dev" if isinstance(manager, drivers.ChromiumDriverManager) else "stable"
    )
    return manager


def _browser(root: Path) -> Path:
    # These characters must be treated as filename data, never shell syntax.
    """Browser.

    Args:
        root: Fixture or parametrized root input for this regression.

    Returns:
        The Path value produced by this operation.
    """
    path = root / "浏览器 with spaces;literal"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


@pytest.mark.parametrize("manager_class", _MANAGERS)
@pytest.mark.parametrize(
    "path_kind",
    [
        "absolute-string",
        "path-object",
        "relative-string",
        "relative-path-object",
        "tilde",
    ],
)
def test_explicit_binary_path_is_normalized_without_changing_literal_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any, path_kind: Any
) -> None:
    """Verify explicit binary path is normalized without changing literal name.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        path_kind: Fixture or parametrized path kind input for this regression.
    """
    manager = _manager(tmp_path, manager_class)
    browser = _browser(tmp_path / "synthetic-home")
    monkeypatch.chdir(tmp_path)
    if path_kind == "absolute-string":
        supplied = str(browser)
    elif path_kind == "path-object":
        supplied = browser
    elif path_kind == "relative-string":
        supplied = str(browser.relative_to(tmp_path))
    elif path_kind == "relative-path-object":
        supplied = browser.relative_to(tmp_path)
    else:
        supplied = "~/" + browser.name
        monkeypatch.setenv("HOME", str(browser.parent))
        monkeypatch.setenv("USERPROFILE", str(browser.parent))

    manager._parse_target_binary(supplied)

    assert manager._target_binary == browser
    assert isinstance(manager._target_binary, Path)
    assert manager._target_binary.is_absolute()


def test_explicit_binary_preserves_leading_and_trailing_filename_spaces(
    tmp_path: Path,
) -> None:
    """Verify explicit binary preserves leading and trailing filename spaces.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = _manager(tmp_path)
    browser = tmp_path / " browser with literal spaces "
    browser.touch()

    manager._parse_target_binary(browser)

    assert manager._target_binary == browser


@pytest.mark.parametrize("path_kind", ["absolute", "relative"])
@pytest.mark.skipif(
    os.name == "nt",
    reason="Symlink-plus-parent traversal has intentionally different Windows semantics.",
)
def test_absolute_binary_normalization_preserves_symlink_parent_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_kind: Any
) -> None:
    """Verify absolute binary normalization preserves symlink parent traversal.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        path_kind: Fixture or parametrized path kind input for this regression.
    """
    manager = _manager(tmp_path)
    launch_root = tmp_path / "launch-root"
    target_root = tmp_path / "target-root"
    launch_root.mkdir()
    (target_root / "nested").mkdir(parents=True)
    link = launch_root / "linked-directory"
    link.symlink_to(target_root / "nested", target_is_directory=True)
    intended = target_root / "browser"
    decoy = launch_root / "browser"
    intended.write_bytes(b"intended synthetic browser; never executed")
    decoy.write_bytes(b"different synthetic browser; never executed")
    supplied = link / ".." / "browser"
    if path_kind == "relative":
        monkeypatch.chdir(tmp_path)
        supplied = supplied.relative_to(tmp_path)

    # Filesystem traversal follows the symlink before processing the parent.
    assert os.path.samefile(supplied, intended)
    assert not os.path.samefile(supplied, decoy)

    manager._parse_target_binary(supplied)

    assert manager._target_binary.is_absolute()
    assert manager._target_binary.samefile(intended), (
        "Making a browser path absolute must not silently select a different file."
    )


def test_binary_normalization_keeps_lexical_symlink_location(tmp_path: Path) -> None:
    """Verify binary normalization keeps lexical symlink location.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = _manager(tmp_path)
    browser = _browser(tmp_path / "target")
    launcher = tmp_path / "browser-launcher"
    launcher.symlink_to(browser)

    manager._parse_target_binary(launcher)

    assert manager._target_binary == launcher
    assert manager._target_binary.samefile(browser)


class _BytesPath:
    """Represent _BytesPath using the inherited implementation."""

    def __init__(self, path: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            path: Fixture or parametrized path input for this regression.
        """
        self.path = path

    def __fspath__(self) -> Any:
        """Fspath.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return os.fsencode(self.path)


@pytest.mark.parametrize("manager_class", _MANAGERS)
@pytest.mark.parametrize(
    "invalid_kind",
    [
        "bytes-existing",
        "bytes-pathlike",
        "number",
        "object",
        "empty",
        "missing",
        "directory",
    ],
)
def test_invalid_binary_paths_preserve_package_error_and_cause(
    tmp_path: Path, manager_class: Any, invalid_kind: Any
) -> None:
    """Verify invalid binary paths preserve package error and cause.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        manager_class: Fixture or parametrized manager class input for this regression.
        invalid_kind: Fixture or parametrized invalid kind input for this regression.
    """
    manager = _manager(tmp_path, manager_class)
    browser = _browser(tmp_path)
    supplied = {
        "bytes-existing": os.fsencode(browser),
        "bytes-pathlike": _BytesPath(browser),
        "number": 42,
        "object": object(),
        "empty": "",
        "missing": tmp_path / "missing browser",
        "directory": tmp_path,
    }[invalid_kind]

    with pytest.raises(errors.BrowserBinaryNotDetectedError) as failure:
        manager._parse_target_binary(supplied)

    assert failure.value.__cause__ is not None


def test_none_binary_clears_previous_override(tmp_path: Path) -> None:
    """Verify none binary clears previous override.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = _manager(tmp_path)
    manager._parse_target_binary(_browser(tmp_path))
    manager._parse_target_binary(None)
    assert manager._target_binary is None


@pytest.mark.parametrize("os_name", ["linux", "mac", "win"])
def test_environment_roots_omit_empty_entries_and_deduplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, os_name: Any
) -> None:
    """Verify environment roots omit empty entries and deduplicate.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        os_name: Fixture or parametrized os name input for this regression.
    """
    manager = _manager(tmp_path, os_name=os_name)
    roots = [tmp_path / name for name in ("first", "second", "third")]
    separator = os.pathsep
    environment = {
        "PATH": separator.join([str(roots[0]), "", str(roots[1]), str(roots[0]), ""])
    }
    expected = {roots[0], roots[1]}
    if os_name == "win":
        environment.update(
            {
                "PROGRAMFILES": str(roots[1]),
                "LOCALAPPDATA": str(roots[2]),
                "PROGRAMFILES(X86)": "",
            }
        )
        expected.add(roots[2])
    monkeypatch.setattr(drivers, "environ", environment)

    assert set(manager._environ_paths) == expected
    assert len(manager._environ_paths) == len(expected)
    assert Path.cwd() not in manager._environ_paths


@pytest.mark.parametrize("os_name", ["linux", "mac", "win"])
def test_missing_environment_paths_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, os_name: Any
) -> None:
    """Verify missing environment paths are safe.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        os_name: Fixture or parametrized os name input for this regression.
    """
    manager = _manager(tmp_path, os_name=os_name)
    monkeypatch.setattr(drivers, "environ", {})
    assert manager._environ_paths == []


@pytest.mark.parametrize("os_name", ["linux", "mac", "win"])
def test_malformed_environment_root_does_not_abort_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, os_name: Any
) -> None:
    """Skip one invalid external search root while retaining valid entries.

    Args:
        tmp_path: Isolated directory containing the valid search root.
        monkeypatch: Pytest fixture replacing the process environment mapping.
        os_name: Simulated operating-system family.
    """
    manager = _manager(tmp_path, os_name=os_name)
    valid = tmp_path / "valid-root"
    environment = {"PATH": os.pathsep.join(["invalid\x00root", str(valid)])}
    monkeypatch.setattr(drivers, "environ", environment)

    assert manager._environ_paths == [valid]


@pytest.mark.parametrize("manager_class", _MANAGERS)
def test_linux_discovery_normalizes_which_result_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any
) -> None:
    """Verify linux discovery normalizes which result without shell.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
    """
    manager = _manager(tmp_path, manager_class)
    browser = _browser(tmp_path / "bin")
    relative = str(browser.relative_to(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(drivers, "environ", {"PATH": str(browser.parent)})
    calls = []

    def fake_which(command: Any, *, path: Any) -> Any:
        """Fake which.

        Args:
            command: Fixture or parametrized command input for this regression.
            path: Fixture or parametrized path input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        calls.append((command, path))
        return relative

    monkeypatch.setattr(drivers, "which", fake_which)

    assert manager._detect_browser_location() == browser
    assert calls
    assert calls[0][1] == str(browser.parent)


def test_linux_which_miss_does_not_fall_back_to_nonexecutable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify linux which miss does not fall back to nonexecutable file.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager = _manager(tmp_path)
    candidate = tmp_path / "synthetic-browser"
    candidate.touch()
    monkeypatch.setattr(drivers, "environ", {"PATH": str(tmp_path)})
    monkeypatch.setattr(drivers, "which", lambda *_args, **_kwargs: None)

    assert manager._find_linux_browser_location(candidate.name) is None


@pytest.mark.skipif(
    os.name == "nt", reason="This lookup contract uses POSIX execute permissions."
)
def test_linux_discovery_integrates_real_which_without_executing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify linux discovery integrates real which without executing file.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager = _manager(tmp_path)
    candidate = _browser(tmp_path / "临时 executable directory")
    candidate.write_bytes(b"synthetic fixture only; not a program")
    candidate.chmod(0o700)
    monkeypatch.setattr(drivers, "environ", {"PATH": str(candidate.parent)})

    # Real shutil.which checks permissions; it does not execute the candidate.
    assert manager._find_linux_browser_location(candidate.name) == candidate

    candidate.chmod(0o600)
    assert manager._find_linux_browser_location(candidate.name) is None


def test_linux_missing_path_is_not_replaced_by_default_system_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify linux missing path is not replaced by default system search.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager = _manager(tmp_path)
    monkeypatch.setattr(drivers, "environ", {})
    calls = []

    def fake_which(command: Any, *, path: Any) -> None:
        """Fake which.

        Args:
            command: Fixture or parametrized command input for this regression.
            path: Fixture or parametrized path input for this regression.
        """
        calls.append((command, path))
        return None

    monkeypatch.setattr(drivers, "which", fake_which)

    assert manager._find_linux_browser_location("synthetic-browser") is None
    assert calls == [("synthetic-browser", "")]


def test_windows_discovery_includes_vendor_installation_root_from_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify windows discovery includes vendor installation root from path.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager = _manager(tmp_path, os_name="win")
    installation_root = tmp_path / "portable"
    browser = installation_root / "Vendor" / "Browser" / "browser.exe"
    browser.parent.mkdir(parents=True)
    browser.touch()
    monkeypatch.setattr(drivers, "environ", {"PATH": str(installation_root)})

    relative = str(browser.relative_to(installation_root))
    assert manager._find_win_browser_location(relative) == browser


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manager_class", [drivers.ChromeDriverManager, drivers.EdgeDriverManager]
)
@pytest.mark.parametrize("channel", ["unrecognized-channel", "", None, []])
async def test_invalid_channel_is_rejected_even_with_explicit_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any, channel: Any
) -> None:
    """Verify invalid channel is rejected even with explicit binary.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        channel: Fixture or parametrized channel input for this regression.
    """
    manager = _manager(tmp_path, manager_class)
    browser = _browser(tmp_path)

    def unexpected_probe(_path: Any) -> None:
        """Unexpected probe.

        Args:
            _path: Fixture or parametrized  path input for this regression.
        """
        raise AssertionError(
            "Invalid channels must be rejected before a browser probe."
        )

    monkeypatch.setattr(manager, "_detect_browser_version", unexpected_probe)

    with pytest.raises(errors.DriverManagerError, match="channel"):
        await manager.install(binary=browser, channel=channel)


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_class", _MANAGERS)
async def test_explicit_path_installation_passes_normalized_literal_path_to_fake_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any
) -> None:
    """Verify explicit path installation passes normalized literal path to fake probe.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
    """
    manager = _manager(tmp_path, manager_class)
    browser = _browser(tmp_path / "browsers")
    monkeypatch.chdir(tmp_path)
    checked = []
    version = (
        FirefoxVersion("120.0")
        if isinstance(manager, drivers.FirefoxDriverManager)
        else ChromiumVersion("120.0.6099.71")
    )

    def fake_probe(path: Any) -> Any:
        """Fake probe.

        Args:
            path: Fixture or parametrized path input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        checked.append(path)
        return version

    monkeypatch.setattr(manager, "_detect_browser_version", fake_probe)
    monkeypatch.setattr(
        manager, "_match_driver_executable", lambda *_args: "synthetic cached driver"
    )
    # Firefox auto uses the packaged table and a fake cache hit, never a network request.
    selector = "auto" if isinstance(manager, drivers.FirefoxDriverManager) else "build"

    installed = await manager.install(selector, binary=browser.relative_to(tmp_path))

    assert installed == "synthetic cached driver"
    assert checked == [browser]
    assert manager.browser_location == str(browser)


@pytest.mark.asyncio
async def test_result_request_uses_single_parsed_custom_pathlike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish a custom ``PathLike`` as its validated browser path.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible dependency substitution.
    """
    manager = _manager(tmp_path)
    browser = _browser(tmp_path / "browsers")
    supplied = _CountingTextPath(browser)
    monkeypatch.setattr(
        manager,
        "_detect_browser_version",
        lambda _path: ChromiumVersion("120.0.6099.71"),
    )
    monkeypatch.setattr(
        manager, "_match_driver_executable", lambda *_args: "synthetic cached driver"
    )

    result = await manager.install_result("build", binary=supplied)

    assert supplied.calls == 1
    assert result.request.binary == str(browser)
    assert manager.last_result == result


@pytest.mark.asyncio
async def test_cft_result_preserves_ignored_pathlike_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not relabel an ignored CfT override as the provisioned browser.

    Args:
        tmp_path: Isolated directory containing synthetic result locations.
        monkeypatch: Pytest fixture for reversible dependency substitution.
    """
    manager = _manager(tmp_path)
    requested = _CountingTextPath(tmp_path / "ignored browser override")
    driver = tmp_path / "cached chromedriver"
    provisioned_browser = tmp_path / "cached Chrome for Testing"
    version = ChromiumVersion("120.0.6099.71")

    def match(*_args: Any) -> str:
        """Publish one complete synthetic cached CfT pair.

        Returns:
            Driver location used by the cache-hit installation path.
        """
        manager._driver_version = version
        manager._driver_location = str(driver)
        manager._browser_version = version
        manager._browser_location = str(provisioned_browser)
        return str(driver)

    monkeypatch.setattr(manager, "_match_cft_driver_and_binary", match)

    result = await manager.install_result(
        version, channel="cft", binary=requested, policy="compatible-build"
    )

    assert requested.calls == 1
    assert result.request.binary == str(requested.path)
    assert result.browser_location == str(provisioned_browser)
    assert result.request.binary != result.browser_location
    assert manager.last_result == result


@pytest.mark.parametrize("manager_class", _MANAGERS)
@pytest.mark.parametrize("output", ["not-a-version", "", None])
def test_invalid_browser_probe_output_preserves_browser_version_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any, output: Any
) -> None:
    """Verify invalid browser probe output preserves browser version cause.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        output: Fixture or parametrized output input for this regression.
    """
    manager = _manager(tmp_path, manager_class)
    browser = _browser(tmp_path)
    monkeypatch.setattr(manager, "_read_from_cmd", lambda _command: output)

    with pytest.raises(errors.BrowserBinaryNotDetectedError) as failure:
        manager._detect_browser_version(str(browser))

    assert isinstance(failure.value.__cause__, errors.InvalidBrowserVersionError)


@pytest.mark.parametrize("manager_class", _MANAGERS)
@pytest.mark.parametrize("error_class", [FileNotFoundError, PermissionError])
@pytest.mark.parametrize("os_name", ["linux", "mac", "win"])
def test_browser_probe_oserror_is_wrapped_with_original_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manager_class: Any,
    error_class: Any,
    os_name: Any,
) -> None:
    """Verify browser probe oserror is wrapped with original cause.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
        error_class: Fixture or parametrized error class input for this regression.
        os_name: Fixture or parametrized os name input for this regression.
    """
    manager = _manager(tmp_path, manager_class, os_name)
    browser = _browser(tmp_path)
    underlying = error_class("synthetic browser probe error")

    def fail_probe(_command: Any) -> None:
        """Fail probe.

        Args:
            _command: Fixture or parametrized  command input for this regression.
        """
        raise underlying

    monkeypatch.setattr(manager, "_read_from_cmd", fail_probe)

    with pytest.raises(errors.BrowserBinaryNotDetectedError) as failure:
        manager._detect_browser_version(str(browser))

    assert failure.value.__cause__ is underlying


@pytest.mark.parametrize("manager_class", _MANAGERS)
def test_unsupported_platform_raises_existing_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_class: Any
) -> None:
    """Verify unsupported platform raises existing error.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_class: Fixture or parametrized manager class input for this regression.
    """
    manager = _manager(tmp_path, manager_class)
    manager._DriverManager__os_name = None
    monkeypatch.setattr(drivers, "system", lambda: "SyntheticUnsupportedOS")

    with pytest.raises(errors.UnsupportedPlatformError, match="SyntheticUnsupportedOS"):
        manager._detect_browser_location()


def test_unsupported_firefox_version_raises_package_diagnostic(tmp_path: Path) -> None:
    """Verify unsupported firefox version raises package diagnostic.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = _manager(tmp_path, drivers.FirefoxDriverManager)

    with pytest.raises(errors.InvalidBrowserVersionError, match="Firefox"):
        manager._find_max_compatible_driver_version(FirefoxVersion("77"))
