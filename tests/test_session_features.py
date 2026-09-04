"""Offline behavior contracts for the public session and Chromium APIs.

These tests inspect commands sent by real session objects. They do not claim
that a physical casting device, browser permission prompt, or renderer ran.
"""

from __future__ import annotations

import asyncio
from base64 import b64encode
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from traceback import format_exception
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aselenium import errors, javascript
from aselenium import session as session_module
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.element import ELEMENT_KEY, Element
from aselenium.options import Timeouts
from aselenium.session import (
    ChromiumBaseSession,
    Cookie,
    DevToolsCMD,
    JavaScript,
    Network,
    Permission,
    Session,
    Window,
    WindowRect,
)


@dataclass
class SessionHarness:
    """Pair a started in-memory session with its recording transport.

    Attributes:
        session: Real Chromium session using synthetic session identifiers.
        execute: Mock of the transport boundary, never a public session method.
    """

    session: ChromiumBaseSession
    execute: AsyncMock

    def assert_command(
        self,
        command: str,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: float | None = None,
        index: int = -1,
    ) -> None:
        """Compare a recorded command with an independently specified contract.

        Args:
            command: Expected WebDriver command identifier.
            body: Expected JSON request body.
            keys: Expected command-route substitutions.
            timeout: Expected transport deadline override in seconds.
            index: Recorded call to inspect, defaulting to the most recent.
        """
        recorded = self.execute.await_args_list[index]
        assert recorded.args == ("/session/offline", command)
        assert recorded.kwargs.get("body") == body
        assert recorded.kwargs.get("keys") == keys
        assert recorded.kwargs.get("timeout") == timeout


@pytest.fixture
def harness() -> SessionHarness:
    """Create a real session without starting a service or HTTP client.

    Returns:
        Session and recording transport isolated from all external resources.
    """
    service = SimpleNamespace(url="http://127.0.0.1:4444", running=True)
    session = ChromiumBaseSession(ChromeOptions(), service)
    session._id = "offline"
    session._base_url = "/session/offline"
    execute = AsyncMock(return_value={"value": None})
    session._conn = SimpleNamespace(execute=execute, transaction=nullcontext)
    return SessionHarness(session, execute)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,arguments,command,body",
    [
        (
            "load",
            ("https://example.invalid/path",),
            Command.GET,
            {"url": "https://example.invalid/path"},
        ),
        ("refresh", (), Command.REFRESH, None),
        ("forward", (), Command.GO_FORWARD, None),
        ("backward", (), Command.GO_BACK, None),
    ],
)
async def test_navigation_dispatch(
    harness: SessionHarness,
    method: str,
    arguments: tuple[Any, ...],
    command: str,
    body: dict[str, Any] | None,
) -> None:
    """Preserve navigation arguments and explicit timeout overrides.

    Args:
        harness: Session with a recording transport.
        method: Public navigation method under test.
        arguments: Positional public API arguments.
        command: Expected WebDriver command.
        body: Expected request body.
    """
    assert await getattr(harness.session, method)(*arguments, timeout=2.5) is None
    harness.assert_command(command, body, timeout=2.5)
    assert harness.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,arguments", [("load", ("https://example.invalid",)), ("refresh", ())]
)
async def test_navigation_retry_budget(
    harness: SessionHarness, method: str, arguments: tuple[Any, ...]
) -> None:
    """Retry only WebDriver timeouts and stop after the requested retry budget.

    Args:
        harness: Session with a recording transport.
        method: Navigation method supporting retries.
        arguments: Required positional arguments for the method.
    """
    failure = errors.WebDriverTimeoutError("navigation deadline")
    harness.execute.side_effect = [failure, {"value": None}]
    await getattr(harness.session, method)(*arguments, retry=1)
    assert harness.execute.await_count == 2
    harness.execute.reset_mock()
    harness.execute.side_effect = failure
    with pytest.raises(errors.WebDriverTimeoutError, match="navigation deadline"):
        await getattr(harness.session, method)(*arguments, retry=1)
    assert harness.execute.await_count == 2
    harness.execute.reset_mock()
    harness.execute.side_effect = errors.InvalidArgumentError("bad URL")
    with pytest.raises(errors.InvalidArgumentError, match="bad URL"):
        await getattr(harness.session, method)(*arguments, retry=3)
    assert harness.execute.await_count == 1


@pytest.mark.asyncio
async def test_navigation_propagates_cancellation(harness: SessionHarness) -> None:
    """Do not retry cancellation or consume a cancelled navigation request.

    Args:
        harness: Session with a recording transport.
    """
    harness.execute.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await harness.session.load("https://example.invalid", retry=10)
    assert harness.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attribute,command,value,keys",
    [
        ("url", Command.GET_CURRENT_URL, "https://example.invalid/", None),
        ("title", Command.GET_TITLE, "An example title", None),
        ("page_source", Command.GET_PAGE_SOURCE, "<html></html>", None),
        (
            "cast_sinks",
            Command.GET_SINKS,
            [{"name": "fixture sink", "id": "one"}],
            {"vendorPrefix": "goog"},
        ),
        (
            "cast_issue",
            Command.GET_ISSUE_MESSAGE,
            "receiver unavailable",
            {"vendorPrefix": "goog"},
        ),
        ("log_types", Command.GET_AVAILABLE_LOG_TYPES, ["browser", "driver"], None),
    ],
)
async def test_scalar_and_collection_properties(
    harness: SessionHarness,
    attribute: str,
    command: str,
    value: Any,
    keys: dict[str, str] | None,
) -> None:
    """Return property response values and reject a missing response envelope.

    Args:
        harness: Session with a recording transport.
        attribute: Awaitable public property.
        command: Expected WebDriver command.
        value: Valid response value for the property.
        keys: Required vendor route substitutions, if any.
    """
    harness.execute.return_value = {"value": value}
    assert await getattr(harness.session, attribute) == value
    harness.assert_command(command, keys=keys)
    harness.execute.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await getattr(harness.session, attribute)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["wait_until_url", "wait_until_title"])
@pytest.mark.parametrize(
    "condition,value",
    [
        ("equals", "prefix-middle-suffix"),
        ("contains", "middle"),
        ("startswith", "prefix"),
        ("endswith", "suffix"),
    ],
)
async def test_text_wait_conditions(
    harness: SessionHarness, method: str, condition: str, value: str
) -> None:
    """Evaluate each documented text condition once when timeout is zero.

    Args:
        harness: Session with a recording transport.
        method: URL or title wait method.
        condition: Supported string comparison condition.
        value: Text that satisfies the selected comparison.
    """
    harness.execute.return_value = {"value": "prefix-middle-suffix"}
    assert await getattr(harness.session, method)(condition, value, timeout=0)
    assert harness.execute.await_count == 1
    assert not await getattr(harness.session, method)(condition, "absent", timeout=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["wait_until_url", "wait_until_title"])
@pytest.mark.parametrize(
    "condition,value",
    [("regex", "text"), ("equals", ""), ("equals", None), ("equals", 4)],
)
async def test_text_wait_validation(
    harness: SessionHarness, method: str, condition: str, value: Any
) -> None:
    """Reject invalid comparisons before issuing a browser command.

    Args:
        harness: Session with a recording transport.
        method: URL or title wait method.
        condition: Supplied comparison condition.
        value: Supplied comparison operand.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(harness.session, method)(condition, value, timeout=0)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,command",
    [("take_screenshot", Command.SCREENSHOT), ("print_page", Command.PRINT_PAGE)],
)
async def test_binary_outputs(
    harness: SessionHarness, method: str, command: str
) -> None:
    """Decode binary output and reject malformed base64 or missing values.

    Args:
        harness: Session with a recording transport.
        method: Public method returning binary screenshot or PDF content.
        command: Expected WebDriver command.
    """
    data = b"\x00\xffbrowser-output"
    harness.execute.return_value = {"value": b64encode(data).decode("ascii")}
    assert await getattr(harness.session, method)() == data
    harness.assert_command(command, {} if method == "print_page" else None)
    for payload in ({}, {"value": "not base64!"}, {"value": None}):
        harness.execute.return_value = payload
        with pytest.raises(errors.InvalidResponseError):
            await getattr(harness.session, method)()


@pytest.mark.asyncio
async def test_print_options_serialization(harness: SessionHarness) -> None:
    """Translate all print options into the W3C nested request structure.

    Args:
        harness: Session with a recording transport.
    """
    harness.execute.return_value = {"value": ""}
    assert (
        await harness.session.print_page(
            orientation="landscape",
            scale=0.8,
            background=True,
            page_width=21,
            page_height=29.7,
            margin_top=1,
            margin_bottom=2,
            margin_left=3,
            margin_right=4,
            shrink_to_fit=False,
            page_ranges=["1-2", "4"],
        )
        == b""
    )
    harness.assert_command(
        Command.PRINT_PAGE,
        {
            "orientation": "landscape",
            "scale": 0.8,
            "background": True,
            "page": {"width": 21, "height": 29.7},
            "margin": {"top": 1, "bottom": 2, "left": 3, "right": 4},
            "shrinkToFit": False,
            "pageRanges": ["1-2", "4"],
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"orientation": "diagonal"},
        {"scale": 0.09},
        {"scale": 2.1},
        {"background": "yes"},
        {"page_width": -1},
        {"page_height": "wide"},
        {"margin_top": -1},
        {"shrink_to_fit": 1},
        {"page_ranges": "1-3"},
    ],
)
async def test_print_options_reject_invalid_values(
    harness: SessionHarness, options: dict[str, Any]
) -> None:
    """Reject unsupported print options before dispatching a request.

    Args:
        harness: Session with a recording transport.
        options: Invalid print option to verify.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await harness.session.print_page(**options)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,extension", [("save_screenshot", ".png"), ("save_page", ".pdf")]
)
async def test_binary_outputs_saved_to_disk(
    harness: SessionHarness, tmp_path: Path, method: str, extension: str
) -> None:
    """Persist returned bytes and avoid creating a file for empty content.

    Args:
        harness: Session with a recording transport.
        tmp_path: Disposable output directory.
        method: Public file-output method.
        extension: File extension required by the method.
    """
    destination = tmp_path / ("output" + extension)
    harness.execute.return_value = {"value": b64encode(b"output bytes").decode("ascii")}
    assert await getattr(harness.session, method)(str(destination))
    assert destination.read_bytes() == b"output bytes"
    empty = tmp_path / ("empty" + extension)
    harness.execute.return_value = {"value": ""}
    assert not await getattr(harness.session, method)(str(empty))
    assert not empty.exists()
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(harness.session, method)(None)


@pytest.mark.asyncio
async def test_timeouts_are_copied_and_refreshed(harness: SessionHarness) -> None:
    """Preserve cached timeout isolation and convert API seconds to wire milliseconds.

    Args:
        harness: Session with a recording transport.
    """
    original = {"implicit": 0, "pageLoad": 20_000, "script": 5_000}
    harness.execute.return_value = {"value": original}
    first = await harness.session.timeouts
    first.script = 99
    second = await harness.session.timeouts
    assert second.script == 5
    assert harness.execute.await_count == 1
    updated = {"implicit": 1_500, "pageLoad": 20_000, "script": 2_000}
    harness.execute.side_effect = [{"value": None}, {"value": updated}]
    result = await harness.session.set_timeouts(implicit=1.5, script=2)
    assert result.dict == updated
    harness.assert_command(Command.SET_TIMEOUTS, updated, index=-2)
    harness.assert_command(Command.GET_TIMEOUTS)
    harness.execute.side_effect = [
        {"value": None},
        {"value": harness.session.options.timeouts.dict},
    ]
    assert (
        await harness.session.reset_timeouts()
    ).dict == harness.session.options.timeouts.dict
    harness.assert_command(
        Command.SET_TIMEOUTS, harness.session.options.timeouts.dict, index=-2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{}, {"value": None}, {"value": {"script": "soon"}}]
)
async def test_malformed_timeout_responses(
    harness: SessionHarness, payload: dict[str, Any]
) -> None:
    """Normalize missing or invalid timeout data to a package response error.

    Args:
        harness: Session with a recording transport.
        payload: Invalid transport response.
    """
    harness.execute.return_value = payload
    with pytest.raises(errors.InvalidResponseError):
        await harness.session.timeouts


@pytest.mark.asyncio
async def test_cookie_crud_contracts(harness: SessionHarness) -> None:
    """Exercise cookie list, creation, lookup, missing lookup, and deletion.

    Args:
        harness: Session with a recording transport.
    """
    data = {
        "name": "session",
        "value": "opaque",
        "path": "/",
        "httpOnly": True,
        "sameSite": "Lax",
    }
    harness.execute.return_value = {"value": [data]}
    assert [cookie.dict for cookie in await harness.session.cookies] == [data]
    harness.assert_command(Command.GET_ALL_COOKIES)
    harness.execute.side_effect = [{"value": None}, {"value": data}]
    cookie = await harness.session.add_cookie(data)
    assert cookie.dict == data
    harness.assert_command(Command.ADD_COOKIE, {"cookie": data}, index=-2)
    harness.assert_command(Command.GET_COOKIE, keys={"name": "session"})
    harness.execute.side_effect = None
    harness.execute.return_value = {"value": None}
    await harness.session.delete_cookie(cookie)
    harness.assert_command(Command.DELETE_COOKIE, keys={"name": "session"})
    await harness.session.delete_cookies()
    harness.assert_command(Command.DELETE_ALL_COOKIES)
    harness.execute.side_effect = errors.CookieNotFoundError("absent")
    assert await harness.session.get_cookie("missing") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,argument",
    [
        ("get_cookie", None),
        ("delete_cookie", 3),
        ("add_cookie", []),
        ("add_cookie", "name=value"),
    ],
)
async def test_cookie_invalid_inputs(
    harness: SessionHarness, method: str, argument: Any
) -> None:
    """Reject unsupported cookie input types before touching the transport.

    Args:
        harness: Session with a recording transport.
        method: Cookie operation under test.
        argument: Invalid public API input.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(harness.session, method)(argument)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_window_registry_refresh_and_rename(harness: SessionHarness) -> None:
    """Refresh closed handles, resolve names, and rename without browser navigation.

    Args:
        harness: Session with a recording transport.
    """
    harness.execute.return_value = {"value": ["first", "second"]}
    windows = await harness.session.windows
    assert [window.handle for window in windows] == ["first", "second"]
    renamed = await harness.session.rename_window(windows[0], "primary")
    assert renamed.handle == "first"
    assert await harness.session.get_window("primary") is renamed
    assert await harness.session.get_window("first") is renamed
    with pytest.raises(errors.InvalidArgumentError):
        await harness.session.rename_window(windows[1], "primary")
    harness.execute.return_value = {"value": ["second", "third"]}
    assert {window.handle for window in await harness.session.windows} == {
        "second",
        "third",
    }
    assert "primary" not in harness.session._window_by_name
    harness.execute.side_effect = errors.InvalidSessionError("session ended")
    assert await harness.session.windows == []
    assert not harness.session._window_by_handle


@pytest.mark.asyncio
async def test_new_switch_and_close_window(harness: SessionHarness) -> None:
    """Create a named tab, switch by its name, and close back to the prior window.

    Args:
        harness: Session with a recording transport.
    """
    harness.session._cache_window("original", "original")
    harness.execute.side_effect = [
        {"value": {"handle": "new", "type": "tab"}},
        {"value": None},
    ]
    created = await harness.session.new_window("report")
    assert created == Window("new", "report")
    harness.assert_command(Command.NEW_WINDOW, {"type": "tab"}, index=-2)
    harness.assert_command(Command.SWITCH_TO_WINDOW, {"handle": "new"})
    harness.execute.side_effect = [
        {"value": "new"},
        {"value": ["original"]},
        {"value": None},
    ]
    remaining = await harness.session.close_window("original")
    assert remaining.handle == "original"
    assert "new" not in harness.session._window_by_handle
    harness.assert_command(Command.CLOSE, index=-2)
    harness.assert_command(Command.SWITCH_TO_WINDOW, {"handle": "original"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options", [{"name": "", "win_type": "tab"}, {"name": "new", "win_type": "panel"}]
)
async def test_new_window_validates_before_dispatch(
    harness: SessionHarness, options: dict[str, Any]
) -> None:
    """Reject an empty name or unsupported browser window type.

    Args:
        harness: Session with a recording transport.
        options: Invalid window creation arguments.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await harness.session.new_window(**options)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["switch_window", "rename_window"])
async def test_missing_window_is_a_typed_error(
    harness: SessionHarness, method: str
) -> None:
    """Distinguish a missing named window from a malformed command response.

    Args:
        harness: Session with a recording transport.
        method: Window operation requiring an existing handle.
    """
    harness.execute.return_value = {"value": []}
    arguments = ("missing", "renamed") if method == "rename_window" else ("missing",)
    with pytest.raises(errors.WindowNotFountError):
        await getattr(harness.session, method)(*arguments)


@pytest.mark.asyncio
async def test_window_rect_partial_update(harness: SessionHarness) -> None:
    """Preserve omitted geometry fields while returning the driver's final bounds.

    Args:
        harness: Session with a recording transport.
    """
    initial = {"width": 800, "height": 600, "x": 10, "y": 20}
    final = {"width": 1000, "height": 600, "x": 10, "y": 30}
    harness.execute.side_effect = [{"value": initial}, {"value": final}]
    rect = await harness.session.set_window_rect(width=1000, y=30)
    assert isinstance(rect, WindowRect)
    assert rect.dict == final
    harness.assert_command(Command.GET_WINDOW_RECT, index=-2)
    harness.assert_command(Command.SET_WINDOW_RECT, final)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,command",
    [
        ("maximize_window", Command.W3C_MAXIMIZE_WINDOW),
        ("minimize_window", Command.MINIMIZE_WINDOW),
        ("fullscreen_window", Command.FULLSCREEN_WINDOW),
    ],
)
async def test_window_state_commands(
    harness: SessionHarness, method: str, command: str
) -> None:
    """Dispatch each supported window state change and preserve its return contract.

    Args:
        harness: Session with a recording transport.
        method: Public window-state method.
        command: Expected WebDriver command.
    """
    rectangle = {"width": 1000, "height": 700, "x": 0, "y": 0}
    harness.execute.return_value = {"value": rectangle}
    result = await getattr(harness.session, method)()
    if method == "maximize_window":
        assert result.dict == rectangle
    else:
        assert result is None
    harness.assert_command(command)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,arguments,script",
    [
        ("scroll_by", {"width": -5, "height": 12}, javascript.PAGE_SCROLL_BY),
        ("scroll_to", {"x": 3, "y": 7}, javascript.PAGE_SCROLL_TO),
    ],
)
async def test_scroll_request_and_script_failure(
    harness: SessionHarness, method: str, arguments: dict[str, int], script: str
) -> None:
    """Send ordered scroll coordinates and normalize JavaScript execution errors.

    Args:
        harness: Session with a recording transport.
        method: Relative or absolute scroll operation.
        arguments: Coordinate values passed through the public API.
        script: Expected bundled JavaScript helper.
    """
    await getattr(harness.session, method)(**arguments)
    harness.assert_command(
        Command.W3C_EXECUTE_SCRIPT, {"script": script, "args": list(arguments.values())}
    )
    harness.execute.side_effect = errors.InvalidJavaScriptError("script failed")
    with pytest.raises(errors.InvalidResponseError):
        await getattr(harness.session, method)(**arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["scroll_to_top", "scroll_to_bottom", "scroll_to_left", "scroll_to_right"]
)
@pytest.mark.parametrize(
    "arguments",
    [
        {"value": 0},
        {"value": 1.5},
        {"by": "percentage"},
        {"pause": 0},
        {"pause": "soon"},
    ],
)
async def test_directional_scroll_validation(
    harness: SessionHarness, method: str, arguments: dict[str, Any]
) -> None:
    """Reject invalid directional scrolling parameters without issuing commands.

    Args:
        harness: Session with a recording transport.
        method: Directional scrolling method.
        arguments: One invalid strategy, distance, or pause argument.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(harness.session, method)(**arguments)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,value,expected",
    [
        ("scroll_to_top", {"width": 100, "height": 50, "x": 30, "y": 70}, [30, 0]),
        ("scroll_to_left", {"width": 100, "height": 50, "x": 30, "y": 70}, [0, 70]),
    ],
)
async def test_single_step_scroll_to_origin(
    harness: SessionHarness, method: str, value: dict[str, int], expected: list[int]
) -> None:
    """Scroll one axis to its origin while retaining the other viewport offset.

    Args:
        harness: Session with a recording transport.
        method: Top or left directional scroll operation.
        value: Current viewport geometry.
        expected: Expected absolute x and y coordinates.
    """
    harness.execute.side_effect = [{"value": value}, {"value": None}]
    await getattr(harness.session, method)()
    harness.assert_command(
        Command.W3C_EXECUTE_SCRIPT,
        {"script": javascript.PAGE_SCROLL_TO, "args": expected},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,command",
    [
        ("execute_script", Command.W3C_EXECUTE_SCRIPT),
        ("execute_async_script", Command.W3C_EXECUTE_SCRIPT_ASYNC),
    ],
)
async def test_script_cache_and_nested_element_arguments(
    harness: SessionHarness, method: str, command: str
) -> None:
    """Use cached defaults, explicit overrides, and nested W3C element references.

    Args:
        harness: Session with a recording transport.
        method: Synchronous or asynchronous JavaScript execution method.
        command: Expected WebDriver script endpoint.
    """
    element = Element("field", harness.session)
    script = harness.session.cache_script("identity", "return arguments[0]", "default")
    harness.execute.return_value = {"value": {"answer": False}}
    assert await getattr(harness.session, method)(script) == {"answer": False}
    harness.assert_command(
        command, {"script": "return arguments[0]", "args": ["default"]}
    )
    await getattr(harness.session, method)("identity", {"nested": [element, 0]})
    harness.assert_command(
        command,
        {
            "script": "return arguments[0]",
            "args": [{"nested": [{ELEMENT_KEY: "field"}, 0]}],
        },
    )
    harness.execute.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await getattr(harness.session, method)("return 0")


def test_script_cache_lifecycle(harness: SessionHarness) -> None:
    """Keep script names unique and preserve content when renaming a cached script.

    Args:
        harness: Session with a recording transport.
    """
    script = harness.session.cache_script("one", "return arguments[0]", 42)
    assert harness.session.scripts == [script]
    assert harness.session.get_script(script) is script
    for name in ("one", "", None):
        with pytest.raises(errors.InvalidArgumentError):
            harness.session.cache_script(name, "return 0")
    renamed = harness.session.rename_script(script, "two")
    assert renamed.name == "two" and renamed.args == [42]
    assert harness.session.get_script("one") is None
    assert harness.session.remove_script(renamed)
    assert not harness.session.remove_script(renamed)
    with pytest.raises(errors.JavaScriptNotFoundError):
        harness.session.rename_script("missing", "unused")


@pytest.mark.asyncio
async def test_cdp_cache_execution_and_lifecycle(harness: SessionHarness) -> None:
    """Preserve cached CDP parameters and correctly route explicit overrides.

    Args:
        harness: Session with a recording transport.
    """
    command = harness.session.cache_cdp_cmd(
        "evaluate", "Runtime.evaluate", expression="1+1"
    )
    assert harness.session.cdp_cmds == [command]
    assert harness.session.get_cdp_cmd(command) is command
    harness.execute.return_value = {"value": {"result": {"value": 2}}}
    assert await harness.session.execute_cdp_cmd(command) == {"result": {"value": 2}}
    harness.assert_command(
        Command.EXECUTE_CDP_COMMAND,
        {"cmd": "Runtime.evaluate", "params": {"expression": "1+1"}},
        {"vendorPrefix": "goog"},
    )
    await harness.session.execute_cdp_cmd("evaluate", expression="3+3")
    harness.assert_command(
        Command.EXECUTE_CDP_COMMAND,
        {"cmd": "Runtime.evaluate", "params": {"expression": "3+3"}},
        {"vendorPrefix": "goog"},
    )
    renamed = harness.session.rename_cdp_cmd(command, "new-name")
    assert renamed.kwargs == {"expression": "1+1"}
    assert harness.session.get_cdp_cmd("evaluate") is None
    assert harness.session.remove_cdp_cmd(renamed)
    assert not harness.session.remove_cdp_cmd(renamed)
    with pytest.raises(errors.DevToolsCMDNotFoundError):
        harness.session.rename_cdp_cmd("missing", "unused")
    harness.execute.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await harness.session.execute_cdp_cmd("Runtime.evaluate")


@pytest.mark.parametrize("name", ["", None, 3])
def test_cdp_cache_rejects_invalid_names(harness: SessionHarness, name: Any) -> None:
    """Reject non-string and empty CDP cache keys.

    Args:
        harness: Session with a recording transport.
        name: Invalid command cache name.
    """
    with pytest.raises(errors.InvalidArgumentError):
        harness.session.cache_cdp_cmd(name, "Runtime.evaluate")


@pytest.mark.asyncio
async def test_permission_get_set_and_unsupported(harness: SessionHarness) -> None:
    """Serialize permission updates and distinguish unsupported permission queries.

    Args:
        harness: Session with a recording transport.
    """
    harness.execute.side_effect = [{"value": None}, {"value": {"state": "granted"}}]
    permission = await harness.session.set_permission("geolocation", "granted")
    assert permission.dict == {"name": "geolocation", "state": "granted"}
    harness.assert_command(
        Command.SET_PERMISSION,
        {"descriptor": {"name": "geolocation"}, "state": "granted"},
        index=-2,
    )
    harness.assert_command(
        Command.W3C_EXECUTE_SCRIPT,
        {"script": javascript.GET_PERMISSION, "args": ["geolocation"]},
    )
    harness.execute.side_effect = errors.UnknownCommandError("unsupported")
    assert (
        await harness.session.get_permission(Permission("geolocation", "prompt"))
        is None
    )
    harness.execute.side_effect = None
    harness.execute.return_value = {"value": {}}
    with pytest.raises(errors.InvalidResponseError):
        await harness.session.get_permission("geolocation")
    with pytest.raises(errors.InvalidArgumentError):
        await harness.session.get_permission(1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,error",
    [
        ("unrecognized permission state", errors.InvalidPermissionStateError),
        ("Invalid PermissionDescriptor name", errors.InvalidPermissionNameError),
        ("unrelated invalid input", errors.InvalidArgumentError),
    ],
)
async def test_permission_error_classification(
    harness: SessionHarness, message: str, error: type[Exception]
) -> None:
    """Classify known browser permission failures without hiding unrelated errors.

    Args:
        harness: Session with a recording transport.
        message: Driver error text identifying a failure.
        error: Expected public error type.
    """
    harness.execute.side_effect = errors.InvalidArgumentError(message)
    with pytest.raises(error):
        await harness.session.set_permission("geolocation", "granted")


@pytest.mark.asyncio
async def test_network_partial_update_reset_and_unset(harness: SessionHarness) -> None:
    """Preserve unspecified network settings and restore explicit defaults.

    Args:
        harness: Session with a recording transport.
    """
    initial = {
        "offline": False,
        "latency": 10,
        "upload_throughput": 100,
        "download_throughput": 200,
    }
    changed = initial | {"offline": True, "latency": 30}
    harness.execute.side_effect = [
        {"value": initial},
        {"value": None},
        {"value": changed},
    ]
    assert (await harness.session.set_network(offline=True, latency=30)).dict == changed
    harness.assert_command(
        Command.SET_NETWORK_CONDITIONS, {"network_conditions": changed}, index=-2
    )
    defaults = {
        "offline": False,
        "latency": 0,
        "upload_throughput": -1,
        "download_throughput": -1,
    }
    harness.execute.side_effect = [{"value": None}, {"value": defaults}]
    assert (await harness.session.reset_network()).dict == defaults
    harness.assert_command(
        Command.SET_NETWORK_CONDITIONS, {"network_conditions": defaults}, index=-2
    )
    harness.execute.side_effect = errors.UnknownError(
        "network conditions must be set before use"
    )
    assert (await harness.session.network).dict == defaults
    harness.execute.side_effect = errors.UnknownError("unrelated driver error")
    with pytest.raises(errors.UnknownError, match="unrelated"):
        await harness.session.network


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{}, {"value": None}, {"value": {"latency": "slow"}}]
)
async def test_network_malformed_responses(
    harness: SessionHarness, payload: dict[str, Any]
) -> None:
    """Normalize invalid network-condition responses to package response errors.

    Args:
        harness: Session with a recording transport.
        payload: Malformed response returned by the transport.
    """
    harness.execute.return_value = payload
    with pytest.raises(errors.InvalidResponseError):
        await harness.session.network


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,arguments,command",
    [
        ("set_cast_sink", {}, Command.SET_SINK_TO_USE),
        ("start_casting", {"mirror": "tab"}, Command.START_TAB_MIRRORING),
        ("start_casting", {"mirror": "desktop"}, Command.START_DESKTOP_MIRRORING),
        ("stop_casting", {}, Command.STOP_CASTING),
    ],
)
async def test_casting_protocol_only(
    harness: SessionHarness, method: str, arguments: dict[str, str], command: str
) -> None:
    """Verify casting wire contracts without claiming a receiver was exercised.

    Args:
        harness: Session with a recording transport.
        method: Public casting control method.
        arguments: Optional mirroring-mode arguments.
        command: Expected vendor WebDriver command.
    """
    await getattr(harness.session, method)("fixture sink", **arguments)
    harness.assert_command(
        command, {"sinkName": "fixture sink"}, {"vendorPrefix": "goog"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["start_casting", "stop_casting"])
async def test_casting_error_classification(
    harness: SessionHarness, method: str
) -> None:
    """Translate missing receivers but preserve unrelated driver errors.

    Args:
        harness: Session with a recording transport.
        method: Start or stop casting operation.
    """
    harness.execute.side_effect = errors.UnknownError("Sink not found")
    with pytest.raises(errors.CastSinkNotFoundError):
        await getattr(harness.session, method)("missing")
    harness.execute.side_effect = errors.UnknownError("unrelated failure")
    with pytest.raises(errors.UnknownError, match="unrelated"):
        await getattr(harness.session, method)("missing")


@pytest.mark.asyncio
async def test_casting_invalid_mirror(harness: SessionHarness) -> None:
    """Reject an unsupported mirror type without issuing a device command.

    Args:
        harness: Session with a recording transport.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await harness.session.start_casting("fixture", mirror="window")
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_read_and_unsupported_type(harness: SessionHarness) -> None:
    """Return log entries, tolerate unsupported types, and reject missing data.

    Args:
        harness: Session with a recording transport.
    """
    entries = [{"level": "INFO", "message": "fixture event", "timestamp": 1000}]
    harness.execute.return_value = {"value": entries}
    assert await harness.session.get_logs("browser") == entries
    harness.assert_command(Command.GET_LOG, {"type": "browser"})
    harness.execute.side_effect = errors.InvalidArgumentError("unknown log type")
    assert await harness.session.get_logs("unsupported") == []
    harness.execute.side_effect = None
    harness.execute.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await harness.session.get_logs("browser")


@pytest.mark.asyncio
async def test_custom_command_forwards_all_parameters(harness: SessionHarness) -> None:
    """Preserve the custom-command response and all caller-supplied transport options.

    Args:
        harness: Session with a recording transport.
    """
    response = {"value": {"result": 4}}
    harness.execute.return_value = response
    assert (
        await harness.session.execute_command(
            "fixture-command", {"value": 2}, {"name": "field"}, 0.5
        )
        is response
    )
    harness.assert_command("fixture-command", {"value": 2}, {"name": "field"}, 0.5)


def test_transaction_requires_started_session() -> None:
    """Reject transaction entry before any connection has been established."""
    session = Session(ChromeOptions(), SimpleNamespace(url="http://127.0.0.1:4444"))
    with pytest.raises(errors.InvalidSessionError, match="not started"):
        session.transaction()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attribute,script,value",
    [
        (
            "viewport",
            javascript.GET_PAGE_VIEWPORT,
            {"width": 100, "height": 50, "x": 3, "y": 4},
        ),
        ("page_width", javascript.GET_PAGE_WIDTH, 1600),
        ("page_height", javascript.GET_PAGE_HEIGHT, 2400),
    ],
)
async def test_page_geometry_queries(
    harness: SessionHarness, attribute: str, script: str, value: Any
) -> None:
    """Decode page geometry and normalize script failures at the session boundary.

    Args:
        harness: Session with a recording transport.
        attribute: Awaitable geometry property.
        script: Bundled geometry query script.
        value: Driver response representing the requested geometry.
    """
    harness.execute.return_value = {"value": value}
    actual = await getattr(harness.session, attribute)
    assert (actual.dict if attribute == "viewport" else actual) == value
    harness.assert_command(Command.W3C_EXECUTE_SCRIPT, {"script": script, "args": []})
    harness.execute.side_effect = errors.InvalidJavaScriptError("geometry unavailable")
    with pytest.raises(errors.InvalidResponseError):
        await getattr(harness.session, attribute)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["scroll_to_top", "scroll_to_bottom", "scroll_to_left", "scroll_to_right"]
)
async def test_directional_scroll_detects_stalled_page(
    harness: SessionHarness, method: str
) -> None:
    """Bound each directional scroll when repeated viewport observations never move.

    Args:
        harness: Session with a recording transport.
        method: Directional scrolling method under test.
    """

    async def stationary_response(
        base_url: str, command: str, **options: Any
    ) -> dict[str, Any]:
        """Model a page that ignores scrolling but reports valid geometry.

        Args:
            base_url: Recorded session URL.
            command: Recorded WebDriver command.
            **options: Transport options including the script body.

        Returns:
            Stable viewport geometry, page extent, or a null scroll result.
        """
        assert base_url == "/session/offline"
        assert command == Command.W3C_EXECUTE_SCRIPT
        script = options["body"]["script"]
        if script == javascript.GET_PAGE_VIEWPORT:
            return {"value": {"width": 100, "height": 50, "x": 25, "y": 25}}
        if script in (javascript.GET_PAGE_WIDTH, javascript.GET_PAGE_HEIGHT):
            return {"value": 1000}
        assert script == javascript.PAGE_SCROLL_BY
        return {"value": None}

    harness.execute.side_effect = stationary_response
    with pytest.raises(errors.WebDriverTimeoutError, match="no progress"):
        await asyncio.wait_for(
            getattr(harness.session, method)(by="pixels", value=10, pause=0.001),
            timeout=1,
        )
    assert harness.execute.await_count < 30


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["scroll_to_bottom", "scroll_to_right"])
async def test_scroll_to_far_edge_reaches_target(
    harness: SessionHarness, method: str
) -> None:
    """Calculate the remaining page distance and stop once the far edge is reached.

    Args:
        harness: Session with a recording transport.
        method: Bottom or right directional scrolling operation.
    """
    axis = "y" if method == "scroll_to_bottom" else "x"
    end = {"width": 100, "height": 100, "x": 0, "y": 0}
    end[axis] = 900
    harness.execute.side_effect = [
        {"value": {"width": 100, "height": 100, "x": 0, "y": 0}},
        {"value": 1000},
        {"value": None},
        {"value": 1000},
        {"value": end},
    ]
    await getattr(harness.session, method)(pause=0.001)
    harness.assert_command(
        Command.W3C_EXECUTE_SCRIPT,
        {
            "script": javascript.PAGE_SCROLL_BY,
            "args": [0, 900] if axis == "y" else [900, 0],
        },
        index=2,
    )
    assert harness.execute.await_count == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "by,selector,strategy",
    [("css", "#field", "css selector"), ("xpath", "//input", "xpath")],
)
async def test_root_dom_lookup_contracts(
    harness: SessionHarness, by: str, selector: str, strategy: str
) -> None:
    """Translate root selectors and distinguish missing elements from invalid selectors.

    Args:
        harness: Session with a recording transport.
        by: Public selector strategy.
        selector: Selector expression.
        strategy: Expected W3C selector strategy.
    """
    harness.execute.return_value = {"value": {ELEMENT_KEY: "field"}}
    assert (await harness.session.find_element(selector, by=by)).id == "field"
    harness.assert_command(Command.FIND_ELEMENT, {"using": strategy, "value": selector})
    harness.execute.return_value = {
        "value": [{ELEMENT_KEY: "one"}, {ELEMENT_KEY: "two"}]
    }
    assert [
        item.id for item in await harness.session.find_elements(selector, by=by)
    ] == ["one", "two"]
    harness.assert_command(
        Command.FIND_ELEMENTS, {"using": strategy, "value": selector}
    )
    harness.execute.side_effect = errors.ElementNotFoundError("absent")
    assert await harness.session.find_element(selector, by=by) is None
    assert await harness.session.find_elements(selector, by=by) == []
    harness.execute.side_effect = errors.InvalidArgumentError("bad selector")
    for method in ("find_element", "find_elements"):
        with pytest.raises(errors.InvalidSelectorError):
            await getattr(harness.session, method)(selector, by=by)


@pytest.mark.asyncio
async def test_first_matching_selector_and_active_element(
    harness: SessionHarness,
) -> None:
    """Search ordered alternatives using the implicit budget and decode focused elements.

    Args:
        harness: Session with a recording transport.
    """
    harness.session._timeouts = Timeouts(implicit=0)
    harness.execute.side_effect = [{"value": None}, {"value": {ELEMENT_KEY: "found"}}]
    assert (await harness.session.find_1st_element("#missing", "#found")).id == "found"
    assert [
        call.kwargs["body"]["args"] for call in harness.execute.await_args_list
    ] == [["#missing"], ["#found"]]
    harness.execute.side_effect = None
    harness.execute.return_value = {"value": {ELEMENT_KEY: "focused"}}
    assert (await harness.session.active_element).id == "focused"
    harness.assert_command(Command.W3C_GET_ACTIVE_ELEMENT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "all_,responses,expected,calls",
    [
        (True, [True, False, True], False, 2),
        (False, [False, True, False], True, 2),
        (True, [True, True, True], True, 3),
        (False, [False, False, False], False, 3),
    ],
)
async def test_multiple_element_existence_short_circuit(
    harness: SessionHarness,
    all_: bool,
    responses: list[bool],
    expected: bool,
    calls: int,
) -> None:
    """Implement all/any semantics without unnecessary browser queries.

    Args:
        harness: Session with a recording transport.
        all_: Whether all selectors must match.
        responses: Existence observations in selector order.
        expected: Expected combined result.
        calls: Number of observations needed before short-circuiting.
    """
    harness.execute.side_effect = [{"value": value} for value in responses]
    assert (
        await harness.session.elements_exist("#one", "#two", "#three", all_=all_)
        is expected
    )
    assert harness.execute.await_count == calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition", ["gone", "exist", "unobscured", "in_viewport", "enabled", "selected"]
)
@pytest.mark.parametrize("as_element", [False, True])
async def test_root_element_wait_conditions(
    harness: SessionHarness, condition: str, as_element: bool
) -> None:
    """Exercise each supported wait condition through selectors and element objects.

    Args:
        harness: Session with a recording transport.
        condition: Documented DOM state to wait for.
        as_element: Whether to supply an existing element rather than a selector.
    """
    target = Element("target", harness.session) if as_element else "#target"
    for method in ("wait_until_element", "wait_until_elements"):
        states = [{"value": condition != "gone"}]
        if not as_element and condition not in {"gone", "exist"}:
            states.insert(0, {"value": {ELEMENT_KEY: "target"}})
        harness.execute.side_effect = states
        assert await getattr(harness.session, method)(condition, target, timeout=0)
    harness.execute.side_effect = None
    harness.execute.return_value = {"value": False}
    assert (
        await harness.session.element_exists(Element("target", harness.session))
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["wait_until_element", "wait_until_elements"])
async def test_root_wait_invalid_condition(
    harness: SessionHarness, method: str
) -> None:
    """Reject unsupported element wait conditions before dispatch.

    Args:
        harness: Session with a recording transport.
        method: Single or multiple element-state wait method.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(harness.session, method)("clickable", "#field", timeout=0)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_shadow_lookup_and_scroll_into_view(harness: SessionHarness) -> None:
    """Resolve a shadow root and scroll a located host using its W3C reference.

    Args:
        harness: Session with a recording transport.
    """
    harness.execute.side_effect = [
        {"value": {ELEMENT_KEY: "host"}},
        {"value": {"shadow-6066-11e4-a52e-4f735466cecf": "root"}},
    ]
    shadow = await harness.session.get_shadow("#host", timeout=0)
    assert shadow.id == "root"
    harness.execute.side_effect = [
        {"value": {ELEMENT_KEY: "host"}},
        {"value": None},
        {"value": True},
    ]
    assert await harness.session.scroll_into_view("#host", timeout=0)
    harness.assert_command(
        Command.W3C_EXECUTE_SCRIPT,
        {
            "script": javascript.ELEMENT_SCROLL_INTO_VIEW,
            "args": [{ELEMENT_KEY: "host"}],
        },
        index=-2,
    )
    harness.execute.side_effect = [{"value": None}]
    assert await harness.session.get_shadow("#missing", timeout=0) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["index", "element", "selector"])
async def test_frame_switching_contracts(harness: SessionHarness, form: str) -> None:
    """Convert frame selectors, indices, and element objects to WebDriver frame IDs.

    Args:
        harness: Session with a recording transport.
        form: Public frame identifier representation.
    """
    if form == "index":
        assert await harness.session.switch_frame(2, by="index", timeout=0)
        expected: Any = 2
    elif form == "element":
        assert await harness.session.switch_frame(
            Element("frame", harness.session), timeout=0
        )
        expected = {ELEMENT_KEY: "frame"}
    else:
        harness.execute.side_effect = [
            {"value": {ELEMENT_KEY: "frame"}},
            {"value": None},
        ]
        assert await harness.session.switch_frame("iframe", timeout=0)
        expected = {ELEMENT_KEY: "frame"}
    harness.assert_command(Command.SWITCH_TO_FRAME, {"id": expected})
    harness.execute.side_effect = errors.FrameNotFoundError("frame vanished")
    assert not await harness.session.switch_frame(2, by="index", timeout=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,command,body",
    [
        ("default_frame", Command.SWITCH_TO_FRAME, {"id": None}),
        ("parent_frame", Command.SWITCH_TO_PARENT_FRAME, None),
    ],
)
async def test_frame_restoration(
    harness: SessionHarness, method: str, command: str, body: dict[str, Any] | None
) -> None:
    """Restore parent or default frame and report missing frame failures as false.

    Args:
        harness: Session with a recording transport.
        method: Frame restoration operation.
        command: Expected WebDriver command.
        body: Expected request body.
    """
    assert await getattr(harness.session, method)()
    harness.assert_command(command, body)
    harness.execute.side_effect = errors.FrameNotFoundError("absent")
    assert not await getattr(harness.session, method)()


@pytest.mark.asyncio
async def test_alert_discovery_and_pause_cancellation(harness: SessionHarness) -> None:
    """Discover an alert without hidden waiting and preserve cancellation during a pause.

    Args:
        harness: Session with a recording transport.
    """
    harness.execute.return_value = {"value": "Prompt text"}
    assert await harness.session.get_alert(timeout=0) is not None
    harness.assert_command(Command.W3C_GET_ALERT_TEXT)
    harness.execute.side_effect = errors.AlertNotFoundError("no alert")
    assert await harness.session.get_alert(timeout=0) is None
    await harness.session.pause(None)
    await harness.session.pause(0)
    with pytest.raises(errors.InvalidArgumentError):
        await harness.session.pause("invalid")
    pending = asyncio.create_task(harness.session.pause(60))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,arguments", [("load", ("https://example.invalid",)), ("refresh", ())]
)
@pytest.mark.parametrize(
    "retry", [-1, -2, True, False, 1.0, -0.5, float("nan"), float("inf"), "1", [], {}]
)
async def test_invalid_navigation_retry_rejected(
    harness: SessionHarness, method: str, arguments: tuple[str, ...], retry: Any
) -> None:
    """Reject invalid retry budgets before any navigation request.

    Args:
        harness: Session with a recording transport.
        method: Navigation operation with a retry budget.
        arguments: Required navigation arguments.
        retry: Negative, nonintegral, or incorrectly typed retry budget.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(harness.session, method)(*arguments, retry=retry)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute_script", "execute_async_script"])
@pytest.mark.parametrize("state", ["standalone", "removed", "renamed"])
async def test_uncached_script_object_execution(
    harness: SessionHarness, method: str, state: str
) -> None:
    """Reject unavailable script handles without sending a non-JSON request.

    Args:
        harness: Session with a recording transport.
        method: Synchronous or asynchronous JavaScript execution operation.
        state: How the value object became unavailable in this session's cache.
    """
    script = JavaScript("standalone", "return arguments[0]", 42)
    if state != "standalone":
        script = harness.session.cache_script("cached", "return arguments[0]", 42)
        if state == "removed":
            harness.session.remove_script(script)
        else:
            harness.session.rename_script(script, "renamed")
    with pytest.raises(errors.JavaScriptNotFoundError):
        await getattr(harness.session, method)(script)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["standalone", "removed", "renamed"])
async def test_uncached_cdp_object_execution(
    harness: SessionHarness, state: str
) -> None:
    """Reject unavailable CDP handles without sending a non-JSON request.

    Args:
        harness: Session with a recording transport.
        state: How the value object became unavailable in this session's cache.
    """
    command = DevToolsCMD("standalone", "Runtime.evaluate", expression="1+1")
    if state != "standalone":
        command = harness.session.cache_cdp_cmd(
            "cached", "Runtime.evaluate", expression="1+1"
        )
        if state == "removed":
            harness.session.remove_cdp_cmd(command)
        else:
            harness.session.rename_cdp_cmd(command, "renamed")
    with pytest.raises(errors.DevToolsCMDNotFoundError):
        await harness.session.execute_cdp_cmd(command)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, {}, "", "secret", 0, False, (), b"[]"])
async def test_cookie_collection_shape_validation(
    harness: SessionHarness, value: Any
) -> None:
    """Reject non-list cookie collections with a typed package error.

    Args:
        harness: Session with a recording transport.
        value: Malformed collection returned by the driver.
    """
    harness.execute.return_value = {"value": value}
    with pytest.raises(errors.InvalidResponseError):
        await harness.session.cookies


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,arguments", [("load", ("https://example.invalid",)), ("refresh", ())]
)
@pytest.mark.parametrize("retry", [None, 0])
async def test_navigation_no_retry_keeps_one_attempt(
    harness: SessionHarness, method: str, arguments: tuple[str, ...], retry: int | None
) -> None:
    """Preserve one-attempt navigation for explicit zero and the default budget.

    Args:
        harness: Session with a recording transport.
        method: Navigation operation under test.
        arguments: Required URL argument, if any.
        retry: Equivalent no-retry settings supported by the public API.
    """
    await getattr(harness.session, method)(*arguments, retry=retry)
    assert harness.execute.await_count == 1
    harness.execute.reset_mock()
    harness.execute.side_effect = errors.WebDriverTimeoutError("native timeout")
    with pytest.raises(errors.WebDriverTimeoutError):
        await getattr(harness.session, method)(*arguments, retry=retry)
    assert harness.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,arguments", [("load", ("https://example.invalid",)), ("refresh", ())]
)
async def test_navigation_cancellation_during_backoff(
    harness: SessionHarness,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    arguments: tuple[str, ...],
) -> None:
    """Propagate cancellation during retry backoff without starting another attempt.

    Args:
        harness: Session with a recording transport.
        monkeypatch: Fixture restoring the deterministic cancellation boundary.
        method: Navigation method performing retry backoff.
        arguments: Required URL argument, if any.
    """
    pause = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(session_module, "sleep", pause)
    harness.execute.side_effect = errors.WebDriverTimeoutError("native timeout")
    with pytest.raises(asyncio.CancelledError):
        await getattr(harness.session, method)(*arguments, retry=2)
    pause.assert_awaited_once_with(0.1)
    assert harness.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["execute_script", "execute_async_script", "execute_cdp_cmd"]
)
@pytest.mark.parametrize("value", [None, True, 7, [], {}, object()])
async def test_execution_rejects_invalid_value_types(
    harness: SessionHarness, method: str, value: Any
) -> None:
    """Raise typed errors for invalid executable values before hashing or dispatch.

    Args:
        harness: Session with a recording transport.
        method: Script or CDP public execution method.
        value: Invalid scalar or unhashable value supplied by the caller.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await getattr(harness.session, method)(value)
    harness.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute_script", "execute_async_script"])
@pytest.mark.parametrize("key_kind", ["name", "object", "copy", "same-name"])
async def test_script_name_lookup_and_falsey_overrides(
    harness: SessionHarness, method: str, key_kind: str
) -> None:
    """Preserve name-based lookup and explicit falsey arguments without changing defaults.

    Args:
        harness: Session with a recording transport.
        method: Script execution endpoint.
        key_kind: Supported name-equivalent cache key representation.
    """
    script = harness.session.cache_script(
        "identity", "return arguments[0]", {"default": [1]}
    )
    keys = {
        "name": "identity",
        "object": script,
        "copy": script.copy(),
        "same-name": JavaScript("identity", "throw 'not used'", 999),
    }
    await getattr(harness.session, method)(keys[key_kind])
    body = harness.execute.await_args.kwargs["body"]
    assert body == {"script": "return arguments[0]", "args": [{"default": [1]}]}
    await getattr(harness.session, method)(keys[key_kind], 0, False, None)
    assert harness.execute.await_args.kwargs["body"] == {
        "script": "return arguments[0]",
        "args": [0, False, None],
    }
    assert script.args == [{"default": [1]}]


@pytest.mark.asyncio
@pytest.mark.parametrize("key_kind", ["name", "object", "copy", "same-name"])
async def test_cdp_name_lookup_and_falsey_overrides(
    harness: SessionHarness, key_kind: str
) -> None:
    """Preserve cached command lookup and falsey parameters without mutating defaults.

    Args:
        harness: Session with a recording transport.
        key_kind: Supported name-equivalent cache key representation.
    """
    command = harness.session.cache_cdp_cmd("network", "Network.enable", enabled=True)
    keys = {
        "name": "network",
        "object": command,
        "copy": command.copy(),
        "same-name": DevToolsCMD("network", "Unused.command", count=999),
    }
    await harness.session.execute_cdp_cmd(keys[key_kind])
    assert harness.execute.await_args.kwargs["body"] == {
        "cmd": "Network.enable",
        "params": {"enabled": True},
    }
    await harness.session.execute_cdp_cmd(keys[key_kind], enabled=False, count=0)
    assert harness.execute.await_args.kwargs["body"] == {
        "cmd": "Network.enable",
        "params": {"enabled": False, "count": 0},
    }
    assert command.kwargs == {"enabled": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [None, 1, "secret", [], {}, {"value": "secret"}, {1: "secret", "name": "key"}],
)
async def test_cookie_collection_rejects_invalid_members(
    harness: SessionHarness, value: Any
) -> None:
    """Reject malformed entries instead of returning a partially parsed collection.

    Args:
        harness: Session with a recording transport.
        value: Invalid member after one valid cookie in the response list.
    """
    harness.execute.return_value = {"value": [{"name": "valid", "value": ""}, value]}
    with pytest.raises(errors.InvalidResponseError):
        await harness.session.cookies


@pytest.mark.asyncio
async def test_cookie_collection_preserves_empty_order_and_metadata(
    harness: SessionHarness,
) -> None:
    """Preserve empty lists, response order and supported cookie data without mutation.

    Args:
        harness: Session with a recording transport.
    """
    harness.execute.return_value = {"value": []}
    assert await harness.session.cookies == []
    values = [
        {"name": "b", "value": "", "path": "/", "httpOnly": True},
        {"Name": "a", "value": "second", "vendorMetadata": {"test": True}},
    ]
    harness.execute.return_value = {"value": values}
    parsed = await harness.session.cookies
    assert [cookie.name for cookie in parsed] == ["b", "a"]
    assert [cookie.dict for cookie in parsed] == values


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["cookies", "get_cookie", "add_cookie"])
async def test_malformed_cookie_traceback_omits_values(
    harness: SessionHarness, method: str
) -> None:
    """Do not leak malformed cookie secrets through messages or constructor cause chains.

    Args:
        harness: Session with a recording transport.
        method: Cookie parser entry point sharing the safe construction boundary.
    """
    invalid = {"value": "private-cookie-canary-9d2a"}
    harness.execute.return_value = {
        "value": [invalid] if method == "cookies" else invalid
    }
    with pytest.raises(errors.InvalidResponseError) as failure:
        if method == "cookies":
            await harness.session.cookies
        elif method == "get_cookie":
            await harness.session.get_cookie("key")
        else:
            await harness.session.add_cookie(invalid)
    assert invalid["value"] not in "".join(format_exception(failure.value))
    if method == "add_cookie":
        harness.execute.assert_not_awaited()


def test_cookie_copy_and_name_validation() -> None:
    """Keep copied cookie names independent and validate explicit renaming."""
    original = Cookie(name="session", value="opaque", path="/")
    copied = original.copy()
    copied.name = "copied"
    assert original.name == "session"
    assert copied.data == {"name": "copied", "value": "opaque", "path": "/"}
    with pytest.raises(errors.InvalidArgumentError):
        copied.name = ""
    with pytest.raises(errors.InvalidArgumentError):
        Cookie(value="missing name")


def test_network_and_permission_copy_contracts() -> None:
    """Keep mutable network and permission copies independent of their originals."""
    original_network = Network(
        offline=False, latency=30, upload_throughput=100, download_throughput=200
    )
    copied_network = original_network.copy()
    copied_network.latency = 50
    assert original_network.latency == 30
    assert copied_network.dict == {
        "offline": False,
        "latency": 50,
        "upload_throughput": 100,
        "download_throughput": 200,
    }
    permission = Permission("geolocation", "prompt")
    copied_permission = permission.copy()
    copied_permission.state = "granted"
    assert permission.state == "prompt"
    assert copied_permission.dict == {"name": "geolocation", "state": "granted"}
    assert bool(original_network) and bool(permission)


@pytest.mark.asyncio
async def test_permission_collection_omits_unsupported_queries(
    harness: SessionHarness,
) -> None:
    """Return supported queried permissions and omit browser-unsupported ones.

    Args:
        harness: Session with a recording transport.
    """
    queried: list[str] = []

    async def permission_response(
        base_url: str, command: str, **options: Any
    ) -> dict[str, Any]:
        """Model geolocation support with all other permission names unsupported.

        Args:
            base_url: Session URL supplied by the implementation.
            command: WebDriver script command supplied by the implementation.
            **options: Script body and transport options.

        Returns:
            The permission state when the queried name is supported.

        Raises:
            UnknownCommandError: The simulated browser does not support this name.
        """
        assert base_url == "/session/offline"
        assert command == Command.W3C_EXECUTE_SCRIPT
        assert options["body"]["script"] == javascript.GET_PERMISSION
        name = options["body"]["args"][0]
        queried.append(name)
        if name == "geolocation":
            return {"value": {"state": "prompt"}}
        raise errors.UnknownCommandError("permission unavailable")

    harness.execute.side_effect = permission_response
    assert [permission.dict for permission in await harness.session.permissions] == [
        {"name": "geolocation", "state": "prompt"}
    ]
    assert len(queried) > 1
    assert queried == sorted(set(queried))


@pytest.mark.asyncio
async def test_general_wait_returns_value_and_propagates_cancellation(
    harness: SessionHarness,
) -> None:
    """Retain a successful condition result and propagate a cancelled condition.

    Args:
        harness: Session with a recording transport.
    """
    result = {"ready": True}
    ready = AsyncMock(return_value=result)
    assert await harness.session.wait_for(ready, timeout=0) is result
    ready.assert_awaited_once_with()
    cancelled = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await harness.session.wait_for(cancelled, timeout=0)
