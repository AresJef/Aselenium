"""Local filesystem, geometry, mapping, and version value-object contracts."""

from __future__ import annotations

import plistlib
from pathlib import Path
from types import SimpleNamespace

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
from aselenium.utils import CustomDict, Rectangle, load_plist_file


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


@pytest.mark.parametrize("value", [True, float("inf"), float("-inf"), float("nan")])
def test_rectangle_rejects_boolean_and_nonfinite_geometry(value: float) -> None:
    """Reject ambiguous or non-serializable numeric geometry.

    Args:
        value: Boolean or nonfinite value that WebDriver cannot represent safely.
    """
    with pytest.raises(errors.InvalidRectValueError):
        Rectangle(value, 20, 3, 4)

    rectangle = Rectangle(10, 20, 3, 4)
    with pytest.raises(errors.InvalidRectValueError):
        rectangle.width = value
    assert rectangle.width == 10


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


def test_identity_value_objects_do_not_use_hashes_as_equality_proofs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep identity semantics even when distinct instances have colliding hashes.

    Args:
        monkeypatch: Fixture restoring the patched built-in hash lookup.
    """
    first_rectangle = Rectangle(1, 2, 3, 4)
    second_rectangle = Rectangle(1, 2, 3, 4)
    first_mapping = CustomDict(value=1)
    second_mapping = CustomDict(value=1)
    monkeypatch.setattr("builtins.hash", lambda value: 7)

    assert first_rectangle != second_rectangle
    assert first_mapping != second_mapping


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


def test_plist_loading_accepts_pathlike_input(tmp_path: Path) -> None:
    """Decode a local property list through the retained Path workflow.

    Args:
        tmp_path: Directory for the generated property-list fixture.
    """
    data = {"name": "中文", "nested": {"enabled": True}, "empty": {}}
    plist_path = tmp_path / "fixture.plist"
    plist_path.write_bytes(plistlib.dumps(data))
    assert load_plist_file(plist_path) == data


def test_plist_loading_rejects_non_mapping_root(tmp_path: Path) -> None:
    """Reject syntactically valid plist data that lacks Safari metadata keys.

    Args:
        tmp_path: Directory for the generated property-list fixture.
    """
    plist_path = tmp_path / "array.plist"
    plist_path.write_bytes(plistlib.dumps(["Safari", "metadata"]))

    with pytest.raises(ValueError, match="root must be a dictionary"):
        load_plist_file(plist_path)


def test_plist_loading_rejects_non_string_top_level_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject decoder results outside the declared string-key mapping contract.

    Args:
        tmp_path: Directory for an existing file accepted by the path boundary.
        monkeypatch: Fixture restoring the plist decoder after the test.
    """
    plist_path = tmp_path / "fixture.plist"
    plist_path.touch()
    monkeypatch.setattr("aselenium.utils.load", lambda stream: {1: "invalid"})

    with pytest.raises(ValueError, match="keys must all be strings"):
        load_plist_file(plist_path)


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
        proxy.auto_detect is True and proxy.pac_url == "http://config.invalid/proxy.pac"
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
        driver_path = Path("/fixture/driver")
        service = SimpleNamespace(
            driver_location=driver_path,
            driver_version=driver_version,
        )
        session = session_class(options, service)
        assert session.options is options and session.service is service
        assert session.browser_location == binary
        assert session.browser_version == "123.4.5"
        options.browser_version = version_class("124.0.0")
        assert session.browser_version == "123.4.5"
        assert (
            session.driver_location == driver_path
            and session.driver_version is driver_version
        )
        assert session.connection is None
        connection = object()
        session._conn = connection
        assert session.connection is connection
    finally:
        options.close()
