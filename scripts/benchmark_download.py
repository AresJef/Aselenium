"""Measure traced peak Python memory for a generated, streamed download (no network)."""

from __future__ import annotations

import asyncio
import json
import platform
import time
import tracemalloc
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from aselenium.manager._http import request

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from aselenium.manager.driver import DriverManager


async def measure(mebibytes: int) -> dict[str, Any]:
    """Measure peak traced Python memory for a generated, streamed download.

    Args:
        mebibytes: Synthetic download size in mebibytes.

    Returns:
        A mapping containing the measure data.
    """

    class Response:
        """Stream deterministic bytes through the manager's response protocol."""

        status = 200
        headers: dict[str, str] = {}

        @property
        def content(self) -> Response:
            """Return the object exposing the response-body iterator.

            Returns:
                This synthetic response.
            """
            return self

        async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
            """Yield deterministic body chunks of the requested size.

            Args:
                size: Bytes in each generated chunk.

            Yields:
                Byte chunks until the configured total size is reached.
            """
            for _ in range(mebibytes * 4):
                yield b"x" * size

        async def __aenter__(self) -> Response:
            """Enter the synthetic response context.

            Returns:
                This response.
            """
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Leave the no-resource synthetic response context.

            Args:
                *args: Standard asynchronous context-manager exception details.
            """
            return None

    class Client:
        """Provide the minimal asynchronous HTTP-client protocol for the benchmark."""

        async def __aenter__(self) -> Client:
            """Enter the synthetic client context.

            Returns:
                This client.
            """
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Leave the no-resource synthetic client context.

            Args:
                *args: Standard asynchronous context-manager exception details.
            """
            return None

        def get(self, *args: Any, **kwargs: Any) -> Response:
            """Return a fresh deterministic response for one request.

            Args:
                *args: Request arguments accepted by the HTTP-client protocol.
                **kwargs: Request options accepted by the HTTP-client protocol.

            Returns:
                A synthetic streamed response.
            """
            return Response()

    manager = SimpleNamespace(
        _require_online=lambda: None,
        _invocation=ContextVar("benchmark", default=None),
        download_timeout=60,
        requests_timeout=10,
        proxy=None,
    )
    tracemalloc.start()
    started = time.monotonic()
    result = await request(
        cast("DriverManager[Any, Any]", manager),
        "https://fixture.invalid/archive.zip",
        "file",
        cast("Callable[[], ClientSession]", Client),
    )
    duration = time.monotonic() - started
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    content = result["content"]
    expected_size = mebibytes * 1024 * 1024
    try:
        if content.size != expected_size:
            raise RuntimeError(
                f"Streamed download size {content.size} != expected {expected_size}"
            )
    finally:
        content.close()
    return dict(
        download_bytes=content.size, traced_peak_python_bytes=peak, seconds=duration
    )


async def main() -> None:
    """Parse command-line arguments and run the requested program workflow."""
    samples = [await measure(size) for size in (8, 64, 128)]
    print(
        json.dumps(
            dict(
                python=platform.python_version(),
                platform=platform.platform(),
                scope="Generated chunks, no network; tracemalloc excludes OS file cache and native-library allocations; not RSS",
                samples=samples,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
