"""Owned vendor GET requests with bounded bodies and classified retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from urllib.parse import urljoin, urlsplit
from weakref import ReferenceType, WeakKeyDictionary, ref

from aiohttp import (
    ClientConnectionError,
    ClientError,
    ClientPayloadError,
    ClientResponse,
    ClientSession,
    ClientSSLError,
    ClientTimeout,
)

from aselenium import errors
from aselenium._async import finish_owned, run_blocking

if TYPE_CHECKING:
    from aselenium.manager.driver import DriverManager

MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
ResponseKind: TypeAlias = Literal["file", "json", "text", "url"]
_DOWNLOAD_GATES: WeakKeyDictionary[
    asyncio.AbstractEventLoop, ReferenceType[asyncio.Semaphore]
] = WeakKeyDictionary()


class Download:
    """Own a temporary vendor payload and its running SHA-256 digest.

    ``size`` is populated with the complete observed byte count after streaming
    succeeds; partial payloads are closed and discarded by the request helper.
    """

    def __init__(self) -> None:
        """Open a private temporary binary stream and initialize digest state."""
        self.stream = tempfile.TemporaryFile()
        self.sha256 = hashlib.sha256()
        self.size = 0

    def close(self) -> None:
        """Close the temporary payload stream and release its file descriptor."""
        self.stream.close()

    def write(self, chunk: bytes) -> None:
        """Append one response chunk and update the running SHA-256 digest.

        Args:
            chunk: Downloaded bytes to append to the temporary stream.
        """
        self.stream.write(chunk)
        self.sha256.update(chunk)


def retry_delay(headers: Mapping[str, str], attempt: int) -> float:
    """Parse ``Retry-After`` or calculate bounded exponential backoff.

    Args:
        headers: HTTP response headers that may contain ``Retry-After``.
        attempt: Zero-based retry attempt used for exponential backoff.

    Returns:
        Nonnegative retry delay in seconds, capped at thirty seconds.
    """
    value = headers.get("Retry-After", "")
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            seconds = 0.25 * 2**attempt
    return max(0, min(seconds, 30))


async def request(
    manager: DriverManager,
    url: str,
    kind: ResponseKind,
    session_factory: Callable[[], ClientSession],
) -> Any:
    """Perform a bounded vendor GET with invocation-owned resources.

    File downloads additionally share a four-request admission gate per event
    loop. The outer deadline includes time spent waiting for that capacity.

    Args:
        manager: Driver manager supplying online policy, timeouts, proxy, and
            invocation-owned resources.
        url: HTTPS vendor resource URL without embedded credentials.
        kind: Required response representation: file, JSON, text, or final URL
            filename.
        session_factory: Factory that creates the owned HTTP client session.

    Returns:
        Text, decoded JSON, the final URL's last path component for ``"url"``,
        or an owned download record for ``"file"``. A 404 response returns
        ``None``.

    Raises:
        errors.DriverRequestFailedError: URL validation, transport, response
            status, response-size, or decoding checks fail.
        errors.FileDownloadTimeoutError: The download budget expires, including
            admission and client-creation waits. Owned cleanup finishes before
            the exception propagates.
        errors.DriverRequestTimeoutError: A metadata request exceeds its total
            budget.
    """
    manager._require_online()
    timeout = manager.download_timeout if kind == "file" else manager.requests_timeout
    try:
        return await asyncio.wait_for(
            _admitted_request(manager, url, kind, session_factory), timeout
        )
    except errors.AseleniumError:
        # ``_request`` has already translated transport/client deadlines into
        # the package's public timeout hierarchy.  Those timeout classes also
        # inherit ``asyncio.TimeoutError``, so preserve their type, message,
        # traceback, and original cause instead of wrapping them a second time.
        raise
    except asyncio.TimeoutError as cause:
        error = (
            errors.FileDownloadTimeoutError
            if kind == "file"
            else errors.DriverRequestTimeoutError
        )
        raise error("Vendor GET exceeded its total request deadline") from cause


async def _admitted_request(
    manager: DriverManager,
    url: str,
    kind: ResponseKind,
    session_factory: Callable[[], ClientSession],
) -> Any:
    """Gate file-download concurrency before issuing the vendor request.

    Args:
        manager: Manager supplying request policy and invocation-owned resources.
        url: HTTPS vendor resource URL.
        kind: Response mode: file, json, text, or url.
        session_factory: Factory used only after admission to create an HTTP client.

    Returns:
        Decoded metadata, an owned download record, or ``None`` for HTTP 404.
    """
    if kind != "file":
        return await _request(manager, url, kind, session_factory)
    loop = asyncio.get_running_loop()
    reference = _DOWNLOAD_GATES.get(loop)
    gate = reference() if reference is not None else None
    if gate is None:
        gate = asyncio.Semaphore(4)
        _DOWNLOAD_GATES[loop] = ref(gate)
    async with gate:
        return await _request(manager, url, kind, session_factory)


def _validate_vendor_url(url: str) -> None:
    """Require an HTTPS vendor URL without embedded credentials.

    Args:
        url: Candidate vendor resource or redirect URL.

    Raises:
        errors.DriverRequestFailedError: The URL is not HTTPS, has no hostname,
            or embeds a username or password.
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise errors.DriverRequestFailedError(
            "Vendor requests require HTTPS without URL credentials"
        )


@asynccontextmanager
async def _get_response(
    session: ClientSession, url: str, deadline: float, proxy: str | None
) -> AsyncIterator[ClientResponse]:
    """Follow a bounded chain of validated HTTPS redirects for an idempotent GET.

    Args:
        session: Active HTTP client owned by this provisioning invocation.
        url: Initial HTTPS vendor resource URL.
        deadline: Absolute monotonic deadline shared by the request and redirects.
        proxy: Explicit provisioning proxy URL, or None for a direct connection.

    Yields:
        The first non-redirect response. The client response closes when the
        context exits.

    Raises:
        errors.DriverRequestFailedError: A redirect is missing its location,
            exceeds the five-hop limit, or points to a disallowed URL.
        asyncio.TimeoutError: The shared monotonic deadline expires.
    """
    # CDN redirects may change hosts, but may never downgrade transport or
    # introduce credentials. Validate before following, not after the request.
    for redirect in range(6):
        _validate_vendor_url(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        async with session.get(
            url,
            timeout=ClientTimeout(total=remaining),
            proxy=proxy,
            allow_redirects=False,
        ) as response:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if redirect == 5 or not location:
                    raise errors.DriverRequestFailedError(
                        "Invalid or excessive vendor redirect"
                    )
                url = urljoin(url, location)
                continue
            yield response
            return


async def _request(
    manager: DriverManager,
    url: str,
    kind: ResponseKind,
    session_factory: Callable[[], ClientSession],
) -> Any:
    """Fetch one vendor resource with a deadline, body limit, and safe retries.

    Args:
        manager: Driver manager supplying policy and invocation resources.
        url: Candidate HTTPS vendor resource URL, validated before network I/O.
        kind: Required response representation.
        session_factory: Factory that creates an HTTP client when the invocation
            does not already own one.

    Returns:
        Text, decoded JSON, a final URL filename, an owned download record, or
        ``None`` for HTTP 404.

    Raises:
        errors.DriverRequestRateLimitError: Three attempts all receive HTTP 429.
        errors.DriverRequestFailedError: TLS, transport, status, response-size,
            decoding, or JSON validation fails.
        errors.DriverRequestTimeoutError: A metadata request exceeds its deadline.
        errors.FileDownloadTimeoutError: A file request exceeds its deadline.
    """
    manager._require_online()
    _validate_vendor_url(url)
    active = manager._invocation.get()
    stack = active.resources if active is not None else AsyncExitStack()
    try:
        if active is None:
            session = await stack.enter_async_context(session_factory())
        else:
            async with active.client_lock:
                if active.client is None:
                    active.client = await stack.enter_async_context(session_factory())
                assert active.client is not None
                session = active.client
        timeout = (
            manager.download_timeout if kind == "file" else manager.requests_timeout
        )
        deadline = time.monotonic() + timeout
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            try:
                async with _get_response(
                    session, url, deadline, manager.proxy
                ) as response:
                    code = response.status
                    if code == 404:
                        return None
                    if code in {429, 500, 502, 503, 504}:
                        if attempt == 2:
                            error = (
                                errors.DriverRequestRateLimitError
                                if code == 429
                                else errors.DriverRequestFailedError
                            )
                            raise error(
                                "Vendor GET failed after three attempts (HTTP %s)"
                                % code
                            )
                        delay = retry_delay(response.headers, attempt)
                    elif code != 200:
                        raise errors.DriverRequestFailedError(
                            "Vendor GET rejected (HTTP %s)" % code
                        )
                    else:
                        if kind == "url":
                            return response.url.name
                        limit = (
                            MAX_DOWNLOAD_BYTES if kind == "file" else MAX_METADATA_BYTES
                        )
                        length = response.headers.get("Content-Length")
                        if length is not None and int(length) > limit:
                            raise errors.DriverRequestFailedError(
                                "Vendor response exceeds size limit"
                            )
                        download = Download() if kind == "file" else None
                        data = bytearray()
                        count = 0
                        try:
                            async for chunk in response.content.iter_chunked(
                                256 * 1024
                            ):
                                count += len(chunk)
                                if count > limit:
                                    raise errors.DriverRequestFailedError(
                                        "Vendor response exceeds size limit"
                                    )
                                if download is None:
                                    data.extend(chunk)
                                else:
                                    await run_blocking(download.write, chunk)
                            if download is not None:
                                download.size = count
                                download.stream.seek(0)
                                if active is not None:
                                    active.resources.callback(download.close)
                                return {"url": url, "content": download}
                            try:
                                text = data.decode("utf-8")
                            except UnicodeDecodeError:
                                text = data.decode("utf-16")
                            return json.loads(text) if kind == "json" else text
                        except BaseException:
                            if download is not None:
                                download.close()
                            raise
            except (asyncio.TimeoutError, TimeoutError):
                raise
            except ClientSSLError as cause:
                raise errors.DriverRequestFailedError(
                    "Vendor TLS verification failed"
                ) from cause
            except (ClientConnectionError, ClientPayloadError) as cause:
                if attempt == 2:
                    raise errors.DriverRequestFailedError(
                        "Vendor GET transport failed after three attempts"
                    ) from cause
                delay = 0.25 * 2**attempt
            except ClientError as cause:
                # Only idempotent vendor GETs are retried. TLS/auth failures do
                # not become successful cache misses or silent downgrade paths.
                raise errors.DriverRequestFailedError(
                    "Vendor GET transport failed"
                ) from cause
            await asyncio.sleep(min(delay, max(0, deadline - time.monotonic())))
    except (asyncio.TimeoutError, TimeoutError) as cause:
        error = (
            errors.FileDownloadTimeoutError
            if kind == "file"
            else errors.DriverRequestTimeoutError
        )
        raise error("Vendor GET exceeded its request deadline") from cause
    except (ValueError, UnicodeError) as cause:
        raise errors.DriverRequestFailedError("Malformed vendor response") from cause
    finally:
        if active is None:
            await finish_owned(stack.aclose())
