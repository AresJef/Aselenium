"""Reproduce public session state races and reject malformed DOM evidence offline."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aselenium import _wait as wait_module
from aselenium import errors
from aselenium.chrome.options import ChromeOptions
from aselenium.connection import Connection
from aselenium.element import ELEMENT_KEY, Element
from aselenium.options import Timeouts
from aselenium.session import ChromiumBaseSession, Session, Window
from aselenium.shadow import SHADOWROOT_KEY, Shadow
from aselenium.valuewrap import wrap_value


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide a started session with real command ownership but no network client.

    Yields:
        Session whose per-test protocol boundary must be explicitly supplied.
    """
    options = ChromeOptions()
    value = ChromiumBaseSession(options, SimpleNamespace(url="http://127.0.0.1:4444"))
    value._id = "review"
    value._base_url = "/session/review"
    value._conn = Connection(SimpleNamespace(), 2)
    try:
        yield value
    finally:
        options.close()


@pytest.mark.asyncio
async def test_concurrent_timeout_updates_preserve_unrelated_fields(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove concurrent partial updates cannot overwrite each other's timeout fields.

    Args:
        session: Session using the real serialized command connection.
        monkeypatch: Replace only its network-request boundary.
    """
    state = {"implicit": 0, "pageLoad": 10000, "script": 3000}
    session._timeouts = Timeouts(**state, unit="ms")

    async def request(
        method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """Simulate remote timeout state while retaining real command scheduling.

        Args:
            method: HTTP method selected by the real connection.
            url: Serialized endpoint, required to address timeout state.
            body: Timeout mutation, or None for a read.
            timeout: Transport override unused by the immediate fixture.

        Returns:
            A W3C timeout observation or mutation acknowledgement.
        """
        assert url.endswith("/timeouts")
        if method == "POST":
            assert body is not None
            state.update(body)
        response = {"value": state.copy() if method == "GET" else None}
        await asyncio.sleep(0)
        return response

    monkeypatch.setattr(session.connection, "_request", request)
    await asyncio.gather(
        session.set_timeouts(implicit=2), session.set_timeouts(script=7)
    )
    assert state == {"implicit": 2000, "pageLoad": 10000, "script": 7000}
    assert (await session.timeouts).dict == state


@pytest.mark.asyncio
async def test_cancelled_timeout_mutation_invalidates_cached_snapshot(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh unknown remote state before the next partial timeout update.

    Args:
        session: Session with a cached initial timeout configuration.
        monkeypatch: Supply a mutation that completes remotely before cancellation.
    """
    state = {"implicit": 0, "pageLoad": 10000, "script": 3000}
    session._timeouts = Timeouts(**state, unit="ms")
    written = asyncio.Event()
    block_once = True

    async def request(
        method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """Acknowledge the first mutation only after the caller has cancelled it.

        Args:
            method: Wire method chosen by the real connection.
            url: Timeout endpoint used by this fixture.
            body: Requested timeout values.
            timeout: Unused fixture transport override.

        Returns:
            Remote timeout state for reads and an empty mutation acknowledgement.
        """
        nonlocal block_once
        assert url.endswith("/timeouts")
        if method == "POST":
            assert body is not None
            state.update(body)
            if block_once:
                block_once = False
                written.set()
                await asyncio.Future()
        return {"value": state.copy() if method == "GET" else None}

    monkeypatch.setattr(session.connection, "_request", request)
    mutation = asyncio.create_task(session.set_timeouts(implicit=2))
    await asyncio.wait_for(written.wait(), 1)
    mutation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    await asyncio.wait_for(session.set_timeouts(script=7), 1)
    assert state == {"implicit": 2000, "pageLoad": 10000, "script": 7000}


@pytest.mark.asyncio
async def test_concurrent_rectangle_updates_preserve_unrelated_dimensions(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep width and height updates atomic despite scheduling at every command.

    Args:
        session: Session using the real serialized command connection.
        monkeypatch: Replace only its network-request boundary.
    """
    state = {"width": 800, "height": 600, "x": 10, "y": 20}

    async def request(
        method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """Read and update a remote window rectangle with a scheduling opportunity.

        Args:
            method: Selected GET or POST method.
            url: Expected window rectangle endpoint.
            body: Requested rectangle update.
            timeout: Unused fixture transport override.

        Returns:
            The independently observed remote rectangle.
        """
        assert url.endswith("/window/rect")
        if method == "POST":
            assert body is not None
            state.update(body)
        response = {"value": state.copy()}
        await asyncio.sleep(0)
        return response

    monkeypatch.setattr(session.connection, "_request", request)
    await asyncio.gather(
        session.set_window_rect(width=1000), session.set_window_rect(height=900)
    )
    assert state == {"width": 1000, "height": 900, "x": 10, "y": 20}


@pytest.mark.asyncio
async def test_concurrent_network_updates_preserve_other_conditions(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Serialize vendor network read/modify/write just like session timeout updates.

    Args:
        session: Real Chromium session with command ownership enabled.
        monkeypatch: Provide independently maintained remote network settings.
    """
    assert isinstance(session, ChromiumBaseSession)
    state = {
        "offline": False,
        "latency": 0,
        "upload_throughput": -1,
        "download_throughput": -1,
    }

    async def request(
        method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """Apply a network update and allow competing tasks between wire commands.

        Args:
            method: Requested GET or POST method.
            url: Vendor network-conditions endpoint.
            body: Optional network condition update.
            timeout: Unused fixture transport override.

        Returns:
            Remote settings before the next competing wire command runs.
        """
        assert url.endswith("/network_conditions")
        if method == "POST":
            assert body is not None
            state.update(body["network_conditions"])
        response = {"value": state.copy() if method == "GET" else None}
        await asyncio.sleep(0)
        return response

    monkeypatch.setattr(session.connection, "_request", request)
    await asyncio.gather(
        session.set_network(latency=10), session.set_network(download_throughput=1000)
    )
    assert state == {
        "offline": False,
        "latency": 10,
        "upload_throughput": -1,
        "download_throughput": 1000,
    }


@pytest.mark.asyncio
async def test_new_window_name_reservation_is_atomic(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a competing duplicate name before creating an untracked browser window.

    Args:
        session: Real session whose window-name cache starts empty.
        monkeypatch: Supply only controlled new-window responses.
    """
    created: list[str] = []

    async def request(
        method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """Record each newly created remote handle and yield before its cache update.

        Args:
            method: Required POST command.
            url: Expected new-window endpoint.
            body: Requested window type.
            timeout: Unused fixture transport override.

        Returns:
            One newly created window with a unique remote handle.
        """
        assert method == "POST" and url.endswith("/window/new")
        assert body == {"type": "tab"}
        created.append(f"handle-{len(created) + 1}")
        response = {"value": {"handle": created[-1], "type": "tab"}}
        await asyncio.sleep(0)
        return response

    monkeypatch.setattr(session.connection, "_request", request)
    results = await asyncio.gather(
        session.new_window("shared", switch=False),
        session.new_window("shared", switch=False),
        return_exceptions=True,
    )
    assert sum(isinstance(result, Window) for result in results) == 1
    assert (
        sum(isinstance(result, errors.InvalidArgumentError) for result in results) == 1
    )
    assert created == ["handle-1"]
    assert set(session._window_by_name) == {"shared"}
    assert set(session._window_by_handle) == {"handle-1"}


@pytest.mark.asyncio
async def test_close_window_cannot_close_a_competing_tasks_window(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not permit a concurrent switch between active-handle discovery and close.

    Args:
        session: Real session and connection with two cached windows.
        monkeypatch: Supply controlled remote window state without a browser.
    """
    session._cache_window("alpha", "alpha")
    session._cache_window("beta", "beta")
    active = "alpha"
    handles = ["alpha", "beta"]
    closed: list[str] = []

    async def request(
        method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """Model current-window mutation and record the exact window actually closed.

        Args:
            method: Selected wire method.
            url: Window or window-handles endpoint.
            body: Optional target window handle.
            timeout: Unused fixture transport override.

        Returns:
            The actual controlled window state, after yielding to a competitor.
        """
        nonlocal active
        if url.endswith("/window/handles"):
            value: Any = handles.copy()
        elif method == "GET":
            value = active
        elif method == "DELETE":
            closed.append(active)
            handles.remove(active)
            value = handles.copy()
        else:
            assert body is not None and body["handle"] in handles
            active = body["handle"]
            value = None
        await asyncio.sleep(0)
        return {"value": value}

    monkeypatch.setattr(session.connection, "_request", request)
    await asyncio.gather(session.close_window(), session.switch_window("beta"))
    assert closed == ["alpha"]
    assert handles == ["beta"]
    assert active == "beta"
    assert set(session._window_by_handle) == {"beta"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [None, "alpha", 1, {}, [None], ["alpha", {}], ["alpha", ""]]
)
async def test_malformed_handle_collection_cannot_mutate_window_cache(
    session: Session, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    """Validate an entire handle collection before deleting or inserting cache entries.

    Args:
        session: Real session containing a known valid cached window.
        monkeypatch: Supply only a malformed wire response.
        value: Invalid collection or invalid member supplied by a broken driver.
    """
    original = session._cache_window("original", "named")
    monkeypatch.setattr(
        session.connection, "_request", AsyncMock(return_value={"value": value})
    )
    with pytest.raises(errors.InvalidResponseError):
        await session.windows
    assert session._window_by_handle == {"original": original}
    assert session._window_by_name == {"named": original}


@pytest.mark.asyncio
@pytest.mark.parametrize("attribute", ["enabled", "selected"])
@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
async def test_boolean_dom_observations_reject_non_boolean_values(
    session: Session, monkeypatch: pytest.MonkeyPatch, attribute: str, value: object
) -> None:
    """A truthy malformed payload must not make a wait report enabled or selected.

    Args:
        session: Parent session for the actual element under test.
        monkeypatch: Supply an invalid scalar observation at the wire boundary.
        attribute: Public boolean DOM state.
        value: Non-boolean remote value to reject without coercion.
    """
    monkeypatch.setattr(
        session.connection, "_request", AsyncMock(return_value={"value": value})
    )
    with pytest.raises(errors.InvalidResponseError):
        await getattr(Element("target", session), attribute)


@pytest.mark.asyncio
async def test_poll_preserves_native_script_timeout_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a typed script failure distinct from the polling deadline expiring.

    Args:
        monkeypatch: Advance only the deterministic monotonic test clock.
    """
    clock = [0.0]
    failure = errors.JavaScriptTimeoutError("native script timeout")
    monkeypatch.setattr(wait_module, "monotonic", lambda: clock[0])

    async def condition() -> bool:
        """Report a native script failure when the poll budget is also exhausted.

        Returns:
            Never returns because the native failure must propagate.
        """
        clock[0] = 2.0
        raise failure

    with pytest.raises(errors.JavaScriptTimeoutError) as caught:
        await wait_module.poll(condition, timeout=1)
    assert caught.value is failure
    assert wait_module.DEADLINE.get() is None


class CustomElement(Element):
    """Represent an application-specific extension of the public element handle."""


class CustomShadow(Shadow):
    """Represent an application-specific extension of the public shadow handle."""


class CustomList(list[Any]):
    """Model a caller-owned list subclass containing nested command arguments."""


class CustomDict(dict[str, Any]):
    """Model a caller-owned dictionary subclass containing nested command arguments."""


def test_extended_handles_and_containers_are_encoded_recursively(
    session: Session,
) -> None:
    """Preserve public subclass semantics when serializing browser references.

    Args:
        session: Session owning the element and shadow-root references.
    """
    element = CustomElement("child", session)
    shadow = CustomShadow("root", element)
    value = CustomDict(targets=CustomList([element, {"root": shadow}]))
    actual = wrap_value(value)
    assert actual == {
        "targets": [{ELEMENT_KEY: "child"}, {"root": {SHADOWROOT_KEY: "root"}}]
    }
    assert actual is not value
    assert actual["targets"] is not value["targets"]
    assert value["targets"][0] is element
