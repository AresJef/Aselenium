"""Offline contracts for browser-specific options, profiles, and commands.

These tests exercise real package methods against a recording transport. They do
not establish that an unavailable native browser implements the vendor commands.
"""

from __future__ import annotations

from asyncio import CancelledError
from base64 import b64decode, b64encode
from collections.abc import Callable, Iterator
from io import BytesIO
from json import dumps, loads
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import pytest

from aselenium import Chrome, Chromium, Edge, Firefox, Safari, errors
from aselenium.chrome.options import ChromeOptions
from aselenium.chrome.service import ChromeService
from aselenium.chromium.options import ChromiumOptions
from aselenium.chromium.service import ChromiumService
from aselenium.command import Command
from aselenium.edge.options import EdgeOptions
from aselenium.edge.service import EdgeService
from aselenium.firefox import options as firefox_options_module
from aselenium.firefox import session as firefox_session_module
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.service import FirefoxService
from aselenium.firefox.session import FirefoxSession
from aselenium.firefox.utils import FirefoxAddon, extract_firefox_addon_details
from aselenium.manager.version import ChromiumVersion, FirefoxVersion, GeckoVersion
from aselenium.options import BaseOptions, ChromiumBaseOptions, ChromiumProfile, Proxy
from aselenium.safari.options import SafariOptions
from aselenium.safari.service import SafariService
from aselenium.safari.session import SafariSession
from aselenium.session import Session

OPTION_CLASSES = (
    ChromeOptions,
    ChromiumOptions,
    EdgeOptions,
    FirefoxOptions,
    SafariOptions,
)
CHROMIUM_OPTION_CLASSES = (ChromeOptions, ChromiumOptions, EdgeOptions)


class RecordingTransport:
    """Capture command envelopes and return independently supplied wire responses."""

    def __init__(self, responses: list[Any]) -> None:
        """Store queued wire responses and initialize the command log.

        Args:
            responses: Responses or exceptions returned in command order.
        """
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def execute(
        self,
        base_url: str,
        command: str,
        *,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Record one command and consume the next independent response.

        Args:
            base_url: Session path supplied by the wrapper.
            command: Requested command identifier.
            body: Optional command payload.
            keys: Optional route substitutions.
            timeout: Optional command timeout in seconds.

        Returns:
            The next queued WebDriver response.

        Raises:
            BaseException: If the queued item is an exception.
        """
        self.calls.append(
            {
                "base_url": base_url,
                "command": command,
                "body": body,
                "keys": keys,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.fixture
def make_session() -> Iterator[
    Callable[[type[Session], list[Any]], tuple[Session, RecordingTransport]]
]:
    """Provide vendor sessions with a disposable fake transport and no processes.

    Yields:
        A factory accepting the session class and queued wire responses.
    """
    sessions: list[Session] = []

    def create(
        session_class: type[Session], responses: list[Any]
    ) -> tuple[Session, RecordingTransport]:
        """Construct a real session wrapper with fake external dependencies.

        Args:
            session_class: FirefoxSession or SafariSession implementation to exercise.
            responses: Wire responses consumed by the recording transport.

        Returns:
            The real session and its recording transport.
        """
        options = (
            FirefoxOptions() if session_class is FirefoxSession else SafariOptions()
        )
        session = session_class(options, SimpleNamespace(url="http://127.0.0.1:4444"))
        transport = RecordingTransport(responses)
        session._conn = transport
        session._base_url = "/session/vendor-test"
        sessions.append(session)
        return session, transport

    yield create
    for session in sessions:
        session._Session__closed = True
        session.options.close()


@pytest.fixture
def addon_directory(tmp_path: Path) -> Path:
    """Create a valid local WebExtension with a nested resource.

    Args:
        tmp_path: Disposable directory supplied by pytest.

    Returns:
        The unpacked add-on directory.
    """
    directory = tmp_path / "fixture-addon"
    directory.mkdir()
    manifest = {
        "manifest_version": 3,
        "name": "Offline fixture",
        "version": "1.2.3",
        "browser_specific_settings": {"gecko": {"id": "fixture@example.test"}},
    }
    (directory / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
    (directory / "resources").mkdir()
    (directory / "resources" / "message.txt").write_text(
        "fixture resource", encoding="utf-8"
    )
    return directory


@pytest.mark.parametrize("context", ["content", "chrome"])
@pytest.mark.asyncio
async def test_firefox_context_read_and_switch(
    make_session: Callable[..., Any], context: str
) -> None:
    """Check Firefox context routing and the read-after-write return value.

    Args:
        make_session: Isolated session factory.
        context: Supported Firefox execution context.
    """
    session, transport = make_session(
        FirefoxSession, [{"value": context}, {"value": None}, {"value": context}]
    )
    assert await session.context == context
    assert await session.set_context(context) == context
    assert [call["command"] for call in transport.calls] == [
        Command.FIREFOX_GET_CONTEXT,
        Command.FIREFOX_SET_CONTEXT,
        Command.FIREFOX_GET_CONTEXT,
    ]
    assert transport.calls[1]["body"] == {"context": context}


@pytest.mark.asyncio
async def test_firefox_reset_context(make_session: Callable[..., Any]) -> None:
    """Reset Firefox context to content and return its subsequent wire value.

    Args:
        make_session: Isolated session factory.
    """
    session, transport = make_session(
        FirefoxSession, [{"value": None}, {"value": "content"}]
    )
    assert await session.reset_context() == "content"
    assert transport.calls[0]["body"] == {"context": "content"}
    assert transport.calls[1]["command"] == Command.FIREFOX_GET_CONTEXT


@pytest.mark.parametrize("context", ["", "CHROME", "window", None, 42])
@pytest.mark.asyncio
async def test_firefox_context_rejects_invalid_input(
    make_session: Callable[..., Any], context: Any
) -> None:
    """Reject unsupported context names before sending a command.

    Args:
        make_session: Isolated session factory.
        context: Unsupported input, including incorrect runtime types.
    """
    session, transport = make_session(FirefoxSession, [])
    with pytest.raises(errors.InvalidArgumentError):
        await session.set_context(context)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_firefox_missing_context_is_package_error(
    make_session: Callable[..., Any],
) -> None:
    """Translate a response missing the context field to InvalidResponseError.

    Args:
        make_session: Isolated session factory.
    """
    session, _ = make_session(FirefoxSession, [{}])
    with pytest.raises(errors.InvalidResponseError):
        await session.context


@pytest.mark.parametrize(
    "value", [None, True, 7, "", " ", "invalid", b"content", {}, []]
)
@pytest.mark.asyncio
async def test_firefox_context_rejects_malformed_wire_value(
    make_session: Callable[..., Any], value: Any
) -> None:
    """Require the advertised context union for malformed server responses.

    Args:
        make_session: Isolated session factory.
        value: Invalid wire context value.
    """
    session, _ = make_session(FirefoxSession, [{"value": value}])
    with pytest.raises(errors.InvalidResponseError):
        await session.context


@pytest.mark.parametrize(
    "response", [{}, {"value": None}, {"value": "not base64!"}, {"value": 7}]
)
@pytest.mark.asyncio
async def test_firefox_full_screenshot_rejects_invalid_response(
    make_session: Callable[..., Any], response: dict[str, Any]
) -> None:
    """Translate malformed screenshot envelopes and encodings to package errors.

    Args:
        make_session: Isolated session factory.
        response: Invalid screenshot response envelope.
    """
    session, _ = make_session(FirefoxSession, [response])
    with pytest.raises(errors.InvalidResponseError):
        await session.take_full_screenshot()


@pytest.mark.asyncio
async def test_firefox_full_screenshot_bytes_and_file(
    make_session: Callable[..., Any], tmp_path: Path
) -> None:
    """Decode and save Firefox's full-page screenshot through the real file path.

    Args:
        make_session: Isolated session factory.
        tmp_path: Disposable output directory.
    """
    data = b"\x89PNG\r\n\x1a\nfixture"
    wire = {"value": b64encode(data).decode("ascii")}
    session, transport = make_session(FirefoxSession, [wire, wire, {"value": ""}])
    assert await session.take_full_screenshot() == data
    target = tmp_path / "page.png"
    assert await session.save_full_screenshot(str(target)) is True
    assert target.read_bytes() == data
    assert await session.save_full_screenshot(str(tmp_path / "empty.png")) is False
    assert not (tmp_path / "empty.png").exists()
    assert all(
        call["command"] == Command.FIREFOX_FULL_PAGE_SCREENSHOT
        for call in transport.calls
    )


@pytest.mark.asyncio
async def test_firefox_full_screenshot_invalid_output_path(
    make_session: Callable[..., Any],
) -> None:
    """Reject a non-path destination before requesting browser data.

    Args:
        make_session: Isolated session factory.
    """
    session, transport = make_session(FirefoxSession, [])
    with pytest.raises(errors.InvalidArgumentError):
        await session.save_full_screenshot(None)
    assert transport.calls == []


@pytest.mark.parametrize("packed", [False, True])
@pytest.mark.asyncio
async def test_firefox_addon_install_and_uninstall(
    make_session: Callable[..., Any], addon_directory: Path, packed: bool
) -> None:
    """Install both WebExtension forms, inspect the encoded payload, and remove them.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension fixture.
        packed: Whether to send a packed XPI instead of an unpacked directory.
    """
    path = addon_directory
    if packed:
        path = addon_directory.parent / "addon.xpi"
        with ZipFile(path, "w") as archive:
            for file in addon_directory.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(addon_directory))
    session, transport = make_session(
        FirefoxSession,
        [{"value": "fixture@example.test"}, {"value": None}, {"value": None}],
    )
    addons = await session.install_addons(path, temporary=True)
    assert len(addons) == 1
    assert (addons[0].id, addons[0].name, addons[0].version) == (
        "fixture@example.test",
        "Offline fixture",
        "1.2.3",
    )
    assert session.addons == addons
    assert await session.install_addons(str(path)) == []
    body = transport.calls[0]["body"]
    assert transport.calls[0]["command"] == Command.FIREFOX_INSTALL_ADDON
    assert body["temporary"] is True
    with ZipFile(BytesIO(b64decode(body["addon"]))) as archive:
        assert set(archive.namelist()) == {"manifest.json", "resources/message.txt"}
        assert archive.read("resources/message.txt") == b"fixture resource"
    assert await session.uninstall_addon(addons[0]) is True
    assert session.addons == []
    assert await session.uninstall_addon("absent@example.test") is False
    assert transport.calls[1]["command"] == Command.FIREFOX_UNINSTALL_ADDON
    assert transport.calls[1]["body"] == {"id": "fixture@example.test"}


@pytest.mark.parametrize("addon", [None, 7, {}, []])
@pytest.mark.asyncio
async def test_firefox_uninstall_rejects_invalid_input(
    make_session: Callable[..., Any], addon: Any
) -> None:
    """Reject unsupported add-on identifiers without invoking GeckoDriver.

    Args:
        make_session: Isolated session factory.
        addon: Invalid add-on identifier input.
    """
    session, transport = make_session(FirefoxSession, [])
    with pytest.raises(errors.InvalidArgumentError):
        await session.uninstall_addon(addon)
    assert transport.calls == []


@pytest.mark.parametrize("failure", [RuntimeError("driver rejected add-on"), {}])
@pytest.mark.asyncio
async def test_firefox_addon_failed_install_does_not_cache(
    make_session: Callable[..., Any], addon_directory: Path, failure: Any
) -> None:
    """Leave the add-on cache unchanged when transport or response parsing fails.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension fixture.
        failure: Driver exception or response lacking its identifier.
    """
    session, _ = make_session(FirefoxSession, [failure])
    expected = (
        errors.InvalidExtensionError
        if isinstance(failure, Exception)
        else errors.InvalidResponseError
    )
    with pytest.raises(expected):
        await session.install_addons(str(addon_directory))
    assert session.addons == []


@pytest.mark.parametrize(
    "value", [None, "", " \t\n", True, 7, b"id@example.test", {}, []]
)
@pytest.mark.asyncio
async def test_firefox_addon_rejects_invalid_returned_id(
    make_session: Callable[..., Any], addon_directory: Path, value: Any
) -> None:
    """Require a nonempty returned add-on ID before updating the local cache.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension fixture.
        value: Malformed returned identifier.
    """
    session, _ = make_session(FirefoxSession, [{"value": value}])
    with pytest.raises(errors.InvalidResponseError):
        await session.install_addons(str(addon_directory))
    assert session.addons == []


@pytest.mark.asyncio
async def test_firefox_missing_addon_is_rejected_before_transport(
    make_session: Callable[..., Any], tmp_path: Path
) -> None:
    """Reject a nonexistent local add-on before any driver request.

    Args:
        make_session: Isolated session factory.
        tmp_path: Disposable directory containing no add-on.
    """
    session, transport = make_session(FirefoxSession, [])
    with pytest.raises(errors.InvalidExtensionError):
        await session.install_addons(str(tmp_path / "absent.xpi"))
    assert transport.calls == []


@pytest.mark.asyncio
async def test_safari_permissions_read_merge_and_missing(
    make_session: Callable[..., Any],
) -> None:
    """Preserve existing Safari permissions while updating one permission.

    Args:
        make_session: Isolated session factory.
    """
    before = {"value": {"permissions": {"getUserMedia": True, "other": False}}}
    after = {"value": {"permissions": {"getUserMedia": False, "other": False}}}
    session, transport = make_session(
        SafariSession, [before, before, before, before, {"value": None}, after]
    )
    assert await session.permissions == {"getUserMedia": True, "other": False}
    assert await session.get_permission("getUserMedia") is True
    assert await session.get_permission("missing") is None
    assert await session.set_permission("getUserMedia", False) == {
        "getUserMedia": False,
        "other": False,
    }
    assert transport.calls[4]["command"] == Command.SAFARI_SET_PERMISSIONS
    assert transport.calls[4]["body"] == {
        "permissions": {"getUserMedia": False, "other": False}
    }


@pytest.mark.parametrize("response", [{}, {"value": {}}])
@pytest.mark.asyncio
async def test_safari_permissions_missing_fields(
    make_session: Callable[..., Any], response: dict[str, Any]
) -> None:
    """Translate missing Safari permission response keys to a package error.

    Args:
        make_session: Isolated session factory.
        response: Incomplete permission response envelope.
    """
    session, _ = make_session(SafariSession, [response])
    with pytest.raises(errors.InvalidResponseError):
        await session.permissions


@pytest.mark.parametrize(
    "response",
    [
        {"value": None},
        {"value": []},
        {"value": {"permissions": []}},
        {"value": {"permissions": {"getUserMedia": "yes"}}},
        {"value": {"permissions": {"getUserMedia": 1}}},
        {"value": {"permissions": {"getUserMedia": 0}}},
        {"value": {"permissions": {"getUserMedia": None}}},
        {"value": {"permissions": {7: True}}},
        {"value": {"permissions": "permissions"}},
        None,
        [],
    ],
)
@pytest.mark.asyncio
async def test_safari_permissions_rejects_malformed_values(
    make_session: Callable[..., Any], response: Any
) -> None:
    """Require Safari permission responses to match dict[str, bool].

    Args:
        make_session: Isolated session factory.
        response: Malformed permission response envelope.
    """
    session, _ = make_session(SafariSession, [response])
    with pytest.raises(errors.InvalidResponseError):
        await session.permissions


@pytest.mark.asyncio
async def test_safari_disabled_features_do_not_send_commands(
    make_session: Callable[..., Any],
) -> None:
    """Record current unsupported Safari API return values without native effects.

    Args:
        make_session: Isolated session factory.
    """
    session, transport = make_session(SafariSession, [])
    assert await session.print_page() is None
    assert await session.switch_frame("#frame") is False
    assert await session.default_frame() is True
    assert await session.parent_frame() is True
    assert session.actions() is None
    assert transport.calls == []


@pytest.mark.asyncio
async def test_safari_execute_forwards_timeout_and_route_keys(
    make_session: Callable[..., Any],
) -> None:
    """Preserve every caller-supplied command envelope field in Safari forwarding.

    Args:
        make_session: Isolated session factory.
    """
    session, transport = make_session(SafariSession, [{"value": "done"}])
    assert await session.execute_command(
        "fixture-command", body={"a": 1}, keys={"key": "value"}, timeout=0.25
    ) == {"value": "done"}
    assert transport.calls == [
        {
            "base_url": "/session/vendor-test",
            "command": "fixture-command",
            "body": {"a": 1},
            "keys": {"key": "value"},
            "timeout": 0.25,
        }
    ]


@pytest.mark.parametrize("options_class", OPTION_CLASSES)
def test_option_common_capabilities_round_trip(
    options_class: type[BaseOptions],
) -> None:
    """Exercise common option setters, snapshots, defensive copies, and resets.

    Args:
        options_class: Concrete browser option implementation.
    """
    options = options_class()
    options.platform_name = "linux"
    options.page_load_strategy = "eager"
    options.accept_insecure_certs = True
    options.strict_file_interactability = True
    options.unhandled_prompt_behavior = "dismiss and notify"
    options.set_timeouts(implicit=0.125, pageLoad=12, script=3)
    options.set_capability("custom:payload", {"nested": [1]})
    caps = options.capabilities
    assert caps["platformName"] == "linux"
    assert caps["pageLoadStrategy"] == "eager"
    assert caps["acceptInsecureCerts"] is True
    assert caps["strictFileInteractability"] is True
    assert caps["unhandledPromptBehavior"] == "dismiss and notify"
    assert caps["timeouts"] == {"implicit": 125, "pageLoad": 12000, "script": 3000}
    caps["custom:payload"]["nested"].append(2)
    assert options.get_capability("custom:payload") == {"nested": [1]}
    snapshot = options.snapshot()
    options.rem_capability("custom:payload")
    assert snapshot.get_capability("custom:payload") == {"nested": [1]}
    with pytest.raises(errors.OptionsNotSetError):
        options.get_capability("custom:payload")
    options.platform_name = None
    options.page_load_strategy = None
    options.accept_insecure_certs = False
    options.strict_file_interactability = False
    assert options.platform_name is None
    assert options.page_load_strategy == "normal"
    assert not options.accept_insecure_certs
    assert not options.strict_file_interactability
    options.close()
    snapshot.close()


@pytest.mark.parametrize("options_class", OPTION_CLASSES)
@pytest.mark.parametrize(
    "field,value",
    [
        ("platform_name", 7),
        ("page_load_strategy", "invalid"),
        ("unhandled_prompt_behavior", "invalid"),
        ("browser_version", "120.0.1.2"),
    ],
)
def test_options_reject_invalid_common_values(
    options_class: type[BaseOptions], field: str, value: Any
) -> None:
    """Reject invalid common option assignments without changing capabilities.

    Args:
        options_class: Concrete browser option implementation.
        field: Property receiving the invalid value.
        value: Invalid property value.
    """
    options = options_class()
    before = options.capabilities
    with pytest.raises(errors.InvalidOptionsError):
        setattr(options, field, value)
    assert options.capabilities == before


@pytest.mark.parametrize("options_class", (*CHROMIUM_OPTION_CLASSES, FirefoxOptions))
def test_vendor_option_serialization(
    options_class: type[BaseOptions], tmp_path: Path
) -> None:
    """Serialize binary, arguments, preferences, and experimental vendor options.

    Args:
        options_class: Browser option implementation with vendor capabilities.
        tmp_path: Disposable directory for a browser-path fixture.
    """
    binary = tmp_path / "browser"
    binary.write_bytes(b"fixture executable path")
    options = options_class()
    options.browser_location = str(binary)
    options.add_arguments("--fixture-one", "--fixture-two", "--fixture-one")
    options.set_preferences(**{"fixture.preference": {"nested": [1]}})
    options.add_experimental_options(fixture={"flag": True})
    vendor_key = (
        "moz:firefoxOptions"
        if options_class is FirefoxOptions
        else "ms:edgeOptions"
        if options_class is EdgeOptions
        else "goog:chromeOptions"
    )
    assert options.capabilities[vendor_key] == {
        "binary": str(binary),
        "fixture": {"flag": True},
        "prefs": {"fixture.preference": {"nested": [1]}},
        "args": ["--fixture-one", "--fixture-two"],
    }
    options.get_preference("fixture.preference")["nested"].append(2)
    assert options.get_preference("fixture.preference") == {"nested": [1]}
    options.get_experimental_option("fixture")["flag"] = False
    assert options.get_experimental_option("fixture") == {"flag": True}
    options.rem_preference("fixture.preference")
    options.rem_experimental_option("fixture")
    options.reset_arguments()
    options.browser_location = None
    assert options.capabilities[vendor_key] == {}
    with pytest.raises(errors.OptionsNotSetError):
        options.get_preference("fixture.preference")
    with pytest.raises(errors.OptionsNotSetError):
        options.get_experimental_option("fixture")


@pytest.mark.parametrize("options_class", CHROMIUM_OPTION_CLASSES)
def test_chromium_extensions_and_debugger_address(
    options_class: type[ChromiumBaseOptions], tmp_path: Path
) -> None:
    """Encode local extension files, deduplicate entries, and reset debugger state.

    Args:
        options_class: Concrete Chromium-family options implementation.
        tmp_path: Disposable directory for an extension fixture.
    """
    extension = tmp_path / "fixture.crx"
    extension.write_bytes(b"extension fixture bytes")
    options = options_class()
    options.add_extensions(extension)
    options.add_extensions_base64(b64encode(extension.read_bytes()), "")
    assert options.extensions == [b64encode(extension.read_bytes()).decode("ascii")]
    options.extensions.clear()
    assert len(options.extensions) == 1
    options.debugger_address = "127.0.0.1:9222"
    assert options.debugger_address == "127.0.0.1:9222"
    assert options.capabilities[options.KEY]["debuggerAddress"] == "127.0.0.1:9222"
    options.debugger_address = None
    assert "debuggerAddress" not in options.capabilities[options.KEY]


def test_edge_webview_change_invalidates_cached_capabilities() -> None:
    """Require WebView2 selection changes to update already-read capabilities."""
    options = EdgeOptions()
    assert options.capabilities["browserName"] == "MicrosoftEdge"
    options.use_webview = True
    assert options.use_webview is True
    assert options.capabilities["browserName"] == "webview2"
    options.use_webview = False
    assert options.capabilities["browserName"] == "MicrosoftEdge"


@pytest.mark.parametrize("value", [1, "true", None])
def test_edge_webview_rejects_nonboolean(value: Any) -> None:
    """Reject non-boolean WebView2 selections.

    Args:
        value: Invalid WebView2 selection.
    """
    with pytest.raises(errors.InvalidOptionsError):
        EdgeOptions().use_webview = value


def test_safari_option_flags_toggle_and_proxy_is_unsupported() -> None:
    """Exercise Safari-specific flags and the explicit unsupported proxy behavior."""
    options = SafariOptions()
    assert options.capabilities["browserName"] == "safari"
    assert options.platform_name == "mac"
    options.automatic_inspection = True
    options.automatic_profiling = True
    options.technology_preview = True
    assert options.capabilities["safari:automaticInspection"] is True
    assert options.capabilities["safari:automaticProfiling"] is True
    assert options.capabilities["browserName"] == "Safari Technology Preview"
    options.automatic_inspection = False
    options.automatic_profiling = False
    options.technology_preview = False
    options.proxy = "http://127.0.0.1:8080"
    assert options.proxy is None
    assert options.capabilities["browserName"] == "safari"
    assert "safari:automaticInspection" not in options.capabilities
    assert "safari:automaticProfiling" not in options.capabilities
    assert "proxy" not in options.capabilities


@pytest.mark.parametrize(
    "options_class,version,wire",
    [
        (ChromeOptions, ChromiumVersion("120.0.1.2"), "120.0.1.2"),
        (FirefoxOptions, FirefoxVersion("130.0.1"), "130.0.1"),
    ],
)
def test_browser_version_wire_string_and_reset(
    options_class: type[BaseOptions], version: Any, wire: str
) -> None:
    """Serialize typed browser versions and reset them without probing executables.

    Args:
        options_class: Concrete browser options implementation.
        version: Parsed browser version object.
        wire: Expected wire version string.
    """
    options = options_class()
    options.browser_version = version
    assert options.browser_version == wire
    assert options.capabilities["browserVersion"] == wire
    options.browser_version = None
    assert options.browser_version is None
    assert "browserVersion" not in options.capabilities


@pytest.mark.parametrize("options_class", (*CHROMIUM_OPTION_CLASSES, FirefoxOptions))
def test_proxy_mutation_is_reflected_in_browser_capabilities(
    options_class: type[BaseOptions],
) -> None:
    """Refresh browser capabilities when an attached Proxy changes in place.

    Args:
        options_class: Browser options implementation supporting proxy settings.
    """
    options = options_class()
    proxy = Proxy(
        http_proxy="http://localhost:8080", no_proxy=["localhost", "127.0.0.1"]
    )
    options.proxy = proxy
    assert options.capabilities["proxy"] == {
        "proxyType": "manual",
        "httpProxy": "localhost:8080",
        "noProxy": ["localhost", "127.0.0.1"],
    }
    proxy.https_proxy = "https://localhost:8443"
    assert options.capabilities["proxy"]["sslProxy"] == "localhost:8443"
    options.proxy = None
    assert "proxy" not in options.capabilities


def test_firefox_profile_cloning_encoding_extensions_and_cleanup(
    addon_directory: Path, tmp_path: Path
) -> None:
    """Clone Firefox data, exclude locks, load extensions, and isolate snapshots.

    Args:
        addon_directory: Valid local WebExtension fixture.
        tmp_path: Disposable source-profile directory.
    """
    source = tmp_path / "firefox-profile"
    source.mkdir()
    (source / "prefs.js").write_text('user_pref("fixture", true);', encoding="utf-8")
    (source / "parent.lock").write_text("lock", encoding="utf-8")
    (source / "extensions").mkdir()
    with ZipFile(source / "extensions" / "fixture.xpi", "w") as archive:
        archive.write(addon_directory / "manifest.json", "manifest.json")
    (source / "extensions" / "broken.xpi").write_bytes(b"invalid archive ignored")
    options = FirefoxOptions()
    snapshot: FirefoxOptions | None = None
    try:
        profile = options.set_profile(source)
        clone = Path(profile.directory_temp)
        assert profile.directory == str(source)
        assert profile._profile_dir == source
        assert isinstance(profile._temp_profile_dir, Path)
        assert clone != source
        assert not (clone / "parent.lock").exists()
        assert profile.extensions["fixture@example.test"].name == "Offline fixture"
        with ZipFile(BytesIO(b64decode(profile.encode))) as archive:
            assert archive.read("prefs.js") == b'user_pref("fixture", true);'
            assert "parent.lock" not in archive.namelist()
        assert options.capabilities["moz:firefoxOptions"]["profile"] == profile.encode
        snapshot = options.snapshot()
        snapshot_clone = Path(snapshot.profile.directory_temp)
        (clone / "prefs.js").write_text("changed clone", encoding="utf-8")
        assert (
            snapshot_clone / "prefs.js"
        ).read_text() == 'user_pref("fixture", true);'
        assert (source / "prefs.js").read_text() == 'user_pref("fixture", true);'
        options.close()
        options.rem_profile()
        assert options.profile is None
        assert not clone.exists()
        assert snapshot_clone.exists()
        assert "profile" not in options.capabilities["moz:firefoxOptions"]
    finally:
        options.close()
        if snapshot is not None:
            snapshot.close()


@pytest.mark.parametrize("options_class", CHROMIUM_OPTION_CLASSES)
def test_chromium_profile_arguments_and_replacement_cleanup(
    options_class: type[ChromiumBaseOptions], tmp_path: Path
) -> None:
    """Replace cloned profiles and remove only owned profile arguments and data.

    Args:
        options_class: Chromium-family options implementation.
        tmp_path: Disposable source-profile directory.
    """
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Preferences").write_text("original", encoding="utf-8")
    options = options_class()
    try:
        options.add_arguments("--headless=new")
        first = options.set_profile(tmp_path, "Default")
        first_clone = Path(first.directory_temp)
        assert first.directory == str(tmp_path)
        assert first._profile_dir == tmp_path / "Default"
        assert isinstance(first._temp_profile_dir, Path)
        assert first.profile_folder == "Default"
        assert first.profile_folder_temp == "TEMP_PROFILE"
        assert "--profile-directory=TEMP_PROFILE" in options.arguments
        assert "--user-data-dir=" + str(first_clone) in options.arguments
        second = options.set_profile(str(tmp_path), "Default")
        second_clone = Path(second.directory_temp)
        assert second_clone.exists()
        first._delete_temp_profile()
        assert not first_clone.exists()
        options.close()
        options.rem_profile()
        assert options.arguments == ["--headless=new"]
        assert not second_clone.exists()
        assert (tmp_path / "Default" / "Preferences").read_text() == "original"
    finally:
        options.close()


@pytest.mark.parametrize(
    "profile_folder", ["Default", "Profile 1", " Profile", ".profile", "用户 配置"]
)
def test_chromium_profile_accepts_portable_single_directory_names(
    tmp_path: Path, profile_folder: str
) -> None:
    """Preserve ordinary spaces, dot prefixes, and Unicode in profile names.

    Args:
        tmp_path: Isolated user-data directory containing the selected profile.
        profile_folder: Portable single-component profile-directory name.
    """
    source = tmp_path / profile_folder
    source.mkdir()
    (source / "Preferences").write_text("original", encoding="utf-8")
    profile = ChromiumProfile(tmp_path, profile_folder)
    assert profile.directory_temp is not None
    clone = Path(profile.directory_temp)
    try:
        assert profile.profile_folder == profile_folder
        assert profile._profile_dir == source
        assert clone.is_dir()
        assert (clone / "TEMP_PROFILE" / "Preferences").read_text(
            encoding="utf-8"
        ) == "original"
    finally:
        profile._delete_temp_profile()


@pytest.mark.parametrize(
    "profile_folder",
    [
        "",
        ".",
        "..",
        "../Default",
        "..\\Default",
        "/Default",
        "\\Default",
        "Default/Profile 1",
        "Default\\Profile 1",
        "Default/",
        "Default\\",
        "C:",
        "C:Default",
        "C:\\Default",
        "//server/share/Default",
        "\\\\server\\share\\Default",
        "Default\x00Profile",
        "Default:stream",
        'Default"Profile',
        "Default*Profile",
        "Default<Profile",
        "Default>Profile",
        "Default?Profile",
        "Default|Profile",
        "Default.",
        "Default ",
        "CON",
        "con.profile",
        "CON .profile",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "com¹.log",
        "LPT9",
        "CONIN$",
        "CONOUT$",
    ],
)
def test_chromium_profile_rejects_ambiguous_or_reserved_path_names(
    tmp_path: Path, profile_folder: str
) -> None:
    """Reject cross-platform path syntax before selecting or copying a profile.

    Args:
        tmp_path: Existing user-data root that must not override validation.
        profile_folder: Malformed, escaping, or reserved profile-folder value.
    """
    with pytest.raises(errors.InvalidProfileError, match="portable directory basename"):
        ChromiumProfile(tmp_path, profile_folder)


@pytest.mark.parametrize("profile_folder", [None, b"Default", Path("Default"), 1])
def test_chromium_profile_rejects_non_string_folder_names(
    tmp_path: Path, profile_folder: Any
) -> None:
    """Reject path-like and other non-string values for the basename-only input.

    Args:
        tmp_path: Existing user-data root that must not override validation.
        profile_folder: Non-string value supplied despite the public annotation.
    """
    with pytest.raises(errors.InvalidProfileError, match="portable directory basename"):
        ChromiumProfile(tmp_path, profile_folder)


@pytest.mark.parametrize(
    "facade_class,options_class,kwargs",
    [
        (Chrome, ChromeOptions, {"version": "120.0.1.2", "channel": "beta"}),
        (Chromium, ChromiumOptions, {"version": "120.0.1.2"}),
        (Edge, EdgeOptions, {"version": "120.0.1.2", "channel": "dev"}),
        (Firefox, FirefoxOptions, {"version": "auto"}),
        (Safari, SafariOptions, {"channel": "dev"}),
    ],
)
@pytest.mark.asyncio
async def test_facade_acquisition_snapshots_options_without_provisioning(
    facade_class: type[Any], options_class: type[BaseOptions], kwargs: dict[str, Any]
) -> None:
    """Construct every facade and check acquisition-time option isolation offline.

    Args:
        facade_class: Public browser facade constructor.
        options_class: Its expected options implementation.
        kwargs: Browser-specific acquisition selector arguments.
    """
    driver = facade_class()
    assert isinstance(driver.options, options_class)
    assert driver.manager is not None
    driver.options.set_capability("fixture:setting", {"values": [1]})
    context = driver.acquire(**kwargs)
    try:
        driver.options.set_capability("fixture:setting", {"values": [2]})
        assert context._options.get_capability("fixture:setting") == {"values": [1]}
        assert context._manager is driver.manager
        assert all(
            context._manager_install_kwargs[key] == value
            for key, value in kwargs.items()
        )
        assert context._state == "new"
        assert context._session is None
        assert repr(driver) == f"<{facade_class.__name__}>"
        assert driver == driver
        assert driver != object()
    finally:
        await context.quit()
        driver.options.close()


@pytest.mark.parametrize(
    "service_class,expected",
    [
        (ChromeService, ["--port=4444"]),
        (ChromiumService, ["--port=4444"]),
        (EdgeService, ["--port=4444"]),
        (SafariService, ["-p", "4444"]),
    ],
)
def test_browser_service_port_arguments(
    service_class: type[Any], expected: list[str], tmp_path: Path
) -> None:
    """Build native service port arguments without starting an executable.

    Args:
        service_class: Concrete browser service implementation.
        expected: Independently specified native command-line arguments.
        tmp_path: Disposable directory for the executable-path fixture.
    """
    executable = tmp_path / "driver"
    executable.write_bytes(b"fixture")
    service = service_class(ChromiumVersion("120.0.1.2"), str(executable))
    service._port = 4444
    service._port_str = "4444"
    assert service.port_args == expected


@pytest.mark.parametrize(
    "extra,expected",
    [
        ((), ["--port=4444", "--websocket-port", "5555"]),
        (("--connect-existing",), ["--port=4444"]),
        (("--websocket-port", "6666"), ["--port=4444"]),
    ],
)
def test_firefox_service_respects_explicit_websocket_arguments(
    extra: tuple[str, ...], expected: list[str], tmp_path: Path
) -> None:
    """Avoid adding a second Firefox websocket port when explicitly configured.

    Args:
        extra: Explicit native service arguments supplied by the caller.
        expected: Expected automatically generated port arguments.
        tmp_path: Disposable directory for the executable-path fixture.
    """
    executable = tmp_path / "geckodriver"
    executable.write_bytes(b"fixture")
    service = FirefoxService(GeckoVersion("0.37.0"), str(executable), 10, *extra)
    service._port = 4444
    service._port_str = "4444"
    service._cdp_port = 5555
    service._cdp_port_str = "5555"
    assert service.port_args == expected
    assert service.driver_version == GeckoVersion("0.37.0")
    assert service.cdp_port == 5555
    assert service.cdp_port_str == "5555"


def test_firefox_addon_details_without_id_and_copy(addon_directory: Path) -> None:
    """Allow temporary add-ons without an ID and isolate copied metadata.

    Args:
        addon_directory: Valid local WebExtension fixture.
    """
    manifest_path = addon_directory / "manifest.json"
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("browser_specific_settings")
    manifest_path.write_text(dumps(manifest), encoding="utf-8")
    details = extract_firefox_addon_details(addon_directory)
    assert isinstance(details, FirefoxAddon)
    assert details.id is None
    clone = details.copy()
    clone.id = "runtime@example.test"
    assert details.id is None
    assert clone.id == "runtime@example.test"
    assert "Offline fixture" in repr(clone)


@pytest.mark.asyncio
async def test_firefox_temporary_addon_uses_runtime_identifier(
    make_session: Callable[..., Any], addon_directory: Path
) -> None:
    """Cache an unsigned temporary add-on under its GeckoDriver-assigned ID.

    Args:
        make_session: Isolated session factory.
        addon_directory: Local WebExtension directory whose manifest ID is removed.
    """
    manifest_path = addon_directory / "manifest.json"
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("browser_specific_settings")
    manifest_path.write_text(dumps(manifest), encoding="utf-8")
    session, transport = make_session(
        FirefoxSession, [{"value": "assigned@example.test"}]
    )
    addons = await session.install_addons(str(addon_directory), temporary=True)
    assert addons[0].id == "assigned@example.test"
    assert session.addons[0].id == "assigned@example.test"
    assert transport.calls[0]["body"]["temporary"] is True


@pytest.mark.asyncio
async def test_firefox_cancelled_install_does_not_cache_addon(
    make_session: Callable[..., Any], addon_directory: Path
) -> None:
    """Propagate cancellation while leaving unconfirmed add-ons out of the cache.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension directory.
    """
    session, transport = make_session(FirefoxSession, [CancelledError()])
    with pytest.raises(CancelledError):
        await session.install_addons(str(addon_directory))
    assert len(transport.calls) == 1
    assert session.addons == []


@pytest.mark.asyncio
async def test_firefox_failed_uninstall_keeps_known_addon(
    make_session: Callable[..., Any], addon_directory: Path
) -> None:
    """Keep installed metadata when the driver fails to confirm uninstallation.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension directory.
    """
    failure = errors.SessionTimeoutError("fixture uninstall deadline")
    session, _ = make_session(
        FirefoxSession, [{"value": "fixture@example.test"}, failure]
    )
    addons = await session.install_addons(str(addon_directory))
    with pytest.raises(errors.SessionTimeoutError) as captured:
        await session.uninstall_addon(addons[0])
    assert captured.value is failure
    assert session.addons == addons


@pytest.mark.asyncio
async def test_firefox_empty_addon_batch_is_noop(
    make_session: Callable[..., Any],
) -> None:
    """Treat an empty add-on installation batch as an offline no-op.

    Args:
        make_session: Isolated session factory.
    """
    session, transport = make_session(FirefoxSession, [])
    assert await session.install_addons() == []
    assert session.addons == []
    assert transport.calls == []


@pytest.mark.asyncio
async def test_firefox_session_reads_existing_profile_addon_metadata(
    tmp_path: Path, addon_directory: Path
) -> None:
    """Avoid reinstalling an extension already present in the cloned profile.

    Args:
        tmp_path: Disposable source-profile location.
        addon_directory: Valid WebExtension directory.
    """
    profile_directory = tmp_path / "profile"
    extensions = profile_directory / "extensions"
    extensions.mkdir(parents=True)
    with ZipFile(extensions / "fixture.xpi", "w") as archive:
        archive.write(addon_directory / "manifest.json", "manifest.json")
    options = FirefoxOptions()
    options.set_profile(str(profile_directory))
    session = FirefoxSession(options, SimpleNamespace(url="http://127.0.0.1:4444"))
    transport = RecordingTransport([])
    session._conn = transport
    session._base_url = "/session/profile-fixture"
    try:
        assert [addon.id for addon in session.addons] == ["fixture@example.test"]
        assert await session.install_addons(str(addon_directory)) == []
        assert transport.calls == []
    finally:
        session._Session__closed = True
        options.close()


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"auto_detect": True}, {"proxyType": "autodetect"}),
        (
            {"pac_url": "http://localhost/proxy.pac"},
            {"proxyType": "pac", "proxyAutoconfigUrl": "http://localhost/proxy.pac"},
        ),
        (
            {"socks_proxy": "socks4://localhost:1080"},
            {"proxyType": "manual", "socksProxy": "localhost:1080", "socksVersion": 4},
        ),
        (
            {
                "socks_proxy": "socks5://localhost:1080",
                "socks_username": "test-user",
                "socks_password": "test-password",
            },
            {
                "proxyType": "manual",
                "socksProxy": "localhost:1080",
                "socksVersion": 5,
                "socksUsername": "test-user",
                "socksPassword": "test-password",
            },
        ),
        (
            {
                "https_proxy": "https://localhost:8443",
                "no_proxy": " localhost, ,127.0.0.1 ",
            },
            {
                "proxyType": "manual",
                "sslProxy": "localhost:8443",
                "noProxy": ["localhost", "127.0.0.1"],
            },
        ),
    ],
)
def test_proxy_wire_modes(kwargs: dict[str, Any], expected: dict[str, Any]) -> None:
    """Serialize each supported proxy mode without contacting a proxy server.

    Args:
        kwargs: Proxy configuration supplied by the caller.
        expected: Independently specified WebDriver proxy capability mapping.
    """
    proxy = Proxy(**kwargs)
    assert proxy.to_capabilities() == expected
    assert proxy.to_capabilities() == expected
    assert "test-password" not in repr(proxy)


@pytest.mark.parametrize(
    "field,value",
    [
        ("auto_detect", 1),
        ("pac_url", 42),
        ("http_proxy", "localhost:8080"),
        ("http_proxy", 42),
        ("https_proxy", "ftp://localhost:8080"),
        ("https_proxy", 42),
        ("socks_proxy", "http://localhost:1080"),
        ("socks_proxy", 42),
        ("socks_username", 42),
        ("socks_password", 42),
        ("no_proxy", ["localhost", 42]),
        ("no_proxy", 42),
    ],
)
def test_proxy_invalid_assignment_is_atomic(field: str, value: Any) -> None:
    """Reject invalid proxy property values without corrupting the current mapping.

    Args:
        field: Proxy property receiving an invalid value.
        value: Invalid property value.
    """
    proxy = Proxy(http_proxy="http://localhost:8080")
    before = proxy.to_capabilities()
    with pytest.raises(errors.InvalidProxyError):
        setattr(proxy, field, value)
    assert proxy.to_capabilities() == before


def test_proxy_reset_socks_clears_credentials() -> None:
    """Remove SOCKS credentials and protocol version when clearing its endpoint."""
    proxy = Proxy(
        socks_proxy="socks5://localhost:1080",
        socks_username="user",
        socks_password="password",
    )
    assert proxy.socks_username == "user"
    assert proxy.socks_password == "password"
    proxy.socks_proxy = None
    assert proxy.socks_proxy is None
    assert proxy.socks_username is None
    assert proxy.socks_password is None
    assert proxy.to_capabilities() == {"proxyType": "manual"}


@pytest.mark.parametrize("options_class", (*CHROMIUM_OPTION_CLASSES, FirefoxOptions))
def test_missing_browser_binary_preserves_existing_configuration(
    options_class: type[BaseOptions], tmp_path: Path
) -> None:
    """Preserve a valid executable override when a replacement path is invalid.

    Args:
        options_class: Browser options implementation supporting a binary override.
        tmp_path: Disposable directory containing the valid executable fixture.
    """
    binary = tmp_path / "browser"
    binary.write_bytes(b"fixture")
    options = options_class()
    options.browser_location = str(binary)
    before = options.capabilities
    with pytest.raises(errors.InvalidOptionsError):
        options.browser_location = str(tmp_path / "missing")
    assert options.browser_location == str(binary)
    assert options.capabilities == before


@pytest.mark.parametrize("options_class", CHROMIUM_OPTION_CLASSES)
@pytest.mark.parametrize("value", [1, {}, b"127.0.0.1:9222"])
def test_debugger_address_rejects_invalid_types(
    options_class: type[ChromiumBaseOptions], value: Any
) -> None:
    """Reject non-string debugger endpoint assignments.

    Args:
        options_class: Chromium-family options implementation.
        value: Invalid debugger endpoint value.
    """
    options = options_class()
    with pytest.raises(errors.InvalidOptionsError):
        options.debugger_address = value
    assert options.debugger_address is None


@pytest.mark.parametrize("channel,expected", [("stable", False), ("dev", True)])
@pytest.mark.asyncio
async def test_safari_acquisition_channel_updates_technology_preview(
    channel: str, expected: bool
) -> None:
    """Align acquired Safari options with the resolved installation channel.

    Args:
        channel: Channel reported by the completed installation result.
        expected: Expected Technology Preview option value.
    """
    driver = Safari()
    driver.options.technology_preview = not expected
    context = driver.acquire(channel=channel)
    try:
        context._installation = SimpleNamespace(channel=channel)
        context._extra_options_updates()
        assert context._options.technology_preview is expected
        context._extra_options_updates()
        assert context._options.technology_preview is expected
        assert driver.options.technology_preview is not expected
    finally:
        await context.quit()
        driver.options.close()


@pytest.mark.parametrize("session_class", [FirefoxSession, SafariSession])
def test_vendor_session_basic_properties(
    make_session: Callable[..., Any], session_class: type[Session]
) -> None:
    """Expose browser/service state without extra network or executable probes.

    Args:
        make_session: Isolated session factory.
        session_class: Vendor session wrapper being inspected.
    """
    session, transport = make_session(session_class, [])
    session._service._driver_version = GeckoVersion("0.37.0")
    assert session.options is session._options
    assert session.service is session._service
    assert session.browser_version is None
    assert session.driver_version == GeckoVersion("0.37.0")
    assert transport.calls == []


@pytest.mark.asyncio
async def test_firefox_addon_encoding_failure_does_not_send_or_cache(
    make_session: Callable[..., Any],
    addon_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Translate an archive-encoding I/O failure without a partial installation.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension directory.
        monkeypatch: Reversible patch fixture for the I/O boundary.
    """

    def fail_encoding(directory: str) -> str:
        """Simulate a disk-read failure while packing an unpacked extension.

        Args:
            directory: Extension directory requested by the package.

        Returns:
            Never returns because the simulated disk is unavailable.

        Raises:
            OSError: Always, to simulate a failed archive read.
        """
        raise OSError("fixture archive read failure")

    monkeypatch.setattr(
        firefox_session_module, "encode_dir_to_firefox_wire_protocol", fail_encoding
    )
    session, transport = make_session(FirefoxSession, [])
    with pytest.raises(errors.InvalidExtensionError, match="Failed to encode add-on"):
        await session.install_addons(str(addon_directory))
    assert session.addons == []
    assert transport.calls == []


def test_firefox_profile_encoding_failure_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the cloned profile usable after a transient archive-read failure.

    Args:
        tmp_path: Disposable Firefox source-profile directory.
        monkeypatch: Reversible patch fixture for the archive-encoding boundary.
    """

    def fail_encoding(directory: str) -> str:
        """Simulate a disk-read failure while encoding a Firefox profile.

        Args:
            directory: Profile directory requested by the package.

        Returns:
            Never returns because the simulated disk is unavailable.

        Raises:
            OSError: Always, to simulate a failed archive read.
        """
        raise OSError("fixture profile read failure")

    (tmp_path / "prefs.js").write_text("fixture", encoding="utf-8")
    options = FirefoxOptions()
    try:
        profile = options.set_profile(str(tmp_path))
        with monkeypatch.context() as patch:
            patch.setattr(
                firefox_options_module,
                "encode_dir_to_firefox_wire_protocol",
                fail_encoding,
            )
            with pytest.raises(errors.InvalidProfileError, match="Failed to encode"):
                profile.encode
        with ZipFile(BytesIO(b64decode(profile.encode))) as archive:
            assert archive.read("prefs.js") == b"fixture"
    finally:
        options.close()


@pytest.mark.parametrize("response", [None, [], "content", False])
@pytest.mark.asyncio
async def test_firefox_context_rejects_nonmapping_envelopes(
    make_session: Callable[..., Any], response: Any
) -> None:
    """Reject malformed context envelopes without leaking Python indexing errors.

    Args:
        make_session: Isolated session factory.
        response: Non-mapping GeckoDriver response.
    """
    session, transport = make_session(FirefoxSession, [response])
    with pytest.raises(errors.InvalidResponseError, match="Firefox context response"):
        await session.context
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "method,args", [("set_context", ("chrome",)), ("reset_context", ())]
)
@pytest.mark.asyncio
async def test_firefox_context_mutations_validate_observed_state(
    make_session: Callable[..., Any], method: str, args: tuple[str, ...]
) -> None:
    """Validate the read-after-write state without replaying a context mutation.

    Args:
        make_session: Isolated session factory.
        method: Context mutation method under test.
        args: Its valid positional arguments.
    """
    session, transport = make_session(
        FirefoxSession, [{"value": None}, {"value": "secret invalid context"}]
    )
    with pytest.raises(errors.InvalidResponseError) as captured:
        await getattr(session, method)(*args)
    assert "secret invalid context" not in str(captured.value)
    assert [call["command"] for call in transport.calls] == [
        Command.FIREFOX_SET_CONTEXT,
        Command.FIREFOX_GET_CONTEXT,
    ]


@pytest.mark.parametrize("response", [None, [], "id@example.test", False])
@pytest.mark.asyncio
async def test_firefox_addon_rejects_nonmapping_response_without_cache_update(
    make_session: Callable[..., Any], addon_directory: Path, response: Any
) -> None:
    """Reject malformed installation envelopes before adding any local metadata.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension fixture.
        response: Non-mapping GeckoDriver response.
    """
    session, transport = make_session(FirefoxSession, [response])
    with pytest.raises(errors.InvalidResponseError, match="non-blank string"):
        await session.install_addons(str(addon_directory))
    assert session.addons == []
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_firefox_batch_invalid_id_preserves_confirmed_prior_installations(
    make_session: Callable[..., Any], addon_directory: Path
) -> None:
    """Keep confirmed add-ons while excluding and permitting retry of an invalid ID.

    Args:
        make_session: Isolated session factory.
        addon_directory: First valid local WebExtension fixture.
    """
    second = addon_directory.parent / "second-addon"
    second.mkdir()
    manifest = loads((addon_directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["name"] = "Second fixture"
    manifest["browser_specific_settings"]["gecko"]["id"] = "second@example.test"
    (second / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
    session, transport = make_session(
        FirefoxSession,
        [
            {"value": "fixture@example.test"},
            {"value": []},
            {"value": "second@example.test"},
        ],
    )
    with pytest.raises(errors.InvalidResponseError):
        await session.install_addons(str(addon_directory), str(second))
    assert [(addon.id, addon.name) for addon in session.addons] == [
        ("fixture@example.test", "Offline fixture")
    ]
    retry = await session.install_addons(str(second))
    assert [(addon.id, addon.name) for addon in retry] == [
        ("second@example.test", "Second fixture")
    ]
    assert len(session.addons) == 2
    assert len(transport.calls) == 3


@pytest.mark.asyncio
async def test_firefox_addon_retains_exact_valid_runtime_identifier(
    make_session: Callable[..., Any], addon_directory: Path
) -> None:
    """Preserve valid driver-assigned identifiers without casing or text normalization.

    Args:
        make_session: Isolated session factory.
        addon_directory: Valid local WebExtension fixture.
    """
    identifier = "{A1B2-C3D4}@Fixture.Example"
    session, transport = make_session(
        FirefoxSession, [{"value": identifier}, {"value": None}]
    )
    addons = await session.install_addons(str(addon_directory))
    assert addons[0].id == identifier
    assert await session.uninstall_addon(addons[0]) is True
    assert transport.calls[1]["body"] == {"id": identifier}


@pytest.mark.asyncio
async def test_safari_empty_permissions_remain_valid_and_can_be_extended(
    make_session: Callable[..., Any],
) -> None:
    """Accept empty permission maps and preserve False when adding a permission.

    Args:
        make_session: Isolated session factory.
    """
    empty = {"value": {"permissions": {}}}
    session, transport = make_session(
        SafariSession,
        [
            empty,
            empty,
            empty,
            {"value": None},
            {"value": {"permissions": {"getUserMedia": False}}},
        ],
    )
    assert await session.permissions == {}
    assert await session.get_permission("getUserMedia") is None
    assert await session.set_permission("getUserMedia", False) == {
        "getUserMedia": False
    }
    assert transport.calls[3]["body"] == {"permissions": {"getUserMedia": False}}
    assert empty == {"value": {"permissions": {}}}


@pytest.mark.asyncio
async def test_safari_invalid_current_permissions_prevent_mutation(
    make_session: Callable[..., Any],
) -> None:
    """Reject malformed current permissions before issuing a mutation request.

    Args:
        make_session: Isolated session factory.
    """
    session, transport = make_session(
        SafariSession,
        [{"value": {"permissions": {"secret.permission.name": "secret value"}}}],
    )
    with pytest.raises(errors.InvalidResponseError) as captured:
        await session.set_permission("getUserMedia", True)
    assert "secret" not in str(captured.value)
    assert [call["command"] for call in transport.calls] == [
        Command.SAFARI_GET_PERMISSIONS
    ]


@pytest.mark.asyncio
async def test_safari_invalid_post_update_permissions_do_not_replay_write(
    make_session: Callable[..., Any],
) -> None:
    """Validate read-back data after mutation without repeating an uncertain write.

    Args:
        make_session: Isolated session factory.
    """
    initial = {"value": {"permissions": {"getUserMedia": False}}}
    session, transport = make_session(
        SafariSession, [initial, {"value": None}, {"value": {"permissions": None}}]
    )
    with pytest.raises(errors.InvalidResponseError):
        await session.set_permission("getUserMedia", True)
    assert [call["command"] for call in transport.calls] == [
        Command.SAFARI_GET_PERMISSIONS,
        Command.SAFARI_SET_PERMISSIONS,
        Command.SAFARI_GET_PERMISSIONS,
    ]
    assert initial == {"value": {"permissions": {"getUserMedia": False}}}


def test_edge_webview_snapshot_is_independent_and_invalid_change_is_atomic() -> None:
    """Preserve acquired WebView2 snapshots and valid state after an invalid update."""
    options = EdgeOptions()
    options.use_webview = True
    assert options.capabilities["browserName"] == "webview2"
    snapshot = options.snapshot()
    try:
        options.use_webview = False
        assert options.capabilities["browserName"] == "MicrosoftEdge"
        assert snapshot.capabilities["browserName"] == "webview2"
        before = options.capabilities
        with pytest.raises(errors.InvalidOptionsError):
            options.use_webview = 1
        assert options.capabilities == before
        assert options.use_webview is False
    finally:
        options.close()
        snapshot.close()
