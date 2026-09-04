"""Local filesystem, geometry, mapping, and version value-object contracts."""

from __future__ import annotations

import json
import plistlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aselenium import errors
from aselenium.chrome.options import ChromeOptions
from aselenium.chrome.session import ChromeSession
from aselenium.chromium.options import ChromiumOptions
from aselenium.chromium.session import ChromiumSession
from aselenium.edge.options import EdgeOptions
from aselenium.edge.session import EdgeSession
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.session import FirefoxSession
from aselenium.manager.version import (
    ChromiumVersion,
    FirefoxVersion,
    GeckoVersion,
    SafariVersion,
    Version,
)
from aselenium.options import BaseOptions, Proxy, Timeouts
from aselenium.safari.options import SafariOptions
from aselenium.safari.session import SafariSession
from aselenium.session import (
    ChromiumBaseSession,
    DevToolsCMD,
    JavaScript,
    Network,
    Session,
    Window,
)
from aselenium.utils import (
    CustomDict,
    Rectangle,
    is_file_dir_exists,
    is_path_dir,
    is_path_file,
    load_json_file,
    load_plist_file,
    prettify_dict,
    validate_dir,
    validate_file,
    validate_save_file_path,
)


def test_rectangle_coordinates_copy_and_mutation() -> None:
    """Calculate derived geometry and keep copied rectangles independent."""
    rectangle = Rectangle(11, 21, -3, 5)
    assert (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom) == (
        -3,
        5,
        8,
        26,
    )
    assert (rectangle.center_x, rectangle.center_y) == (2, 15)
    assert rectangle and rectangle == rectangle
    assert rectangle.dict == rectangle.copy().dict
    assert rectangle != rectangle.copy()
    assert rectangle != object()
    assert "Rectangle" in repr(rectangle)
    assert hash(rectangle) == id(rectangle)
    copy = rectangle.copy()
    rectangle.width = 30
    rectangle.height = 40
    rectangle.x = 10
    rectangle.y = -10
    assert rectangle.dict == {"width": 30, "height": 40, "x": 10, "y": -10}
    assert copy.dict == {"width": 11, "height": 21, "x": -3, "y": 5}
    for name in ("width", "height", "x", "y"):
        before = getattr(rectangle, name)
        setattr(rectangle, name, None)
        assert getattr(rectangle, name) == before


@pytest.mark.parametrize("name", ["width", "height", "x", "y"])
def test_rectangle_invalid_assignment_does_not_mutate(name: str) -> None:
    """Reject a nonnumeric assignment without overwriting the previous geometry.

    Args:
        name: Rectangle component receiving the invalid value.
    """
    rectangle = Rectangle(10, 20, 3, 4)
    before = rectangle.dict
    with pytest.raises(errors.InvalidRectValueError):
        setattr(rectangle, name, "invalid")
    assert rectangle.dict == before


def test_custom_mapping_public_accessors_and_top_level_copy() -> None:
    """Keep mapping operations ordered and independent at the documented top level."""
    value = CustomDict(first=1, second=2)
    assert list(value) == ["first", "second"]
    assert list(value.keys()) == ["first", "second"]
    assert list(value.values()) == [1, 2]
    assert list(value.items()) == [("first", 1), ("second", 2)]
    assert value.get("missing", "fallback") == "fallback"
    assert value.get("first") == 1
    assert len(value) == 2 and "first" in value and "missing" not in value
    detached = value.dict
    detached["first"] = 99
    assert value["first"] == 1
    value["third"] = 3
    assert value["third"] == 3 and len(value) == 3
    with pytest.raises(KeyError):
        _ = value["missing"]
    assert value == value and value != object()
    assert hash(value) == id(value)
    assert "CustomDict" in repr(value)


@pytest.mark.parametrize(
    "version_class",
    [Version, FirefoxVersion, GeckoVersion, SafariVersion, ChromiumVersion],
)
def test_version_public_views_and_numeric_ordering(
    version_class: type[Version],
) -> None:
    """Cover component getters, memoized views, comparison operators, and identity copies.

    Args:
        version_class: Base or browser-specific version parser.
    """
    text = "10.2.3.4" if version_class is ChromiumVersion else "10.2.3"
    version = version_class(text)
    copied = version_class(version)
    older, newer = version_class("9.9.9"), version_class("11")
    assert version > older and version >= older and version >= copied
    assert version < newer and version <= newer and version <= copied
    assert version == copied and version != older
    assert hash(version) == hash(copied)
    assert version != 1
    with pytest.raises(TypeError):
        _ = version < 1
    assert bool(version) and str(version) == text and repr(version) == repr(text)
    assert version.version == text and len(version) == len(text.split("."))
    for _ in range(2):
        assert version.major == "10" and version.major_num == 10
        assert version.patch == text
        if version_class is ChromiumVersion:
            assert version.minor == "10.2" and version.minor_num == 2
            assert version.build == "10.2.3" and version.build_num == 3
            assert version.patch_num == 4
        else:
            assert version.build == "10.2" and version.build_num == 2
            assert version.patch_num == 3
    short = version_class("10")
    assert short.major == short.build == short.patch == "10"
    assert short.build_num == short.patch_num == 0


def test_path_predicates_and_validation(tmp_path: Path) -> None:
    """Distinguish existing files/directories and normalize output extensions.

    Args:
        tmp_path: Private directory holding a synthetic input and output paths.
    """
    file = tmp_path / "input.txt"
    file.write_text("fixture", encoding="utf-8")
    assert is_path_file(file) and not is_path_dir(file)
    assert is_path_dir(tmp_path) and not is_path_file(tmp_path)
    assert is_file_dir_exists(file)
    assert validate_dir(str(tmp_path)) == str(tmp_path)
    assert validate_file(str(file)) == str(file)
    assert validate_save_file_path(str(tmp_path / "capture"), ".png") == str(
        tmp_path / "capture.png"
    )
    assert validate_save_file_path(str(tmp_path / "capture.png"), ".png") == str(
        tmp_path / "capture.png"
    )
    with pytest.raises(errors.AseleniumDirectoryNotFoundError):
        validate_dir(str(file))
    with pytest.raises(errors.AseleniumFileNotFoundError):
        validate_file(str(tmp_path))
    with pytest.raises(errors.AseleniumDirectoryNotFoundError):
        validate_save_file_path(str(tmp_path / "missing" / "out"), ".png")


@pytest.mark.parametrize("invalid", [None, object(), {"path": "invalid"}])
def test_path_helpers_reject_non_path_inputs(invalid: Any) -> None:
    """Return false from predicates and raise package errors from validators.

    Args:
        invalid: Value that is neither a path string nor a filesystem-path object.
    """
    assert not is_path_file(invalid)
    assert not is_path_dir(invalid)
    assert not is_file_dir_exists(invalid)
    for validator in (validate_file, validate_dir):
        with pytest.raises(errors.AseleniumInvalidPathError):
            validator(invalid)
    with pytest.raises(errors.AseleniumInvalidPathError):
        validate_save_file_path(invalid, ".png")


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_validated_relative_paths_match_documented_absolute_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Expose the documented absolute-path contract for relative valid inputs.

    Args:
        tmp_path: Isolated working directory.
        monkeypatch: Fixture restoring the original working directory.
        kind: Whether the relative input names a file or a directory.
    """
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "fixture"
    if kind == "file":
        target.write_bytes(b"fixture")
        result = validate_file("fixture")
    else:
        target.mkdir()
        result = validate_dir("fixture")
    assert result == str(target)


def test_json_plist_loading_and_nested_diagnostic_format(tmp_path: Path) -> None:
    """Read local structured files and retain nested values in diagnostic formatting.

    Args:
        tmp_path: Directory for generated JSON and plist fixtures.
    """
    data = {"name": "中文", "nested": {"enabled": True}, "empty": {}}
    json_path, plist_path = tmp_path / "fixture.json", tmp_path / "fixture.plist"
    json_path.write_text(json.dumps(data), encoding="utf-8")
    plist_path.write_bytes(plistlib.dumps(data))
    assert load_json_file(str(json_path)) == data
    assert load_plist_file(str(plist_path)) == data
    formatted = prettify_dict(data, lead="--")
    assert "--'name': '中文'" in formatted
    assert "----'enabled': True" in formatted
    assert "--'empty': {}" in formatted
    with pytest.raises(FileNotFoundError):
        load_json_file(str(tmp_path / "missing"))


def test_cached_value_copies_and_network_accessors() -> None:
    """Copy nested script/CDP arguments independently and expose network units unchanged."""
    command = DevToolsCMD("sample", "Runtime.evaluate", payload={"items": [1]})
    copied_command = command.copy()
    assert copied_command.name == "sample" and copied_command.cmd == "Runtime.evaluate"
    copied_command.kwargs["payload"]["items"].append(2)
    assert command.kwargs == {"payload": {"items": [1]}}
    script = JavaScript("sample", "return arguments[0]", {"items": [1]})
    copied_script = script.copy()
    assert copied_script.name == "sample" and copied_script.script == script.script
    copied_script.args[0]["items"].append(2)
    assert script.args == [{"items": [1]}]
    window = Window("handle", "named")
    copied_window = window.copy()
    assert copied_window is not window and copied_window == window
    assert copied_window.handle == "handle" and copied_window.name == "named"
    network = Network(
        offline=True, latency=50, upload_throughput=100, download_throughput=200
    )
    assert network.offline is True and network.latency == 50
    assert network.upload_throughput == 100 and network.download_throughput == 200


def test_option_public_views_and_abstract_construction() -> None:
    """Read proxy modes and timeout units and enforce the base constructor boundary."""

    class UnconstructedOptions(BaseOptions):
        """Provide initial capabilities while deliberately omitting construction."""

        DEFAULT_CAPABILITIES = {"fixture": True}

    proxy = Proxy(auto_detect=True)
    assert proxy.auto_detect is True and proxy.pac_url is None
    proxy.pac_url = "http://config.invalid/proxy.pac"
    assert (
        proxy.auto_detect is False
        and proxy.pac_url == "http://config.invalid/proxy.pac"
    )
    timeouts = Timeouts(implicit=0, pageLoad=2.5, script=1.5, unit="s")
    assert timeouts.pageLoad == 2.5 and timeouts.pageLoad_ms == 2500
    assert timeouts.script == 1.5 and timeouts.script_ms == 1500
    options = UnconstructedOptions()
    try:
        with pytest.raises(NotImplementedError):
            options.construct()
        with pytest.raises(errors.InvalidOptionsError):
            _ = options.browser_name
        options.set_capability("browserName", "fixture")
        assert options.browser_name == "fixture"
        options.unhandled_prompt_behavior = "dismiss"
        assert options.unhandled_prompt_behavior == "dismiss"
    finally:
        options.close()
    safari = SafariOptions()
    try:
        assert not safari.automatic_inspection and not safari.automatic_profiling
        assert not safari.technology_preview
        safari.automatic_inspection = True
        safari.automatic_profiling = True
        safari.technology_preview = True
        assert safari.automatic_inspection and safari.automatic_profiling
        assert safari.technology_preview
    finally:
        safari.close()


@pytest.mark.parametrize(
    "session_class,options_class,version_class",
    [
        (Session, ChromeOptions, ChromiumVersion),
        (ChromiumBaseSession, ChromeOptions, ChromiumVersion),
        (ChromeSession, ChromeOptions, ChromiumVersion),
        (ChromiumSession, ChromiumOptions, ChromiumVersion),
        (EdgeSession, EdgeOptions, ChromiumVersion),
        (FirefoxSession, FirefoxOptions, FirefoxVersion),
        (SafariSession, SafariOptions, SafariVersion),
    ],
)
def test_session_metadata_accessors_preserve_configuration_snapshot(
    tmp_path: Path,
    session_class: type[Session],
    options_class: type[BaseOptions],
    version_class: type[Version],
) -> None:
    """Expose owned objects and capture configured versions without probing a browser.

    Args:
        tmp_path: Directory for a harmless stand-in browser executable path.
        session_class: Base or vendor-specific session class.
        options_class: Matching options implementation.
        version_class: Browser version type accepted by the options.
    """
    binary = tmp_path / "browser"
    binary.write_bytes(b"fixture")
    options = options_class()
    try:
        options.browser_location = str(binary)
        options.browser_version = version_class("123.4.5")
        driver_version = Version("1.2.3")
        service = SimpleNamespace(
            _driver_location="/fixture/driver", _driver_version=driver_version
        )
        session = session_class(options, service)
        assert session.options is options and session.service is service
        assert session.browser_location == str(binary)
        assert session.browser_version == "123.4.5"
        options.browser_version = version_class("124.0.0")
        assert session.browser_version == "123.4.5"
        assert (
            session.driver_location == "/fixture/driver"
            and session.driver_version is driver_version
        )
        assert session.connection is None
        connection = object()
        session._conn = connection
        assert session.connection is connection
    finally:
        options.close()
