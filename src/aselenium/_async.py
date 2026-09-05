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
    """Drain owned asynchronous work before propagating cancellation.

    This helper shields cleanup and bounded worker tasks so their resources are
    not abandoned when the waiting task is cancelled. If cancellation arrives,
    it is re-raised only after the owned task reaches a terminal state.

    Args:
        awaitable: Asynchronous cleanup or worker operation owned by the caller.

    Returns:
        The awaitable's result when the caller is not cancelled.

    Raises:
        asyncio.CancelledError: The caller or owned work is cancelled. Caller
            cancellation is re-raised only after the owned work terminates.
        BaseException: Any non-cancellation failure raised by the owned work
            while the caller remains active.
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
    """Run blocking work with per-event-loop concurrency and cancellation ownership.

    At most four calls execute concurrently for each event loop. Cancellation
    waits for an admitted worker call to finish before it propagates, preventing
    filesystem and subprocess-adjacent work from continuing without an owner.

    Args:
        function: Blocking callable to run in a bounded worker thread.
        *args: Positional arguments forwarded to the wrapped operation.
        **kwargs: Keyword arguments forwarded to the wrapped operation.

    Returns:
        The value returned by ``function``.

    Raises:
        asyncio.CancelledError: The caller is cancelled; raised after an
            admitted worker call finishes.
        BaseException: Any exception raised by ``function``.
    """
    loop = asyncio.get_running_loop()
    reference = _GATES.get(loop)
    gate = reference() if reference is not None else None
    if gate is None:
        gate = asyncio.Semaphore(4)
        _GATES[loop] = ref(gate)
    async with gate:
        return await finish_owned(asyncio.to_thread(function, *args, **kwargs))
