"""Real HTTPS driver-manager transport and cache integration on one local origin.

Only this fixture's ephemeral 127.0.0.1 TLS listener is reachable. The public
test-only certificate is trusted through a dedicated client SSL context, never
through the operating-system trust store. Installed browsers are never launched.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import socket
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zipfile import ZipFile

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web

from aselenium import errors
from aselenium.manager import _http
from aselenium.manager import driver as driver_module
from aselenium.manager.driver import ChromeDriverManager, EdgeDriverManager
from aselenium.manager.version import ChromiumVersion

pytestmark = pytest.mark.loopback
TLS_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tls"
_CLIENT_REQUEST = aiohttp.ClientSession._request
_SOCKET_CONNECT = socket.socket.connect
_SOCKET_CONNECT_EX = socket.socket.connect_ex
_DOWNLOAD_CLASS = _http.Download


class VendorLoopbackOnlyError(BaseException):
    """Fail immediately if a TLS test attempts any non-fixture connection."""


@dataclass
class VendorReply:
    """Describe one independently specified HTTPS response.

    Args:
        body: Response bytes, or first streamed bytes for a partial response.
        status: HTTP response status.
        headers: Additional wire headers.
        delay: Seconds to wait before sending response headers.
        truncate: Abort after sending body with an intentionally larger length.
        hold_stream: Keep a partial stream open until fixture cleanup or cancellation.
    """

    body: bytes = b""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0
    truncate: bool = False
    hold_stream: bool = False


@dataclass
class TLSVendor:
    """Own queued replies, observed requests, and transport resources for one test.

    Args:
        url: Exact allowed local HTTPS origin, assigned after server startup.
        replies: Planned responses consumed in request order.
        paths: Observed request method/path pairs.
        clients: Real aiohttp clients created by the package request helper.
        downloads: Real temporary downloads created by the package.
        trusted: Whether new clients explicitly trust the public test certificate.
        entered: Signal that the server received at least one request.
        release: Signal allowing deliberately suspended response handlers to exit.
    """

    url: str = ""
    replies: list[VendorReply] = field(default_factory=list)
    paths: list[tuple[str, str]] = field(default_factory=list)
    clients: list[aiohttp.ClientSession] = field(default_factory=list)
    downloads: list[_http.Download] = field(default_factory=list)
    trusted: bool = True
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)


@pytest_asyncio.fixture
async def tls_vendor(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[TLSVendor]:
    """Run a real TLS server while retaining external network and process guards.

    Args:
        monkeypatch: Reversible overrides restricted to the exact fixture origin.

    Yields:
        Vendor fixture with real clients and downloaded temporary-file tracking.
    """
    vendor = TLSVendor()
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(
        TLS_FIXTURES / "loopback-cert.pem", TLS_FIXTURES / "loopback-key.pem"
    )
    trusted_context = ssl.create_default_context(
        cafile=str(TLS_FIXTURES / "loopback-cert.pem")
    )

    async def handle(request: web.Request) -> web.StreamResponse:
        """Record one request and emit the planned real HTTP/TLS response.

        Args:
            request: Incoming request from the allowed real aiohttp client.

        Returns:
            Complete, delayed, deliberately truncated, or suspended response.
        """
        vendor.paths.append((request.method, request.raw_path))
        vendor.entered.set()
        if not vendor.replies:
            return web.Response(status=500, body=b"Unplanned test request")
        reply = vendor.replies.pop(0)
        if reply.delay:
            await asyncio.sleep(reply.delay)
        if reply.truncate or reply.hold_stream:
            headers = dict(reply.headers)
            headers["Content-Length"] = str(len(reply.body) + 1024)
            response = web.StreamResponse(status=reply.status, headers=headers)
            await response.prepare(request)
            await response.write(reply.body)
            if reply.truncate:
                assert request.transport is not None
                request.transport.abort()
            else:
                await vendor.release.wait()
            return response
        return web.Response(status=reply.status, body=reply.body, headers=reply.headers)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)
    runner = web.AppRunner(app, shutdown_timeout=0.05)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context)
        await site.start()
        endpoint = ("127.0.0.1", runner.addresses[0][1])
        vendor.url = "https://127.0.0.1:%d" % endpoint[1]

        async def guarded_request(
            client: aiohttp.ClientSession, method: str, url: Any, **kwargs: Any
        ) -> aiohttp.ClientResponse:
            """Permit a real client request only to the fixture's precise TLS origin.

            Args:
                client: Actual aiohttp client managed by the package.
                method: HTTP method requested by the package.
                url: Absolute request URL.
                **kwargs: Timeout, redirect, proxy, and request-body options.

            Returns:
                The real response from the exact allowed server.

            Raises:
                VendorLoopbackOnlyError: If any other origin or proxy is requested.
            """
            parsed = urlsplit(str(url))
            if (
                parsed.scheme != "https"
                or (parsed.hostname, parsed.port) != endpoint
                or kwargs.get("proxy") is not None
            ):
                raise VendorLoopbackOnlyError(
                    "Only the TLS vendor fixture origin is permitted"
                )
            return await _CLIENT_REQUEST(client, method, url, **kwargs)

        def guarded_connect(sock: socket.socket, target: Any) -> None:
            """Connect only to the exact listener owned by this fixture.

            Args:
                sock: TCP socket opened by the real aiohttp connector.
                target: Network address requested by the event loop.

            Raises:
                VendorLoopbackOnlyError: If target is not the fixture endpoint.
            """
            if target != endpoint:
                raise VendorLoopbackOnlyError(
                    "Only the TLS fixture socket is permitted"
                )
            return _SOCKET_CONNECT(sock, target)

        def guarded_connect_ex(sock: socket.socket, target: Any) -> int:
            """Perform connect_ex only against the fixture's exact local listener.

            Args:
                sock: TCP socket opened by the real aiohttp connector.
                target: Requested network address.

            Returns:
                The operating system's connect status.

            Raises:
                VendorLoopbackOnlyError: If target is not the fixture endpoint.
            """
            if target != endpoint:
                raise VendorLoopbackOnlyError(
                    "Only the TLS fixture socket is permitted"
                )
            return _SOCKET_CONNECT_EX(sock, target)

        def client_factory() -> aiohttp.ClientSession:
            """Create a real client with isolated trust and no environment proxy.

            Returns:
                Actual aiohttp client owned and closed by the package.
            """
            context = (
                trusted_context if vendor.trusted else ssl.create_default_context()
            )
            client = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=context), trust_env=False
            )
            vendor.clients.append(client)
            return client

        def observed_download() -> _http.Download:
            """Track an unmodified temporary download for ownership assertions.

            Returns:
                Real package Download with unchanged stream and hashing behavior.
            """
            download = _DOWNLOAD_CLASS()
            vendor.downloads.append(download)
            return download

        monkeypatch.setattr(aiohttp.ClientSession, "_request", guarded_request)
        monkeypatch.setattr(socket.socket, "connect", guarded_connect)
        monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
        monkeypatch.setattr(driver_module, "ClientSession", client_factory)
        monkeypatch.setattr(_http, "Download", observed_download)
        yield vendor
    finally:
        vendor.release.set()
        await runner.cleanup()
        for client in vendor.clients:
            await client.close()
        for download in vendor.downloads:
            download.close()


@pytest.mark.asyncio
async def test_tls_vendor_fixture_blocks_unapproved_origins(
    tls_vendor: TLSVendor,
) -> None:
    """Ensure the narrow test allowlist does not grant general network access.

    Args:
        tls_vendor: Running loopback TLS fixture.
    """
    async with aiohttp.ClientSession(trust_env=False) as client:
        for url in (
            "https://example.invalid/",
            tls_vendor.url.replace("https://", "http://"),
            "https://127.0.0.1:1/",
        ):
            with pytest.raises(VendorLoopbackOnlyError):
                await client.get(url)
    with socket.socket() as client_socket:
        with pytest.raises(VendorLoopbackOnlyError):
            client_socket.connect(("127.0.0.1", 1))
        with pytest.raises(VendorLoopbackOnlyError):
            client_socket.connect_ex(("127.0.0.1", 1))
    assert tls_vendor.paths == []


@pytest.mark.parametrize(
    "kind,body,expected",
    [
        ("text", "Chrome 驱动".encode(), "Chrome 驱动"),
        ("json", b'{"version":"120.0.1.2"}', {"version": "120.0.1.2"}),
        ("url", b"", "manifest.json"),
    ],
)
@pytest.mark.asyncio
async def test_trusted_tls_metadata_uses_real_client_and_closes_it(
    tls_vendor: TLSVendor, tmp_path: Path, kind: str, body: bytes, expected: Any
) -> None:
    """Decode actual TLS metadata and release the owned HTTP client afterward.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        kind: Package metadata response mode.
        body: Independently supplied wire bytes.
        expected: Expected decoded package return value.
    """
    tls_vendor.replies.append(VendorReply(body=body))
    manager = ChromeDriverManager(directory=str(tmp_path))
    method = getattr(manager, "_request_response_" + kind)
    assert await method(tls_vendor.url + "/manifest.json") == expected
    assert tls_vendor.paths == [("GET", "/manifest.json")]
    assert len(tls_vendor.clients) == 1
    assert tls_vendor.clients[0].closed


@pytest.mark.asyncio
async def test_untrusted_tls_certificate_fails_without_retry(
    tls_vendor: TLSVendor, tmp_path: Path
) -> None:
    """Reject the self-signed fixture certificate when it is not explicitly trusted.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
    """
    tls_vendor.trusted = False
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(
        errors.DriverRequestFailedError, match="TLS verification"
    ) as captured:
        await manager._request_response_json(tls_vendor.url + "/manifest.json")
    assert isinstance(captured.value.__cause__, aiohttp.ClientSSLError)
    assert tls_vendor.paths == []
    assert len(tls_vendor.clients) == 1
    assert tls_vendor.clients[0].closed
    assert tls_vendor.downloads == []


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.asyncio
async def test_real_https_redirects_preserve_metadata_contract(
    tls_vendor: TLSVendor, tmp_path: Path, status: int
) -> None:
    """Follow validated relative TLS redirects using the real HTTP response headers.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        status: HTTP redirect status emitted by the fixture.
    """
    tls_vendor.replies.extend(
        [
            VendorReply(status=status, headers={"Location": "/final"}),
            VendorReply(body=b"120.0.1.2"),
        ]
    )
    manager = ChromeDriverManager(directory=str(tmp_path))
    assert (
        await manager._request_response_text(tls_vendor.url + "/redirect")
        == "120.0.1.2"
    )
    assert tls_vendor.paths == [("GET", "/redirect"), ("GET", "/final")]
    assert all(client.closed for client in tls_vendor.clients)


@pytest.mark.parametrize("target", ["downgrade", "credentials"])
@pytest.mark.asyncio
async def test_invalid_tls_redirect_is_rejected_before_second_connection(
    tls_vendor: TLSVendor, tmp_path: Path, target: str
) -> None:
    """Reject HTTP downgrades and credential-bearing URLs before following redirects.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        target: Invalid redirect category under test.
    """
    location = (
        tls_vendor.url.replace("https://", "http://")
        if target == "downgrade"
        else tls_vendor.url.replace("https://", "https://user:password@")
    )
    tls_vendor.replies.append(
        VendorReply(status=302, headers={"Location": location + "/forbidden"})
    )
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(
        errors.DriverRequestFailedError, match="HTTPS without URL credentials"
    ):
        await manager._request_response_text(tls_vendor.url + "/redirect")
    assert tls_vendor.paths == [("GET", "/redirect")]
    assert all(client.closed for client in tls_vendor.clients)


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.asyncio
async def test_real_retry_after_is_bounded_and_recovers(
    tls_vendor: TLSVendor, tmp_path: Path, status: int
) -> None:
    """Retry transient real HTTP statuses and return a subsequent successful response.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        status: Retryable status emitted twice before successful metadata.
    """
    tls_vendor.replies.extend(
        [
            VendorReply(status=status, headers={"Retry-After": "0"}),
            VendorReply(status=status, headers={"Retry-After": "0"}),
            VendorReply(body=b"ready"),
        ]
    )
    manager = ChromeDriverManager(directory=str(tmp_path))
    assert await manager._request_response_text(tls_vendor.url + "/retry") == "ready"
    assert tls_vendor.paths == [("GET", "/retry")] * 3
    assert len(tls_vendor.clients) == 1
    assert tls_vendor.clients[0].closed


@pytest.mark.parametrize(
    "kind,error",
    [
        ("text", errors.DriverRequestTimeoutError),
        ("file", errors.FileDownloadTimeoutError),
    ],
)
@pytest.mark.asyncio
async def test_real_retry_delay_consumes_total_deadline(
    tls_vendor: TLSVendor, tmp_path: Path, kind: str, error: type[Exception]
) -> None:
    """Bound Retry-After by the complete request budget and close its real client.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        kind: Text metadata or streamed download mode.
        error: Expected deadline exception for that operation.
    """
    tls_vendor.replies.append(VendorReply(status=429, headers={"Retry-After": "30"}))
    manager = ChromeDriverManager(
        directory=str(tmp_path), request_timeout=0.25, download_timeout=0.25
    )
    with pytest.raises(error):
        await asyncio.wait_for(
            getattr(manager, "_request_response_" + kind)(
                tls_vendor.url + "/slow-retry"
            ),
            2,
        )
    assert tls_vendor.paths == [("GET", "/slow-retry")]
    assert all(client.closed for client in tls_vendor.clients)


@pytest.mark.asyncio
async def test_truncated_tls_stream_retries_and_closes_every_partial_file(
    tls_vendor: TLSVendor, tmp_path: Path
) -> None:
    """Discard every real partial download when the peer aborts all three attempts.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
    """
    tls_vendor.replies.extend(
        [VendorReply(body=b"partial ZIP bytes", truncate=True) for _ in range(3)]
    )
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(errors.DriverRequestFailedError, match="three attempts"):
        await manager._request_response_file(tls_vendor.url + "/driver.zip")
    assert tls_vendor.paths == [("GET", "/driver.zip")] * 3
    assert len(tls_vendor.downloads) == 3
    assert all(download.stream.closed for download in tls_vendor.downloads)
    assert all(client.closed for client in tls_vendor.clients)
    assert manager._cache_view.cached_versions() == []


async def wait_for_download_bytes(vendor: TLSVendor) -> None:
    """Wait until at least one chunk has reached an actual temporary download.

    Args:
        vendor: Fixture tracking the real download objects.
    """
    while not vendor.downloads or vendor.downloads[-1].stream.tell() == 0:
        await asyncio.sleep(0.001)


@pytest.mark.parametrize("cancel", [True, False])
@pytest.mark.asyncio
async def test_inflight_tls_download_cancellation_or_timeout_cleans_partial_state(
    tls_vendor: TLSVendor, tmp_path: Path, cancel: bool
) -> None:
    """Clean a partially written download after cancellation or its total deadline.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        cancel: Whether to cancel explicitly instead of waiting for the deadline.
    """
    tls_vendor.replies.append(VendorReply(body=b"partial archive", hold_stream=True))
    manager = ChromeDriverManager(
        directory=str(tmp_path), download_timeout=2 if cancel else 0.5
    )
    task = asyncio.create_task(
        manager._request_response_file(tls_vendor.url + "/driver.zip")
    )
    try:
        await asyncio.wait_for(wait_for_download_bytes(tls_vendor), 1)
        if cancel:
            task.cancel()
        with pytest.raises(
            asyncio.CancelledError if cancel else errors.FileDownloadTimeoutError
        ):
            await asyncio.wait_for(task, 2)
        assert len(tls_vendor.downloads) == 1
        assert tls_vendor.downloads[0].stream.closed
        assert all(client.closed for client in tls_vendor.clients)
        assert manager._cache_view.cached_versions() == []
        tls_vendor.replies.append(VendorReply(body=b"retry completed"))
        result = await manager._request_response_file(tls_vendor.url + "/retry.zip")
        try:
            assert result["content"].stream.read() == b"retry completed"
        finally:
            result["content"].close()
    finally:
        tls_vendor.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_compressed_metadata_limit_applies_after_real_http_decompression(
    tls_vendor: TLSVendor, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a compressed body whose decoded size exceeds the metadata limit.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        monkeypatch: Reversible override of the metadata-size limit for this fixture.
    """
    compressed = gzip.compress(b"x" * 4096)
    assert len(compressed) < 128
    monkeypatch.setattr(_http, "MAX_METADATA_BYTES", 128)
    tls_vendor.replies.append(
        VendorReply(body=compressed, headers={"Content-Encoding": "gzip"})
    )
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(errors.DriverRequestFailedError, match="size limit"):
        await manager._request_response_text(tls_vendor.url + "/compressed")
    assert len(tls_vendor.paths) == 1
    assert all(client.closed for client in tls_vendor.clients)


@pytest.mark.asyncio
async def test_real_tls_provisioning_publishes_archive_and_reuses_cache_offline(
    tls_vendor: TLSVendor, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve, stream, unpack, and publish a driver, then reuse it without HTTP.

    Args:
        tls_vendor: Running loopback TLS fixture serving metadata and ZIP bytes.
        tmp_path: Disposable browser-path and cache parent.
        monkeypatch: Reversible endpoint/platform and inert executable-probe overrides.
    """
    version = ChromiumVersion("120.0.1.2")
    browser = tmp_path / "inert-browser"
    browser.write_bytes(b"This fixture is never executed")
    payload = b"This downloaded driver fixture is never executed"
    archive = BytesIO()
    with ZipFile(archive, "w") as output:
        output.writestr("msedgedriver", payload)
    wire_bytes = archive.getvalue()
    tls_vendor.replies.extend(
        [VendorReply(body=str(version).encode()), VendorReply(body=wire_bytes)]
    )
    manager = EdgeDriverManager(directory=str(tmp_path))
    monkeypatch.setattr(manager, "_AZUREEDGE_ENDPOINT_URL", tls_vendor.url)
    monkeypatch.setattr(manager, "_DriverManager__os_name", "linux")
    monkeypatch.setattr(manager, "_DriverManager__os_arch", "64")
    monkeypatch.setattr(manager, "_DriverManager__os_is_arm", False)
    monkeypatch.setattr(manager, "_detect_browser_version", lambda path: version)
    online = await manager.install_result(
        "build", binary=str(browser), validate_compatibility=True
    )
    assert online.driver_version == "120.0.1.2"
    assert online.browser_version == "120.0.1.2"
    location = Path(online.driver_location)
    assert location.read_bytes() == payload
    assert tls_vendor.paths == [
        ("GET", "/LATEST_RELEASE_120_LINUX"),
        ("GET", "/120.0.1.2/edgedriver_linux64.zip"),
    ]
    assert len(tls_vendor.clients) == 1
    assert tls_vendor.clients[0].closed
    assert len(tls_vendor.downloads) == 1
    download = tls_vendor.downloads[0]
    assert download.size == len(wire_bytes)
    assert download.sha256.hexdigest() == hashlib.sha256(wire_bytes).hexdigest()
    assert download.stream.closed
    assert manager._cache_view.cached_versions() == ["120.0.1.2"]
    before = list(tls_vendor.paths)
    offline = await manager.install_result(
        "offline", binary=str(browser), validate_compatibility=True
    )
    assert offline.driver_location == online.driver_location
    assert offline.request.policy == "offline"
    assert tls_vendor.paths == before
    assert len(tls_vendor.clients) == 1
    manifests = list(tmp_path.glob(".aselenium/v2/*/artifact.json"))
    assert len(manifests) == 1
    assert (
        json.loads(manifests[0].read_text(encoding="utf-8"))["version"] == "120.0.1.2"
    )


@pytest.mark.parametrize(
    "status,error",
    [(429, errors.DriverRequestRateLimitError), (503, errors.DriverRequestFailedError)],
)
@pytest.mark.asyncio
async def test_real_transient_failures_stop_after_three_attempts(
    tls_vendor: TLSVendor, tmp_path: Path, status: int, error: type[Exception]
) -> None:
    """Exhaust the retry budget without issuing a fourth real HTTP request.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        status: Retryable HTTP status returned on all attempts.
        error: Expected package exception after retry exhaustion.
    """
    tls_vendor.replies.extend(
        [VendorReply(status=status, headers={"Retry-After": "0"}) for _ in range(4)]
    )
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(error, match="three attempts"):
        await manager._request_response_text(tls_vendor.url + "/unavailable")
    assert tls_vendor.paths == [("GET", "/unavailable")] * 3
    assert len(tls_vendor.replies) == 1
    assert all(client.closed for client in tls_vendor.clients)


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_real_authorization_failure_is_not_retried(
    tls_vendor: TLSVendor, tmp_path: Path, status: int
) -> None:
    """Fail once for denied vendor authorization instead of treating it as transient.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
        status: Non-retryable authentication or authorization status.
    """
    tls_vendor.replies.append(VendorReply(status=status))
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(errors.DriverRequestFailedError, match="rejected"):
        await manager._request_response_file(tls_vendor.url + "/denied.zip")
    assert tls_vendor.paths == [("GET", "/denied.zip")]
    assert tls_vendor.downloads == []
    assert all(client.closed for client in tls_vendor.clients)


@pytest.mark.asyncio
async def test_real_redirect_loop_has_a_six_request_limit(
    tls_vendor: TLSVendor, tmp_path: Path
) -> None:
    """Bound a redirect cycle without issuing unlimited real TLS requests.

    Args:
        tls_vendor: Running loopback TLS fixture.
        tmp_path: Disposable driver-manager cache parent.
    """
    tls_vendor.replies.extend(
        [VendorReply(status=302, headers={"Location": "/cycle"}) for _ in range(7)]
    )
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(
        errors.DriverRequestFailedError, match="excessive vendor redirect"
    ):
        await manager._request_response_text(tls_vendor.url + "/cycle")
    assert tls_vendor.paths == [("GET", "/cycle")] * 6
    assert len(tls_vendor.replies) == 1
    assert all(client.closed for client in tls_vendor.clients)


@pytest.mark.asyncio
async def test_corrupt_download_cannot_publish_and_retry_then_reuses_offline_cache(
    tls_vendor: TLSVendor, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a complete but corrupt downloaded ZIP without polluting cache state.

    Args:
        tls_vendor: Running loopback TLS fixture serving bad then valid archive bytes.
        tmp_path: Disposable browser-path and driver cache parent.
        monkeypatch: Reversible local endpoint/platform and inert probe overrides.
    """
    version = ChromiumVersion("120.0.1.2")
    browser = tmp_path / "inert-browser"
    browser.write_bytes(b"never executed")
    manager = EdgeDriverManager(directory=str(tmp_path))
    monkeypatch.setattr(manager, "_AZUREEDGE_ENDPOINT_URL", tls_vendor.url)
    monkeypatch.setattr(manager, "_DriverManager__os_name", "linux")
    monkeypatch.setattr(manager, "_DriverManager__os_arch", "64")
    monkeypatch.setattr(manager, "_DriverManager__os_is_arm", False)
    monkeypatch.setattr(manager, "_detect_browser_version", lambda path: version)
    tls_vendor.replies.append(VendorReply(body=b"this is not a ZIP archive"))
    with pytest.raises(errors.InvalidDownloadFileError):
        await manager.install_result(str(version), binary=str(browser), policy="exact")
    assert manager.last_result is None
    assert manager._cache_view.cached_versions() == []
    assert not list(tmp_path.glob(".aselenium/v2/*/artifact.json"))
    assert not list(tmp_path.glob(".aselenium/v2/.aselenium-stage-*"))
    assert all(download.stream.closed for download in tls_vendor.downloads)
    assert all(client.closed for client in tls_vendor.clients)
    archive = BytesIO()
    with ZipFile(archive, "w") as output:
        output.writestr("msedgedriver", b"verified inert payload")
    tls_vendor.replies.append(VendorReply(body=archive.getvalue()))
    result = await manager.install_result(
        str(version), binary=str(browser), policy="exact"
    )
    assert Path(result.driver_location).read_bytes() == b"verified inert payload"
    request_count = len(tls_vendor.paths)
    reused = await manager.install_result(
        str(version), binary=str(browser), policy="offline"
    )
    assert reused.driver_location == result.driver_location
    assert len(tls_vendor.paths) == request_count == 2
    assert all(download.stream.closed for download in tls_vendor.downloads)
    assert all(client.closed for client in tls_vendor.clients)
