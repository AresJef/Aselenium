"""Browser-free protocol, lifecycle, option and wait contracts."""

from __future__ import annotations

import asyncio
import base64
import json
from contextvars import Context
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aselenium import errors
from aselenium._profiles import claim_profile, release_profile
from aselenium._wait import poll
from aselenium.actions import Actions
from aselenium.chrome.options import ChromeOptions
from aselenium.command import Command
from aselenium.connection import Connection
from aselenium.element import Element
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.service import FirefoxService
from aselenium.firefox.utils import extract_firefox_addon_details
from aselenium.manager import ChromeDriverManager
from aselenium.manager.version import ChromiumVersion, GeckoVersion
from aselenium.options import Proxy, Timeouts
from aselenium.service import ChromiumBaseService
from aselenium.session import Session
from aselenium.shadow import Shadow


class Response:
    """Represent Response using the inherited implementation."""

    def __init__(
        self,
        payload: Any = None,
        status: int = 200,
        raw: Any = None,
        headers: Any = None,
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            payload: Fixture or parametrized payload input for this regression.
            status: Fixture or parametrized status input for this regression.
            raw: Fixture or parametrized raw input for this regression.
            headers: Fixture or parametrized headers input for this regression.
        """
        self.status = status
        self.payload = raw if raw is not None else json.dumps(payload).encode()
        self.headers = headers or {"Content-Type": "application/json"}

    async def __aenter__(self) -> Response:
        """Start the owned asynchronous context and return its managed value.

        Returns:
            The Response value produced by this operation.
        """
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Await owned cleanup when leaving the asynchronous context.

        Args:
            *args: Fixture or parametrized args input for this regression.
        """
        pass

    async def read(self) -> Any:
        """Read.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return self.payload


class Client:
    """Represent Client using the inherited implementation."""

    def __init__(self, *responses: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            *responses: Fixture or parametrized responses input for this regression.
        """
        self.responses = list(responses)
        self.calls = []

    def request(self, *args: Any, **kwargs: Any) -> Any:
        """Request.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        [],
        "text",
        {"error": "not a protocol error", "message": "JavaScript result"},
        {"status": 7, "value": "application data"},
    ],
)
async def test_success_values_are_preserved(value: Any) -> None:
    """Verify success values are preserved.

    Args:
        value: Fixture or parametrized value input for this regression.
    """
    conn = Connection(Client(Response({"value": value})), 5)
    assert (await conn.execute("/session/id", Command.GET_TITLE))["value"] == value


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 501, 502, 503, 504])
async def test_all_http_errors_map_without_attribute_errors(status: Any) -> None:
    """Verify all http errors map without attribute errors.

    Args:
        status: Fixture or parametrized status input for this regression.
    """
    conn = Connection(
        Client(
            Response(
                {"value": {"error": "invalid argument", "message": "invalid fixture"}},
                status,
            )
        ),
        5,
    )
    with pytest.raises(errors.InvalidArgumentError, match="invalid fixture"):
        await conn.execute("/session/id", Command.GET_TITLE)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], 7, "text", {}, {"other": 1}])
async def test_malformed_success_envelopes_fail(payload: Any) -> None:
    """Verify malformed success envelopes fail.

    Args:
        payload: Fixture or parametrized payload input for this regression.
    """
    conn = Connection(Client(Response(payload)), 5)
    with pytest.raises(errors.SessionDataError):
        await conn.execute("/session/id", Command.GET_TITLE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,status", [(b"not-json", 200), (b"<html>failed</html>", 503), (b"\xff", 200)]
)
async def test_non_json_responses_raise_typed_errors(raw: Any, status: Any) -> None:
    """Verify non json responses raise typed errors.

    Args:
        raw: Fixture or parametrized raw input for this regression.
        status: Fixture or parametrized status input for this regression.
    """
    conn = Connection(Client(Response(raw=raw, status=status)), 5)
    with pytest.raises((errors.SessionDataError, errors.WebDriverError)):
        await conn.execute("/session/id", Command.GET_TITLE)


@pytest.mark.asyncio
async def test_raw_png_response_is_not_a_w3c_screenshot() -> None:
    """Verify raw png response is not a w3c screenshot."""
    response = Response(raw=b"\x89PNG\r\n\x1a\n", headers={"Content-Type": "image/png"})
    with pytest.raises(errors.SessionDataError, match="Malformed JSON"):
        await Connection(Client(response), 5).execute("/session/id", Command.SCREENSHOT)


@pytest.mark.asyncio
async def test_empty_http_success_does_not_invent_json_wire_status() -> None:
    """Verify empty http success does not invent json wire status."""
    result = await Connection(Client(Response(status=204, raw=b"")), 5).execute(
        "/session/id", Command.QUIT
    )
    assert result == {"value": None}


@pytest.mark.asyncio
async def test_route_keys_are_encoded_and_body_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify route keys are encoded and body not logged.

    Args:
        caplog: Pytest fixture capturing log records emitted by the operation.
    """
    client = Client(Response({"value": None}))
    conn = Connection(client, 5)
    await conn.execute(
        "/session/id",
        Command.GET_ELEMENT_ATTRIBUTE,
        keys={"name": "a/b?# c"},
        body={"password": "secret"},
    )
    assert client.calls[0][0][1].endswith("a%2Fb%3F%23%20c")
    assert "secret" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,url", [("POST", "/next"), ("GET", "https://foreign.invalid/next")]
)
async def test_redirects_do_not_replay_mutations_or_cross_origins(
    method: Any, url: Any
) -> None:
    """Verify redirects do not replay mutations or cross origins.

    Args:
        method: Fixture or parametrized method input for this regression.
        url: Fixture or parametrized url input for this regression.
    """
    client = Client(Response(status=302, headers={"Location": url}))
    with pytest.raises(errors.SessionDataError):
        await Connection(client, 5)._request(method, "/session/id", {"secret": 1}, None)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_relative_get_redirect_has_a_finite_budget() -> None:
    """Verify relative get redirect has a finite budget."""
    client = Client(
        *[Response(status=302, headers={"Location": "/next%d" % i}) for i in range(5)]
    )
    with pytest.raises(errors.SessionDataError):
        await Connection(client, 5)._request("GET", "/start", None, None)
    assert len(client.calls) == 4


def session() -> Any:
    """Session.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    service = SimpleNamespace(
        _driver_version=None,
        _driver_location="fixture",
        url="http://127.0.0.1:1",
        stop=AsyncMock(),
    )
    value = Session(ChromeOptions(), service)
    value._id = "fixture"
    value._base_url = "/session/fixture"
    value._conn = SimpleNamespace(execute=AsyncMock(return_value={"value": None}))
    return value


@pytest.mark.asyncio
async def test_submit_is_awaited_and_errors_translate() -> None:
    """Verify submit is awaited and errors translate."""
    value = session()
    value._execute_script = AsyncMock()
    element = Element("element", value)
    await element.submit()
    value._execute_script.assert_awaited_once()
    value._execute_script.side_effect = errors.InvalidJavaScriptError("no form")
    with pytest.raises(errors.InvalidResponseError):
        await element.submit()


def test_timeouts_copy_equality_units_and_mutable_unhashability() -> None:
    """Verify timeouts copy equality units and mutable unhashability."""
    first = Timeouts(implicit=1, pageLoad=2, script=3)
    assert first == first.copy()
    assert first != Timeouts(implicit=2)
    with pytest.raises(TypeError):
        hash(first)


def test_shadow_hash_equality() -> None:
    """Verify shadow hash equality."""
    value = session()
    element = Element("element", value)
    a, b = Shadow("shadow", element), Shadow("shadow", element)
    assert a == b
    assert hash(a) == hash(b)
    assert a != Shadow("other", element)


@pytest.mark.parametrize("cls", [ChromeOptions, FirefoxOptions])
def test_options_snapshot_does_not_share_mutable_configuration(cls: type[Any]) -> None:
    """Verify options snapshot does not share mutable configuration.

    Args:
        cls: Patched class or instance used by this regression.
    """
    value = cls()
    value.add_arguments("--fixture")
    value.set_preferences(nested={"key": [1]})
    snapshot = value.snapshot()
    value.add_arguments("--later")
    value.preferences["nested"]["key"].append(2)
    assert "--later" not in snapshot.arguments
    assert snapshot.preferences["nested"]["key"] == [1]


@pytest.mark.parametrize("cls", [ChromeOptions, FirefoxOptions])
def test_profile_snapshots_own_different_physical_directories(
    tmp_path: Path, cls: type[Any]
) -> None:
    """Verify profile snapshots own different physical directories.

    Args:
        cls: Patched class or instance used by this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    source = tmp_path / "user"
    source.mkdir()
    (source / "sentinel").write_text("original")
    options = cls()
    if cls is ChromeOptions:
        options.set_profile(str(tmp_path), "user")
    else:
        options.set_profile(str(source))
    first, second = options.snapshot(), options.snapshot()
    assert first.profile.directory_temp != second.profile.directory_temp
    a, b = first.profile._temp_profile_dir, second.profile._temp_profile_dir
    Path(a, "sentinel").write_text("changed")
    first.close()
    assert Path(b, "sentinel").read_text() == "original"
    assert (source / "sentinel").read_text() == "original"
    second.close()
    options.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["session", "element", "shadow"])
async def test_zero_timeout_first_lookup_runs_once_without_sleep(target: Any) -> None:
    """Verify zero timeout first lookup runs once without sleep.

    Args:
        target: Fixture or parametrized target input for this regression.
    """
    value = session()
    value._get_timeouts = AsyncMock(return_value=Timeouts(implicit=0))
    element = Element("element", value)
    obj = {"session": value, "element": element, "shadow": Shadow("shadow", element)}[
        target
    ]
    result = object()
    obj._find_element_no_wait = AsyncMock(return_value=result)
    assert await obj.find_1st_element("#fixture") is result
    obj._find_element_no_wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_has_one_total_deadline_and_zero_means_one_check() -> None:
    """Verify poll has one total deadline and zero means one check."""
    check = AsyncMock(return_value=False)
    assert await poll(check, 0) is False
    check.assert_awaited_once()

    async def frozen() -> None:
        """Frozen."""
        await asyncio.sleep(10)

    before = asyncio.get_running_loop().time()
    assert await poll(frozen, 0.02) is None
    assert asyncio.get_running_loop().time() - before < 0.5


@pytest.mark.asyncio
async def test_frame_is_resolved_again_until_it_appears() -> None:
    """Verify frame is resolved again until it appears."""
    value = session()
    value._find_element_no_wait = AsyncMock(
        side_effect=[None, Element("new-frame", value)]
    )
    assert await value.switch_frame("#late-frame", timeout=0.5)
    assert value._find_element_no_wait.await_count == 2


@pytest.mark.asyncio
async def test_failed_service_teardown_retains_session_for_retry() -> None:
    """Verify failed service teardown retains session for retry."""
    value = session()
    service = value._service
    service.stop.side_effect = [errors.ServiceStopError("fixture"), None]
    with pytest.raises(errors.ServiceStopError):
        await value.quit()
    assert value._service is service
    await value.quit()
    assert value._service is None
    await value.quit()
    assert service.stop.await_count == 2


@pytest.mark.asyncio
async def test_print_invalid_orientation_is_actionable() -> None:
    """Verify print invalid orientation is actionable."""
    with pytest.raises(errors.InvalidArgumentError, match="orientation"):
        await session().print_page(orientation="diagonal")


def test_firefox_manifest_id_and_addon_mutation(tmp_path: Path) -> None:
    """Verify firefox manifest id and addon mutation.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    manifest = {
        "manifest_version": 2,
        "name": "fixture",
        "version": "1.0",
        "browser_specific_settings": {"gecko": {"id": "real@example"}},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    addon = extract_firefox_addon_details(str(tmp_path))
    assert addon.id == "real@example"
    addon.id = "server@example"
    assert addon.id == "server@example"
    assert addon.copy().id == "server@example"


@pytest.mark.asyncio
async def test_transaction_holds_related_commands_and_supports_wait_child_tasks() -> (
    None
):
    """Verify transaction holds related commands and supports wait child tasks."""
    conn = Connection(Client(*[Response({"value": "ok"}) for _ in range(3)]), 5)
    order = []

    async def other() -> None:
        """Other."""
        await conn.execute("/session/id", Command.GET_TITLE)
        order.append("other")

    async with conn.transaction():
        # Spawn unrelated work in an empty context to represent another caller.
        job = Context().run(asyncio.create_task, other())
        await poll(lambda: conn.execute("/session/id", Command.GET_TITLE), 1)
        await asyncio.sleep(0)
        order.append("owner")
    await job
    assert order == ["owner", "other"]


@pytest.mark.asyncio
async def test_actions_can_be_reused_without_replaying_previous_input() -> None:
    """Verify actions can be reused without replaying previous input."""
    value = session()
    actions = Actions(value)
    actions.send_keys("first")
    await actions.perform()
    actions.send_keys("second")
    await actions.perform()
    assert value._conn.execute.await_count == 2
    first, second = value._conn.execute.await_args_list
    assert first != second
    await actions.reset()


@pytest.mark.asyncio
async def test_invalid_actions_wait_fails_before_command() -> None:
    """Verify invalid actions wait fails before command."""
    value = session()
    with pytest.raises(errors.InvalidArgumentError):
        await Actions(value).perform(float("nan"))
    value._conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_screenshot_decoding_is_strict() -> None:
    """Verify screenshot decoding is strict."""
    value = session()
    value._conn.execute.return_value = {
        "value": base64.b64encode(b"PNG fixture").decode()
    }
    assert await value.take_screenshot() == b"PNG fixture"
    value._conn.execute.return_value = {"value": "not a valid base64 !!!"}
    with pytest.raises(errors.InvalidResponseError):
        await value.take_screenshot()


def test_explicit_shared_profile_is_not_claimed_twice(tmp_path: Path) -> None:
    """Verify explicit shared profile is not claimed twice.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    options = ChromeOptions()
    options.add_arguments("--user-data-dir=" + str(tmp_path))
    first, second = object(), object()
    claim_profile(options, first)
    try:
        with pytest.raises(errors.InvalidProfileError):
            claim_profile(options, second)
    finally:
        release_profile(first)
    claim_profile(options, second)
    release_profile(second)


def test_firefox_service_restart_regenerates_websocket_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify firefox service restart regenerates websocket port.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    driver = tmp_path / "driver"
    driver.touch()
    service = FirefoxService(GeckoVersion("0.37.1"), str(driver))
    ports = iter([10001, 10002, 10003, 10004])
    monkeypatch.setattr(service, "get_free_port", lambda: next(ports))
    first = service.port_args
    service._reset_port()
    second = service.port_args
    assert first != second
    assert service._args == []


@pytest.mark.asyncio
async def test_service_start_stop_and_failed_stop_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify service start stop and failed stop ownership.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    driver = tmp_path / "driver"
    driver.touch()
    service = ChromiumBaseService(ChromiumVersion("120.0.1.1"), str(driver))
    response = Response({"value": {"ready": True}})
    response.json = AsyncMock(return_value={"value": {"ready": True}})
    client = SimpleNamespace(
        closed=False,
        get=lambda *a, **kw: response,
        post=lambda *a, **kw: response,
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_start_process",
        lambda: setattr(service, "_process", SimpleNamespace(is_running=lambda: True)),
    )
    monkeypatch.setattr(
        service, "_start_session", lambda: setattr(service, "_session", client)
    )
    await service.start()
    await service.start()
    original = service._process

    def fail_stop() -> None:
        """Fail stop."""
        raise errors.ServiceProcessError("fixture process still alive")

    monkeypatch.setattr(service, "_stop_process", fail_stop)
    with pytest.raises(errors.ServiceProcessError):
        await service.stop()
    assert service._process is original
    monkeypatch.setattr(
        service, "_stop_process", lambda: setattr(service, "_process", None)
    )
    await service.stop()
    assert service._process is None


def test_all_webdriver_exception_subclasses_have_usable_message_constructors() -> None:
    """Verify all webdriver exception subclasses have usable message constructors."""
    for name in dir(errors):
        cls = getattr(errors, name)
        if isinstance(cls, type) and issubclass(cls, errors.WebDriverError):
            assert isinstance(str(cls("fixture")), str), name


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1])
def test_nonfinite_timeout_values_are_rejected(value: Any, tmp_path: Path) -> None:
    """Verify nonfinite timeout values are rejected.

    Args:
        value: Fixture or parametrized value input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    with pytest.raises(errors.InvalidOptionsError):
        Timeouts(implicit=value)
    with pytest.raises(errors.InvalidOptionsError):
        ChromeOptions().session_timeout = value
    with pytest.raises(errors.InvalidArgumentError):
        ChromeDriverManager(str(tmp_path), request_timeout=value)


def test_options_and_proxy_repr_do_not_expose_secrets() -> None:
    """Verify options and proxy repr do not expose secrets."""
    proxy = Proxy(
        socks_proxy="socks5://localhost:1080", socks_password="secret-fixture"
    )
    options = ChromeOptions()
    options.set_capability("password", "secret-fixture")
    assert "secret-fixture" not in repr(proxy)
    assert "secret-fixture" not in repr(options)
    with pytest.raises(TypeError):
        hash(options)
