"""Opt-in browser test of package proxy routing through strictly local servers.

Browser mode uses installed Chrome/Edge and already-cached drivers. Manager mode
exercises the package's actual HTTPS download transport, including proxy Basic
authentication, without launching a browser. Forwarding is restricted to one
HTTP URL and one TLS origin on 127.0.0.1. No server starts on import. The public
test certificate is trusted only by this fixture, never installed system-wide.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import select
import ssl
import threading
import time
from base64 import b64encode
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import compare_digest, token_hex
from socket import create_connection, socket
from tempfile import TemporaryDirectory
from typing import Any, cast
from urllib.parse import urlsplit

import psutil
from aiohttp import ClientSession, TCPConnector

from aselenium import Chrome, Edge, Proxy, errors
from aselenium.manager import ChromeDriverManager, _http

TITLE = "Aselenium local proxy proof"
MAX_RESPONSE_BYTES = 65536
SOCKET_TIMEOUT = 3.0
TUNNEL_TIMEOUT = 10.0
MAX_TUNNEL_BYTES = 1024 * 1024
TLS_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tls"


def require(condition: bool, message: str) -> None:
    """Enforce an acceptance condition even when Python optimization is enabled.

    Args:
        condition: Required property of the observed local acceptance run.
        message: Diagnostic raised when the required property is absent.

    Raises:
        AssertionError: The condition is false; unlike assert, this is not optimized out.
    """
    if not condition:
        raise AssertionError(message)


@dataclass
class FixtureState:
    """Keep proof material and synchronized counters for one local proxy test.

    Attributes:
        token: Per-run token required at the origin and displayed in its response.
        origin_port: Exact loopback port to which forwarding is allowed.
        tls_port: Exact loopback TLS port to which CONNECT is allowed.
        forwarded: Successful proxy-to-origin requests.
        origin_hits: Origin requests bearing the correct proxy-only proof.
        rejected: Proxy requests rejected without forwarding.
        direct_rejected: Origin requests lacking the proxy-only proof.
        connects: Accepted CONNECT tunnels to the TLS origin.
        tls_origin_hits: TLS origin requests received through a registered tunnel.
        auth_required: Whether the proxy requires the fixture's Basic credentials.
        auth_rejected: Requests refused with a 407 authentication challenge.
        credential_leaks: Proxy credentials incorrectly sent inside an origin request.
        tunnel_sources: Active proxy TCP source endpoints accepted by the TLS origin.
        tunnel_bytes: Total bytes relayed across bounded CONNECT tunnels.
        lock: Lock protecting counters across request threads.
    """

    token: str = field(default_factory=lambda: token_hex(16))
    origin_port: int = 0
    tls_port: int = 0
    forwarded: int = 0
    origin_hits: int = 0
    rejected: int = 0
    direct_rejected: int = 0
    connects: int = 0
    tls_origin_hits: int = 0
    auth_required: bool = False
    auth_rejected: int = 0
    credential_leaks: int = 0
    tunnel_sources: set[tuple[str, int]] = field(default_factory=set)
    tunnel_bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def path(self) -> str:
        """Return the sole request path admitted by this test.

        Returns:
            An absolute path containing the unpredictable fixture token.
        """
        return "/proxy-proof/" + self.token

    @property
    def url(self) -> str:
        """Return the sole absolute URL admitted by the proxy.

        Returns:
            Exact HTTP URL for the paired loopback origin.
        """
        return f"http://127.0.0.1:{self.origin_port}{self.path}"

    def counters(self) -> dict[str, int]:
        """Read a consistent snapshot of request counters.

        Returns:
            Forwarded, accepted-origin, rejected-proxy, and rejected-direct counts.
        """
        with self.lock:
            return {
                "forwarded": self.forwarded,
                "origin_hits": self.origin_hits,
                "rejected": self.rejected,
                "direct_rejected": self.direct_rejected,
                "connects": self.connects,
                "tls_origin_hits": self.tls_origin_hits,
                "auth_rejected": self.auth_rejected,
                "credential_leaks": self.credential_leaks,
                "active_tunnels": len(self.tunnel_sources),
                "tunnel_bytes": self.tunnel_bytes,
            }

    @property
    def tls_url(self) -> str:
        """Return the exact HTTPS origin proof URL.

        Returns:
            HTTPS URL using the fixture's allowlisted loopback TLS listener.
        """
        return f"https://127.0.0.1:{self.tls_port}{self.path}"

    @property
    def authorization(self) -> str:
        """Return synthetic per-run proxy Basic credentials for local acceptance.

        Returns:
            Authorization header used only by the disposable fixture proxy.
        """
        value = ("aselenium-fixture:" + self.token).encode("ascii")
        return "Basic " + b64encode(value).decode("ascii")


def allowed_connect(target: str, state: FixtureState) -> bool:
    """Allow only the exact authority of the paired loopback TLS origin.

    Args:
        target: Authority-form target from the CONNECT request line.
        state: Fixture state containing the separately assigned TLS port.

    Returns:
        True for the exact literal loopback address and TLS port, otherwise False.
    """
    return 1 <= state.tls_port <= 65535 and target == f"127.0.0.1:{state.tls_port}"


def allowed_target(target: str, state: FixtureState) -> bool:
    """Permit only the exact paired origin URL, without credentials or redirects.

    Args:
        target: Absolute-form proxy request target.
        state: Fixture state containing the allowed port and path.

    Returns:
        True only for the exact HTTP loopback URL generated by this fixture.
    """
    if not 1 <= state.origin_port <= 65535 or target != state.url:
        return False
    try:
        parsed = urlsplit(target)
        return (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == state.origin_port
            and parsed.username is None
            and parsed.password is None
            and parsed.path == state.path
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


class FixtureServer(ThreadingHTTPServer):
    """Bind a fixture handler exclusively to an ephemeral IPv4 loopback port.

    Request threads are joined during close. Each accepted socket has a finite
    timeout so incomplete HTTP requests cannot hold shutdown indefinitely.
    """

    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        handler: type[BaseHTTPRequestHandler],
        state: FixtureState,
        tls_context: ssl.SSLContext | None = None,
    ) -> None:
        """Bind one server and attach its shared state.

        Args:
            handler: Origin or allowlisted forward-proxy request handler.
            state: Per-run state shared by both fixture servers.
            tls_context: Test-only server context, or None for plaintext HTTP.
        """
        self.state = state
        self.tls_context = tls_context
        super().__init__(("127.0.0.1", 0), handler)

    def get_request(self) -> tuple[socket, tuple[str, int]]:
        """Accept one connection with a bounded optional TLS handshake.

        Returns:
            Accepted socket and peer endpoint, wrapped in TLS when configured.
        """
        incoming, address = super().get_request()
        incoming.settimeout(SOCKET_TIMEOUT)
        if self.tls_context is not None:
            try:
                incoming = self.tls_context.wrap_socket(incoming, server_side=True)
            except BaseException:
                incoming.close()
                raise
        return incoming, address


class FixtureHandler(BaseHTTPRequestHandler):
    """Provide bounded, quiet HTTP handling for the local test servers."""

    @property
    def state(self) -> FixtureState:
        """Return the state attached to the serving fixture.

        Returns:
            Shared state for the paired origin and proxy.
        """
        return cast(FixtureServer, self.server).state

    def setup(self) -> None:
        """Apply a finite socket timeout before reading any request bytes."""
        self.request.settimeout(SOCKET_TIMEOUT)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:
        """Keep request logging out of the machine-readable JSON output.

        Args:
            format: HTTP server diagnostic format string.
            *args: Diagnostic interpolation values deliberately not emitted.
        """

    def respond(
        self,
        status: int,
        content: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Write a bounded response with no persistent connection or caching.

        Args:
            status: HTTP response status code.
            content: Bytes to return to the browser.
            content_type: Explicit response media type.
            headers: Optional challenge headers for a refused proxy request.
        """
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # Background requests can be abandoned when the fresh browser quits.
            # Their explicit denial remains counted even if its body is unread.
            pass
        finally:
            self.close_connection = True


class OriginHandler(FixtureHandler):
    """Serve the proof page only after receiving the proxy's private header."""

    def is_proxied(self) -> bool:
        """Check the private header inserted by the paired plaintext proxy.

        Returns:
            True when the request carries the exact fixture proof token.
        """
        return self.headers.get("X-Aselenium-Proxy-Proof") == self.state.token

    def do_GET(self) -> None:
        """Return proof content or reject direct browser access to the origin."""
        if self.path != self.state.path or not self.is_proxied():
            with self.state.lock:
                self.state.direct_rejected += 1
            self.respond(403, b"Proxy proof is required", "text/plain")
            return
        with self.state.lock:
            self.state.origin_hits += 1
            if getattr(self.server, "tls_context", None) is not None:
                self.state.tls_origin_hits += 1
            if self.headers.get("Proxy-Authorization") is not None:
                self.state.credential_leaks += 1
        content = (
            f"<!doctype html><title>{TITLE}</title>"
            "<link rel='icon' href='data:,'>"
            f"<main id='proxy-proof'>{self.state.token}</main>"
        ).encode("utf-8")
        self.respond(200, content, "text/html; charset=utf-8")


class TLSOriginHandler(OriginHandler):
    """Accept TLS proof requests only from a currently registered proxy tunnel."""

    def is_proxied(self) -> bool:
        """Verify the TCP peer belongs to a proxy-created CONNECT tunnel.

        Returns:
            True only while the peer's exact loopback endpoint is registered.
        """
        with self.state.lock:
            return self.client_address in self.state.tunnel_sources


class ProxyHandler(FixtureHandler):
    """Forward one HTTP URL or a bounded tunnel to one exact loopback TLS port."""

    def authenticate(self) -> bool:
        """Validate optional synthetic Basic credentials without contacting an origin.

        Returns:
            True if credentials are unnecessary or correct; otherwise emits 407.
        """
        if not self.state.auth_required:
            return True
        supplied = self.headers.get("Proxy-Authorization", "")
        if supplied.isascii() and compare_digest(supplied, self.state.authorization):
            return True
        with self.state.lock:
            self.state.auth_rejected += 1
        self.respond(
            407,
            b"Fixture proxy authentication required",
            "text/plain",
            {"Proxy-Authenticate": 'Basic realm="aselenium-local-fixture"'},
        )
        return False

    def do_CONNECT(self) -> None:
        """Relay bounded TLS bytes only to the separately allowlisted local origin."""
        if not allowed_connect(self.path, self.state):
            with self.state.lock:
                self.state.rejected += 1
            self.respond(403, b"CONNECT destination is not allowlisted", "text/plain")
            return
        if not self.authenticate():
            return
        upstream = None
        peer = None
        count = 0
        try:
            upstream = create_connection(
                ("127.0.0.1", self.state.tls_port), timeout=SOCKET_TIMEOUT
            )
            peer = upstream.getsockname()
            with self.state.lock:
                self.state.connects += 1
                self.state.tunnel_sources.add(peer)
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.wfile.flush()
            deadline = time.monotonic() + TUNNEL_TIMEOUT
            streams = (self.connection, upstream)
            while count < MAX_TUNNEL_BYTES and time.monotonic() < deadline:
                readable, _, _ = select.select(streams, [], [], 0.1)
                for source in readable:
                    chunk = source.recv(min(16384, MAX_TUNNEL_BYTES - count))
                    if not chunk:
                        return
                    count += len(chunk)
                    destination = (
                        upstream if source is self.connection else self.connection
                    )
                    destination.sendall(chunk)
        except (OSError, ValueError):
            # A TLS verification failure or closed browser naturally aborts its
            # tunnel. The fixture owns and closes both endpoints in all cases.
            pass
        finally:
            self.close_connection = True
            with self.state.lock:
                self.state.tunnel_bytes += count
                if peer is not None:
                    self.state.tunnel_sources.discard(peer)
            if upstream is not None:
                upstream.close()

    def do_GET(self) -> None:
        """Forward the exact fixture request with a proxy-only origin proof header."""
        if not allowed_target(self.path, self.state):
            with self.state.lock:
                self.state.rejected += 1
            self.respond(403, b"Destination is not allowlisted", "text/plain")
            return
        if not self.authenticate():
            return
        # Do not use the requested host for connection creation: the destination
        # is hard-coded loopback plus the independently assigned origin port.
        connection = HTTPConnection(
            "127.0.0.1", self.state.origin_port, timeout=SOCKET_TIMEOUT
        )
        try:
            connection.request(
                "GET",
                self.state.path,
                headers={"X-Aselenium-Proxy-Proof": self.state.token},
            )
            response = connection.getresponse()
            content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                self.respond(502, b"Origin response exceeded limit", "text/plain")
                return
            if response.status == 200:
                with self.state.lock:
                    self.state.forwarded += 1
            self.respond(
                response.status,
                content,
                response.getheader("Content-Type", "application/octet-stream"),
            )
        except OSError:
            self.respond(502, b"Local origin unavailable", "text/plain")
        finally:
            connection.close()


@contextmanager
def serving(server: FixtureServer) -> Iterator[FixtureServer]:
    """Start one fixture server and always close its listener and request threads.

    Args:
        server: Already-bound loopback server owned by this context.

    Yields:
        The server while its listener thread is running.

    Raises:
        RuntimeError: A listener thread fails to finish its bounded shutdown.
    """
    listener = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        name="aselenium-local-proxy-fixture",
    )
    try:
        listener.start()
        yield server
    finally:
        if listener.is_alive():
            server.shutdown()
        server.server_close()
        if listener.ident is not None:
            listener.join(timeout=5)
        if listener.is_alive():
            raise RuntimeError("Local fixture listener failed to shut down")


def configure_driver(args: argparse.Namespace, proxy_port: int) -> Chrome | Edge:
    """Configure headless package proxy routing without provisioning or launching.

    Args:
        args: Browser name and existing driver-cache directory.
        proxy_port: Ephemeral loopback proxy port shared by HTTP and HTTPS routing.

    Returns:
        Configured Chrome or Edge driver facade; the caller must close its options.
    """
    driver = (Chrome if args.browser == "chrome" else Edge)(directory=args.cache_dir)
    proxy_url = f"http://127.0.0.1:{proxy_port}"
    driver.options.proxy = Proxy(http_proxy=proxy_url, https_proxy=proxy_url)
    driver.options.add_arguments(
        "--headless=new",
        "--proxy-bypass-list=<-loopback>",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-quic",
        "--no-first-run",
        "--no-default-browser-check",
    )
    driver.options.set_timeouts(implicit=0, pageLoad=15, script=5)
    driver.options.session_timeout = 20
    if getattr(args, "scheme", "http") != "http":
        # Browser mode proves encrypted CONNECT routing, not certificate-store
        # integration. Only the isolated loopback fixture is permitted by proxy.
        driver.options.accept_insecure_certs = True
    return driver


async def run_browser(
    args: argparse.Namespace, state: FixtureState, proxy_port: int
) -> dict[str, Any]:
    """Verify the proof page through one fresh browser session and await cleanup.

    Args:
        args: Browser, installed binary, and populated cache directory.
        state: Active paired origin/proxy state.
        proxy_port: Loopback proxy listener port.

    Returns:
        Browser versions, routing evidence, and owned-resource cleanup observations.
    """
    driver = configure_driver(args, proxy_port)
    observed: set[tuple[int, float]] = set()
    initial_tasks = set(asyncio.all_tasks())
    started = time.monotonic()
    try:
        async with driver.acquire("offline", binary=args.binary) as session:
            for process in psutil.Process().children(recursive=True):
                try:
                    observed.add((process.pid, process.create_time()))
                except psutil.NoSuchProcess:
                    pass
            scheme = getattr(args, "scheme", "http")
            urls = [state.url] if scheme == "http" else [state.tls_url]
            if scheme == "both":
                urls = [state.url, state.tls_url]
            for url in urls:
                await session.load(url)
                require(
                    await session.title == TITLE,
                    "The browser did not load the origin proof page",
                )
                element = await session.find_element("#proxy-proof")
                if element is None:
                    raise AssertionError("The proof element was absent")
                require(
                    await element.text == state.token,
                    "The origin proof token did not match",
                )
            counts = state.counters()
            if scheme in {"http", "both"}:
                require(counts["forwarded"] >= 1, "The browser bypassed the HTTP proxy")
            if scheme in {"https", "both"}:
                require(
                    counts["connects"] >= 1, "The browser did not establish CONNECT"
                )
                require(
                    counts["tls_origin_hits"] >= 1,
                    "The TLS origin did not receive tunneled proof",
                )
            require(
                counts["origin_hits"] >= 1, "The origin did not receive proxy proof"
            )
        installation = driver.manager.last_result
        remaining = []
        for pid, created in sorted(observed):
            try:
                process = psutil.Process(pid)
                if (
                    process.create_time() == created
                    and process.status() != psutil.STATUS_ZOMBIE
                ):
                    remaining.append(pid)
            except psutil.NoSuchProcess:
                pass
        pending = [
            task for task in asyncio.all_tasks() - initial_tasks if not task.done()
        ]
        require(not remaining, f"Observed child processes remained alive: {remaining}")
        require(not pending, "Owned asynchronous tasks remained pending")
        return {
            "status": "passed",
            "browser": args.browser,
            "scheme": scheme,
            "browser_version": installation.browser_version if installation else None,
            "driver_version": installation.driver_version if installation else None,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "elapsed_seconds": time.monotonic() - started,
            "routing": state.counters(),
            "remaining_observed_processes": remaining,
            "remaining_owned_tasks": len(pending),
            "scope": f"Browser package Proxy {scheme.upper()} routing to exact loopback origins; browser proxy authentication is not claimed",
            "browser_tls_trust": "not applicable"
            if scheme == "http"
            else "Explicit test-only accept_insecure_certs capability; no system trust changes",
        }
    finally:
        driver.options.close()


async def run_manager(
    args: argparse.Namespace, state: FixtureState, proxy_port: int
) -> dict[str, Any]:
    """Exercise the package HTTPS transport through a controlled CONNECT proxy.

    Args:
        args: Disposable manager-cache directory and proxy-authentication option.
        state: Active plaintext/TLS origins and allowlisted proxy state.
        proxy_port: Exact local proxy listener port.

    Returns:
        Successful/rejected routing cases, certificate trust scope, and cleanup proof.
    """
    context = ssl.create_default_context(cafile=str(TLS_FIXTURES / "loopback-cert.pem"))
    clients: list[ClientSession] = []
    initial_tasks = set(asyncio.all_tasks())

    def client_factory() -> ClientSession:
        """Create a real client trusting only the explicit fixture addition.

        Returns:
            Client whose connector validates the loopback fixture certificate.
        """
        client = ClientSession(connector=TCPConnector(ssl=context), trust_env=False)
        clients.append(client)
        return client

    proxy_url = f"http://127.0.0.1:{proxy_port}"
    authenticated_proxy = (
        f"http://aselenium-fixture:{state.token}@127.0.0.1:{proxy_port}"
    )
    manager = ChromeDriverManager(directory=args.cache_dir, request_timeout=5)
    manager.proxy = authenticated_proxy if state.auth_required else proxy_url
    cases: dict[str, str] = {}
    started = time.monotonic()
    content = await _http.request(manager, state.tls_url, "text", client_factory)
    require(
        state.token in content and TITLE in content,
        "Manager did not receive origin proof",
    )
    require(
        state.counters()["tls_origin_hits"] >= 1, "Manager did not use the TLS tunnel"
    )
    cases["verified_tls_through_connect"] = "passed"

    manager.proxy = None
    try:
        await _http.request(manager, state.tls_url, "text", client_factory)
    except errors.DriverRequestFailedError:
        cases["direct_bypass_rejected"] = "passed"
    else:
        raise AssertionError("Direct TLS bypass unexpectedly satisfied proxy proof")
    require(
        state.counters()["direct_rejected"] >= 1,
        "Origin did not record direct bypass refusal",
    )

    manager.proxy = authenticated_proxy if state.auth_required else proxy_url
    previous = state.counters()
    try:
        await _http.request(
            manager, f"https://127.0.0.1:1{state.path}", "text", client_factory
        )
    except errors.DriverRequestFailedError:
        cases["unallowlisted_connect_rejected"] = "passed"
    else:
        raise AssertionError("Proxy admitted a destination outside its TLS allowlist")
    require(
        state.counters()["connects"] == previous["connects"],
        "Rejected destination opened a tunnel",
    )
    require(
        state.counters()["rejected"] > previous["rejected"],
        "Proxy did not record destination refusal",
    )

    if state.auth_required:
        cases["authenticated_connect"] = "passed"
        for name, supplied_proxy in (
            ("missing_credentials_rejected", proxy_url),
            (
                "wrong_credentials_rejected",
                f"http://aselenium-fixture:wrong@127.0.0.1:{proxy_port}",
            ),
        ):
            previous = state.counters()
            manager.proxy = supplied_proxy
            try:
                await _http.request(manager, state.tls_url, "text", client_factory)
            except errors.DriverRequestFailedError:
                cases[name] = "passed"
            else:
                raise AssertionError("Proxy authentication failure was accepted")
            require(
                state.counters()["auth_rejected"] > previous["auth_rejected"],
                "Proxy did not record authentication refusal",
            )
            require(
                state.counters()["connects"] == previous["connects"],
                "Invalid credentials opened a tunnel",
            )

    require(
        not state.counters()["credential_leaks"],
        "Proxy credentials leaked to the origin",
    )
    require(all(client.closed for client in clients), "Manager retained an HTTP client")
    pending = [task for task in asyncio.all_tasks() - initial_tasks if not task.done()]
    require(not pending, "Manager retained an owned asynchronous task")
    return {
        "status": "passed",
        "client": "manager HTTPS transport",
        "authentication_required": state.auth_required,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "elapsed_seconds": time.monotonic() - started,
        "cases": cases,
        "proxy_authentication": "Basic credentials in explicit manager.proxy URL"
        if state.auth_required
        else "disabled",
        "tls_verification": "Certificate and IP hostname verified using test-only client-factory trust; system trust unchanged",
        "routing": state.counters(),
        "closed_clients": len(clients),
        "remaining_owned_tasks": len(pending),
        "scope": "Actual package manager HTTPS transport and CONNECT proxy authentication; no browser proxy-authentication support is inferred",
    }


def main() -> int:
    """Run an explicitly requested browser proxy test and emit JSON evidence.

    Returns:
        Zero on successful routing and cleanup; one on any validation failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("browser", "manager"), default="browser")
    parser.add_argument("--browser", choices=("chrome", "edge"))
    parser.add_argument("--binary")
    parser.add_argument("--cache-dir")
    parser.add_argument("--scheme", choices=("http", "https", "both"), default="http")
    parser.add_argument(
        "--proxy-auth",
        action="store_true",
        help="Require Basic credentials in manager mode; browser proxy authentication is not asserted",
    )
    parser.add_argument(
        "--output", type=Path, help="Optional JSON evidence destination"
    )
    args = parser.parse_args()
    if args.client == "browser" and not all(
        (args.browser, args.binary, args.cache_dir)
    ):
        parser.error("Browser mode requires --browser, --binary, and --cache-dir")
    if args.client == "browser" and args.proxy_auth:
        parser.error(
            "Use --client manager --proxy-auth; browser credential handling is not implemented by this harness"
        )
    state = FixtureState(auth_required=args.proxy_auth)
    initial_threads = set(threading.enumerate())
    try:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.load_cert_chain(
            TLS_FIXTURES / "loopback-cert.pem", TLS_FIXTURES / "loopback-key.pem"
        )
        with TemporaryDirectory(prefix="aselenium-proxy-client-") as temporary:
            if args.cache_dir is None:
                args.cache_dir = temporary
            with serving(FixtureServer(OriginHandler, state)) as origin:
                state.origin_port = origin.server_port
                with serving(
                    FixtureServer(TLSOriginHandler, state, tls_context)
                ) as tls_origin:
                    state.tls_port = tls_origin.server_port
                    with serving(FixtureServer(ProxyHandler, state)) as proxy:
                        run = run_browser if args.client == "browser" else run_manager
                        result = asyncio.run(
                            asyncio.wait_for(
                                run(args, state, proxy.server_port), timeout=60
                            )
                        )
        remaining_threads = [
            thread.name
            for thread in set(threading.enumerate()) - initial_threads
            if thread.is_alive()
        ]
        result["remaining_fixture_threads"] = remaining_threads
        result["routing"] = state.counters()
        if remaining_threads or state.counters()["active_tunnels"]:
            result["status"] = "failed"
    except Exception as cause:
        result = {
            "status": "failed",
            "browser": args.browser,
            "client": args.client,
            "error_type": type(cause).__name__,
            "error": str(cause),
            "routing": state.counters(),
        }
    serialized = json.dumps(result, indent=2)
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
