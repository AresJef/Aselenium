"""Real aiohttp transport contracts restricted to one ephemeral loopback server.

The ordinary suite's external-network guards remain in force. This fixture
restores client and socket operations only for its exact 127.0.0.1 address and
assigned port; redirects to any other origin cannot reach the network.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web

from aselenium import errors
from aselenium.command import Command
from aselenium.connection import Connection

pytestmark = pytest.mark.loopback

_CLIENT_REQUEST = aiohttp.ClientSession._request
_SOCKET_CONNECT = socket.socket.connect
_SOCKET_CONNECT_EX = socket.socket.connect_ex


class LoopbackOnlyError(AssertionError):
    """A transport test attempted to leave its specifically permitted endpoint."""


@dataclass
class Reply:
    """Describe one synthetic driver's actual HTTP response on the local wire.

    Attributes:
        status: HTTP response status.
        body: Raw response bytes, including deliberately malformed payloads.
        headers: Response headers, such as a redirect Location.
        delay: Delay before headers, used to test request deadlines.
        stream_delay: Delay after headers, used to test response-body deadlines.
        disconnect: Abort the TCP connection without returning a response.
    """

    status: int = 200
    body: bytes = b'{"value":null}'
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0
    stream_delay: float = 0
    disconnect: bool = False


@dataclass
class WireRequest:
    """Record what the local HTTP server actually received.

    Attributes:
        method: Received HTTP method.
        path: Raw URL path and query, preserving percent-encoded route keys.
        body: Received request body bytes.
        headers: Received request headers.
    """

    method: str
    path: str
    body: bytes
    headers: dict[str, str]


@dataclass
class LoopbackDriver:
    """Control one local synthetic driver while preserving real client I/O.

    Attributes:
        url: Exact permitted HTTP origin.
        replies: Ordered response plans consumed by the server.
        requests: Actual requests received by the server.
        entered: Event set after the first request body has been read.
    """

    url: str = ""
    replies: list[Reply] = field(default_factory=list)
    requests: list[WireRequest] = field(default_factory=list)
    entered: asyncio.Event = field(default_factory=asyncio.Event)


@pytest_asyncio.fixture
async def loopback_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[LoopbackDriver]:
    """Permit real network operations only to this fixture's exact local endpoint.

    Args:
        monkeypatch: Reversible overrides layered over the default network guards.

    Yields:
        Synthetic driver whose responses and observed requests are test-controlled.
    """
    driver = LoopbackDriver()

    async def handle(request: web.Request) -> web.StreamResponse:
        """Capture a real request and send its next planned wire response.

        Args:
            request: Request delivered by aiohttp's local HTTP server.

        Returns:
            Planned raw response, stream response, or an aborted connection result.
        """
        driver.requests.append(
            WireRequest(
                request.method,
                request.raw_path,
                await request.read(),
                dict(request.headers),
            )
        )
        driver.entered.set()
        if not driver.replies:
            return web.Response(
                status=500,
                body=b'{"value":{"error":"unknown error","message":"unexpected request"}}',
            )
        reply = driver.replies.pop(0)
        if reply.disconnect:
            assert request.transport is not None
            request.transport.abort()
            return web.Response()
        if reply.delay:
            await asyncio.sleep(reply.delay)
        if reply.stream_delay:
            response = web.StreamResponse(status=reply.status, headers=reply.headers)
            await response.prepare(request)
            await asyncio.sleep(reply.stream_delay)
            if request.transport is not None and not request.transport.is_closing():
                await response.write(reply.body)
                await response.write_eof()
            return response
        return web.Response(status=reply.status, body=reply.body, headers=reply.headers)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)
    runner = web.AppRunner(app, shutdown_timeout=0.05)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        address = runner.addresses[0]
        endpoint = ("127.0.0.1", address[1])
        driver.url = "http://127.0.0.1:%d" % endpoint[1]

        async def guarded_request(
            client: aiohttp.ClientSession, method: str, url: Any, **kwargs: Any
        ) -> aiohttp.ClientResponse:
            """Allow aiohttp requests only for the fixture's exact HTTP origin.

            Args:
                client: Real HTTP client issuing the request.
                method: HTTP method passed to aiohttp.
                url: Absolute target URL.
                **kwargs: Remaining real aiohttp request options.

            Returns:
                Real aiohttp response from the permitted loopback server.
            """
            parsed = urlsplit(str(url))
            if parsed.scheme != "http" or (parsed.hostname, parsed.port) != endpoint:
                raise LoopbackOnlyError(
                    "Only the test fixture's exact loopback origin is permitted"
                )
            return await _CLIENT_REQUEST(client, method, url, **kwargs)

        def guarded_connect(sock: socket.socket, target: Any) -> None:
            """Allow TCP connects only to the fixture's exact loopback socket.

            Args:
                sock: Client socket opened by the real aiohttp connector.
                target: Address tuple requested by the asynchronous event loop.
            """
            if target != endpoint:
                raise LoopbackOnlyError(
                    "Only the test fixture's exact loopback socket is permitted"
                )
            return _SOCKET_CONNECT(sock, target)

        def guarded_connect_ex(sock: socket.socket, target: Any) -> int:
            """Allow connect_ex only to the fixture's exact loopback socket.

            Args:
                sock: Client socket opened by the real aiohttp connector.
                target: Address tuple requested by the asynchronous event loop.

            Returns:
                Operating-system connect status for the permitted socket.
            """
            if target != endpoint:
                raise LoopbackOnlyError(
                    "Only the test fixture's exact loopback socket is permitted"
                )
            return _SOCKET_CONNECT_EX(sock, target)

        monkeypatch.setattr(aiohttp.ClientSession, "_request", guarded_request)
        monkeypatch.setattr(socket.socket, "connect", guarded_connect)
        monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
        yield driver
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_loopback_guards_reject_every_other_origin(
    loopback_driver: LoopbackDriver,
) -> None:
    """Prove this test's network exception does not permit other local or remote targets.

    Args:
        loopback_driver: Exact local origin permitted by this test fixture.
    """
    async with aiohttp.ClientSession(trust_env=False) as client:
        for url in (
            "https://example.invalid",
            "http://127.0.0.1:1",
            loopback_driver.url.replace("127.0.0.1", "localhost"),
        ):
            with pytest.raises(LoopbackOnlyError):
                await client.get(url)
    assert not loopback_driver.requests
    with socket.socket() as sock:
        with pytest.raises(LoopbackOnlyError):
            sock.connect(("127.0.0.1", 1))
        with pytest.raises(LoopbackOnlyError):
            sock.connect_ex(("192.0.2.1", 80))


@pytest.mark.asyncio
async def test_real_get_post_headers_and_json_bytes(
    loopback_driver: LoopbackDriver,
) -> None:
    """Exercise actual JSON serialization, Unicode bytes, headers, and method routing.

    Args:
        loopback_driver: Local server recording raw requests.
    """
    loopback_driver.replies.extend(
        [Reply(body=b'{"value":"title"}'), Reply(body=b'{"value":7}'), Reply()]
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        connection = Connection(client, 1)
        base = loopback_driver.url + "/session/test"
        assert await connection.execute(base, Command.GET_TITLE) == {"value": "title"}
        body = {"script": "return arguments[0]", "args": ["中文", {"enabled": True}]}
        assert await connection.execute(base, Command.W3C_EXECUTE_SCRIPT, body) == {
            "value": 7
        }
        assert await connection.execute(base, Command.GO_BACK) == {"value": None}
        assert client.connector is not None and not client.connector._acquired
    assert client.closed
    get, post, empty_post = loopback_driver.requests
    assert (get.method, get.path, get.body) == ("GET", "/session/test/title", b"")
    assert (post.method, post.path) == ("POST", "/session/test/execute/sync")
    assert json.loads(post.body) == body
    assert "中文".encode() in post.body
    assert json.loads(empty_post.body) == {}
    assert empty_post.method == "POST" and empty_post.path == "/session/test/back"
    for request in loopback_driver.requests:
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json;charset=UTF-8"
        assert request.headers["User-Agent"].startswith("aselenium (python ")


@pytest.mark.asyncio
async def test_real_route_key_encoding_and_no_content(
    loopback_driver: LoopbackDriver,
) -> None:
    """Keep reserved route-key characters encoded and normalize an actual HTTP 204.

    Args:
        loopback_driver: Local server recording raw paths and methods.
    """
    loopback_driver.replies.extend(
        [Reply(body=b'{"value":null}'), Reply(status=204, body=b"")]
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        connection = Connection(client, 1)
        base = loopback_driver.url + "/session/test"
        assert await connection.execute(
            base, Command.GET_COOKIE, keys={"name": "a/b ?#"}
        ) == {"value": None}
        assert await connection.execute(base, Command.QUIT) == {"value": None}
    assert loopback_driver.requests[0].path == "/session/test/cookie/a%2Fb%20%3F%23"
    assert loopback_driver.requests[1].method == "DELETE"


@pytest.mark.parametrize("status", [400, 404, 500])
@pytest.mark.asyncio
async def test_real_protocol_errors_use_package_taxonomy(
    loopback_driver: LoopbackDriver, status: int
) -> None:
    """Map actual HTTP failures using the W3C error payload rather than status alone.

    Args:
        loopback_driver: Local server returning a typed W3C error.
        status: Representative client or server error status.
    """
    loopback_driver.replies.append(
        Reply(
            status=status,
            body=b'{"value":{"error":"invalid argument","message":"wire fixture"}}',
        )
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        with pytest.raises(errors.InvalidArgumentError, match="wire fixture"):
            await Connection(client, 1).execute(loopback_driver.url, Command.GET_TITLE)
        assert client.connector is not None and not client.connector._acquired
    assert len(loopback_driver.requests) == 1


@pytest.mark.parametrize(
    "error_name,error_type,command",
    [
        (
            "script timeout",
            errors.JavaScriptTimeoutError,
            Command.W3C_EXECUTE_SCRIPT_ASYNC,
        ),
        ("timeout", errors.WebDriverTimeoutError, Command.GET),
    ],
)
@pytest.mark.asyncio
async def test_native_timeout_response_preserves_type_and_connection_usability(
    loopback_driver: LoopbackDriver,
    error_name: str,
    error_type: type[errors.WebDriverError],
    command: str,
) -> None:
    """Keep browser-reported timeouts distinct from an expired transport deadline.

    Args:
        loopback_driver: Exact local server returning a timeout then a valid response.
        error_name: W3C timeout code returned before the connection budget expires.
        error_type: Specific package exception required by that W3C response.
        command: Browser command whose response reports the native timeout.
    """
    loopback_driver.replies.extend(
        [
            Reply(
                status=500,
                body=json.dumps(
                    {
                        "value": {
                            "error": error_name,
                            "message": "Native browser operation expired",
                            "stacktrace": "native frame one\nnative frame two",
                        }
                    }
                ).encode(),
            ),
            Reply(body=b'{"value":"still usable"}'),
        ]
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        connection = Connection(client, 5)
        with pytest.raises(
            error_type, match="Native browser operation expired"
        ) as captured:
            await connection.execute(loopback_driver.url, command)
        assert type(captured.value) is error_type
        assert captured.value.msg == "Native browser operation expired"
        assert captured.value.stacktrace == ["native frame one", "native frame two"]
        assert not isinstance(captured.value, errors.SessionTimeoutError)
        assert captured.value.__cause__ is None
        assert client.connector is not None and not client.connector._acquired
        assert not connection._wire_lock.locked()
        assert not connection._command_lock.locked()
        assert await connection.execute(loopback_driver.url, Command.GET_TITLE) == {
            "value": "still usable"
        }
    assert len(loopback_driver.requests) == 2


@pytest.mark.parametrize(
    "status,body",
    [
        (200, b"not JSON"),
        (200, b"\xff"),
        (200, b"[]"),
        (200, b"null"),
        (200, b"{}"),
        (200, b'{"status":0}'),
        (503, b"<html>unavailable</html>"),
    ],
)
@pytest.mark.asyncio
async def test_real_malformed_response_envelopes(
    loopback_driver: LoopbackDriver, status: int, body: bytes
) -> None:
    """Reject malformed payloads delivered by a real HTTP parser and socket.

    Args:
        loopback_driver: Local server returning deliberately malformed bytes.
        status: HTTP status attached to the malformed response.
        body: Response bytes that cannot represent a valid W3C envelope.
    """
    loopback_driver.replies.append(Reply(status=status, body=body))
    async with aiohttp.ClientSession(trust_env=False) as client:
        with pytest.raises(errors.SessionDataError):
            await Connection(client, 1).execute(loopback_driver.url, Command.GET_TITLE)
        assert client.connector is not None and not client.connector._acquired
    assert len(loopback_driver.requests) == 1


@pytest.mark.asyncio
async def test_real_same_origin_get_redirect(loopback_driver: LoopbackDriver) -> None:
    """Follow a relative GET redirect only within the original loopback origin.

    Args:
        loopback_driver: Local server issuing one allowed relative redirect.
    """
    loopback_driver.replies.extend(
        [
            Reply(status=302, headers={"Location": "/redirected"}),
            Reply(body=b'{"value":"redirect success"}'),
        ]
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        assert await Connection(client, 1).execute(
            loopback_driver.url, Command.GET_TITLE
        ) == {"value": "redirect success"}
    assert [(request.method, request.path) for request in loopback_driver.requests] == [
        ("GET", "/title"),
        ("GET", "/redirected"),
    ]


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1:1/forbidden",
        "https://example.invalid/forbidden",
        "//localhost:1/forbidden",
    ],
)
@pytest.mark.asyncio
async def test_real_cross_origin_redirect_is_refused_before_connect(
    loopback_driver: LoopbackDriver, location: str
) -> None:
    """Reject cross-origin redirects before the fixture's socket guard is involved.

    Args:
        loopback_driver: Local server returning an unsafe redirect.
        location: Destination outside the permitted server origin.
    """
    loopback_driver.replies.append(Reply(status=302, headers={"Location": location}))
    async with aiohttp.ClientSession(trust_env=False) as client:
        with pytest.raises(errors.SessionDataError, match="redirect"):
            await Connection(client, 1).execute(loopback_driver.url, Command.GET_TITLE)
    assert len(loopback_driver.requests) == 1


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.asyncio
async def test_real_post_redirect_is_never_replayed(
    loopback_driver: LoopbackDriver, status: int
) -> None:
    """Do not replay a mutating command or turn it into GET after any redirect.

    Args:
        loopback_driver: Local server redirecting a received POST command.
        status: Redirect code, including method-preserving and method-changing forms.
    """
    loopback_driver.replies.append(
        Reply(status=status, headers={"Location": "/replay-target"})
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        with pytest.raises(errors.SessionDataError, match="redirect"):
            await Connection(client, 1).execute(loopback_driver.url, Command.GO_BACK)
    assert [(request.method, request.path) for request in loopback_driver.requests] == [
        ("POST", "/back")
    ]


@pytest.mark.asyncio
async def test_real_redirect_chain_is_bounded(loopback_driver: LoopbackDriver) -> None:
    """Stop an otherwise safe redirect chain after the documented transport limit.

    Args:
        loopback_driver: Local server with an intentionally excessive redirect chain.
    """
    loopback_driver.replies.extend(
        Reply(status=302, headers={"Location": "/hop/%d" % index}) for index in range(4)
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        with pytest.raises(errors.SessionDataError, match="excessive"):
            await Connection(client, 1).execute(loopback_driver.url, Command.GET_TITLE)
    assert [request.path for request in loopback_driver.requests] == [
        "/title",
        "/hop/0",
        "/hop/1",
        "/hop/2",
    ]


@pytest.mark.asyncio
async def test_real_post_disconnect_is_not_replayed(
    loopback_driver: LoopbackDriver,
) -> None:
    """Preserve unknown mutation outcomes after a real connection abort.

    Args:
        loopback_driver: Local server aborting after receiving the full POST body.
    """
    loopback_driver.replies.append(Reply(disconnect=True))
    async with aiohttp.ClientSession(trust_env=False) as client:
        with pytest.raises(errors.SessionClientError, match="not replayed"):
            await Connection(client, 1).execute(loopback_driver.url, Command.GO_BACK)
        assert client.connector is not None and not client.connector._acquired
    assert len(loopback_driver.requests) == 1
    assert loopback_driver.requests[0].method == "POST"


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_real_deadline_releases_socket_and_command_locks(
    loopback_driver: LoopbackDriver, streaming: bool
) -> None:
    """Bound both header and body waits, release resources, and allow the next command.

    Args:
        loopback_driver: Local server delaying one response then serving a success.
        streaming: Whether to stall after response headers instead of before them.
    """
    loopback_driver.replies.extend(
        [
            Reply(stream_delay=0.2) if streaming else Reply(delay=0.2),
            Reply(body=b'{"value":"next"}'),
        ]
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        connection = Connection(client, 1)
        with pytest.raises(errors.SessionTimeoutError):
            await connection.execute(
                loopback_driver.url, Command.GET_TITLE, timeout=0.03
            )
        assert client.connector is not None and not client.connector._acquired
        assert (
            not connection._wire_lock.locked() and not connection._command_lock.locked()
        )
        assert await connection.execute(loopback_driver.url, Command.GET_TITLE) == {
            "value": "next"
        }
    assert client.closed and len(loopback_driver.requests) == 2


@pytest.mark.asyncio
async def test_real_cancellation_releases_socket_and_next_command(
    loopback_driver: LoopbackDriver,
) -> None:
    """Cancel an actual in-flight request without retaining the pool slot or locks.

    Args:
        loopback_driver: Local server exposing when the blocked command was received.
    """
    loopback_driver.replies.extend(
        [Reply(delay=0.2), Reply(body=b'{"value":"recovered"}')]
    )
    async with aiohttp.ClientSession(trust_env=False) as client:
        connection = Connection(client, 1)
        task = asyncio.create_task(
            connection.execute(loopback_driver.url, Command.GET_TITLE)
        )
        await asyncio.wait_for(loopback_driver.entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.connector is not None and not client.connector._acquired
        assert (
            not connection._wire_lock.locked() and not connection._command_lock.locked()
        )
        assert await connection.execute(loopback_driver.url, Command.GET_TITLE) == {
            "value": "recovered"
        }
    assert client.closed and len(loopback_driver.requests) == 2


@pytest.mark.asyncio
async def test_real_wire_queue_deadline_does_not_send_second_request(
    loopback_driver: LoopbackDriver,
) -> None:
    """Include command-lock admission in the deadline before any additional I/O.

    Args:
        loopback_driver: Local server holding the first command in flight.
    """
    loopback_driver.replies.append(Reply(delay=0.15, body=b'{"value":"first"}'))
    async with aiohttp.ClientSession(trust_env=False) as client:
        connection = Connection(client, 1)
        first = asyncio.create_task(
            connection.execute(loopback_driver.url, Command.GET_TITLE)
        )
        await asyncio.wait_for(loopback_driver.entered.wait(), timeout=1)
        with pytest.raises(errors.SessionTimeoutError):
            await connection.execute(loopback_driver.url, Command.GO_BACK, timeout=0.02)
        assert await first == {"value": "first"}
    assert len(loopback_driver.requests) == 1
    assert loopback_driver.requests[0].method == "GET"
