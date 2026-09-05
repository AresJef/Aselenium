"""Compatibility baselines for the real, publicly exported manager API.

These tests do not install a driver or inspect a real browser.  The compatibility
resource checks establish that the checked-in data is loadable, not that its
historical version ranges agree with current Mozilla releases.
"""

from __future__ import annotations

import inspect
import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

import aselenium
from aselenium import errors, manager
from aselenium import options as options_module
from aselenium import service as service_module

MANAGER_NAMES = (
    "EdgeDriverManager",
    "ChromeDriverManager",
    "ChromiumDriverManager",
    "FirefoxDriverManager",
    "SafariDriverManager",
)
VERSION_NAMES = (
    "ChromiumVersion",
    "FirefoxVersion",
    "GeckoVersion",
    "SafariVersion",
)
FACADE_NAMES = ("Chrome", "Chromium", "Edge", "Firefox", "Safari")
CONSTRUCTOR_PARAMETERS = (
    ("self", inspect.Parameter.empty),
    ("directory", None),
    ("max_cache_size", None),
    ("request_timeout", 10),
    ("download_timeout", 300),
    ("proxy", None),
)
INSTALL_PARAMETERS = {
    "EdgeDriverManager": (
        ("self", inspect.Parameter.empty),
        ("version", "build"),
        ("channel", "stable"),
        ("binary", None),
    ),
    "ChromeDriverManager": (
        ("self", inspect.Parameter.empty),
        ("version", "build"),
        ("channel", "stable"),
        ("binary", None),
    ),
    "ChromiumDriverManager": (
        ("self", inspect.Parameter.empty),
        ("version", "build"),
        ("binary", None),
    ),
    "FirefoxDriverManager": (
        ("self", inspect.Parameter.empty),
        ("version", "latest"),
        ("binary", None),
    ),
    "SafariDriverManager": (
        ("self", inspect.Parameter.empty),
        ("channel", "stable"),
        ("driver", None),
        ("binary", None),
    ),
}


def assert_parameters(callable_object: Any, expected: Any) -> None:
    """Compare callable semantics without annotation-string formatting noise.

    Args:
        callable_object: Fixture or parametrized callable object input for this regression.
        expected: Fixture or parametrized expected input for this regression.
    """
    parameters = tuple(inspect.signature(callable_object).parameters.values())
    assert (
        tuple((parameter.name, parameter.default) for parameter in parameters)
        == expected
    )
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for parameter in parameters
    )


def test_manager_public_exports_are_available_at_both_import_paths() -> None:
    """Verify manager public exports are available at both import paths."""
    expected = set(MANAGER_NAMES + VERSION_NAMES) | {
        "InstallationRequest",
        "InstallationResult",
    }
    assert set(manager.__all__) == expected
    assert len(manager.__all__) == len(expected)
    for name in expected:
        exported = getattr(manager, name)
        assert inspect.isclass(exported)
        assert getattr(aselenium, name) is exported


@pytest.mark.parametrize("name", MANAGER_NAMES)
def test_manager_constructor_and_install_signatures(name: Any) -> None:
    """Verify manager constructor and install signatures.

    Args:
        name: Fixture or parametrized name input for this regression.
    """
    manager_class = getattr(manager, name)
    constructor = (
        (("self", inspect.Parameter.empty),)
        if name == "SafariDriverManager"
        else CONSTRUCTOR_PARAMETERS
    )
    assert_parameters(manager_class.__init__, constructor)
    assert_parameters(manager_class.install, INSTALL_PARAMETERS[name])
    assert inspect.iscoroutinefunction(manager_class.install)
    assert_parameters(manager_class.reset, (("self", inspect.Parameter.empty),))
    assert not inspect.iscoroutinefunction(manager_class.reset)


@pytest.mark.parametrize(
    "argument",
    [
        {"directory": "/tmp"},
        {"max_cache_size": 1},
        {"request_timeout": 1},
        {"download_timeout": 1},
        {"proxy": "https://proxy.invalid"},
    ],
)
def test_safari_manager_rejects_inapplicable_provisioning_configuration(
    argument: dict[str, Any],
) -> None:
    """Keep Safari's constructor limited to its system-managed behavior.

    Args:
        argument: Unsupported cache, network, or proxy keyword argument.
    """
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        manager.SafariDriverManager(**argument)


@pytest.mark.parametrize("name", MANAGER_NAMES)
def test_manager_can_be_constructed_without_browser_discovery(
    name: Any, tmp_path: Path
) -> None:
    """Verify manager can be constructed without browser discovery.

    Args:
        name: Fixture or parametrized name input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager_class = getattr(manager, name)
    instance = (
        manager_class()
        if name == "SafariDriverManager"
        else manager_class(directory=str(tmp_path))
    )
    assert instance.max_cache_size is None
    assert instance.requests_timeout == 10
    assert instance.download_timeout == 300
    assert instance.proxy is None
    instance.reset()


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="bool"),
        pytest.param(1.5, id="fractional-float"),
        pytest.param("2", id="numeric-text"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
    ],
)
def test_manager_cache_limit_requires_a_positive_exact_integer(
    tmp_path: Path, value: Any
) -> None:
    """Reject coercible and nonpositive cache limits without mutating configuration.

    Args:
        tmp_path: Isolated cache parent for a real manager instance.
        value: Invalid cache limit that must not be coerced to an integer.
    """
    instance = manager.ChromeDriverManager(directory=tmp_path, max_cache_size=2)

    with pytest.raises(errors.InvalidArgumentError, match="max cache size"):
        instance.max_cache_size = value

    assert instance.max_cache_size == 2


@pytest.mark.parametrize(
    ("argument", "message"),
    [
        pytest.param({"max_cache_size": True}, "max cache size", id="cache-limit"),
        pytest.param({"request_timeout": 0}, "requests timeout", id="request-timeout"),
        pytest.param(
            {"download_timeout": float("inf")},
            "download timeout",
            id="download-timeout",
        ),
        pytest.param(
            {"proxy": "https://proxy.invalid"},
            "HTTP proxy",
            id="proxy-scheme",
        ),
    ],
)
def test_invalid_manager_configuration_does_not_create_cache(
    tmp_path: Path, argument: dict[str, Any], message: str
) -> None:
    """Validate scalar constructor inputs before creating cache directories.

    Args:
        tmp_path: Isolated parent whose contents expose filesystem side effects.
        argument: Invalid manager constructor keyword and value.
        message: Diagnostic fragment identifying the rejected setting.
    """
    with pytest.raises(errors.InvalidArgumentError, match=message):
        manager.ChromeDriverManager(directory=tmp_path, **argument)

    assert not (tmp_path / ".aselenium").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,message",
    [
        pytest.param({"policy": []}, "policy", id="non-text-policy"),
        pytest.param(
            {"validate_compatibility": 1},
            "validate_compatibility",
            id="non-boolean-validation",
        ),
    ],
)
async def test_install_result_control_values_require_exact_public_types(
    tmp_path: Path, kwargs: dict[str, Any], message: str
) -> None:
    """Reject invalid policy and compatibility controls before installation starts.

    Args:
        tmp_path: Isolated cache parent for a real manager instance.
        kwargs: Invalid install-result control passed by keyword.
        message: Required diagnostic fragment identifying the rejected control.
    """
    instance = manager.ChromeDriverManager(directory=tmp_path)

    with pytest.raises(errors.InvalidArgumentError, match=message):
        await instance.install_result(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args,kwargs,message",
    [
        pytest.param((120,), {}, "version", id="non-text-version"),
        pytest.param(
            ("120.0.1.1",), {"artifact": []}, "artifact", id="non-text-artifact"
        ),
        pytest.param(("120.0.1.1",), {"pinned": 1}, "pinned", id="non-boolean-pin"),
    ],
)
async def test_pin_controls_require_exact_public_types(
    tmp_path: Path,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    message: str,
) -> None:
    """Reject malformed pin inputs before parsing a version or touching the cache.

    Args:
        tmp_path: Isolated cache parent for a real manager instance.
        args: Positional pin arguments containing the version candidate.
        kwargs: Optional malformed artifact or pin-state control.
        message: Required diagnostic fragment identifying the rejected input.
    """
    instance = manager.ChromeDriverManager(directory=tmp_path)

    with pytest.raises(errors.InvalidArgumentError, match=message):
        await instance.pin(*args, **kwargs)


@pytest.mark.parametrize("name", FACADE_NAMES)
def test_browser_facade_constructs_without_starting_or_creating_profile(
    name: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify browser facade constructs without starting or creating profile.

    Args:
        name: Fixture or parametrized name input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """

    def forbidden(*args: Any, **kwargs: Any) -> None:
        """Forbidden.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        pytest.fail("Facade construction must not launch a service or create a profile")

    # The suite already blocks manager probes/network traffic. These additional
    # guards cover the service process and temporary profile creation paths.
    monkeypatch.setattr(service_module, "Popen", forbidden)
    monkeypatch.setattr(options_module, "mkdtemp", forbidden)
    facade_class = getattr(aselenium, name)
    facade = (
        facade_class() if name == "Safari" else facade_class(directory=str(tmp_path))
    )

    assert isinstance(facade.manager, getattr(manager, name + "DriverManager"))
    assert isinstance(facade.options, getattr(aselenium, name + "Options"))
    assert getattr(facade.options, "_profile", None) is None
    for field in (
        "_driver_location",
        "_driver_version",
        "_browser_location",
        "_browser_version",
    ):
        assert getattr(facade.manager, field) is None
    if name == "Safari":
        assert facade.manager._file_manager is None
        assert not (tmp_path / ".aselenium").exists()
    else:
        assert (tmp_path / ".aselenium").is_dir()


@pytest.mark.parametrize("name", VERSION_NAMES)
def test_version_constructor_signature(name: Any) -> None:
    """Verify version constructor signature.

    Args:
        name: Fixture or parametrized name input for this regression.
    """
    assert_parameters(
        getattr(manager, name).__init__,
        (("self", inspect.Parameter.empty), ("version", inspect.Parameter.empty)),
    )


def test_source_gecko_resource_is_readable_and_loaded_by_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify source gecko resource is readable and loaded by manager.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    resource = resources.files("aselenium.manager").joinpath(
        "geckodriver", "compatibility.json"
    )
    assert resource.is_file()
    data = json.loads(resource.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data
    for gecko_version, bounds in data.items():
        assert isinstance(gecko_version, str)
        assert set(bounds) == {"min_firefox_version", "max_firefox_version"}
        assert all(isinstance(value, str) for value in bounds.values())

    manager_class = manager.FirefoxDriverManager
    # Force a real read rather than inheriting another test's class-level cache.
    for name in (
        "_GECKODRIVER_TABLE",
        "_GECKODRIVER_TABLE_MAX_VERSION",
        "_GECKODRIVER_MAX_VERSION",
    ):
        monkeypatch.setattr(manager_class, name, None)
    manager_class.load_driver_compatibility_table()

    loaded = {
        str(version): {key: str(value) for key, value in bounds.items()}
        for version, bounds in manager_class._GECKODRIVER_TABLE.items()
    }
    assert loaded == data
    expected_maximum = max(manager.GeckoVersion(version) for version in data)
    assert manager_class._GECKODRIVER_TABLE_MAX_VERSION == expected_maximum
    assert manager_class._GECKODRIVER_MAX_VERSION == expected_maximum
