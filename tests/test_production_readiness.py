"""Failure-path contracts added during the production-readiness review."""

from __future__ import annotations

import ast
import asyncio
import doctest
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from weakref import ref

import pytest

from aselenium import errors
from aselenium._wait import first_match
from aselenium.actions import Actions
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.element import ELEMENT_KEY, Element, ElementRect
from aselenium.firefox.options import FirefoxOptions
from aselenium.manager import ChromeDriverManager, _http
from aselenium.manager._cache import artifact_lock
from aselenium.session import (
    Cookie,
    DevToolsCMD,
    JavaScript,
    Session,
    Viewport,
    WindowRect,
)
from aselenium.shadow import Shadow
from aselenium.utils import KeyboardKeys, Rectangle, process_keys


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1, True, None])
def test_artifact_lock_rejects_invalid_timeout(tmp_path: Path, timeout: Any) -> None:
    """Reject invalid lock budgets before opening a lock file.

    Args:
        tmp_path: Isolated directory in which no lock file should be created.
        timeout: Non-finite, negative, boolean, or missing lock budget.
    """
    with pytest.raises(errors.DriverManagerError, match="timeout"):
        with artifact_lock(tmp_path, "a" * 64, timeout):
            pytest.fail("Invalid lock timeout was accepted")
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_download_budget_includes_admission_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expire a queued download without opening an HTTP client.

    Args:
        tmp_path: Parent for an isolated driver cache.
        monkeypatch: Fixture restoring the per-loop download gate after the test.
    """
    manager = ChromeDriverManager(directory=str(tmp_path), download_timeout=0.02)
    gate = asyncio.Semaphore(0)
    monkeypatch.setitem(_http._DOWNLOAD_GATES, asyncio.get_running_loop(), ref(gate))

    def forbidden_client() -> Any:
        """Fail if an expired queued download attempts to create a client.

        Returns:
            Never returns because client creation is forbidden in this test.
        """
        pytest.fail("Queued request created an HTTP client")

    with pytest.raises(errors.FileDownloadTimeoutError):
        await asyncio.wait_for(
            _http.request(
                manager, "https://vendor.invalid/file", "file", forbidden_client
            ),
            timeout=0.5,
        )
    assert gate._value == 0
    assert not gate._waiters


@pytest.mark.parametrize("value", [0, False, "", [], {}])
@pytest.mark.asyncio
async def test_first_match_preserves_non_none_falsey_values(value: Any) -> None:
    """Return a valid falsey lookup result instead of polling until timeout.

    Args:
        value: A valid match whose truth value is false.
    """
    calls = 0

    async def find(candidate: int) -> Any:
        """Return the supplied match and count the number of observations.

        Args:
            candidate: Candidate index supplied by first_match.

        Returns:
            The exact test value, even when its truth value is false.
        """
        nonlocal calls
        calls += 1
        return value

    assert await first_match([1], find, timeout=0.01) is value
    assert calls == 1


@pytest.mark.parametrize("rectangle_type", [ElementRect, Viewport, WindowRect])
def test_rectangle_copy_preserves_concrete_type(
    rectangle_type: type[Rectangle],
) -> None:
    """Keep copies consistent with their public return annotations.

    Args:
        rectangle_type: Public rectangle subclass whose copy must preserve its type.
    """
    original = rectangle_type(100, 50, 1, 2)
    copied = original.copy()
    assert type(copied) is rectangle_type
    assert copied is not original
    assert copied.dict == original.dict


def test_firefox_requires_explicit_insecure_certificate_opt_in() -> None:
    """Match Firefox's secure default to the documented cross-browser default."""
    options = FirefoxOptions()
    assert options.accept_insecure_certs is False
    options.accept_insecure_certs = True
    assert options.accept_insecure_certs is True


@pytest.mark.parametrize(
    "value",
    [
        Cookie(name="session", value="private-token"),
        DevToolsCMD("command", "Runtime.evaluate", expression="private-token"),
        JavaScript("script", "return 'private-token'", "private-token"),
    ],
)
def test_diagnostic_reprs_do_not_expose_browser_payloads(value: object) -> None:
    """Keep cookie values, script bodies, and command arguments out of repr output.

    Args:
        value: Browser value object containing a synthetic secret.
    """
    assert "private-token" not in repr(value)


def test_keyboard_constants_are_strings_and_instances_are_rejected() -> None:
    """Accept key constants but reject the namespace object as a key value."""
    assert process_keys("ab", KeyboardKeys.ENTER, 12) == [
        "a",
        "b",
        KeyboardKeys.ENTER,
        "1",
        "2",
    ]
    with pytest.raises(errors.InvalidArgumentError):
        process_keys(KeyboardKeys())


@pytest.fixture
def protocol_session() -> Session:
    """Construct an in-memory session whose transport records WebDriver commands.

    Returns:
        A session with synthetic IDs and no owned browser process or HTTP client.
    """
    service = SimpleNamespace(url="http://127.0.0.1:4444", running=True)
    session = Session(ChromeOptions(), service)
    session._id = "fixture"
    session._base_url = service.url + "/session/fixture"
    session._conn = SimpleNamespace(execute=AsyncMock(return_value={"value": None}))
    return session


def test_element_requires_started_session() -> None:
    """Report an unstarted session as a package error before binding an element."""
    session = Session(ChromeOptions(), SimpleNamespace(url="http://127.0.0.1:4444"))
    with pytest.raises(errors.InvalidSessionError, match="started"):
        Element("element", session)


@pytest.mark.parametrize("scope", ["session", "element", "shadow"])
@pytest.mark.parametrize(
    "payload", [None, {}, "invalid", [None], [{}], [{ELEMENT_KEY: 1}]]
)
@pytest.mark.asyncio
async def test_plural_lookup_rejects_malformed_references(
    protocol_session: Session, scope: str, payload: Any
) -> None:
    """Reject malformed plural responses consistently at each DOM lookup scope.

    Args:
        protocol_session: Session with a recording in-memory transport.
        scope: Public lookup object on which find_elements is invoked.
        payload: Invalid W3C response value returned by the transport.
    """
    element = Element("parent", protocol_session)
    target = {
        "session": protocol_session,
        "element": element,
        "shadow": Shadow("root", element),
    }[scope]
    protocol_session._conn.execute.return_value = {"value": payload}
    with pytest.raises(errors.InvalidResponseError):
        await target.find_elements(".item")


@pytest.mark.parametrize("scope", ["session", "element", "shadow"])
@pytest.mark.asyncio
async def test_plural_lookup_preserves_order_and_empty_results(
    protocol_session: Session, scope: str
) -> None:
    """Decode ordered element references and preserve an actual empty result.

    Args:
        protocol_session: Session with a recording in-memory transport.
        scope: Public lookup object whose plural response is decoded.
    """
    element = Element("parent", protocol_session)
    target = {
        "session": protocol_session,
        "element": element,
        "shadow": Shadow("root", element),
    }[scope]
    execute = protocol_session._conn.execute
    execute.return_value = {"value": [{ELEMENT_KEY: "second"}, {ELEMENT_KEY: "first"}]}
    assert [item.id for item in await target.find_elements(".item")] == [
        "second",
        "first",
    ]
    execute.return_value = {"value": []}
    assert await target.find_elements(".missing") == []


@pytest.mark.asyncio
async def test_requested_actions_example_executes_against_recording_transport(
    protocol_session: Session,
) -> None:
    """Execute the documented prompted example and inspect its actual wire payload.

    Args:
        protocol_session: Session with a recording in-memory transport.
    """
    execute = protocol_session._conn.execute
    execute.side_effect = [{"value": {ELEMENT_KEY: "inputbox"}}, {"value": None}]
    doc = inspect.getdoc(Actions.send_keys)
    examples = doctest.DocTestParser().get_examples(doc)
    namespace = {"session": protocol_session}
    for example in examples:
        code = compile(
            example.source,
            "Actions.send_keys:Example",
            "exec",
            ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
        pending = eval(code, namespace)
        if inspect.isawaitable(pending):
            await pending
    assert execute.await_count == 2
    call = execute.await_args
    assert call.args[1] == Command.W3C_ACTIONS
    actions = call.kwargs["body"]["actions"]
    pointer = next(action for action in actions if action["type"] == "pointer")
    keyboard = next(action for action in actions if action["type"] == "key")
    assert pointer["actions"][0]["origin"] == {ELEMENT_KEY: "inputbox"}
    assert (
        "".join(
            action["value"]
            for action in keyboard["actions"]
            if action["type"] == "keyDown"
        )
        == "Hello world!" + KeyboardKeys.ENTER
    )


@pytest.mark.asyncio
async def test_action_failure_clears_queue_and_repr_redacts_input(
    protocol_session: Session,
) -> None:
    """Prevent accidental replay or diagnostic exposure after a failed dispatch.

    Args:
        protocol_session: Session with a recording in-memory transport.
    """
    actions = protocol_session.actions().send_keys("private-token")
    assert "private-token" not in repr(actions)
    protocol_session._conn.execute.side_effect = errors.MoveTargetOutOfBoundsError(
        "fixture"
    )
    with pytest.raises(errors.MoveTargetOutOfBoundsError):
        await actions.perform()
    assert all(not value for value in actions.actions.values())
