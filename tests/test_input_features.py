"""Offline pointer, keyboard, wheel, alert, and nested-value behavioral contracts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aselenium import actions as actions_module
from aselenium import alert as alert_module
from aselenium import errors
from aselenium.actions import Actions
from aselenium.alert import Alert
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.element import ELEMENT_KEY, Element
from aselenium.session import Session
from aselenium.shadow import SHADOWROOT_KEY, Shadow
from aselenium.utils import KeyboardKeys, MouseButtons
from aselenium.valuewrap import wrap_value


@pytest.fixture
def input_session() -> Session:
    """Create a session with synthetic IDs and a recording command boundary.

    Returns:
        A started-shaped session without a real driver process or HTTP connection.
    """
    session = Session(ChromeOptions(), SimpleNamespace(url="http://127.0.0.1:1"))
    session._id = "input-session"
    session._base_url = "/session/input-session"
    session._conn = SimpleNamespace(execute=AsyncMock(return_value={"value": None}))
    session.execute_command = AsyncMock(return_value={"value": None})
    return session


def device_actions(chain: Actions, device: str) -> list[dict[str, Any]]:
    """Read the pending action ticks for one W3C input device.

    Args:
        chain: Builder containing pointer, keyboard, and wheel queues.
        device: One of pointer, key, or wheel.

    Returns:
        The pending ticks, or an empty list before that device is initialized.
    """
    return chain.actions[device].get("actions", [])


@pytest.mark.parametrize("pointer", ["mouse", "pen", "touch"])
def test_pointer_origins_and_default_duration(
    input_session: Session, pointer: str
) -> None:
    """Preserve pointer identity and distinguish viewport, relative, and element origins.

    Args:
        input_session: Browser-free session used to create an element handle.
        pointer: Supported W3C pointer type.
    """
    element = Element("a/b", input_session)
    chain = Actions(input_session, pointer=pointer, duration=0.125)
    assert chain.move_to(x=8, y=12) is chain
    assert chain.move_by(x=-3, y=7) is chain
    assert chain.move_to(element, x=2, y=-1) is chain
    assert chain.actions["pointer"]["parameters"] == {"pointerType": pointer}
    assert device_actions(chain, "pointer") == [
        {"type": "pointerMove", "duration": 125, "x": 8, "y": 12, "origin": "viewport"},
        {"type": "pointerMove", "duration": 125, "x": -3, "y": 7, "origin": "pointer"},
        {
            "type": "pointerMove",
            "duration": 125,
            "x": 2,
            "y": -1,
            "origin": {ELEMENT_KEY: "a/b"},
        },
    ]
    assert device_actions(chain, "key") == [{"type": "pause", "duration": 0}] * 3
    assert device_actions(chain, "wheel") == [{"type": "pause", "duration": 0}] * 3


@pytest.mark.parametrize(
    "button",
    [
        MouseButtons.LEFT,
        MouseButtons.MIDDLE,
        MouseButtons.RIGHT,
        MouseButtons.BACK,
        MouseButtons.FORWARD,
    ],
)
@pytest.mark.parametrize(
    "hold,double,types",
    [
        (False, False, ["pointerDown", "pointerUp"]),
        (False, True, ["pointerDown", "pointerUp", "pointerDown", "pointerUp"]),
        (True, False, ["pointerDown"]),
        (True, True, ["pointerDown"]),
    ],
)
def test_click_variants_and_release(
    input_session: Session, button: int, hold: bool, double: bool, types: list[str]
) -> None:
    """Build single, double, and held clicks with explicit matching releases.

    Args:
        input_session: Browser-free session owning the builder.
        button: W3C button code, including back/forward auxiliary buttons.
        hold: Whether the click leaves the button pressed.
        double: Whether an unheld click repeats the down/up pair.
        types: Independently specified event order for this variant.
    """
    chain = Actions(input_session)
    assert chain.click(button, hold, double) is chain
    assert device_actions(chain, "pointer") == [
        {"type": kind, "duration": 0, "button": button} for kind in types
    ]
    assert chain.release(button) is chain
    assert device_actions(chain, "pointer")[-1] == {
        "type": "pointerUp",
        "duration": 0,
        "button": button,
    }


@pytest.mark.parametrize("use_elements", [False, True])
def test_drag_and_drop_preserves_both_endpoints(
    input_session: Session, use_elements: bool
) -> None:
    """Move, hold, move, and release without confusing the drag/drop offsets.

    Args:
        input_session: Session used for optional source and destination handles.
        use_elements: Whether coordinates are relative to elements or the viewport.
    """
    source = Element("source", input_session) if use_elements else None
    target = Element("target", input_session) if use_elements else None
    chain = Actions(input_session).drag_and_drop(source, 1, 2, target, 30, 40)
    ticks = device_actions(chain, "pointer")
    assert [tick["type"] for tick in ticks] == [
        "pointerMove",
        "pointerDown",
        "pointerMove",
        "pointerUp",
    ]
    assert (ticks[0]["x"], ticks[0]["y"], ticks[2]["x"], ticks[2]["y"]) == (
        1,
        2,
        30,
        40,
    )
    assert ticks[0]["origin"] == (
        {ELEMENT_KEY: "source"} if use_elements else "viewport"
    )
    assert ticks[2]["origin"] == (
        {ELEMENT_KEY: "target"} if use_elements else "viewport"
    )


def test_keyboard_unicode_chords_and_tick_alignment(input_session: Session) -> None:
    """Keep individual text strokes and held modifier chords in the correct order.

    Args:
        input_session: Browser-free session owning the action queues.
    """
    chain = Actions(input_session)
    assert chain.key_down(KeyboardKeys.SHIFT).key_up(KeyboardKeys.SHIFT) is chain
    assert chain.send_keys("中🙂", KeyboardKeys.ENTER) is chain
    assert chain.send_key_combo(KeyboardKeys.CONTROL, "a") is chain
    actual = [(tick["type"], tick["value"]) for tick in device_actions(chain, "key")]
    assert actual == [
        ("keyDown", KeyboardKeys.SHIFT),
        ("keyUp", KeyboardKeys.SHIFT),
        ("keyDown", "中"),
        ("keyUp", "中"),
        ("keyDown", "🙂"),
        ("keyUp", "🙂"),
        ("keyDown", KeyboardKeys.ENTER),
        ("keyUp", KeyboardKeys.ENTER),
        ("keyDown", KeyboardKeys.CONTROL),
        ("keyDown", "a"),
        ("keyUp", "a"),
        ("keyUp", KeyboardKeys.CONTROL),
    ]
    assert len(device_actions(chain, "pointer")) == len(actual)
    assert len(device_actions(chain, "wheel")) == len(actual)


def test_wheel_origins_and_synchronized_pause(input_session: Session) -> None:
    """Serialize wheel deltas and align pauses across all three input devices.

    Args:
        input_session: Session providing a wheel-origin element handle.
    """
    target = Element("wheel", input_session)
    chain = Actions(input_session)
    assert (
        chain.scroll_to(target, x=10, y=-20).scroll_by(x=-1, y=2).pause(0.025) is chain
    )
    ticks = device_actions(chain, "wheel")
    assert ticks[:2] == [
        {
            "type": "scroll",
            "x": 0,
            "y": 0,
            "deltaX": 10,
            "deltaY": -20,
            "duration": 0,
            "origin": {ELEMENT_KEY: "wheel"},
        },
        {
            "type": "scroll",
            "x": 0,
            "y": 0,
            "deltaX": -1,
            "deltaY": 2,
            "duration": 0,
            "origin": "viewport",
        },
    ]
    for device in ("pointer", "key", "wheel"):
        assert device_actions(chain, device)[-1] == {"type": "pause", "duration": 25}
    with pytest.raises(errors.InvalidArgumentError):
        Actions(input_session).scroll_to(None)


@pytest.mark.asyncio
async def test_empty_perform_reset_and_post_dispatch_delay(
    input_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dispatch once, clear queues, and delay only after a successful response.

    Args:
        input_session: Session with a recording execute_command boundary.
        monkeypatch: Fixture restoring the asynchronous sleep callback.
    """
    sleep = AsyncMock()
    monkeypatch.setattr(actions_module, "sleep", sleep)
    chain = Actions(input_session)
    await chain.perform()
    input_session.execute_command.assert_awaited_once_with(
        Command.W3C_ACTIONS, {"actions": []}
    )
    sleep.assert_not_awaited()
    chain.click().send_keys("a")
    expected = deepcopy([value for value in chain.actions.values() if value])
    await chain.perform(explicit_wait=0.25)
    input_session.execute_command.assert_awaited_with(
        Command.W3C_ACTIONS, {"actions": expected}
    )
    sleep.assert_awaited_once_with(0.25)
    assert all(not value for value in chain.actions.values())
    chain.click()
    assert await chain.reset() is chain
    input_session.execute_command.assert_awaited_with(Command.W3C_CLEAR_ACTIONS)
    assert all(not value for value in chain.actions.values())


@pytest.mark.asyncio
async def test_cancelled_action_dispatch_does_not_replay(
    input_session: Session,
) -> None:
    """Propagate cancellation and clear local input queues even during dispatch.

    Args:
        input_session: Session whose command boundary reports cancellation.
    """
    chain = Actions(input_session).send_keys("secret")
    input_session.execute_command.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await chain.perform()
    assert all(not value for value in chain.actions.values())
    assert "secret" not in repr(chain)


@pytest.mark.parametrize("pointer", ["trackball", "", None])
def test_invalid_pointer_type_is_rejected(input_session: Session, pointer: Any) -> None:
    """Reject unsupported device types before a queue can be dispatched.

    Args:
        input_session: Session that should receive no commands.
        pointer: Invalid W3C pointer type.
    """
    with pytest.raises(errors.InvalidArgumentError):
        Actions(input_session, pointer=pointer)
    input_session.execute_command.assert_not_called()


@pytest.mark.parametrize("command", ["accept", "dismiss", "send"])
@pytest.mark.asyncio
async def test_alert_commands_and_optional_pause(
    input_session: Session, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """Send independent prompt commands with the documented post-command delay.

    Args:
        input_session: Session with an observable command boundary.
        monkeypatch: Fixture replacing real sleeping with a recording awaitable.
        command: Alert operation to exercise.
    """
    sleep = AsyncMock()
    monkeypatch.setattr(alert_module, "sleep", sleep)
    alert = Alert(input_session)
    if command == "send":
        await alert.send("one", "二", sep="/", pause=0.1)
        input_session.execute_command.assert_awaited_once_with(
            Command.W3C_SET_ALERT_VALUE, body={"text": "one/二", "value": ["one", "二"]}
        )
    else:
        await getattr(alert, command)(pause=0.1)
        input_session.execute_command.assert_awaited_once_with(
            Command.W3C_ACCEPT_ALERT
            if command == "accept"
            else Command.W3C_DISMISS_ALERT
        )
    sleep.assert_awaited_once_with(0.1)


@pytest.mark.asyncio
async def test_alert_text_absence_malformed_and_protocol_errors(
    input_session: Session,
) -> None:
    """Decode alert text, distinguish unsupported operations, and propagate failures.

    Args:
        input_session: Session returning controlled text/error responses.
    """
    alert = Alert(input_session)
    input_session.execute_command.return_value = {"value": "prompt"}
    assert await alert.text == "prompt"
    input_session.execute_command.assert_awaited_once_with(Command.W3C_GET_ALERT_TEXT)
    input_session.execute_command.return_value = {}
    with pytest.raises(errors.InvalidResponseError):
        await alert.text
    input_session.execute_command.side_effect = errors.InvalidMethodError("unsupported")
    assert await alert.text is None
    failure = errors.SessionTimeoutError("fixture")
    input_session.execute_command.side_effect = failure
    with pytest.raises(errors.SessionTimeoutError) as caught:
        await alert.text
    assert caught.value is failure


@pytest.mark.asyncio
async def test_alert_pause_none_invalid_and_cancellation(
    input_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid sleeping for None, wrap ordinary sleep failures, and preserve cancellation.

    Args:
        input_session: Session owning the alert.
        monkeypatch: Fixture controlling the sleep boundary without real delay.
    """
    sleep = AsyncMock()
    monkeypatch.setattr(alert_module, "sleep", sleep)
    alert = Alert(input_session)
    await alert.pause(None)
    sleep.assert_not_awaited()
    cause = TypeError("invalid duration")
    sleep.side_effect = cause
    with pytest.raises(errors.InvalidArgumentError) as caught:
        await alert.pause("bad")
    assert caught.value.__cause__ is cause
    sleep.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await alert.pause(1)


def test_alert_identity_and_nested_handle_encoding(input_session: Session) -> None:
    """Compare alerts by session and encode nested handles without mutating inputs.

    Args:
        input_session: Session supplying alert, element, and shadow-root handles.
    """
    first, second = Alert(input_session), Alert(input_session)
    assert first == second and hash(first) == hash(second)
    assert first != object()
    assert "input-session" in repr(first)
    element = Element("element", input_session)
    shadow = Shadow("root", element)
    source = {"items": (element, [shadow, None, 0, False, "text"])}
    encoded = wrap_value(source)
    assert encoded == {
        "items": [
            {ELEMENT_KEY: "element"},
            [{SHADOWROOT_KEY: "root"}, None, 0, False, "text"],
        ]
    }
    assert source["items"][0] is element
    assert source["items"][1][0] is shadow
    assert encoded is not source
