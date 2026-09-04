"""Bounded, cancellation-owned work compatible with Python 3.10."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import (
    ParamSpec,
    TypeVar,
)
from weakref import ReferenceType, WeakKeyDictionary, ref

_GATES: WeakKeyDictionary[
    asyncio.AbstractEventLoop, ReferenceType[asyncio.Semaphore]
] = WeakKeyDictionary()
T = TypeVar("T")
P = ParamSpec("P")


async def finish_owned(awaitable: Awaitable[T]) -> T:
    """Do not abandon cleanup/worker work when its waiter is cancelled.

    Args:
        awaitable: Owned asynchronous work that must be drained before cancellation propagates.

    Returns:
        The value produced by the owned awaitable.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if not task.cancelled():
            task.exception()  # retrieve worker failure without replacing cancellation
        raise


async def run_blocking(
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Run blocking work in a bounded worker pool without abandoning it on cancellation.

    Args:
        function: Blocking callable to run in a bounded worker thread.
        *args: Positional arguments forwarded to the wrapped operation.
        **kwargs: Keyword arguments forwarded to the wrapped operation.

    Returns:
        The value returned by the blocking callable.

    Example:
        >>> payload = await run_blocking(Path("page.html").read_bytes)
    """
    loop = asyncio.get_running_loop()
    reference = _GATES.get(loop)
    gate = reference() if reference is not None else None
    if gate is None:
        gate = asyncio.Semaphore(4)
        _GATES[loop] = ref(gate)
    async with gate:
        return await finish_owned(asyncio.to_thread(function, *args, **kwargs))
