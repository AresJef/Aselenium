"""Removed compatibility paths fail explicitly; their current replacements work."""

from __future__ import annotations

import importlib.util
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

import aselenium
from aselenium import errors, javascript
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.connection import Connection
from aselenium.element import Element
from aselenium.firefox.utils import FirefoxAddon, extract_firefox_addon_details
from aselenium.manager import (
    ChromeDriverManager,
    ChromiumDriverManager,
    EdgeDriverManager,
)
from aselenium.manager.file import ChromeDriverFile, FileManager
from aselenium.manager.version import ChromiumVersion
from aselenium.options import Proxy
from aselenium.session import Session
from aselenium.shadow import Shadow

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module",
    [
        "aselenium.manager.migration",
        "aselenium.javascript.get_attribute",
        "aselenium.javascript.is_viewable",
    ],
)
def test_removed_modules_are_not_importable(module: Any) -> None:
    """Verify removed modules are not importable.

    Args:
        module: Fixture or parametrized module input for this regression.
    """
    assert importlib.util.find_spec(module) is None


def test_removed_public_and_private_members_are_absent() -> None:
    """Verify removed public and private members are absent."""
    for name in ("visible", "viewable", "get_attribute"):
        assert not hasattr(Element, name)
    for name in ("ELEMENT_IS_VISIBLE", "ELEMENT_IS_VIEWABLE", "GET_ELEMENT_ATTRIBUTE"):
        assert not hasattr(javascript, name)
    for name in (
        "ElementNotVisibleError",
        "ElementNotSelectableError",
        "ElementCoordinatesError",
        "ImeError",
        "ImeNotAvailableError",
        "ImeActivationFailedError",
    ):
        assert not hasattr(aselenium, name)
        assert not hasattr(errors, name)
    assert not hasattr(FirefoxAddon, "unpack")
    assert not hasattr(FileManager, "_FileManager__instances")
    assert not hasattr(ChromeDriverManager, "_request_reponse_json")
    assert all(isinstance(key, str) for key in errors.WEBDRIVER_ERROR_MAP)
    assert not (ROOT / "src/demo.py").exists()
    assert not (ROOT / "src/test_files").exists()


@pytest.mark.parametrize(
    "member,command",
    [
        ("EXECUTE_ASYNC_SCRIPT", "executeAsyncScript"),
        ("DELETE_SESSION", "deleteSession"),
        ("DELETE_NETWORK_CONDITIONS", "deleteNetworkConditions"),
        ("SET_SCREEN_ORIENTATION", "setScreenOrientation"),
        ("GET_SCREEN_ORIENTATION", "getScreenOrientation"),
        ("GET_NETWORK_CONNECTION", "getNetworkConnection"),
        ("SET_NETWORK_CONNECTION", "setNetworkConnection"),
        ("CURRENT_CONTEXT_HANDLE", "getCurrentContextHandle"),
        ("CONTEXT_HANDLES", "getContextHandles"),
        ("SWITCH_TO_CONTEXT", "switchToContext"),
        ("LAUNCH_APP", "launchApp"),
    ],
)
def test_obsolete_command_routes_are_absent(member: Any, command: Any) -> None:
    """Verify obsolete command routes are absent.

    Args:
        member: Fixture or parametrized member input for this regression.
        command: Fixture or parametrized command input for this regression.
    """
    assert not hasattr(Command, member)
    connection = Connection(SimpleNamespace(), 5)
    with pytest.raises(errors.InvalidArgumentError):
        connection.map_command(command)
    assert connection.map_command(Command.W3C_EXECUTE_SCRIPT_ASYNC) == (
        "POST",
        "/execute/async",
    )


def test_proxy_has_no_ftp_setting_and_requires_explicit_keywords() -> None:
    """Verify proxy has no ftp setting and requires explicit keywords."""
    assert not hasattr(Proxy, "ftp_proxy")
    with pytest.raises(TypeError):
        Proxy(ftp_proxy="ftp://proxy.invalid:21")
    with pytest.raises(TypeError):
        Proxy(False, None, "ftp://proxy.invalid:21")
    proxy = Proxy(
        http_proxy="http://proxy.invalid:8080",
        https_proxy="http://proxy.invalid:8080",
        no_proxy=["localhost", "127.0.0.1"],
    )
    assert proxy.to_capabilities() == {
        "proxyType": "manual",
        "httpProxy": "proxy.invalid:8080",
        "sslProxy": "proxy.invalid:8080",
        "noProxy": ["localhost", "127.0.0.1"],
    }


def make_session() -> Any:
    """Make session.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    service = SimpleNamespace(
        _driver_version=None, _driver_location="fixture", url="fixture", running=True
    )
    session = Session(ChromeOptions(), service)
    session._id = "fixture"
    session._base_url = "/session/fixture"
    session._conn = SimpleNamespace(execute=AsyncMock(return_value={"value": None}))
    session._execute_script = AsyncMock(return_value=True)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        "element",
        "session-one",
        "session-many",
        "element-one",
        "element-many",
        "shadow-one",
        "shadow-many",
    ],
)
@pytest.mark.parametrize(
    "condition", ["in_viewport", "unobscured", "visible", "viewable"]
)
async def test_waits_use_explicit_geometry_and_hit_test_conditions(
    scope: Any, condition: Any
) -> None:
    """Verify waits use explicit geometry and hit test conditions.

    Args:
        scope: Fixture or parametrized scope input for this regression.
        condition: Fixture or parametrized condition input for this regression.
    """
    session = make_session()
    element = Element("element", session)
    shadow = Shadow("shadow", element)
    if scope == "element":
        operation = element.wait_until(condition, timeout=0)
    else:
        owner, count = scope.split("-")
        context = {"session": session, "element": element, "shadow": shadow}[owner]
        context._find_element_no_wait = AsyncMock(return_value=element)
        operation = getattr(
            context, "wait_until_element" if count == "one" else "wait_until_elements"
        )(condition, "#field", timeout=0)
    if condition in {"visible", "viewable"}:
        with pytest.raises(errors.InvalidArgumentError):
            await operation
        session._execute_script.assert_not_awaited()
    else:
        assert await operation
        script = session._execute_script.call_args.args[0]
        assert ("elementFromPoint" in script) == (condition == "unobscured")


@pytest.mark.asyncio
async def test_w3c_element_and_session_commands_do_not_inject_route_ids(
    tmp_path: Path,
) -> None:
    """Verify w3c element and session commands do not inject route ids.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    session = make_session()
    element = Element("element", session)
    await element.send("Hello")
    assert session._conn.execute.call_args.kwargs["body"] == {"text": "Hello"}
    upload = tmp_path / "upload.txt"
    upload.write_text("fixture")
    await element.upload(str(upload))
    assert session._conn.execute.call_args.kwargs["body"] == {"text": str(upload)}
    await session.execute_command(Command.GET_TITLE)
    assert session._conn.execute.call_args.kwargs["body"] is None
    await Shadow("shadow", element).find_element("#field")
    assert set(session._conn.execute.call_args.kwargs["body"]) == {"using", "value"}


@pytest.mark.asyncio
async def test_only_nested_w3c_new_session_id_is_accepted() -> None:
    """Verify only nested w3c new session id is accepted."""
    session = make_session()
    session._conn.execute.return_value = {
        "sessionId": "removed-top-level-format",
        "value": {},
    }
    with pytest.raises(errors.InvalidSessionError, match="value.sessionId"):
        await session._start_session()


@pytest.mark.parametrize(
    "payload,http_status",
    [
        ({"status": 0, "value": "old success"}, 200),
        ({"status": 7, "value": {"message": "old error"}}, 500),
        ({"value": {"error": 7, "message": "numeric error"}}, 500),
        ({"value": '{"error":"no such element"}'}, 404),
        ({"value": {"value": {"error": "no such element"}}}, 404),
    ],
)
def test_json_wire_envelopes_are_rejected(payload: Any, http_status: Any) -> None:
    """Verify json wire envelopes are rejected.

    Args:
        payload: Fixture or parametrized payload input for this regression.
        http_status: Fixture or parametrized http status input for this regression.
    """
    with pytest.raises(errors.InvalidResponseError):
        errors.webdriver_error_handler(payload, http_status=http_status)


def test_w3c_errors_retain_type_and_diagnostics_without_touching_script_results() -> (
    None
):
    """Verify w3c errors retain type and diagnostics without touching script results."""
    payload = {
        "value": {
            "error": "unexpected alert open",
            "message": "dialog",
            "data": {"text": "Hi"},
            "stacktrace": "one\ntwo",
        }
    }
    with pytest.raises(errors.UnexpectedAlertFoundError) as caught:
        errors.webdriver_error_handler(payload, http_status=500)
    assert caught.value.alert_text == "Hi"
    assert caught.value.stacktrace == ["one", "two"]
    # The same keys can be application data on a successful HTTP response.
    errors.webdriver_error_handler(
        {"value": {"status": 7, "error": "no such element", "message": "data"}}
    )


@pytest.mark.asyncio
async def test_post_commands_have_empty_json_parameters_when_no_body_is_given() -> None:
    """Verify post commands have empty json parameters when no body is given."""
    connection = Connection(SimpleNamespace(), 5)
    connection._request = AsyncMock(return_value={"value": None})
    await connection.execute("/session/id", Command.REFRESH)
    assert connection._request.call_args.args[2] == {}
    await connection.execute("/session/id", Command.GET_TITLE)
    assert connection._request.call_args.args[2] is None


@pytest.mark.parametrize("packed", [False, True])
@pytest.mark.parametrize(
    "kind", ["rdf", "applications", "invalid-version", "modern", "temporary"]
)
def test_firefox_accepts_only_webextension_manifests(
    tmp_path: Path, packed: Any, kind: Any
) -> None:
    """Verify firefox accepts only webextension manifests.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        packed: Fixture or parametrized packed input for this regression.
        kind: Fixture or parametrized kind input for this regression.
    """
    manifest = {"manifest_version": 3, "name": "Fixture", "version": "1.0"}
    manifest["browser_specific_settings"] = {"gecko": {"id": "modern@example"}}
    if kind == "applications":
        manifest["applications"] = manifest.pop("browser_specific_settings")
    elif kind == "invalid-version":
        manifest["manifest_version"] = 1
    elif kind == "temporary":
        manifest.pop("browser_specific_settings")
    filename, content = (
        ("install.rdf", "<RDF/>")
        if kind == "rdf"
        else ("manifest.json", json.dumps(manifest))
    )
    if packed:
        path = tmp_path / "addon.xpi"
        with ZipFile(path, "w") as archive:
            archive.writestr(filename, content)
    else:
        path = tmp_path / "addon"
        path.mkdir()
        (path / filename).write_text(content)
    if kind in {"rdf", "applications", "invalid-version"}:
        with pytest.raises(errors.InvalidExtensionError):
            extract_firefox_addon_details(str(path))
    else:
        addon = extract_firefox_addon_details(str(path))
        assert addon.id == (None if kind == "temporary" else "modern@example")
        assert "unpack" not in addon.dict


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manager_type,cft",
    [
        (ChromeDriverManager, False),
        (ChromiumDriverManager, False),
        (ChromeDriverManager, True),
    ],
)
@pytest.mark.parametrize("selector", ["114", "114.0.5735", "114.0.5735.90"])
async def test_pre_cft_selectors_fail_before_network_or_cache_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manager_type: Any,
    cft: Any,
    selector: Any,
) -> None:
    """Verify pre cft selectors fail before network or cache lookup.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_type: Fixture or parametrized manager type input for this regression.
        cft: Fixture or parametrized cft input for this regression.
        selector: Fixture or parametrized selector input for this regression.
    """
    manager = manager_type(str(tmp_path))
    lookup = AsyncMock(
        side_effect=AssertionError("unsupported versions must not download")
    )
    monkeypatch.setattr(manager, "_request_response_text", lookup)
    with pytest.raises(errors.InvalidDriverVersionError, match="115"):
        await manager.install_result(selector, **({"channel": "cft"} if cft else {}))
    lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_type", [ChromeDriverManager, ChromiumDriverManager])
async def test_cached_pre_cft_browser_cannot_bypass_minimum_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager_type: Any
) -> None:
    """Verify cached pre cft browser cannot bypass minimum version.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        manager_type: Fixture or parametrized manager type input for this regression.
    """
    manager = manager_type(str(tmp_path))
    binary = tmp_path / "browser"
    binary.touch()
    version = ChromiumVersion("114.0.5735.90")
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("chromedriver", "fixture")
    cache = manager._cache_view.cache_driver(
        version,
        ChromeDriverFile(
            "linux", "https://example.invalid/driver.zip", stream.getvalue()
        ),
    )
    monkeypatch.setattr(manager, "_detect_browser_version", lambda _: version)
    with pytest.raises(errors.InvalidBrowserVersionError, match="115"):
        await manager.install_result("offline", binary=str(binary))
    assert Path(cache["location"]).exists()  # Unsupported does not mean delete it.


def test_edge_keeps_its_independent_version_selection(tmp_path: Path) -> None:
    """Verify edge keeps its independent version selection.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manager = EdgeDriverManager(str(tmp_path))
    manager._parse_target_version("114.0.1823.82")
    manager._validate_supported_version(ChromiumVersion("114.0.1823.82"), browser=True)


def test_active_guides_no_longer_offer_removed_imports_or_extra() -> None:
    """Verify active guides no longer offer removed imports or extra."""
    for path in ("README.md", "docs/modernization-guide.md", "docs/demo.md"):
        content = (ROOT / path).read_text()
        assert "aselenium.manager.migration import" not in content
        assert "[legacy-cache]" not in content
        assert "remains a compatibility launcher" not in content
