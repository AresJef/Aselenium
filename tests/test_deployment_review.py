"""Exercise dispatch ownership, admission deadlines, and pre-command validation."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from aselenium import errors
from aselenium._wait import DEADLINE
from aselenium.actions import Actions
from aselenium.alert import Alert
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.connection import Connection
from aselenium.element import Element
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.session import FirefoxSession
from aselenium.manager.version import ChromiumVersion
from aselenium.safari.options import SafariOptions
from aselenium.safari.session import SafariSession
from aselenium.service import ChromiumBaseService
from aselenium.session import ChromiumBaseSession, Session
from aselenium.shadow import Shadow


@pytest.fixture
def session() -> Iterator[ChromiumBaseSession]:
    """Provide real session scheduling with a browser-free transport boundary.

    Yields:
        A started-shaped session whose HTTP request method is an async mock.
    """
    options = ChromeOptions()
    value = ChromiumBaseSession(options, SimpleNamespace(url="http://127.0.0.1:1"))
    value._id = "deployment-review"
    value._base_url = "/session/deployment-review"
    value._conn = Connection(SimpleNamespace(), 0.03)
    value._conn._request = AsyncMock(return_value={"value": None})
    try:
        yield value
    finally:
        options.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_inflight_actions_keep_their_batch_and_preserve_new_input(
    session: Session, outcome: str
) -> None:
    """Keep later queued keys separate even when an earlier dispatch fails.

    Args:
        session: Session providing the action builder's command boundary.
        outcome: Completion mode of the first in-flight action request.
    """
    entered = asyncio.Event()
    release = asyncio.Event()
    received: list[dict[str, Any]] = []

    async def dispatch(command: str, body: dict[str, Any]) -> dict[str, Any]:
        """Hold the first payload by reference across a scheduling point.

        Args:
            command: Expected W3C action command.
            body: Batch whose contents must remain stable during dispatch.

        Returns:
            Empty W3C acknowledgement for successful batches.

        Raises:
            errors.SessionClientError: The first batch simulates ambiguous failure.
        """
        assert command == Command.W3C_ACTIONS
        received.append(body)
        if len(received) == 1:
            entered.set()
            await release.wait()
            if outcome == "failure":
                raise errors.SessionClientError("ambiguous transport failure")
        return {"value": None}

    session.execute_command = dispatch
    chain = Actions(session).send_keys("a")
    first_batch = deepcopy([device for device in chain.actions.values() if device])
    pending = asyncio.create_task(chain.perform())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        chain.send_keys("b")
        if outcome == "cancelled":
            pending.cancel()
        release.set()
        if outcome == "success":
            await pending
        else:
            expected = (
                asyncio.CancelledError
                if outcome == "cancelled"
                else errors.SessionClientError
            )
            with pytest.raises(expected):
                await pending
        await chain.perform()
    finally:
        release.set()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)

    assert received[0] == {"actions": first_batch}
    keys = [
        tick["value"]
        for device in received[1]["actions"]
        if device["type"] == "key"
        for tick in device["actions"]
        if tick["type"] == "keyDown"
    ]
    assert keys == ["b"]


@pytest.mark.asyncio
async def test_overlapping_perform_calls_do_not_replay_queued_keys(
    session: Session,
) -> None:
    """Dispatch each batch at most once while preserving connection serialization.

    Args:
        session: Session using the actual connection ownership and wire locks.
    """
    received: list[dict[str, Any]] = []

    async def request(
        method: str, url: str, body: dict[str, Any], timeout: float | None
    ) -> dict[str, Any]:
        """Record serialized payloads and allow a second dispatch to queue.

        Args:
            method: HTTP method chosen by the connection.
            url: Expected action endpoint.
            body: Serialized action batch.
            timeout: Optional command timeout override.

        Returns:
            Empty W3C success envelope.
        """
        received.append(deepcopy(body))
        await asyncio.sleep(0)
        return {"value": None}

    session.connection._request = request
    chain = Actions(session).send_keys("a")
    await asyncio.gather(chain.perform(), chain.perform())
    assert len(received) == 2
    assert received[0]["actions"]
    assert received[1] == {"actions": []}


@pytest.mark.asyncio
async def test_reset_does_not_discard_input_added_during_remote_release(
    session: Session,
) -> None:
    """Reset the initial queue while retaining work added after reset begins.

    Args:
        session: Session whose remote release boundary appends new work.
    """
    chain = Actions(session).send_keys("discard")

    async def release(command: str) -> dict[str, Any]:
        """Append the next batch after remote release has begun.

        Args:
            command: Expected input-state release command.

        Returns:
            Empty W3C success acknowledgement.
        """
        assert command == Command.W3C_CLEAR_ACTIONS
        chain.send_keys("keep")
        return {"value": None}

    session.execute_command = release
    assert await chain.reset() is chain
    assert (
        "".join(
            tick["value"]
            for tick in chain.actions["key"].get("actions", [])
            if tick["type"] == "keyDown"
        )
        == "keep"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["transaction", "set_timeouts", "reset_network"])
async def test_transaction_admission_honors_a_finite_budget(
    session: Session, operation: str
) -> None:
    """Bound outer transaction admission before a multi-command method can send I/O.

    Args:
        session: Session with a short command budget and a held ownership lock.
        operation: Direct transaction or representative wrapped mutation to exercise.
    """
    connection = session.connection
    await connection._command_lock.acquire()

    async def mutate() -> None:
        """Enter the selected transaction without bypassing real lock admission."""
        if operation == "transaction":
            async with session.transaction():
                pytest.fail("Contended transaction must not enter")
        elif operation == "set_timeouts":
            await session.set_timeouts(implicit=0)
        else:
            assert isinstance(session, ChromiumBaseSession)
            await session.reset_network()

    try:
        with pytest.raises(errors.SessionTimeoutError):
            await asyncio.wait_for(mutate(), 0.3)
        connection._request.assert_not_awaited()
    finally:
        connection._command_lock.release()
    async with connection.transaction():
        assert connection._command_lock.locked()
    assert not connection._command_lock.locked()


@pytest.mark.asyncio
async def test_transaction_admission_respects_an_inherited_wait_deadline(
    session: Session,
) -> None:
    """Use an enclosing polling deadline instead of extending its budget.

    Args:
        session: Session whose ordinary command budget exceeds the inherited wait.
    """
    connection = session.connection
    connection._session_timeout = 10
    await connection._command_lock.acquire()
    token = DEADLINE.set(monotonic() + 0.02)
    try:
        with pytest.raises(errors.SessionTimeoutError):
            await asyncio.wait_for(session.set_timeouts(implicit=0), 0.3)
    finally:
        DEADLINE.reset(token)
        connection._command_lock.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [True, float("nan")])
@pytest.mark.parametrize(
    "operation",
    [
        "click",
        "clear",
        "send",
        "submit",
        "upload",
        "accept",
        "dismiss",
        "alert_send",
        "scroll_by",
        "scroll_to",
    ],
)
async def test_invalid_pause_is_rejected_before_browser_mutation(
    session: Session, tmp_path: Path, operation: str, pause: object
) -> None:
    """Reject a bad post-command delay before clicking, submitting, or sending data.

    Args:
        session: Session with a recording transport boundary.
        tmp_path: Directory for the upload fixture.
        operation: Mutating public API to invoke.
        pause: Invalid delay that must fail before command dispatch.
    """
    element = Element("input", session)
    alert = Alert(session)
    if operation in {"click", "clear", "submit"}:
        call = getattr(element, operation)(pause=pause)
    elif operation == "send":
        call = element.send("text", pause=pause)
    elif operation == "upload":
        fixture = tmp_path / "upload.txt"
        fixture.write_text("fixture", encoding="utf-8")
        call = element.upload(fixture, pause=pause)
    elif operation in {"accept", "dismiss"}:
        call = getattr(alert, operation)(pause=pause)
    elif operation == "alert_send":
        call = alert.send("text", pause=pause)
    else:
        call = getattr(session, operation)(pause=pause)

    with pytest.raises(errors.InvalidArgumentError):
        await call
    session.connection._request.assert_not_awaited()


def test_handle_representations_do_not_allocate_service_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep diagnostics passive before startup and after a service has stopped.

    Args:
        tmp_path: Directory containing an unlaunched driver executable fixture.
        monkeypatch: Prevent any actual socket allocation if diagnostics regress.
    """
    executable = tmp_path / "driver"
    executable.write_bytes(b"fixture")
    service = ChromiumBaseService(ChromiumVersion("120.0.1.2"), executable)
    allocate = Mock(return_value=12345)
    monkeypatch.setattr(service, "get_free_port", allocate)
    options = ChromeOptions()
    value = Session(options, service)
    value._id = "fixture"
    value._base_url = "/session/fixture"
    value._conn = Connection(SimpleNamespace(), 1)
    element = Element("element", value)
    shadow = Shadow("shadow", element)
    try:
        for handle in (value, element, shadow, Alert(value)):
            assert repr(handle)
            allocate.assert_not_called()
            assert service._port == -1
            assert service._url is None
    finally:
        options.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("browser", ["chrome", "firefox", "safari"])
async def test_vendor_state_updates_are_observed_in_their_own_transaction(
    session: Session, browser: str
) -> None:
    """Keep concurrent permission/context changes and their observations together.

    Args:
        session: Fixture supplying the real serialized connection.
        browser: Vendor-specific read/modify/write protocol to exercise.
    """
    options = FirefoxOptions() if browser == "firefox" else SafariOptions()
    connection = session.connection
    if browser == "firefox":
        value = FirefoxSession(options, SimpleNamespace())
    elif browser == "safari":
        value = SafariSession(options, SimpleNamespace())
    else:
        value = session
    value._conn = connection
    value._base_url = "/session/vendor"
    state: dict[str, Any] = {
        "permission": "prompt",
        "context": "content",
        "permissions": {"first": False, "second": False},
    }

    async def request(
        method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """Apply a mutation or capture remote state before yielding to another task.

        Args:
            method: Protocol method chosen by the connection.
            url: Vendor context, permission, or script endpoint.
            body: Mutation parameters or permission-query script.
            timeout: Optional command timeout override.

        Returns:
            Snapshot of the vendor-specific state at the time of this request.
        """
        if browser == "firefox":
            if method == "POST":
                state["context"] = body["context"]
            result = state["context"] if method == "GET" else None
        elif browser == "safari":
            if method == "POST":
                state["permissions"] = body["permissions"].copy()
            result = {"permissions": state["permissions"].copy()}
        else:
            if "descriptor" in body:
                state["permission"] = body["state"]
            result = {"state": state["permission"]}
        await asyncio.sleep(0)
        return {"value": result}

    connection._request = request
    try:
        if browser == "firefox":
            results = await asyncio.gather(
                value.set_context("chrome"), value.reset_context()
            )
            assert results == ["chrome", "content"]
        elif browser == "safari":
            await asyncio.gather(
                value.set_permission("first", True),
                value.set_permission("second", True),
            )
            assert state["permissions"] == {"first": True, "second": True}
        else:
            results = await asyncio.gather(
                value.set_permission("geolocation", "granted"),
                value.set_permission("geolocation", "denied"),
            )
            assert [permission.state for permission in results] == ["granted", "denied"]
    finally:
        options.close()


@pytest.mark.asyncio
async def test_transaction_admission_preserves_command_timeout_override(
    session: Session,
) -> None:
    """Allow a command-specific budget to exceed the shorter connection default.

    Args:
        session: Session with a temporarily held admission lock.
    """
    connection = session.connection
    connection._session_timeout = 0.001
    await connection._command_lock.acquire()
    release = asyncio.get_running_loop().call_later(
        0.02, connection._command_lock.release
    )
    try:
        await session.execute_command(Command.GET_TITLE, timeout=0.5)
        connection._request.assert_awaited_once()
    finally:
        release.cancel()
        if connection._command_lock.locked():
            connection._command_lock.release()


@pytest.mark.asyncio
async def test_cancelled_transaction_waiter_leaves_ownership_usable(
    session: Session,
) -> None:
    """Propagate cancellation during admission without orphaning a lock waiter.

    Args:
        session: Session with an independently held ownership lock.
    """
    connection = session.connection
    await connection._command_lock.acquire()
    task = asyncio.create_task(session.set_timeouts(implicit=0))
    try:
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        connection._request.assert_not_awaited()
    finally:
        connection._command_lock.release()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with session.transaction():
        assert connection._command_lock.locked()


@pytest.mark.asyncio
async def test_unrepresentable_pause_is_rejected_before_input(session: Session) -> None:
    """Classify oversized integers without leaking numeric conversion errors.

    Args:
        session: Session with a recording command boundary.
    """
    with pytest.raises(errors.InvalidArgumentError):
        await Element("input", session).click(pause=10**1000)
    session.connection._request.assert_not_awaited()
