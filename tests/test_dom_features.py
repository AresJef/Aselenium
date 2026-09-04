"""Browser-free public DOM contracts using real handles and a recording transport.

The transport supplies independently chosen WebDriver responses; all lookup,
serialization, polling, decoding, and output methods under test remain real.
Actual JavaScript execution and browser rendering belong to the native suite.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aselenium import errors, javascript
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.element import ELEMENT_KEY, Element, ElementRect
from aselenium.options import Timeouts
from aselenium.session import Session
from aselenium.shadow import SHADOWROOT_KEY, Shadow
from aselenium.utils import KeyboardKeys


@pytest.fixture
def dom_session() -> Session:
    """Return an active synthetic session with no real process or HTTP client.

    Returns:
        Real session whose transport can supply responses and record calls.
    """
    service = SimpleNamespace(url="http://127.0.0.1:4444", running=True)
    session = Session(ChromeOptions(), service)
    session._id = "dom-session"
    session._base_url = service.url + "/session/dom-session"
    session._conn = SimpleNamespace(execute=AsyncMock(return_value={"value": None}))
    session._timeouts = Timeouts(implicit=0)
    return session


@pytest.fixture
def element(dom_session: Session) -> Element:
    """Return a real DOM handle bound to the synthetic session.

    Args:
        dom_session: Synthetic started session with a recording transport.

    Returns:
        Element handle with a reserved character in its remote ID.
    """
    return Element("parent/id", dom_session)


@pytest.fixture(params=["element", "shadow"])
def scope(request: pytest.FixtureRequest, element: Element) -> Element | Shadow:
    """Exercise the same descendant contract in element and shadow-root scopes.

    Args:
        request: Scope variant selected by pytest.
        element: Real host element bound to the synthetic session.

    Returns:
        Host element or its synthetic shadow-root handle.
    """
    return element if request.param == "element" else Shadow("shadow/id", element)


@pytest.mark.parametrize("identifier", [None, "", 0, [], {}])
def test_dom_handles_reject_invalid_ids(element: Element, identifier: Any) -> None:
    """Reject malformed element and shadow IDs before issuing any command.

    Args:
        element: Valid host used when constructing the shadow root.
        identifier: Invalid wire reference identifier.
    """
    with pytest.raises(errors.InvalidResponseError):
        Element(identifier, element._session)
    with pytest.raises(errors.InvalidResponseError):
        Shadow(identifier, element)
    element._conn.execute.assert_not_called()


def test_dom_identity_and_encoded_routes(element: Element) -> None:
    """Keep logical identity separate from percent-encoded command routes.

    Args:
        element: Real host with a slash in its remote identifier.
    """
    session = element._session
    duplicate = Element("parent/id", session)
    other = Element("different", session)
    shadow = Shadow("shadow/id", element)
    assert element.id == "parent/id"
    assert element.session_id == "dom-session"
    assert element.base_url.endswith("/element/parent%2Fid")
    assert element == duplicate and hash(element) == hash(duplicate)
    assert element != other and element != object()
    assert "parent/id" in repr(element)
    assert shadow.id == "shadow/id" and shadow.element_id == element.id
    assert shadow.session_id == element.session_id
    assert shadow.base_url.endswith("/shadow/shadow%2Fid")
    assert shadow == Shadow("shadow/id", element)
    assert hash(shadow) == hash(Shadow("shadow/id", element))
    assert shadow != Shadow("other", element) and shadow != object()
    assert "shadow/id" in repr(shadow)
    rectangle = ElementRect(100, 80, 10, 20)
    assert rectangle.copy().dict == {"width": 100, "height": 80, "x": 10, "y": 20}


@pytest.mark.asyncio
async def test_dom_execute_forwards_overrides(scope: Element | Shadow) -> None:
    """Preserve custom command payload, route keys, timeout, and raw response.

    Args:
        scope: Element or shadow-root handle using the real execute wrapper.
    """
    response = {"value": {"custom": 7}}
    scope._conn.execute.return_value = response
    assert (
        await scope.execute_command("custom", {"a": 1}, {"name": "a/b"}, 2) is response
    )
    scope._conn.execute.assert_awaited_once_with(
        scope.base_url, "custom", body={"a": 1}, keys={"name": "a/b"}, timeout=2
    )


_WIRE_PROPERTIES = [
    ("enabled", Command.IS_ELEMENT_ENABLED, True),
    ("selected", Command.IS_ELEMENT_SELECTED, False),
    ("tag", Command.GET_ELEMENT_TAG_NAME, "input"),
    ("text", Command.GET_ELEMENT_TEXT, "Visible text"),
    ("aria_role", Command.GET_ELEMENT_ARIA_ROLE, "textbox"),
    ("aria_label", Command.GET_ELEMENT_ARIA_LABEL, "Name"),
]


@pytest.mark.parametrize("name,command,value", _WIRE_PROPERTIES)
@pytest.mark.asyncio
async def test_element_wire_properties(
    element: Element, name: str, command: str, value: Any
) -> None:
    """Read standard element properties through their dedicated W3C commands.

    Args:
        element: Real element handle with a recording transport.
        name: Public asynchronous property name.
        command: Expected WebDriver command independent of response value.
        value: Legal value supplied by the browser protocol boundary.
    """
    element._conn.execute.return_value = {"value": value}
    assert await getattr(element, name) == value
    element._conn.execute.assert_awaited_once_with(
        element.base_url, command, body=None, keys=None, timeout=None
    )


@pytest.mark.parametrize("name,command,value", _WIRE_PROPERTIES)
@pytest.mark.asyncio
async def test_element_wire_properties_require_value(
    element: Element, name: str, command: str, value: Any
) -> None:
    """Turn missing response fields into package errors, not KeyError.

    Args:
        element: Real element handle with a recording transport.
        name: Property requiring a WebDriver value field.
        command: Command associated with the property table.
        value: Legal reference value from the property table.
    """
    element._conn.execute.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await getattr(element, name)


@pytest.mark.parametrize("name", [entry[0] for entry in _WIRE_PROPERTIES])
@pytest.mark.asyncio
async def test_element_unsupported_properties_have_documented_fallbacks(
    element: Element, name: str
) -> None:
    """Return False for unsupported state checks and None for value properties.

    Args:
        element: Real element handle with an unsupported-command transport.
        name: Public property under observation.
    """
    element._conn.execute.side_effect = errors.InvalidMethodError("unsupported")
    assert await getattr(element, name) is (
        False if name in {"enabled", "selected"} else None
    )


@pytest.mark.parametrize("name", ["exists", "enabled", "selected"])
@pytest.mark.parametrize(
    "failure", [errors.ElementNotFoundError, errors.ElementStaleReferenceError]
)
@pytest.mark.asyncio
async def test_element_missing_state_checks_return_false(
    element: Element, name: str, failure: type[Exception]
) -> None:
    """Treat absent and stale handles as false state observations.

    Args:
        element: Real handle whose next browser operation fails.
        name: State check that documents a missing-element fallback.
        failure: Missing or stale-reference protocol error class.
    """
    element._conn.execute.side_effect = failure("detached")
    assert await getattr(element, name) is False


@pytest.mark.parametrize(
    "method,command,keys",
    [
        ("get_property", Command.GET_ELEMENT_PROPERTY, {"name": "value"}),
        (
            "get_property_css",
            Command.GET_ELEMENT_VALUE_OF_CSS_PROPERTY,
            {"propertyName": "value"},
        ),
        ("get_attribute_dom", Command.GET_ELEMENT_ATTRIBUTE, {"name": "value"}),
    ],
)
@pytest.mark.asyncio
async def test_element_named_property_contracts(
    element: Element, method: str, command: str, keys: dict[str, str]
) -> None:
    """Read named properties with the correct route placeholder and fallback.

    Args:
        element: Real element handle using the recording transport.
        method: Public accessor name.
        command: Expected protocol command.
        keys: Expected route parameters for that command.
    """
    accessor = getattr(element, method)
    element._conn.execute.return_value = {"value": "provided"}
    assert await accessor("value") == "provided"
    element._conn.execute.assert_awaited_once_with(
        element.base_url, command, body=None, keys=keys, timeout=None
    )
    element._conn.execute.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await accessor("value")
    element._conn.execute.side_effect = errors.InvalidMethodError("unsupported")
    assert await accessor("value") is None


@pytest.mark.parametrize("value", [None, False, 0, 1.5, ["a"], {"application": 1}])
@pytest.mark.asyncio
async def test_element_property_preserves_application_values(
    element: Element, value: Any
) -> None:
    """Do not confuse ordinary JavaScript values with remote element references.

    Args:
        element: Real handle whose property response is controlled.
        value: Nullable or structured application property value.
    """
    element._conn.execute.return_value = {"value": value}
    assert await element.get_property("custom") is value


@pytest.mark.asyncio
async def test_element_property_decodes_element_reference(element: Element) -> None:
    """Bind element-valued DOM properties to the originating session.

    Args:
        element: Real handle whose property points at a second DOM element.
    """
    element._conn.execute.return_value = {"value": {ELEMENT_KEY: "child"}}
    child = await element.get_property("firstElementChild")
    assert isinstance(child, Element) and child.id == "child"
    assert child._session is element._session


@pytest.mark.parametrize(
    "name,script,value",
    [
        ("exists", javascript.ELEMENT_IS_VALID, True),
        ("properties", javascript.GET_ELEMENT_PROPERTIES, ["value", "checked"]),
        ("properties_css", javascript.GET_ELEMENT_CSS_PROPERTIES, {"color": "red"}),
        ("attributes", javascript.GET_ELEMENT_ATTRIBUTES, {"id": "field"}),
        ("dom_text", "return arguments[0].textContent;", "  raw text  "),
    ],
)
@pytest.mark.asyncio
async def test_element_script_properties_wrap_reference(
    element: Element, name: str, script: str, value: Any
) -> None:
    """Serialize a real handle into the W3C script argument reference shape.

    Args:
        element: Real handle passed through the session's script wrapper.
        name: Public script-backed property.
        script: Expected script for that property.
        value: Protocol result returned unchanged by the property.
    """
    element._conn.execute.return_value = {"value": value}
    assert await getattr(element, name) == value
    call = element._conn.execute.await_args
    assert call.args == (element._session.base_url, Command.W3C_EXECUTE_SCRIPT)
    assert call.kwargs["body"] == {
        "script": script,
        "args": [{ELEMENT_KEY: element.id}],
    }


@pytest.mark.parametrize(
    "name,fallback",
    [("exists", False), ("properties", []), ("properties_css", {}), ("attributes", {})],
)
@pytest.mark.asyncio
async def test_element_script_property_errors(
    element: Element, name: str, fallback: Any
) -> None:
    """Distinguish unsupported properties from invalid JavaScript responses.

    Args:
        element: Real handle using a failing recording transport.
        name: Script-backed property with documented error handling.
        fallback: Empty result for an unsupported method.
    """
    element._conn.execute.side_effect = errors.InvalidMethodError("unsupported")
    assert await getattr(element, name) == fallback
    element._conn.execute.side_effect = errors.InvalidJavaScriptError("bad script")
    with pytest.raises(errors.InvalidResponseError) as caught:
        await getattr(element, name)
    assert isinstance(caught.value.__cause__, errors.InvalidJavaScriptError)


@pytest.mark.parametrize(
    "method,command",
    [("click", Command.CLICK_ELEMENT), ("clear", Command.CLEAR_ELEMENT)],
)
@pytest.mark.asyncio
async def test_element_direct_mutation_contract(
    element: Element, method: str, command: str
) -> None:
    """Issue one mutation command and do not swallow a stale-element failure.

    Args:
        element: Real handle exercising its mutation wrapper.
        method: Public element mutation method.
        command: Expected protocol command.
    """
    assert await getattr(element, method)(pause=0) is None
    element._conn.execute.assert_awaited_once_with(
        element.base_url, command, body=None, keys=None, timeout=None
    )
    element._conn.execute.side_effect = errors.ElementStaleReferenceError("detached")
    with pytest.raises(errors.ElementStaleReferenceError):
        await getattr(element, method)()


@pytest.mark.asyncio
async def test_element_send_and_upload(element: Element, tmp_path: Path) -> None:
    """Serialize Unicode keys and newline-separated validated upload paths.

    Args:
        element: Real input handle using a recording transport.
        tmp_path: Isolated directory for real temporary upload files.
    """
    await element.send("Hello 中文", KeyboardKeys.ENTER, pause=0)
    assert element._conn.execute.await_args.kwargs["body"] == {
        "text": "Hello 中文" + KeyboardKeys.ENTER
    }
    assert element._conn.execute.await_args.args[1] == Command.SEND_KEYS_TO_ELEMENT
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.touch()
    second.touch()
    await element.upload(first, second, pause=0)
    assert element._conn.execute.await_args.kwargs["body"] == {
        "text": str(first) + "\n" + str(second)
    }
    element._conn.execute.reset_mock()
    with pytest.raises(errors.InvalidArgumentError, match="Upload"):
        await element.upload(str(tmp_path / "missing.txt"))
    element._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_element_submit_script_and_error_translation(element: Element) -> None:
    """Submit via the form script and translate invalid form context errors.

    Args:
        element: Real handle whose submit script is sent through the session.
    """
    await element.submit(pause=0)
    assert element._conn.execute.await_args.kwargs["body"] == {
        "script": javascript.ELEMENT_SUBMIT_FORM,
        "args": [{ELEMENT_KEY: element.id}],
    }
    element._conn.execute.side_effect = errors.InvalidJavaScriptError("not a form")
    with pytest.raises(errors.InvalidResponseError, match="form"):
        await element.submit()


@pytest.mark.asyncio
async def test_element_switch_frame_routes_to_session(element: Element) -> None:
    """Switch context at the session endpoint with a serialized frame element.

    Args:
        element: Real frame handle bound to the recording session.
    """
    assert await element.switch_frame() is True
    call = element._conn.execute.await_args
    assert call.args == (element._session.base_url, Command.SWITCH_TO_FRAME)
    assert call.kwargs["body"] == {"id": {ELEMENT_KEY: element.id}}
    for failure in (
        errors.FrameNotFoundError,
        errors.ElementNotFoundError,
        errors.InvalidMethodError,
    ):
        element._conn.execute.side_effect = failure("missing frame")
        assert await element.switch_frame() is False


@pytest.mark.parametrize("name", ["in_viewport", "unobscured"])
@pytest.mark.parametrize("value", [True, False])
@pytest.mark.asyncio
async def test_element_visibility_script_contract(
    element: Element, name: str, value: bool
) -> None:
    """Pass the target handle to geometry/hit-testing scripts and preserve state.

    Args:
        element: Real handle bound to the recording session.
        name: Geometry or hit-testing property.
        value: Browser observation supplied at the protocol boundary.
    """
    element._conn.execute.return_value = {"value": value}
    assert await getattr(element, name) is value
    body = element._conn.execute.await_args.kwargs["body"]
    assert body["args"] == [{ELEMENT_KEY: element.id}]
    assert "getBoundingClientRect()" in body["script"]
    if name == "unobscured":
        assert "elementFromPoint" in body["script"]


@pytest.mark.asyncio
async def test_element_scroll_observes_post_scroll_geometry(element: Element) -> None:
    """Report observed viewport intersection instead of assuming scroll success.

    Args:
        element: Real handle whose script responses represent scroll and geometry.
    """
    element._conn.execute.side_effect = [{"value": None}, {"value": False}]
    assert await element.scroll_into_view() is False
    calls = element._conn.execute.await_args_list
    assert calls[0].kwargs["body"]["script"] == javascript.ELEMENT_SCROLL_INTO_VIEW
    assert "getBoundingClientRect()" in calls[1].kwargs["body"]["script"]
    element._conn.execute.side_effect = errors.InvalidJavaScriptError("scroll failed")
    with pytest.raises(errors.InvalidResponseError, match="scroll"):
        await element.scroll_into_view()


@pytest.mark.asyncio
async def test_element_rectangle_decoding_and_failures(element: Element) -> None:
    """Decode valid geometry and reject incomplete or invalid rectangle payloads.

    Args:
        element: Real handle whose geometry response is controlled.
    """
    expected = {"width": 100, "height": 50, "x": 10, "y": 20}
    element._conn.execute.return_value = {"value": expected}
    rect = await element.rect
    assert isinstance(rect, ElementRect) and rect.dict == expected
    assert element._conn.execute.await_args.args[1] == Command.GET_ELEMENT_RECT
    for response in ({}, {"value": None}, {"value": {}}, {"value": {"x": "bad"}}):
        element._conn.execute.return_value = response
        with pytest.raises(errors.InvalidResponseError):
            await element.rect
    element._conn.execute.side_effect = errors.InvalidMethodError("unsupported")
    assert await element.rect is None


@pytest.mark.asyncio
async def test_element_screenshot_decoding_and_output(
    element: Element, tmp_path: Path
) -> None:
    """Decode screenshot bytes and save a PNG without bypassing the output helper.

    Args:
        element: Real handle whose screenshot payload is controlled.
        tmp_path: Isolated directory receiving the screenshot.
    """
    png = b"\x89PNG\r\n\x1a\nsynthetic image"
    element._conn.execute.return_value = {
        "value": base64.b64encode(png).decode("ascii")
    }
    assert await element.take_screenshot() == png
    assert element._conn.execute.await_args.args[1] == Command.ELEMENT_SCREENSHOT
    path = tmp_path / "element.png"
    assert await element.save_screenshot(str(path)) is True
    assert path.read_bytes() == png
    element._conn.execute.side_effect = errors.InvalidMethodError("unsupported")
    assert await element.take_screenshot() is None
    assert await element.save_screenshot(str(tmp_path / "absent.png")) is False
    assert not (tmp_path / "absent.png").exists()


@pytest.mark.parametrize(
    "response", [{}, {"value": "not-base64!"}, {"value": None}, {"value": 42}]
)
@pytest.mark.asyncio
async def test_element_screenshot_rejects_invalid_data(
    element: Element, response: Any
) -> None:
    """Classify malformed screenshot responses as package-level response errors.

    Args:
        element: Real handle using the recording transport.
        response: Missing, invalid-base64, or wrong-typed screenshot response.
    """
    element._conn.execute.return_value = response
    with pytest.raises(errors.InvalidResponseError):
        await element.take_screenshot()


@pytest.mark.asyncio
async def test_element_screenshot_rejects_invalid_path_before_request(
    element: Element,
) -> None:
    """Validate wrong-typed output paths before requesting screenshot bytes.

    Args:
        element: Real element whose recording transport must remain unused.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await element.save_screenshot(None)
    element._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_element_screenshot_rejects_empty_path_before_request(
    element: Element,
) -> None:
    """Do not let an empty path choose an unintended file beside the workspace.

    Args:
        element: Real element whose transport must remain unused for this input.
    """
    element._conn.execute.side_effect = AssertionError(
        "Empty path reached the screenshot request; no output was written"
    )
    with pytest.raises(errors.InvalidArgumentError):
        await element.save_screenshot("")
    element._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_element_shadow_decoding_and_error_paths(element: Element) -> None:
    """Decode W3C shadow references and distinguish missing roots from bad data.

    Args:
        element: Real host element whose shadow-root response is controlled.
    """
    element._conn.execute.return_value = {"value": {SHADOWROOT_KEY: "root"}}
    root = await element.shadow
    assert (
        isinstance(root, Shadow) and root.id == "root" and root.element_id == element.id
    )
    assert element._conn.execute.await_args.args[1] == Command.GET_SHADOW_ROOT
    for response in (
        {},
        {"value": {}},
        {"value": None},
        {"value": {SHADOWROOT_KEY: 1}},
    ):
        element._conn.execute.return_value = response
        with pytest.raises(errors.InvalidResponseError):
            await element.shadow
    for failure in (errors.ShadowRootNotFoundError, errors.InvalidMethodError):
        element._conn.execute.side_effect = failure("no root")
        assert await element.shadow is None


@pytest.mark.parametrize("plural", [False, True])
@pytest.mark.asyncio
async def test_scoped_lookup_commands_and_errors(
    scope: Element | Shadow, plural: bool
) -> None:
    """Use scoped CSS lookups and preserve absence, order, and error taxonomy.

    Args:
        scope: Real element or shadow-root search context.
        plural: Whether to invoke the plural lookup contract.
    """
    method = scope.find_elements if plural else scope.find_element
    references = [{ELEMENT_KEY: "first"}, {ELEMENT_KEY: "second"}]
    scope._conn.execute.return_value = {
        "value": references if plural else references[0]
    }
    result = await method(".child")
    assert ([item.id for item in result] if plural else result.id) == (
        ["first", "second"] if plural else "first"
    )
    scope._conn.execute.assert_awaited_once_with(
        scope.base_url,
        Command.FIND_ELEMENTS if plural else Command.FIND_ELEMENT,
        body={"using": "css selector", "value": ".child"},
        keys=None,
        timeout=None,
    )
    scope._conn.execute.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await method(".child")
    scope._conn.execute.side_effect = errors.ElementNotFoundError("missing")
    assert await method(".child") == ([] if plural else None)
    scope._conn.execute.side_effect = errors.InvalidArgumentError("invalid selector")
    with pytest.raises(errors.InvalidSelectorError) as caught:
        await method("[")
    assert isinstance(caught.value.__cause__, errors.InvalidArgumentError)


@pytest.mark.parametrize("plural", [False, True])
@pytest.mark.asyncio
async def test_element_xpath_lookup_and_invalid_strategy(
    element: Element, plural: bool
) -> None:
    """Send XPath unchanged and reject unsupported selector strategies locally.

    Args:
        element: Real descendant search context.
        plural: Whether to call plural or singular lookup.
    """
    method = element.find_elements if plural else element.find_element
    element._conn.execute.return_value = {"value": [] if plural else None}
    assert await method(".//input", by="xpath") == ([] if plural else None)
    assert element._conn.execute.await_args.kwargs["body"] == {
        "using": "xpath",
        "value": ".//input",
    }
    element._conn.execute.reset_mock()
    with pytest.raises(errors.InvalidSelectorError):
        await method("field", by="id")
    element._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_scoped_first_match_preserves_priority_and_context(
    scope: Element | Shadow,
) -> None:
    """Observe candidate selectors in order without issuing implicit-wait lookups.

    Args:
        scope: Element or shadow-root search context with implicit timeout zero.
    """
    scope._conn.execute.side_effect = [
        {"value": None},
        {"value": {ELEMENT_KEY: "match"}},
    ]
    found = await scope.find_1st_element(".missing", ".match", ".not-observed")
    assert isinstance(found, Element) and found.id == "match"
    calls = scope._conn.execute.await_args_list
    assert len(calls) == 2
    key = SHADOWROOT_KEY if isinstance(scope, Shadow) else ELEMENT_KEY
    assert [call.kwargs["body"]["args"] for call in calls] == [
        [".missing", {key: scope.id}],
        [".match", {key: scope.id}],
    ]
    assert all(call.args[1] == Command.W3C_EXECUTE_SCRIPT for call in calls)
    scope._conn.execute.reset_mock()
    assert await scope.find_1st_element() is None
    scope._conn.execute.assert_not_called()


@pytest.mark.parametrize("handles", [False, True])
@pytest.mark.parametrize("exists", [False, True])
@pytest.mark.asyncio
async def test_scoped_single_existence_serializes_context(
    scope: Element | Shadow, handles: bool, exists: bool
) -> None:
    """Observe one selector or direct handle using the correct script arguments.

    Args:
        scope: Real element or shadow-root search context.
        handles: Whether to inspect a handle directly rather than a selector.
        exists: Browser-observed existence result.
    """
    target = Element("child", scope._session) if handles else ".child"
    scope._conn.execute.return_value = {"value": exists}
    assert await scope.element_exists(target) is exists
    body = scope._conn.execute.await_args.kwargs["body"]
    if handles:
        assert body == {
            "script": javascript.ELEMENT_IS_VALID,
            "args": [{ELEMENT_KEY: "child"}],
        }
    else:
        key = SHADOWROOT_KEY if isinstance(scope, Shadow) else ELEMENT_KEY
        assert body["args"] == [".child", {key: scope.id}]
        assert "querySelector" in body["script"]


@pytest.mark.asyncio
async def test_element_xpath_no_wait_lookup_serializes_context(
    element: Element,
) -> None:
    """Keep XPath lookup scoped to the parent element rather than the document.

    Args:
        element: Real parent element serving as the XPath evaluation context.
    """
    element._conn.execute.return_value = {"value": {ELEMENT_KEY: "child"}}
    child = await element.find_1st_element(".//input", by="xpath")
    assert isinstance(child, Element) and child.id == "child"
    body = element._conn.execute.await_args.kwargs["body"]
    assert body["args"] == [".//input", {ELEMENT_KEY: element.id}]
    assert "evaluate" in body["script"]


@pytest.mark.parametrize("method", ["element_exists", "find_1st_element"])
@pytest.mark.asyncio
async def test_scoped_script_lookup_error_translation(
    scope: Element | Shadow, method: str
) -> None:
    """Handle detached scope and invalid CSS consistently in no-wait lookups.

    Args:
        scope: Element or shadow-root search context.
        method: Public method backed by the no-wait script lookup.
    """
    lookup = getattr(scope, method)
    scope._conn.execute.side_effect = errors.ElementStaleReferenceError("detached")
    assert await lookup(".child") is (False if method == "element_exists" else None)
    scope._conn.execute.side_effect = errors.InvalidElementStateError("invalid CSS")
    with pytest.raises(errors.InvalidSelectorError):
        await lookup("[")


@pytest.mark.parametrize("method", ["element_exists", "find_1st_element"])
@pytest.mark.asyncio
async def test_element_xpath_script_error_translation(
    element: Element, method: str
) -> None:
    """Translate invalid XPath script evaluations to a selector-specific error.

    Args:
        element: Real element search context.
        method: Public no-wait lookup entry point.
    """
    element._conn.execute.side_effect = errors.InvalidJavaScriptError("invalid XPath")
    with pytest.raises(errors.InvalidXPathSelectorError):
        await getattr(element, method)("//*[", by="xpath")


@pytest.mark.parametrize("response", [42, {}, {ELEMENT_KEY: None}])
@pytest.mark.asyncio
async def test_scoped_first_match_rejects_malformed_handle(
    scope: Element | Shadow, response: Any
) -> None:
    """Fail rather than returning malformed element values from lookup scripts.

    Args:
        scope: Element or shadow-root search context.
        response: Invalid non-null script result where a handle is required.
    """
    scope._conn.execute.return_value = {"value": response}
    with pytest.raises(errors.InvalidResponseError):
        await scope.find_1st_element(".child")


@pytest.mark.parametrize(
    "all_,observations,expected,count",
    [
        (True, [True, True], True, 2),
        (True, [False, True], False, 1),
        (False, [False, True], True, 2),
        (False, [True, False], True, 1),
        (False, [False, False], False, 2),
    ],
)
@pytest.mark.parametrize("handles", [False, True])
@pytest.mark.asyncio
async def test_scoped_existence_quantifiers_short_circuit(
    scope: Element | Shadow,
    all_: bool,
    observations: list[bool],
    expected: bool,
    count: int,
    handles: bool,
) -> None:
    """Honor all/any semantics for selectors and handles without extra commands.

    Args:
        scope: Real element or shadow-root search context.
        all_: Whether all candidates must exist.
        observations: Successive browser existence observations.
        expected: Independently expected quantifier result.
        count: Number of candidates required before short-circuiting.
        handles: Whether candidates are existing handles instead of selectors.
    """
    values = (
        [Element("one", scope._session), Element("two", scope._session)]
        if handles
        else [".one", ".two"]
    )
    scope._conn.execute.side_effect = [{"value": value} for value in observations]
    assert await scope.elements_exist(*values, all_=all_) is expected
    assert scope._conn.execute.await_count == count
    scope._conn.execute.reset_mock()
    assert await scope.elements_exist(all_=True) is True
    assert await scope.elements_exist(all_=False) is False
    scope._conn.execute.assert_not_called()


@pytest.mark.parametrize(
    "condition", ["gone", "exist", "unobscured", "in_viewport", "enabled", "selected"]
)
@pytest.mark.parametrize("handles", [False, True])
@pytest.mark.parametrize("plural", [False, True])
@pytest.mark.parametrize("satisfied", [False, True])
@pytest.mark.asyncio
async def test_scoped_wait_conditions_single_observation(
    scope: Element | Shadow,
    condition: str,
    handles: bool,
    plural: bool,
    satisfied: bool,
) -> None:
    """Evaluate every descendant wait condition once when timeout is zero.

    Args:
        scope: Real element or shadow-root search context.
        condition: Public condition name.
        handles: Whether the target is already an Element handle.
        plural: Whether to exercise the plural wait entry point.
        satisfied: Desired browser state for the selected condition.
    """
    target = Element("child", scope._session) if handles else ".child"
    observed = not satisfied if condition == "gone" else satisfied
    responses = [{"value": observed}]
    if not handles and condition not in {"gone", "exist"}:
        responses.insert(0, {"value": {ELEMENT_KEY: "child"}})
    scope._conn.execute.side_effect = responses
    wait = scope.wait_until_elements if plural else scope.wait_until_element
    assert await wait(condition, target, timeout=0) is satisfied
    assert scope._conn.execute.await_count == len(responses)


@pytest.mark.parametrize(
    "condition", ["unobscured", "in_viewport", "enabled", "selected"]
)
@pytest.mark.parametrize("plural", [False, True])
@pytest.mark.asyncio
async def test_scoped_state_waits_handle_missing_candidates(
    scope: Element | Shadow, condition: str, plural: bool
) -> None:
    """Return false if a selector has no element on the immediate observation.

    Args:
        scope: Real element or shadow-root search context.
        condition: State requiring a matched element.
        plural: Whether to exercise plural or singular waiting.
    """
    scope._conn.execute.return_value = {"value": None}
    wait = scope.wait_until_elements if plural else scope.wait_until_element
    assert await wait(condition, ".missing", timeout=0) is False
    assert scope._conn.execute.await_count == 1


@pytest.mark.parametrize(
    "all_,observations,expected,count",
    [
        (True, [True, True], True, 2),
        (True, [False, True], False, 1),
        (False, [False, True], True, 2),
        (False, [True, False], True, 1),
        (False, [False, False], False, 2),
    ],
)
@pytest.mark.asyncio
async def test_scoped_wait_quantifiers(
    scope: Element | Shadow,
    all_: bool,
    observations: list[bool],
    expected: bool,
    count: int,
) -> None:
    """Apply all/any wait quantifiers and stop observing once determined.

    Args:
        scope: Real element or shadow-root search context.
        all_: Whether every candidate must satisfy the condition.
        observations: Successive browser existence observations.
        expected: Independently expected quantifier result.
        count: Number of observations needed for the result.
    """
    scope._conn.execute.side_effect = [{"value": value} for value in observations]
    assert (
        await scope.wait_until_elements("exist", ".one", ".two", all_=all_, timeout=0)
        is expected
    )
    assert scope._conn.execute.await_count == count
    assert await scope.wait_until_elements("exist", all_=True, timeout=0) is True
    assert await scope.wait_until_elements("exist", all_=False, timeout=0) is False


@pytest.mark.parametrize(
    "condition", ["gone", "unobscured", "in_viewport", "enabled", "selected"]
)
@pytest.mark.parametrize("satisfied", [False, True])
@pytest.mark.asyncio
async def test_element_own_wait_conditions(
    element: Element, condition: str, satisfied: bool
) -> None:
    """Observe each direct element wait condition without changing its meaning.

    Args:
        element: Real element handle whose state is controlled.
        condition: Supported direct element wait condition.
        satisfied: Expected condition result after one observation.
    """
    element._conn.execute.return_value = {
        "value": not satisfied if condition == "gone" else satisfied
    }
    assert await element.wait_until(condition, timeout=0) is satisfied
    assert element._conn.execute.await_count == 1


@pytest.mark.parametrize("method", ["wait_until_tag", "wait_until_text"])
@pytest.mark.parametrize(
    "condition,expected_value",
    [
        ("equals", "input-field"),
        ("contains", "put-f"),
        ("startswith", "input"),
        ("endswith", "field"),
    ],
)
@pytest.mark.parametrize("actual", ["input-field", "other", None])
@pytest.mark.asyncio
async def test_element_text_wait_comparisons(
    element: Element,
    method: str,
    condition: str,
    expected_value: str,
    actual: str | None,
) -> None:
    """Apply documented string comparisons, including absent tag/text results.

    Args:
        element: Real handle whose tag or text response is controlled.
        method: Public text or tag wait entry point.
        condition: Comparison operation.
        expected_value: Required value or fragment.
        actual: Browser-observed text, including no supported value.
    """
    element._conn.execute.return_value = {"value": actual}
    assert await getattr(element, method)(condition, expected_value, timeout=0) is (
        actual == "input-field"
    )


@pytest.mark.parametrize("method", ["wait_until_tag", "wait_until_text"])
@pytest.mark.parametrize("value", ["", None, 1, []])
@pytest.mark.asyncio
async def test_element_text_wait_rejects_invalid_values(
    element: Element, method: str, value: Any
) -> None:
    """Reject unsupported comparison values before reading browser state.

    Args:
        element: Real handle whose transport must remain unused.
        method: Text or tag wait method.
        value: Empty or non-string comparison value.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(element, method)("equals", value, timeout=0)
    element._conn.execute.assert_not_called()


@pytest.mark.parametrize("method", ["wait_until_element", "wait_until_elements"])
@pytest.mark.asyncio
async def test_scoped_wait_rejects_unknown_condition(
    scope: Element | Shadow, method: str
) -> None:
    """Reject misspelled wait conditions before evaluating a selector.

    Args:
        scope: Real element or shadow-root search context.
        method: Descendant wait method.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(scope, method)("visible-ish", ".child", timeout=0)
    scope._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_element_own_wait_rejects_unknown_conditions(element: Element) -> None:
    """Validate direct and string-comparison wait conditions locally.

    Args:
        element: Real handle whose transport must remain unused.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await element.wait_until("visible-ish", timeout=0)
    for method in (element.wait_until_text, element.wait_until_tag):
        with pytest.raises(errors.InvalidArgumentError):
            await method("similar", "text", timeout=0)
    element._conn.execute.assert_not_called()


@pytest.mark.parametrize("timeout", [-1, True, float("nan"), float("inf"), "5"])
@pytest.mark.asyncio
async def test_scoped_wait_validates_budget(
    scope: Element | Shadow, timeout: Any
) -> None:
    """Reject invalid time budgets without an initial browser observation.

    Args:
        scope: Real element or shadow-root search context.
        timeout: Invalid wait budget.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await scope.wait_until_element("exist", ".child", timeout=timeout)
    scope._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_scoped_wait_cancels_inflight_observation(
    scope: Element | Shadow,
) -> None:
    """Propagate cancellation into a pending command without leaving child work.

    Args:
        scope: Real element or shadow-root search context.
    """
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """Represent an in-flight browser command and record cancellation.

        Args:
            *args: Transport command positional arguments.
            **kwargs: Transport payload and timeout arguments.

        Returns:
            Never returns normally because the command waits for cancellation.
        """
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return {"value": True}

    scope._conn.execute.side_effect = blocked
    task = asyncio.create_task(scope.wait_until_element("exist", ".child", timeout=30))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert scope._conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_scoped_wait_deadline_and_transport_failure(
    scope: Element | Shadow,
) -> None:
    """Bound slow observations but preserve immediate unrelated driver failures.

    Args:
        scope: Real element or shadow-root search context.
    """

    async def slow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """Simulate a pending browser command beyond the caller's wait deadline.

        Args:
            *args: Transport command positional arguments.
            **kwargs: Transport payload and timeout arguments.

        Returns:
            A late success that must not escape the wait deadline.
        """
        await asyncio.sleep(10)
        return {"value": True}

    scope._conn.execute.side_effect = slow
    assert (
        await asyncio.wait_for(
            scope.wait_until_element("exist", ".child", timeout=0.01), timeout=1
        )
        is False
    )
    scope._conn.execute.side_effect = errors.InvalidSessionError("session lost")
    with pytest.raises(errors.InvalidSessionError, match="session lost"):
        await scope.wait_until_element("exist", ".child", timeout=1)


@pytest.mark.asyncio
async def test_element_pause_accepts_noop_and_propagates_cancellation(
    element: Element,
) -> None:
    """Keep optional delays cooperative and report invalid duration types.

    Args:
        element: Real handle whose pause method does not need transport access.
    """
    assert await element.pause(None) is None
    assert await element.pause(0) is None
    with pytest.raises(errors.InvalidArgumentError):
        await element.pause("invalid")
    task = asyncio.create_task(element.pause(30))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    element._conn.execute.assert_not_called()
