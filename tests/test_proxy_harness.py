"""Offline checks of the opt-in browser proxy fixture's routing safety boundary."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import ssl
import sys
import threading
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest


@pytest.fixture
def proxy_harness(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the opt-in script without starting servers or browsers.

    Args:
        monkeypatch: Fixture restoring the temporary module registration.

    Returns:
        Imported proxy fixture module, with all operations still explicitly opt-in.
    """
    path = Path(__file__).resolve().parents[1] / "scripts" / "test_browser_proxy.py"
    spec = importlib.util.spec_from_file_location("aselenium_proxy_fixture_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "target",
    [
        "http://example.invalid:12345/proxy-proof/fixture",
        "https://127.0.0.1:12345/proxy-proof/fixture",
        "http://127.0.0.1:12346/proxy-proof/fixture",
        "http://localhost:12345/proxy-proof/fixture",
        "http://127.0.0.2:12345/proxy-proof/fixture",
        "http://user@127.0.0.1:12345/proxy-proof/fixture",
        "http://127.0.0.1:12345/proxy-proof/fixture?redirect=external",
        "http://127.0.0.1:12345/proxy-proof/fixture#fragment",
        "http://127.0.0.1:12345/other",
        "/proxy-proof/fixture",
        "http://[::1]:12345/proxy-proof/fixture",
        "http://127.0.0.1:invalid/proxy-proof/fixture",
    ],
)
def test_proxy_allowlist_rejects_other_destinations(
    proxy_harness: ModuleType, target: str
) -> None:
    """Reject alternative hosts, ports, schemes, credentials, and URL suffixes.

    Args:
        proxy_harness: Imported opt-in fixture module.
        target: Request URL outside the exact allowlisted origin/path.
    """
    state = proxy_harness.FixtureState(token="fixture", origin_port=12345)
    assert not proxy_harness.allowed_target(target, state)
    assert proxy_harness.allowed_target(state.url, state)


@pytest.mark.parametrize(
    "method,target",
    [("do_CONNECT", "external.invalid:443"), ("do_GET", "http://external.invalid/")],
)
def test_proxy_rejects_without_creating_outbound_connection(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch, method: str, target: str
) -> None:
    """Ensure denied proxy requests never instantiate an HTTP connection.

    Args:
        proxy_harness: Imported opt-in fixture module.
        monkeypatch: Fixture restoring the outbound connection constructor.
        method: Handler method for a GET or CONNECT request.
        target: Disallowed destination supplied by the client.
    """
    state = proxy_harness.FixtureState(token="fixture", origin_port=12345)
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = target
    handler.respond = Mock()
    connection = Mock(
        side_effect=AssertionError("An external connection was attempted")
    )
    monkeypatch.setattr(proxy_harness, "HTTPConnection", connection)
    getattr(handler, method)()
    assert handler.respond.call_args.args[0] == 403
    connection.assert_not_called()
    assert state.counters()["rejected"] == 1


@pytest.mark.parametrize("headers", [{}, {"X-Aselenium-Proxy-Proof": "wrong"}])
def test_origin_rejects_direct_access(
    proxy_harness: ModuleType, headers: dict[str, str]
) -> None:
    """Prevent direct loopback access from satisfying the browser proxy test.

    Args:
        proxy_harness: Imported opt-in fixture module.
        headers: Browser headers without the correct proxy-only proof.
    """
    state = proxy_harness.FixtureState(token="fixture", origin_port=12345)
    handler = object.__new__(proxy_harness.OriginHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = state.path
    handler.headers = headers
    handler.respond = Mock()
    handler.do_GET()
    assert handler.respond.call_args.args[0] == 403
    assert state.counters()["origin_hits"] == 0
    assert state.counters()["direct_rejected"] == 1


def test_proxy_forwards_only_hardcoded_loopback_origin(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forward admitted requests to loopback with proof and close the connection.

    Args:
        proxy_harness: Imported opt-in fixture module.
        monkeypatch: Fixture restoring the simulated HTTP connection constructor.
    """
    state = proxy_harness.FixtureState(token="fixture", origin_port=12345)
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = state.url
    handler.respond = Mock()
    response = SimpleNamespace(
        status=200,
        read=Mock(return_value=b"proof"),
        getheader=Mock(return_value="text/html"),
    )
    connection = Mock()
    connection.getresponse.return_value = response
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(proxy_harness, "HTTPConnection", constructor)
    handler.do_GET()
    constructor.assert_called_once_with("127.0.0.1", 12345, timeout=3.0)
    connection.request.assert_called_once_with(
        "GET", state.path, headers={"X-Aselenium-Proxy-Proof": "fixture"}
    )
    connection.close.assert_called_once_with()
    assert state.counters()["forwarded"] == 1
    handler.respond.assert_called_once_with(200, b"proof", "text/html")


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(OSError("origin unavailable"), id="origin-unavailable"),
        pytest.param(b"x" * 65537, id="oversized-response"),
    ],
)
def test_proxy_forwarding_failure_still_closes_connection(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: Any
) -> None:
    """Bound upstream response size and close an unsuccessful forwarding attempt.

    Args:
        proxy_harness: Imported opt-in fixture module.
        monkeypatch: Fixture restoring the simulated HTTP connection constructor.
        failure: Upstream connection exception or oversized response body.
    """
    state = proxy_harness.FixtureState(token="fixture", origin_port=12345)
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = state.url
    handler.respond = Mock()
    connection = Mock()
    if isinstance(failure, Exception):
        connection.request.side_effect = failure
    else:
        connection.getresponse.return_value = SimpleNamespace(
            status=200, read=Mock(return_value=failure)
        )
    monkeypatch.setattr(proxy_harness, "HTTPConnection", Mock(return_value=connection))
    handler.do_GET()
    assert handler.respond.call_args.args[0] == 502
    connection.close.assert_called_once_with()
    assert state.counters()["forwarded"] == 0


@pytest.mark.parametrize("browser", ["chrome", "edge"])
def test_browser_proxy_configuration_without_launch(
    proxy_harness: ModuleType, tmp_path: Path, browser: str
) -> None:
    """Configure package HTTP/HTTPS proxy routing without starting a browser.

    Args:
        proxy_harness: Imported opt-in fixture module.
        tmp_path: Disposable manager cache directory.
        browser: Chrome or Edge facade to configure.
    """
    args = argparse.Namespace(browser=browser, cache_dir=str(tmp_path))
    driver = proxy_harness.configure_driver(args, 12345)
    try:
        assert driver.options.proxy.to_capabilities() == {
            "proxyType": "manual",
            "httpProxy": "127.0.0.1:12345",
            "sslProxy": "127.0.0.1:12345",
        }
        assert "--headless=new" in driver.options.arguments
        assert "--proxy-bypass-list=<-loopback>" in driver.options.arguments
        assert driver.options.timeouts.implicit == 0
    finally:
        driver.options.close()


def test_http_response_is_bounded_and_nonpersistent(proxy_harness: ModuleType) -> None:
    """Emit explicit response length and disable persistent/cacheable proof responses.

    Args:
        proxy_harness: Imported opt-in fixture module.
    """
    handler = object.__new__(proxy_harness.FixtureHandler)
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = BytesIO()
    handler.respond(200, b"fixture", "text/plain")
    handler.send_header.assert_any_call("Content-Length", "7")
    handler.send_header.assert_any_call("Connection", "close")
    assert handler.wfile.getvalue() == b"fixture"
    assert handler.close_connection


def test_origin_accepts_exact_proxy_proof(proxy_harness: ModuleType) -> None:
    """Return the marker only for the expected fixture path and proxy proof header.

    Args:
        proxy_harness: Imported opt-in fixture module.
    """
    state = proxy_harness.FixtureState(token="fixture", origin_port=12345)
    handler = object.__new__(proxy_harness.OriginHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = state.path
    handler.headers = {"X-Aselenium-Proxy-Proof": "fixture"}
    handler.respond = Mock()
    handler.do_GET()
    assert handler.respond.call_args.args[0] == 200
    assert b"<main id='proxy-proof'>fixture</main>" in handler.respond.call_args.args[1]
    assert state.counters()["origin_hits"] == 1


@pytest.mark.parametrize(
    "error", [BrokenPipeError(), ConnectionResetError(), TimeoutError()]
)
def test_http_response_tolerates_client_disconnect(
    proxy_harness: ModuleType, error: OSError
) -> None:
    """Close an abandoned browser request without an unhandled server-thread error.

    Args:
        proxy_harness: Imported opt-in fixture module.
        error: Expected connection failure while returning a response.
    """
    handler = object.__new__(proxy_harness.FixtureHandler)
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = SimpleNamespace(write=Mock(side_effect=error))
    handler.respond(403, b"denied", "text/plain")
    assert handler.close_connection


def test_fixture_server_cleanup_on_exception(proxy_harness: ModuleType) -> None:
    """Stop and join a fixture listener even when its owning context raises.

    Args:
        proxy_harness: Imported opt-in fixture module.
    """
    stopped = threading.Event()
    server = Mock()

    def serve_forever(poll_interval: float) -> None:
        """Wait for explicit shutdown without opening any socket.

        Args:
            poll_interval: Listener polling interval supplied by the fixture.
        """
        assert poll_interval == 0.05
        assert stopped.wait(timeout=2)

    server.serve_forever.side_effect = serve_forever
    server.shutdown.side_effect = stopped.set
    initial_threads = set(threading.enumerate())
    with pytest.raises(ValueError, match="body failed"):
        with proxy_harness.serving(server):
            raise ValueError("body failed")
    server.shutdown.assert_called_once_with()
    server.server_close.assert_called_once_with()
    assert not [
        thread
        for thread in set(threading.enumerate()) - initial_threads
        if thread.is_alive()
    ]


def test_fixture_listener_start_failure_closes_socket(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Close a bound socket when thread creation fails without masking that failure.

    Args:
        proxy_harness: Imported opt-in fixture module.
        monkeypatch: Fixture restoring the mocked thread constructor.
    """
    server = Mock()
    listener = Mock()
    listener.start.side_effect = RuntimeError("no thread resources")
    listener.is_alive.return_value = False
    listener.ident = None
    monkeypatch.setattr(proxy_harness.threading, "Thread", Mock(return_value=listener))
    with pytest.raises(RuntimeError, match="no thread resources"):
        with proxy_harness.serving(server):
            pytest.fail("A failed listener must not enter its context")
    server.server_close.assert_called_once_with()
    listener.join.assert_not_called()


@pytest.mark.parametrize(
    "target",
    [
        "external.invalid:443",
        "127.0.0.1:12346",
        "localhost:12345",
        "127.0.0.2:12345",
        "[::1]:12345",
        "user@127.0.0.1:12345",
        "https://127.0.0.1:12345",
        "127.0.0.1:12345/",
        "127.0.0.1:012345",
        "127.0.0.1:12345?redirect=external",
        "127.0.0.1:12345#fragment",
    ],
)
def test_connect_allowlist_rejects_alternate_authorities(
    proxy_harness: ModuleType, target: str
) -> None:
    """Permit only the literal paired TLS authority without parsing alternatives.

    Args:
        proxy_harness: Imported local proxy acceptance harness.
        target: Disallowed CONNECT authority or URL.
    """
    state = proxy_harness.FixtureState(tls_port=12345)
    assert proxy_harness.allowed_connect("127.0.0.1:12345", state)
    assert not proxy_harness.allowed_connect(target, state)
    state.tls_port = 0
    assert not proxy_harness.allowed_connect("127.0.0.1:0", state)


@pytest.mark.parametrize("method", ["do_GET", "do_CONNECT"])
@pytest.mark.parametrize(
    "header", [None, "", "Basic wrong", "Bearer fixture", "Basic 中文"]
)
def test_proxy_authentication_failure_never_contacts_origin(
    proxy_harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    header: str | None,
) -> None:
    """Challenge missing or invalid credentials before creating outbound sockets.

    Args:
        proxy_harness: Imported fixture with real authentication handling.
        monkeypatch: Fixture restoring outbound connection constructors.
        method: Plaintext forwarding or TLS tunneling entry point.
        header: Missing, malformed, or incorrect proxy credential header.
    """
    state = proxy_harness.FixtureState(
        token="fixture", origin_port=12345, tls_port=12346, auth_required=True
    )
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = state.url if method == "do_GET" else "127.0.0.1:12346"
    handler.headers = {} if header is None else {"Proxy-Authorization": header}
    handler.respond = Mock()
    outgoing = Mock(
        side_effect=AssertionError("Rejected credentials reached an origin")
    )
    monkeypatch.setattr(proxy_harness, "HTTPConnection", outgoing)
    monkeypatch.setattr(proxy_harness, "create_connection", outgoing)
    getattr(handler, method)()
    outgoing.assert_not_called()
    assert handler.respond.call_args.args[0] == 407
    assert handler.respond.call_args.args[3] == {
        "Proxy-Authenticate": 'Basic realm="aselenium-local-fixture"'
    }
    assert state.counters()["auth_rejected"] == 1
    assert state.counters()["connects"] == 0


def test_authenticated_http_forwarding_strips_proxy_credentials(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep authenticated proxy credentials out of the forwarded origin request.

    Args:
        proxy_harness: Imported fixture with real Basic authentication checking.
        monkeypatch: Fixture restoring the recording upstream HTTP connection.
    """
    state = proxy_harness.FixtureState(
        token="fixture", origin_port=12345, auth_required=True
    )
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = state.url
    handler.headers = {"Proxy-Authorization": state.authorization}
    handler.respond = Mock()
    connection = Mock()
    connection.getresponse.return_value = SimpleNamespace(
        status=200,
        read=Mock(return_value=b"proof"),
        getheader=Mock(return_value="text/html"),
    )
    monkeypatch.setattr(proxy_harness, "HTTPConnection", Mock(return_value=connection))
    handler.do_GET()
    assert connection.request.call_args.kwargs["headers"] == {
        "X-Aselenium-Proxy-Proof": "fixture"
    }
    assert state.counters()["forwarded"] == 1
    assert state.counters()["auth_rejected"] == 0
    connection.close.assert_called_once_with()


def test_connect_relays_only_paired_sockets_and_releases_registration(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relay both TLS byte directions then remove proof registration and close upstream.

    Args:
        proxy_harness: Imported bounded CONNECT implementation.
        monkeypatch: Fixture restoring socket creation and readability polling.
    """
    state = proxy_harness.FixtureState(
        token="fixture", tls_port=12345, auth_required=True
    )
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "127.0.0.1:12345"
    handler.headers = {"Proxy-Authorization": state.authorization}
    handler.wfile = BytesIO()
    incoming, upstream = Mock(), Mock()
    handler.connection = incoming
    incoming.recv.side_effect = [b"TLS request", b""]
    upstream.recv.return_value = b"TLS response"
    upstream.getsockname.return_value = ("127.0.0.1", 43210)
    connector = Mock(return_value=upstream)
    monkeypatch.setattr(proxy_harness, "create_connection", connector)
    poll = Mock(
        side_effect=[([incoming], [], []), ([upstream], [], []), ([incoming], [], [])]
    )
    monkeypatch.setattr(proxy_harness.select, "select", poll)
    handler.do_CONNECT()
    connector.assert_called_once_with(("127.0.0.1", 12345), timeout=3.0)
    assert handler.wfile.getvalue() == b"HTTP/1.1 200 Connection Established\r\n\r\n"
    upstream.sendall.assert_called_once_with(b"TLS request")
    incoming.sendall.assert_called_once_with(b"TLS response")
    upstream.close.assert_called_once_with()
    assert state.counters()["connects"] == 1
    assert state.counters()["tunnel_bytes"] == len(b"TLS requestTLS response")
    assert state.counters()["active_tunnels"] == 0
    assert handler.close_connection


@pytest.mark.parametrize("boundary", ["bytes", "deadline", "disconnect"])
def test_connect_resource_bounds_always_close_upstream(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """Bound relay bytes, lifetime, and client failures without retaining sockets.

    Args:
        proxy_harness: Imported bounded CONNECT implementation.
        monkeypatch: Fixture restoring relay limits and socket operations.
        boundary: Resource limit or transport failure terminating the tunnel.
    """
    state = proxy_harness.FixtureState(tls_port=12345)
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "127.0.0.1:12345"
    handler.wfile = BytesIO()
    incoming, upstream = Mock(), Mock()
    handler.connection = incoming
    upstream.getsockname.return_value = ("127.0.0.1", 43210)
    incoming.recv.return_value = b"1234"
    monkeypatch.setattr(proxy_harness, "create_connection", Mock(return_value=upstream))
    monkeypatch.setattr(
        proxy_harness.select, "select", Mock(return_value=([incoming], [], []))
    )
    if boundary == "bytes":
        monkeypatch.setattr(proxy_harness, "MAX_TUNNEL_BYTES", 4)
    elif boundary == "deadline":
        monkeypatch.setattr(proxy_harness, "TUNNEL_TIMEOUT", 0)
    else:
        incoming.recv.side_effect = ConnectionResetError()
    handler.do_CONNECT()
    assert state.counters()["tunnel_bytes"] == (4 if boundary == "bytes" else 0)
    assert state.counters()["active_tunnels"] == 0
    upstream.close.assert_called_once_with()
    assert handler.close_connection


def test_connect_denial_never_opens_raw_socket(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject an unallowlisted CONNECT authority before invoking any connector.

    Args:
        proxy_harness: Imported strict CONNECT allowlist implementation.
        monkeypatch: Fixture restoring the guarded raw-socket connector.
    """
    state = proxy_harness.FixtureState(tls_port=12345)
    handler = object.__new__(proxy_harness.ProxyHandler)
    handler.server = SimpleNamespace(state=state)
    handler.path = "external.invalid:443"
    handler.respond = Mock()
    connector = Mock(side_effect=AssertionError("External connect attempted"))
    monkeypatch.setattr(proxy_harness, "create_connection", connector)
    handler.do_CONNECT()
    connector.assert_not_called()
    assert handler.respond.call_args.args[0] == 403


@pytest.mark.parametrize("registered", [False, True])
def test_tls_origin_uses_active_proxy_tcp_source_proof(
    proxy_harness: ModuleType, registered: bool
) -> None:
    """Do not let a forged HTTP proof header substitute for an actual CONNECT tunnel.

    Args:
        proxy_harness: Imported TLS origin implementation.
        registered: Whether the accepted peer is a currently active proxy endpoint.
    """
    state = proxy_harness.FixtureState(token="fixture", tls_port=12345)
    peer = ("127.0.0.1", 43210)
    if registered:
        state.tunnel_sources.add(peer)
    handler = object.__new__(proxy_harness.TLSOriginHandler)
    handler.server = SimpleNamespace(state=state, tls_context=object())
    handler.client_address = peer
    handler.path = state.path
    handler.headers = {"X-Aselenium-Proxy-Proof": "fixture"}
    handler.respond = Mock()
    handler.do_GET()
    assert handler.respond.call_args.args[0] == (200 if registered else 403)
    assert state.counters()["tls_origin_hits"] == int(registered)
    assert state.counters()["direct_rejected"] == int(not registered)


def test_tls_handshake_failure_closes_accepted_socket(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release the accepted raw socket when the fixture TLS handshake fails.

    Args:
        proxy_harness: Imported fixture server class.
        monkeypatch: Fixture restoring the mocked raw accept implementation.
    """
    server = object.__new__(proxy_harness.FixtureServer)
    server.tls_context = Mock()
    server.tls_context.wrap_socket.side_effect = ssl.SSLError(
        "fixture handshake failure"
    )
    incoming = Mock()
    monkeypatch.setattr(
        proxy_harness.ThreadingHTTPServer,
        "get_request",
        Mock(return_value=(incoming, ("127.0.0.1", 43210))),
    )
    with pytest.raises(ssl.SSLError):
        server.get_request()
    incoming.settimeout.assert_called_once_with(3.0)
    incoming.close.assert_called_once_with()


@pytest.mark.parametrize("scheme", ["https", "both"])
def test_browser_tls_fixture_opt_in_is_explicit(
    proxy_harness: ModuleType, tmp_path: Path, scheme: str
) -> None:
    """Keep local-browser TLS acceptance explicit without claiming certificate-store trust.

    Args:
        proxy_harness: Imported browser configuration helper.
        tmp_path: Disposable manager cache directory.
        scheme: HTTPS-only or combined local routing scenario.
    """
    args = argparse.Namespace(browser="chrome", cache_dir=str(tmp_path), scheme=scheme)
    driver = proxy_harness.configure_driver(args, 12345)
    try:
        assert driver.options.accept_insecure_certs is True
        assert driver.options.proxy.to_capabilities()["sslProxy"] == "127.0.0.1:12345"
    finally:
        driver.options.close()


def test_browser_authentication_cli_is_not_misrepresented(
    proxy_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse a browser-authentication mode that the public browser API cannot supply.

    Args:
        proxy_harness: Imported command-line acceptance harness.
        monkeypatch: Fixture restoring the command-line arguments.
    """
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "test_browser_proxy.py",
            "--browser",
            "chrome",
            "--binary",
            "fixture",
            "--cache-dir",
            "fixture",
            "--proxy-auth",
        ],
    )
    with pytest.raises(SystemExit) as caught:
        proxy_harness.main()
    assert caught.value.code == 2


def test_proxy_acceptance_checks_survive_optimized_python(
    proxy_harness: ModuleType,
) -> None:
    """Keep acceptance failures observable under both python -O and python -OO.

    Args:
        proxy_harness: Imported harness with an explicit non-assert acceptance gate.
    """
    namespace: dict[str, Any] = {}
    source = inspect.getsource(proxy_harness.require)
    exec(compile(source, "proxy-require", "exec", optimize=2), namespace)
    with pytest.raises(AssertionError, match="fixture failed"):
        namespace["require"](False, "fixture failed")
    assert namespace["require"](True, "unused") is None
    tree = ast.parse(Path(proxy_harness.__file__).read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
