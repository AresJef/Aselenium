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
from typing import (
    TYPE_CHECKING,
    Any,
)
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
_DOWNLOAD_GATES: WeakKeyDictionary[
    asyncio.AbstractEventLoop, ReferenceType[asyncio.Semaphore]
] = WeakKeyDictionary()


class Download:
    """Temporary file with deterministic ownership and an observed SHA-256."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self.stream = tempfile.TemporaryFile()
        self.sha256 = hashlib.sha256()
        self.size = 0

    def close(self) -> None:
        """Close the temporary download stream and release its file descriptor."""
        self.stream.close()

    def write(self, chunk: bytes) -> None:
        """Append a download chunk and update its observed SHA-256.

        Args:
            chunk: Downloaded bytes to append to the temporary stream.
        """
        self.stream.write(chunk)
        self.sha256.update(chunk)


def retry_delay(headers: Mapping[str, str], attempt: int) -> float:
    """Parse Retry-After or calculate a bounded exponential retry delay.

    Args:
        headers: HTTP response headers used to interpret Retry-After.
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
    kind: str,
    session_factory: Callable[[], ClientSession],
) -> Any:
    """Perform a bounded vendor GET with shared invocation resources and download admission control.

    Args:
        manager: Driver manager owning the provisioning state and request configuration.
        url: URL used for the request or browser navigation.
        kind: Operation or artifact kind selected by the caller.
        session_factory: Factory creating the HTTP client session owned by this request scope.

    Returns:
        Text, decoded JSON, the final URL's last path component (kind="url"),
        or an owned download record (kind="file"). A missing resource returns None.

    Raises:
        errors.FileDownloadTimeoutError: The download budget expires, including
            admission and client-creation waits. Owned cleanup finishes before returning.
        errors.DriverRequestTimeoutError: A metadata request exceeds its total budget.
    """
    manager._require_online()
    timeout = manager.download_timeout if kind == "file" else manager.requests_timeout
    try:
        return await asyncio.wait_for(
            _admitted_request(manager, url, kind, session_factory), timeout
        )
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
    kind: str,
    session_factory: Callable[[], ClientSession],
) -> Any:
    """Wait for download capacity inside the caller's total request budget.

    Args:
        manager: Manager supplying request policy and invocation-owned resources.
        url: HTTPS vendor resource URL.
        kind: Response mode: file, json, text, or url.
        session_factory: Factory used only after admission to create an HTTP client.

    Returns:
        The decoded resource, or None for a missing vendor resource.
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
        url: URL used for the request or browser navigation.
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
    # CDN redirects may change hosts, but may never downgrade transport or
    # introduce credentials. Validate before following, not after the request.
    """Follow a bounded chain of validated HTTPS redirects for an idempotent GET.

    Args:
        session: Active session that owns the browser or HTTP operation.
        url: URL used for the request or browser navigation.
        deadline: Absolute monotonic deadline shared by the request and redirects.
        proxy: Explicit provisioning proxy URL, or None for a direct connection.

    Yields:
        The resource managed by this context; cleanup runs when the context exits.
    """
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
    kind: str,
    session_factory: Callable[[], ClientSession],
) -> Any:
    """Fetch one vendor resource with a total deadline, bounded body, and classified retries.

    Args:
        manager: Driver manager owning the provisioning state and request configuration.
        url: URL used for the request or browser navigation.
        kind: Operation or artifact kind selected by the caller.
        session_factory: Factory creating the HTTP client session owned by this request scope.

    Returns:
        Decoded response data for the requested transport operation.
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
