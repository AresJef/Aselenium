"""Exercise manager HTTP helpers against in-memory vendor responses only."""

from __future__ import annotations

import asyncio
import json as json_module
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest

from aselenium import errors
from aselenium.manager import ChromeDriverManager, _http
from aselenium.manager import driver as driver_module
from aselenium.manager._http import Download
from aselenium.manager._installation import InstallationRequest, Invocation


@pytest.fixture
def fake_vendor(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fake vendor.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    responses = {}
    calls = []
    sessions = []
    yield_scheduler = asyncio.sleep

    class Response:
        """Represent Response using the inherited implementation."""

        def __init__(
            self,
            *,
            status: int = 200,
            text: str = "",
            json: Any = None,
            body: bytes = b"",
            name: str = "release",
            utf16: bool = False,
        ) -> None:
            """Initialize the instance with the supplied configuration.

            Args:
                status: Fixture or parametrized status input for this regression.
                text: Fixture or parametrized text input for this regression.
                json: Fixture or parametrized json input for this regression.
                body: Fixture or parametrized body input for this regression.
                name: Fixture or parametrized name input for this regression.
                utf16: Fixture or parametrized utf16 input for this regression.
            """
            self.status = status
            self._text = text
            self._json = json
            self._body = body
            self._utf16 = utf16
            self.url = SimpleNamespace(name=name)
            self.content = SimpleNamespace(read=self.read, iter_chunked=self.chunks)
            self.headers = {}

        async def chunks(self, size: Any) -> AsyncIterator[Any]:
            """Chunks.

            Args:
                size: Fixture or parametrized size input for this regression.

            Yields:
                Values produced by this iterator in iteration order.
            """
            payload = self._body or (
                json_module.dumps(self._json).encode()
                if self._json is not None
                else self._text.encode("utf-16" if self._utf16 else "utf-8")
            )
            for offset in range(0, len(payload), size):
                yield payload[offset : offset + size]

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
            return False

        async def text(self, encoding: Any) -> Any:
            """Text.

            Args:
                encoding: Fixture or parametrized encoding input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            if self._utf16 and encoding == "utf-8":
                raise UnicodeDecodeError(
                    "utf-8", b"\xff", 0, 1, "synthetic UTF-16 response"
                )
            return self._text

        async def json(self, encoding: Any) -> Any:
            """Json.

            Args:
                encoding: Fixture or parametrized encoding input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return self._json

        async def read(self) -> Any:
            """Read.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            return self._body

    class Session:
        """Represent Session using the inherited implementation."""

        def __init__(self) -> None:
            """Initialize the instance."""
            self.closed = False
            sessions.append(self)

        async def __aenter__(self) -> Session:
            # Real client adapters may suspend while opening; exercise races.
            """Start the owned asynchronous context and return its managed value.

            Returns:
                The Session value produced by this operation.
            """
            await yield_scheduler(0)
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Await owned cleanup when leaving the asynchronous context.

            Args:
                *args: Fixture or parametrized args input for this regression.
            """
            self.closed = True
            return False

        def get(self, url: Any, **kwargs: Any) -> Any:
            """Get.

            Args:
                url: Fixture or parametrized url input for this regression.
                **kwargs: Fixture or parametrized kwargs input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            calls.append((url, kwargs))
            # Unexpected fixture URLs must not be swallowed by broad excepts.
            if url not in responses:
                raise BaseException("Unregistered fake vendor URL: " + url)
            response = responses[url]
            if isinstance(response, BaseException):
                raise response
            return response

    monkeypatch.setattr(driver_module, "ClientSession", Session)
    return SimpleNamespace(
        responses=responses, calls=calls, sessions=sessions, response=Response
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "payload", "expected"),
    [
        ("_request_response_text", {"text": "120.0.6099.71"}, "120.0.6099.71"),
        (
            "_request_response_json",
            {"json": {"channels": {"Stable": {"version": "120.0.6099.71"}}}},
            {"channels": {"Stable": {"version": "120.0.6099.71"}}},
        ),
        ("_request_response_url", {"name": "v0.33.0"}, "v0.33.0"),
        (
            "_request_response_file",
            {"body": b"synthetic archive"},
            {"url": "https://vendor.invalid/artifact", "content": b"synthetic archive"},
        ),
    ],
)
async def test_vendor_success_preserves_payload_and_request_settings(
    tmp_path: Path, fake_vendor: Any, method: Any, payload: Any, expected: Any
) -> None:
    """Verify vendor success preserves payload and request settings.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
        method: Fixture or parametrized method input for this regression.
        payload: Fixture or parametrized payload input for this regression.
        expected: Fixture or parametrized expected input for this regression.
    """
    manager = ChromeDriverManager(
        directory=str(tmp_path),
        request_timeout=7,
        download_timeout=13,
        proxy="http://proxy.invalid:8080",
    )
    url = "https://vendor.invalid/artifact"
    fake_vendor.responses[url] = fake_vendor.response(**payload)

    result = await getattr(manager, method)(url)
    if method == "_request_response_file":
        assert isinstance(result["content"], Download)
        content = result["content"]
        result["content"] = content.stream.read()
        content.close()
    assert result == expected

    assert len(fake_vendor.calls) == 1
    requested_url, options = fake_vendor.calls[0]
    assert requested_url == url
    assert options["proxy"] == "http://proxy.invalid:8080"
    assert options["timeout"].total == pytest.approx(
        13 if method == "_request_response_file" else 7, abs=0.1
    )
    assert all(session.closed for session in fake_vendor.sessions)


@pytest.mark.asyncio
async def test_vendor_text_utf16_fallback(tmp_path: Path, fake_vendor: Any) -> None:
    """Verify vendor text utf16 fallback.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
    """
    manager = ChromeDriverManager(directory=str(tmp_path))
    url = "https://vendor.invalid/version"
    fake_vendor.responses[url] = fake_vendor.response(text="120.0.6099.71", utf16=True)
    assert await manager._request_response_text(url) == "120.0.6099.71"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    [
        "_request_response_text",
        "_request_response_json",
        "_request_response_url",
        "_request_response_file",
    ],
)
@pytest.mark.parametrize("status", [401, 403])
async def test_vendor_auth_or_rate_limit_is_reported(
    tmp_path: Path, fake_vendor: Any, method: Any, status: Any
) -> None:
    """Characterize the existing public exception mapping, not a retry policy.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
        method: Fixture or parametrized method input for this regression.
        status: Fixture or parametrized status input for this regression.
    """
    manager = ChromeDriverManager(directory=str(tmp_path))
    url = "https://vendor.invalid/limited"
    fake_vendor.responses[url] = fake_vendor.response(status=status)
    with pytest.raises(errors.DriverRequestFailedError):
        await getattr(manager, method)(url)
    assert all(session.closed for session in fake_vendor.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timeout_type", [TimeoutError, asyncio.TimeoutError, aiohttp.ServerTimeoutError]
)
@pytest.mark.parametrize(
    ("method", "error_type"),
    [
        ("_request_response_text", errors.DriverRequestTimeoutError),
        ("_request_response_json", errors.DriverRequestTimeoutError),
        ("_request_response_url", errors.DriverRequestTimeoutError),
        ("_request_response_file", errors.FileDownloadTimeoutError),
    ],
)
async def test_vendor_timeout_is_reported(
    tmp_path: Path, fake_vendor: Any, method: Any, error_type: Any, timeout_type: Any
) -> None:
    """Verify vendor timeout is reported.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
        method: Fixture or parametrized method input for this regression.
        error_type: Fixture or parametrized error type input for this regression.
        timeout_type: Fixture or parametrized timeout type input for this regression.
    """
    manager = ChromeDriverManager(directory=str(tmp_path))
    url = "https://vendor.invalid/timeout"
    fake_vendor.responses[url] = timeout_type("synthetic timeout")
    with pytest.raises(error_type):
        await getattr(manager, method)(url)
    assert all(session.closed for session in fake_vendor.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "error_type"),
    [
        pytest.param("text", errors.DriverRequestTimeoutError, id="metadata"),
        pytest.param("file", errors.FileDownloadTimeoutError, id="download"),
    ],
)
async def test_outer_deadline_preserves_classified_timeout_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: _http.ResponseKind,
    error_type: type[errors.AseleniumError],
) -> None:
    """Do not rewrap a timeout already classified by the inner request layer.

    Args:
        tmp_path: Isolated cache parent for the manager instance.
        monkeypatch: Pytest fixture used to replace the admitted request.
        kind: Response kind selecting the metadata or download deadline.
        error_type: Expected package-defined timeout class.
    """
    manager = ChromeDriverManager(directory=tmp_path)
    original = error_type("classified inner timeout")

    async def raise_classified_timeout(*args: Any, **kwargs: Any) -> None:
        """Raise the exact package exception supplied by the regression."""
        raise original

    def unused_session_factory() -> aiohttp.ClientSession:
        """Fail if the patched request unexpectedly creates an HTTP client."""
        raise AssertionError("classified timeout path must not create a client")

    monkeypatch.setattr(_http, "_admitted_request", raise_classified_timeout)

    with pytest.raises(error_type) as caught:
        await _http.request(
            manager,
            "https://vendor.invalid/resource",
            kind,
            unused_session_factory,
        )

    assert caught.value is original
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_vendor_retry_budget_and_retry_after(
    tmp_path: Path, fake_vendor: Any, monkeypatch: pytest.MonkeyPatch, status: Any
) -> None:
    """Verify vendor retry budget and retry after.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        status: Fixture or parametrized status input for this regression.
    """
    waits = []

    async def record(seconds: Any) -> None:
        """Record the outcome and duration of one awaited demo section.

        Args:
            seconds: Fixture or parametrized seconds input for this regression.
        """
        waits.append(seconds)

    monkeypatch.setattr(_http.asyncio, "sleep", record)
    manager = ChromeDriverManager(directory=str(tmp_path))
    url = "https://vendor.invalid/retry"
    response = fake_vendor.response(status=status)
    response.headers["Retry-After"] = "0.01"
    fake_vendor.responses[url] = response
    error = (
        errors.DriverRequestRateLimitError
        if status == 429
        else errors.DriverRequestFailedError
    )
    with pytest.raises(error):
        await manager._request_response_text(url)
    assert len(fake_vendor.calls) == 3
    assert waits == [0.01, 0.01]


@pytest.mark.asyncio
async def test_oversized_and_dishonest_response_lengths_are_bounded(
    tmp_path: Path, fake_vendor: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify oversized and dishonest response lengths are bounded.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    monkeypatch.setattr(_http, "MAX_DOWNLOAD_BYTES", 3)
    manager = ChromeDriverManager(directory=str(tmp_path))
    url = "https://vendor.invalid/size"
    response = fake_vendor.response(body=b"too large")
    response.headers["Content-Length"] = "1"
    fake_vendor.responses[url] = response
    with pytest.raises(errors.DriverRequestFailedError, match="size limit"):
        await manager._request_response_file(url)
    assert all(session.closed for session in fake_vendor.sessions)


@pytest.mark.asyncio
async def test_one_invocation_reuses_and_closes_its_client(
    tmp_path: Path, fake_vendor: Any
) -> None:
    """Verify one invocation reuses and closes its client.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
    """
    manager = ChromeDriverManager(directory=str(tmp_path))
    active = Invocation(
        InstallationRequest("Chrome", None, "stable", None, None, "mac", "64", True),
        asyncio.current_task(),
    )
    token = manager._invocation.set(active)
    url = "https://vendor.invalid/version"
    fake_vendor.responses[url] = fake_vendor.response(text="version")
    try:
        assert await asyncio.gather(
            manager._request_response_text(url), manager._request_response_text(url)
        ) == ["version", "version"]
        assert len(fake_vendor.sessions) == 1
        assert not fake_vendor.sessions[0].closed
    finally:
        await active.resources.aclose()
        manager._invocation.reset(token)
    assert fake_vendor.sessions[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "http://vendor.invalid/file",
        "https://user:secret@vendor.invalid/file",
        "file:///tmp/file",
    ],
)
async def test_redirect_policy_rejects_unsafe_targets_before_following(
    tmp_path: Path, fake_vendor: Any, location: Any
) -> None:
    """Verify redirect policy rejects unsafe targets before following.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
        location: Fixture or parametrized location input for this regression.
    """
    url = "https://vendor.invalid/start"
    response = fake_vendor.response(status=302)
    response.headers["Location"] = location
    fake_vendor.responses[url] = response
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(errors.DriverRequestFailedError, match="HTTPS"):
        await manager._request_response_file(url)
    assert len(fake_vendor.calls) == 1
    assert fake_vendor.calls[0][1]["allow_redirects"] is False
    assert all(session.closed for session in fake_vendor.sessions)


@pytest.mark.asyncio
async def test_vendor_cdn_redirects_are_bounded_and_https(
    tmp_path: Path, fake_vendor: Any
) -> None:
    """Verify vendor cdn redirects are bounded and https.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
    """
    manager = ChromeDriverManager(directory=str(tmp_path))
    start = "https://vendor.invalid/start"
    final = "https://cdn.invalid/final"
    redirect = fake_vendor.response(status=302)
    redirect.headers["Location"] = final
    fake_vendor.responses[start] = redirect
    fake_vendor.responses[final] = fake_vendor.response(text="fixture")
    assert await manager._request_response_text(start) == "fixture"
    fake_vendor.responses[final] = redirect
    with pytest.raises(errors.DriverRequestFailedError, match="redirect"):
        await manager._request_response_text(start)
    assert len(fake_vendor.calls) == 8  # two success requests, six bounded attempts


@pytest.mark.asyncio
async def test_cancelled_stream_closes_download_and_client(
    tmp_path: Path, fake_vendor: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify cancelled stream closes download and client.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        fake_vendor: Fixture or parametrized fake vendor input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    downloads = []
    original = _http.Download

    class TrackedDownload(original):
        """Represent TrackedDownload using the inherited implementation."""

        def __init__(self) -> None:
            """Initialize the instance."""
            super().__init__()
            downloads.append(self)

    monkeypatch.setattr(_http, "Download", TrackedDownload)
    started = asyncio.Event()

    async def chunks(size: Any) -> AsyncIterator[Any]:
        """Chunks.

        Args:
            size: Fixture or parametrized size input for this regression.

        Yields:
            Values produced by this iterator in iteration order.
        """
        yield b"first"
        started.set()
        await asyncio.Event().wait()

    response = fake_vendor.response()
    response.content.iter_chunked = chunks
    url = "https://vendor.invalid/cancel"
    fake_vendor.responses[url] = response
    manager = ChromeDriverManager(directory=str(tmp_path))
    task = asyncio.create_task(manager._request_response_file(url))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert downloads and all(item.stream.closed for item in downloads)
    assert all(session.closed for session in fake_vendor.sessions)
