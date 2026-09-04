"""One monotonic budget shared by polling and its WebDriver requests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from math import isfinite
from time import monotonic
from typing import (
    TypeVar,
)

from aselenium import errors

T = TypeVar("T")
V = TypeVar("V")

DEADLINE: ContextVar[float | None] = ContextVar("aselenium_wait_deadline", default=None)


async def poll(
    check: Callable[[], Awaitable[T]], timeout: float | None = 5, interval: float = 0.2
) -> T | None:
    """Poll an asynchronous predicate under one monotonic deadline.

    Args:
        check: Asynchronous no-argument predicate evaluated by each poll.
        timeout: Nonnegative total budget in seconds. Zero or None performs one
            immediate observation; positive values share a deadline with nested waits.
        interval: Positive delay in seconds between unsuccessful observations.

    Returns:
        The first truthy predicate result, the last falsey result, or None when the deadline expires.

    Raises:
        errors.InvalidArgumentError: The timeout or polling interval is invalid.
        asyncio.CancelledError: The caller cancels the wait. Predicate failures
            also propagate unless they represent this wait's expired deadline.

    Example:
        >>> value = await poll(lambda: element.text, timeout=5)
    """
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not isfinite(interval)
        or interval <= 0
    ):
        raise errors.InvalidArgumentError(
            "Poll interval must be a finite positive number"
        )
    timeout = 0 if timeout is None else timeout
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not isfinite(timeout)
        or timeout < 0
    ):
        raise errors.InvalidArgumentError(
            "Wait timeout must be a finite nonnegative number"
        )
    # Zero means one immediate observation, not no observation.
    if timeout == 0:
        return await check()
    deadline = monotonic() + timeout
    outer = DEADLINE.get()
    if outer is not None:
        deadline = min(deadline, outer)
    token = DEADLINE.set(deadline)
    try:
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            try:
                result = await asyncio.wait_for(check(), remaining)
            except (asyncio.TimeoutError, errors.SessionTimeoutError) as cause:
                # Native script/page timeouts also inherit TimeoutError. They
                # remain predicate failures even if this poll's budget elapsed.
                if isinstance(cause, errors.AseleniumError) and not isinstance(
                    cause, errors.SessionTimeoutError
                ):
                    raise
                if monotonic() >= deadline:
                    return None
                raise
            if result:
                return result
            remaining = deadline - monotonic()
            if remaining <= 0:
                return result
            await asyncio.sleep(min(interval, remaining))
    finally:
        DEADLINE.reset(token)


async def first_match(
    values: Sequence[V], find: Callable[[V], Awaitable[T | None]], timeout: float | None
) -> T | None:
    """Return the first available match while sharing one deadline across candidates.

    Args:
        values: Input values evaluated in order by this operation.
        find: Asynchronous lookup called for each candidate in order.
        timeout: Nonnegative total budget in seconds. Zero or None scans the
            candidates once without sleeping between observations.

    Returns:
        The first non-None lookup result, or None if nothing matches before the deadline.
    """
    if not values:
        return None

    async def check() -> tuple[T] | None:
        """Observe the enclosing wait predicate once.

        Returns:
            A truthy one-item tuple holding the first non-None match, or None.
        """
        for value in values:
            result = await find(value)
            if result is not None:
                return (result,)
        return None

    match = await poll(check, timeout)
    return match[0] if match is not None else None
