# Licensed to the Software Freedom Conservancy (SFC) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The SFC licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Reusable browser facades and cancellation-safe session ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from math import isfinite
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeVar,
)

from aselenium import errors
from aselenium._async import finish_owned, run_blocking
from aselenium._paths import PathInput
from aselenium._profiles import claim_profile, release_profile
from aselenium.options import BaseOptions

if TYPE_CHECKING:
    from types import TracebackType

    from aselenium.manager._cache import FileManager
    from aselenium.manager._installation import InstallationResult
    from aselenium.manager.driver import DriverManager
    from aselenium.service import BaseService
    from aselenium.session import Session

S = TypeVar("S", bound="Session")
M = TypeVar("M", bound="DriverManager")
O = TypeVar("O", bound=BaseOptions)


# Base Webdriver ----------------------------------------------------------------------------------
class SessionContext(Generic[S]):
    """Own one session's provisioning, startup, and deterministic cleanup."""

    _SESSION_CLS: type[S] | None = None

    def __init__(
        self,
        manager: DriverManager,
        manager_install_args: tuple[Any, ...],
        manager_install_kwargs: dict[str, Any],
        service_cls: type[BaseService],
        service_timeout: int | float,
        service_args: tuple[Any, ...],
        service_kwargs: dict[str, Any],
        options: BaseOptions,
    ) -> None:
        """Capture the dependencies and immutable options snapshot for one session.

        Args:
            manager: Manager used to locate or provision the required executables.
            manager_install_args: Positional arguments for ``manager.install_result``.
            manager_install_kwargs: Keyword arguments for ``manager.install_result``.
            service_cls: Service implementation that owns the driver subprocess.
            service_timeout: Positive startup and shutdown timeout in seconds.
            service_args: Additional positional arguments for the service.
            service_kwargs: Additional keyword arguments for the service.
            options: Browser options to snapshot for this acquisition.
        """
        # Session
        self._session: S | None = None
        # Driver Manager
        self._manager = manager
        self._manager_install_args = manager_install_args
        self._manager_install_kwargs = dict(manager_install_kwargs)
        # Driver Service
        self._service_cls = service_cls
        self._service_timeout = service_timeout
        self._service_args = service_args
        self._service_kwargs = dict(service_kwargs)
        # Browser options
        self._options = options.snapshot()
        self._installation: InstallationResult | None = None
        self._service: BaseService | None = None
        self._state = "new"
        self._lifecycle_lock = asyncio.Lock()
        self._leases: list[tuple[FileManager, str]] = []

    def _extra_options_updates(self) -> None:
        """Extra updates to the browser options."""
        pass

    async def start(self) -> S:
        """Start once; concurrent starts share the same owned session.

        Returns:
            The initialized browser session.
        """
        async with self._lifecycle_lock:
            if self._state == "running":
                assert self._session is not None
                return self._session
            if self._state == "closed":
                raise errors.InvalidSessionError(
                    "This context is closed; acquire a new session"
                )
            if self._state != "new":
                raise errors.InvalidSessionError(
                    "Previous startup or cleanup failed; call quit() before acquiring a new context"
                )
            self._state = "starting"
            try:
                # Canonicalizing explicit profile paths can touch the filesystem.
                await run_blocking(claim_profile, self._options, self)
                installation = await self._manager.install_result(
                    *self._manager_install_args,
                    validate_compatibility=True,
                    **self._manager_install_kwargs,
                )
                self._installation = installation
                # InstallationResult already carries validated Path objects. Retain
                # their identity through leasing, options setup, and construction.
                driver_location = installation.driver_location
                browser_location = installation.browser_location
                cache = getattr(self._manager, "_file_manager", None)
                if cache is not None:
                    for location in (
                        driver_location,
                        browser_location,
                    ):
                        if location:

                            def claim() -> None:
                                """Record a cache lease before the session starts using the executable."""
                                token = cache._lease_path(location)
                                if token:
                                    self._leases.append((cache, token))

                            await run_blocking(claim)
                self._options.browser_version = self._manager._parse_browser_version(
                    installation.browser_version
                )
                self._options._set_browser_location_path(browser_location)
                self._extra_options_updates()
                self._service = self._service_cls(
                    self._manager._parse_driver_version(installation.driver_version),
                    driver_location,
                    self._service_timeout,
                    *self._service_args,
                    **self._service_kwargs,
                )
                if self._SESSION_CLS is None:
                    raise NotImplementedError("SessionContext requires _SESSION_CLS")
                self._session = self._SESSION_CLS(self._options, self._service)
                await self._session.start()
                self._state = "running"
                return self._session
            except BaseException:
                try:
                    await finish_owned(self._cleanup())
                except BaseException:
                    pass
                raise

    async def _cleanup(self) -> None:
        # Retain ownership on failed teardown so quit() can be retried.
        """Release session resources, leases, and profile ownership in teardown order."""
        self._state = "closing"
        if self._session is not None:
            await self._session.quit()
        elif self._service is not None:
            await self._service.stop()
        for cache, token in list(self._leases):
            await run_blocking(cache.release, token)
            self._leases.remove((cache, token))
        if isinstance(self._options, BaseOptions):
            await run_blocking(self._options.close)
        self._session = None
        release_profile(self)
        self._state = "closed"

    async def quit(self) -> None:
        """Cancellation-safe, idempotent teardown of this context's resources."""

        async def close() -> None:
            """Finish cleanup owned by the enclosing operation."""
            async with self._lifecycle_lock:
                if self._state != "closed":
                    await self._cleanup()

        await finish_owned(close())

    async def __aenter__(self) -> S:
        """Start and return the browser session owned by this context.

        Returns:
            The running browser-specific session.
        """
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Await owned cleanup when leaving the asynchronous context.

        Args:
            exc_type: Exception type supplied by the context-manager protocol, or None.
            exc: Exception supplied by the context-manager protocol, or None.
            exc_tb: Exception traceback supplied by the context-manager protocol, or None.
        """
        try:
            await self.quit()
        except BaseException:
            if exc is None:
                raise


C = TypeVar("C", bound="SessionContext[Any]")


class WebDriver(Generic[M, O, C]):
    """Build reusable browser facades from validated manager and service components."""

    def __init__(
        self,
        manager_cls: Callable[..., M] | M,
        service_cls: type[BaseService],
        options_cls: type[O],
        session_context_cls: type[C],
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
        service_timeout: int | float = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        """Initialize a reusable browser facade and its driver manager.

        Args:
            manager_cls: Browser-specific driver-manager factory, or a fully
                configured manager instance. A factory receives the cache and
                provisioning arguments documented below.
            service_cls: Browser-specific service class used for each acquisition.
            options_cls: Browser-specific options class instantiated by the facade.
            session_context_cls: Browser-specific session-context class created by acquire().
            directory: Cache parent directory. ``None`` uses the platform-specific
                user cache directory. Strings, ``Path`` objects, and compatible
                ``os.PathLike[str]`` values are accepted.
            max_cache_size: Maximum number of cached artifacts, or ``None`` for no
                count-based limit.
            request_timeout: Positive timeout in seconds for metadata requests.
            download_timeout: Positive total timeout in seconds for downloads.
            proxy: HTTP proxy URL used only for driver provisioning, or ``None``.
            service_timeout: Positive timeout in seconds for starting and stopping
                the webdriver service.
            *service_args: Additional arguments for the webdriver service.
            **service_kwargs: Additional keyword arguments for the webdriver service.

        Raises:
            TypeError: A supplied constructor argument has an unsupported type.
            ValueError: A timeout, proxy, or cache-size value is invalid.
            aselenium.errors.AseleniumInvalidPathError: A supplied cache path is
                malformed or cannot be represented by the local filesystem.
        """
        # Validate all facade-owned configuration before constructing components
        # whose initializers may create cache directories.
        if (
            isinstance(service_timeout, bool)
            or not isinstance(service_timeout, (int, float))
            or not isfinite(service_timeout)
            or service_timeout <= 0
        ):
            raise errors.InvalidArgumentError(
                "service_timeout must be a finite positive number"
            )

        # Driver Manager
        if callable(manager_cls):
            self._manager = manager_cls(
                directory=directory,
                max_cache_size=max_cache_size,
                request_timeout=request_timeout,
                download_timeout=download_timeout,
                proxy=proxy,
            )
        else:
            if (
                directory is not None
                or max_cache_size is not None
                or request_timeout != 10
                or download_timeout != 300
                or proxy is not None
            ):
                raise TypeError(
                    "cache and provisioning arguments require a driver-manager factory"
                )
            self._manager = manager_cls
        # Driver Service
        self._service_cls: type[BaseService] = service_cls
        self._service_timeout: int | float = service_timeout
        self._service_args: tuple[Any, ...] = service_args
        self._service_kwargs: dict[str, Any] = service_kwargs
        # Browser Options
        self._options: O = options_cls()
        # Session
        self._session_context_cls: type[C] = session_context_cls

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> M:
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return self._manager

    @property
    def options(self) -> O:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(self, *args: Any, **kwargs: Any) -> C:
        """Create a single-use context for a new browser session.

        Browser-specific facades provide typed acquisition parameters. The current
        options are snapshotted immediately; provisioning starts when the context is
        entered.

        Args:
            *args: Positional arguments forwarded to the manager installation call.
            **kwargs: Keyword arguments forwarded to the manager installation call.

        Returns:
            A new single-use session context with an acquisition-time options snapshot.
        """
        return self._session_context_cls(
            self._manager,
            args,
            kwargs,
            self._service_cls,
            self._service_timeout,
            self._service_args,
            self._service_kwargs,
            self._options,
        )

    # Special methods -------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s>" % self.__class__.__name__

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return id(self)

    def __eq__(self, __o: Any) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return self is __o


# Chromium Base Webdriver -------------------------------------------------------------------------
class ChromiumBaseWebDriver(WebDriver[M, O, C], Generic[M, O, C]):
    """Base facade shared by Chromium-family browsers."""
