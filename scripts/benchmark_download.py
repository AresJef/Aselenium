"""Measure traced peak Python memory for a generated, streamed download (no network)."""

from __future__ import annotations

import asyncio
import json
import platform
import time
import tracemalloc
from collections.abc import AsyncIterator
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

from aselenium.manager._http import request


async def measure(mebibytes: int) -> dict[str, Any]:
    """Measure peak traced Python memory for a generated, streamed download.

    Args:
        mebibytes: Synthetic download size in mebibytes.

    Returns:
        A mapping containing the measure data.
    """

    class Response:
        """Represent Response using the inherited implementation."""

        status = 200
        headers = {}

        @property
        def content(self) -> Any:
            """Content.

            Returns:
                The Any value produced by this operation.
            """
            return self

        async def iter_chunked(self, size: int) -> AsyncIterator[Any]:
            """Iter chunked.

            Args:
                size: Declared member size in bytes.

            Yields:
                Values produced by this iterator in iteration order.
            """
            for _ in range(mebibytes * 4):
                yield b"x" * size

        async def __aenter__(self) -> Response:
            """Start the owned asynchronous context and return its managed value.

            Returns:
                The Response value produced by this operation.
            """
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Await owned cleanup when leaving the asynchronous context.

            Args:
                *args: Positional arguments forwarded to the wrapped operation.
            """
            pass

    class Client:
        """Represent Client using the inherited implementation."""

        async def __aenter__(self) -> Client:
            """Start the owned asynchronous context and return its managed value.

            Returns:
                The Client value produced by this operation.
            """
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Await owned cleanup when leaving the asynchronous context.

            Args:
                *args: Positional arguments forwarded to the wrapped operation.
            """
            pass

        def get(self, *args: Any, **kwargs: Any) -> Any:
            """Get.

            Args:
                *args: Positional arguments forwarded to the wrapped operation.
                **kwargs: Keyword arguments forwarded to the wrapped operation.

            Returns:
                The stored mapping value, or default when the key is absent.
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
        manager, "https://fixture.invalid/archive.zip", "file", Client
    )
    duration = time.monotonic() - started
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    content = result["content"]
    assert content.size == mebibytes * 1024 * 1024
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
