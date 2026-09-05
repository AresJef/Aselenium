"""Request-local provisioning state and Python 3.10-compatible task ownership."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Coroutine
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from functools import wraps
from inspect import signature
from pathlib import Path
from threading import RLock
from typing import (
    TYPE_CHECKING,
    Any,
    Concatenate,
    Generic,
    ParamSpec,
    TypeVar,
    cast,
    overload,
)
from weakref import WeakKeyDictionary, WeakValueDictionary

from aselenium import errors
from aselenium._async import finish_owned, run_blocking
from aselenium.manager._cache import FileManager, artifact_lock

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from aselenium.manager.driver import DriverManager
    from aselenium.manager.version import Version
M = TypeVar("M", bound="DriverManager[Any, Any]")
V = TypeVar("V", bound="Version")
T = TypeVar("T")
R = TypeVar("R")
P = ParamSpec("P")


@dataclass(frozen=True)
class InstallationRequest:
    """Immutable selectors, platform, policy, and overrides for one installation.

    Attributes:
        product: Browser product name, such as Chrome or Firefox.
        version: Frozen requested version selector, or None when omitted.
        channel: Requested release channel.
        binary: Parsed browser executable override, or None for discovery.
        driver: Parsed driver executable override, or None for managed resolution.
        os_name: Operating-system identifier used by the driver vendor.
        architecture: Architecture width used to scope the cache view.
        arm: Whether the target architecture belongs to the ARM family.
        policy: Effective version-resolution and network-access policy.
        validate_compatibility: Whether the resolved driver/browser pair must be checked.
    """

    product: str
    version: str | None
    channel: str
    binary: Path | None
    driver: Path | None
    os_name: str
    architecture: str
    arm: bool
    policy: str = "compatible-build"
    validate_compatibility: bool = False


@dataclass(frozen=True)
class InstallationResult:
    """Immutable resolved executable locations and versions for one installation.

    Attributes:
        request: Immutable inputs that produced this result.
        driver_location: Resolved driver executable path.
        driver_version: Resolved driver version string, or None if unavailable.
        browser_location: Resolved browser executable path, or None if unavailable.
        browser_version: Resolved browser version string, or None if unavailable.
        channel: Resolved release channel, falling back to the requested channel.
    """

    request: InstallationRequest
    driver_location: Path
    driver_version: str | None
    browser_location: Path | None
    browser_version: str | None
    channel: str


@dataclass
class Invocation:
    """Mutable resources owned by one isolated installation invocation.

    Attributes:
        request: Frozen inputs for this invocation.
        owner: Task identity used to recognize reentrant installation calls.
        values: Mutable descriptor values private to this invocation.
        resources: Exit stack owning temporary downloads and HTTP cleanup.
        client: Shared HTTP client, created lazily on the first vendor request.
        client_lock: Lock preventing concurrent creation of duplicate HTTP clients.
    """

    request: InstallationRequest
    owner: object
    values: dict[str, Any] = field(default_factory=dict)
    resources: AsyncExitStack = field(default_factory=AsyncExitStack)
    client: ClientSession | None = None
    client_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RequestField(Generic[R]):
    """Route a typed provisioning field to request-local or published state."""

    def __set_name__(self, owner: type[Any], name: str) -> None:
        """Record the attribute name assigned to this descriptor.

        Args:
            owner: Class on which Python installed the descriptor.
            name: Attribute name assigned to the descriptor.
        """
        self.name = name

    @overload
    def __get__(  # noqa: D418 - structural audit requires every definition documented.
        self, instance: None, owner: type[Any] | None = None
    ) -> RequestField[R]:
        """Return the descriptor itself when accessed through its owner class."""
        ...

    @overload
    def __get__(  # noqa: D418 - structural audit requires every definition documented.
        self,
        instance: DriverManager[Any, Any],
        owner: type[Any] | None = None,
    ) -> R:
        """Return request-local or published state for a manager instance."""
        ...

    def __get__(
        self,
        instance: DriverManager[Any, Any] | None,
        owner: type[Any] | None = None,
    ) -> RequestField[R] | R:
        """Read the request-local value, or the last published value outside an invocation.

        Args:
            instance: Descriptor owner instance, or None when accessed on the class.
            owner: Class through which the descriptor is being accessed.

        Returns:
            The descriptor on class access; otherwise its request-local or last-published value.
        """
        if instance is None:
            return self
        active = instance._invocation.get()
        if active is not None:
            return cast(R, active.values.get(self.name))
        return cast(R, instance.__dict__.get(self.name))

    def __set__(self, instance: DriverManager[Any, Any], value: R) -> None:
        """Store the value in the current invocation or the instance state.

        Args:
            instance: Driver manager receiving the assignment.
            value: Provisioning field value to store in the active invocation or instance.
        """
        active = instance._invocation.get()
        if active is not None:
            active.values[self.name] = value
        else:
            instance.__dict__[self.name] = value


_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, WeakValueDictionary[Path | str, asyncio.Lock]
] = WeakKeyDictionary()
_REGISTRY_LOCK = RLock()


def installation_lock(manager: DriverManager[Any, Any]) -> asyncio.Lock:
    """Locks are shared only within the current event loop and cache root.

    Args:
        manager: Driver manager owning the provisioning state and request configuration.

    Returns:
        The shared lock for the current event loop and cache root.
    """
    loop = asyncio.get_running_loop()
    cache = manager._file_manager
    # Filesystem-backed managers share by their already-parsed cache root. A
    # system-managed driver such as Safari has no filesystem cache and uses its
    # product name as the non-path registry identity.
    key: Path | str = cache._directory if cache is not None else manager._name
    with _REGISTRY_LOCK:
        locks = _LOCKS.setdefault(loop, WeakValueDictionary())
        lock = locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            locks[key] = lock
        return lock


async def owned_gather(*coroutines: Coroutine[Any, Any, T]) -> list[T]:
    """Propagate the original failure only after every sibling has finished.

    Args:
        *coroutines: Sibling coroutine objects owned and drained as one operation.

    Returns:
        Results in input order after every owned task has completed successfully.
    """
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        drain = asyncio.gather(*tasks, return_exceptions=True)
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                # Repeated caller cancellation must not abandon owned cleanup.
                continue
        drain.result()
        raise


def isolated_install(
    method: Callable[Concatenate[M, P], Coroutine[Any, Any, Path]],
) -> Callable[Concatenate[M, P], Coroutine[Any, Any, Path]]:
    """Isolate ``install()`` while publishing a stable path snapshot.

    Args:
        method: Asynchronous manager installation method to isolate.

    Returns:
        An asynchronous method preserving the original arguments and ``Path`` result.
    """
    parameters = signature(method)

    @wraps(method)
    async def wrapped(self: M, *args: P.args, **kwargs: P.kwargs) -> Path:
        """Execute one isolated installation and publish its completed result snapshot.

        Args:
            self: Driver manager instance passed to the decorated method.
            *args: Positional arguments forwarded to the wrapped operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.

        Returns:
            The installed executable path after the wrapper has completed its ownership checks.
        """
        active = self._invocation.get()
        if active is not None and active.owner is asyncio.current_task():
            # Chrome/Chromium delegation to the base implementation is one call.
            return await method(self, *args, **kwargs)
        bound = parameters.bind(self, *args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments

        requested_version = values.get("version")
        selector = None if requested_version is None else str(requested_version)
        policy = self._policy_override.get()
        if policy is None:
            policy = {
                "offline": "offline",
                "auto": "cached-compatible",
                "cached": "cached-compatible",
                "latest": "latest-compatible",
                "major": "compatible-major",
                "patch": "exact",
            }.get(selector or "")
            if policy is None:
                segments = 3 if self._name == "Firefox" else 4
                policy = (
                    "exact"
                    if selector is not None and len(selector.split(".")) == segments
                    else "compatible-build"
                )
        request = InstallationRequest(
            self._name,
            selector,
            values.get("channel", "stable"),
            # Path overrides are frozen only after the core manager has parsed
            # them. This avoids consulting a custom PathLike's ``__str__`` and
            # guarantees one filesystem-protocol conversion per public input.
            None,
            None,
            self._os_name,
            self._os_arch,
            self._os_is_arm,
            policy,
            self._validate_pair.get(),
        )
        invocation = Invocation(request, asyncio.current_task())
        token = self._invocation.set(invocation)
        try:
            location = await method(self, *args, **kwargs)
            if not isinstance(location, Path):
                raise errors.DriverInstallationError(
                    "install() implementations must return a pathlib.Path"
                )
            if request.validate_compatibility:
                self._validate_installed_pair()

            def path_snapshot(argument: str, state: str) -> Path | None:
                """Read one explicit override from parsed request-local state.

                Args:
                    argument: Bound public argument name.
                    state: Request-local manager field containing the parsed ``Path``.

                Returns:
                    The parsed absolute path, or None when the public argument was absent.

                Raises:
                    errors.DriverInstallationError: The implementation failed to parse
                        a supplied filesystem override at its core entry boundary.
                """
                raw = values.get(argument)
                if raw is None:
                    return None
                parsed = invocation.values.get(state)
                if not isinstance(parsed, Path):
                    raise errors.DriverInstallationError(
                        "install() did not validate the %s path override" % argument
                    )
                return parsed

            # Explicit overrides remain Path objects from the manager's core entry
            # through the immutable request and result snapshots.
            request = replace(
                request,
                binary=path_snapshot("binary", "_target_binary"),
                driver=path_snapshot("driver", "_target_driver"),
            )
            invocation.request = request
            # The public return is authoritative even for custom install hooks.
            self._driver_location = location
            result = InstallationResult(
                request,
                location,
                None if self._driver_version is None else str(self._driver_version),
                self._browser_location,
                None if self._browser_version is None else str(self._browser_version),
                self._channel or request.channel,
            )
            if request.policy == "exact" and self._file_manager is not None:
                cache = self._cache_view
                if cache is not None and hasattr(cache, "pin"):
                    if self._driver_version is not None:
                        await run_blocking(cache.pin, self._driver_version)
                    if self._browser_version is not None:
                        await run_blocking(cache.pin, self._browser_version, "binary")
        finally:
            try:
                await finish_owned(invocation.resources.aclose())
            finally:
                self._invocation.reset(token)
        # Publish last-success properties synchronously. A concurrent failure
        # cannot reset a different call's successful result.
        for name in self._RESULT_FIELDS:
            self.__dict__[name] = invocation.values.get(name)
        self._last_result = result
        self._completed_result.set(result)
        return location

    return wrapped


def artifact_install(
    kind: str,
) -> Callable[
    [Callable[[M, V], Coroutine[Any, Any, Path]]],
    Callable[[M, V], Coroutine[Any, Any, Path]],
]:
    """Coordinate download work across processes; release before sibling joins.

    Args:
        kind: Operation or artifact kind selected by the caller.

    Returns:
        A decorator that coordinates installation of the selected artifact kind.
    """

    def decorate(
        method: Callable[[M, V], Coroutine[Any, Any, Path]],
    ) -> Callable[[M, V], Coroutine[Any, Any, Path]]:
        """Wrap the artifact installer with cross-process download coordination.

        Args:
            method: Asynchronous artifact installer to coordinate.

        Returns:
            An installer with the original call contract and coordinated artifact acquisition.
        """

        @wraps(method)
        async def wrapped(self: M, version: V) -> Path:
            """Reuse a matching artifact or install it while holding the download lock.

            Args:
                self: Driver manager instance passed to the decorated method.
                version: Parsed artifact version passed to the wrapped installer.

            Returns:
                The installed executable path after the wrapper has completed its ownership checks.
            """
            cache = self._cache_view
            if not isinstance(cache, FileManager):
                return await method(self, version)
            # Distinct from the publication lock so the worker can commit.
            key = hashlib.sha256(
                ("download:" + cache._key(kind, version)).encode()
            ).hexdigest()
            lock = artifact_lock(cache._directory, key)
            acquired = False

            def enter() -> None:
                """Acquire the artifact lock and record ownership for cancellation-safe release."""
                nonlocal acquired
                lock.__enter__()
                acquired = True

            try:
                await run_blocking(enter)
                match = (
                    self._match_driver_executable
                    if kind == "driver"
                    else self._match_browser_binary
                )
                cached = await run_blocking(match, version, "patch")
                if cached is not None:
                    return cached
                return await method(self, version)
            finally:
                if acquired:
                    await finish_owned(run_blocking(lock.__exit__, None, None, None))

        return wrapped

    return decorate
