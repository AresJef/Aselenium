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

# -*- coding: UTF-8 -*-
"""Aselenium webdriver implementation and supporting types."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

from aselenium import errors
from aselenium._async import finish_owned, run_blocking
from aselenium._profiles import claim_profile, release_profile
from aselenium.options import BaseOptions, ChromiumBaseOptions

if TYPE_CHECKING:
    from types import TracebackType

    from aselenium.manager._cache import FileManager
    from aselenium.manager._installation import InstallationResult
    from aselenium.manager.driver import ChromiumDriverManager, DriverManager
    from aselenium.service import BaseService
    from aselenium.session import Session


# Base Webdriver ----------------------------------------------------------------------------------
class SessionContext:
    """The base context manager for a session."""

    _SESSION_CLS: type[Session] | None = None

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
        """Initialize the instance with the supplied configuration.

        Args:
            manager: The driver manager.
            manager_install_args: The arguments for installing the webdriver.
            manager_install_kwargs: The keyword arguments for installing the webdriver.
            service_cls: The webdriver service class.
            service_timeout: Timeout in seconds for starting/stopping the service.
            service_args: Additional arguments for service `subprocess.Popen` constructor.
            service_kwargs: Additional keyword arguments for service `subprocess.Popen` constructor.
            options: The browser options.
        """
        # Session
        self._session: Session | None = None
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
        self._options = (
            options.snapshot()
            if isinstance(options, BaseOptions)
            else deepcopy(options)
        )
        self._installation: InstallationResult | None = None
        self._service: BaseService | None = None
        self._state = "new"
        self._lifecycle_lock = asyncio.Lock()
        self._leases: list[tuple[FileManager, str]] = []

    def _extra_options_updates(self) -> None:
        """Extra updates to the browser options."""
        pass

    async def start(self) -> Session:
        """Start once; concurrent starts share the same owned session.

        Returns:
            The initialized session or default window described by the return annotation.
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
                cache = getattr(self._manager, "_file_manager", None)
                if cache is not None and hasattr(cache, "lease"):
                    for location in (
                        installation.driver_location,
                        installation.browser_location,
                    ):
                        if location:

                            def claim() -> None:
                                """Record a cache lease before the session starts using the executable."""
                                token = cache.lease(location)
                                if token:
                                    self._leases.append((cache, token))

                            await run_blocking(claim)
                self._options.browser_version = self._manager._parse_browser_version(
                    installation.browser_version
                )
                self._options.browser_location = installation.browser_location
                self._extra_options_updates()
                self._service = self._service_cls(
                    self._manager._parse_driver_version(installation.driver_version),
                    installation.driver_location,
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

    async def __aenter__(self) -> Session:
        """Start the owned asynchronous context and return its managed value.

        Returns:
            The Session value produced by this operation.
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


class WebDriver:
    """The base class of the webdriver for the browser."""

    def __init__(
        self,
        manager_cls: Callable[..., DriverManager],
        service_cls: type[BaseService],
        options_cls: type[BaseOptions],
        session_context_cls: type[SessionContext],
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
        service_timeout: int = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        r"""Initialize the instance with the supplied configuration.

        Driver Manager Arguments:

        Driver Service Arguments:

        Args:
            manager_cls: Browser-specific driver-manager class instantiated by the facade.
            service_cls: Browser-specific service class used for each acquisition.
            options_cls: Browser-specific options class instantiated by the facade.
            session_context_cls: Browser-specific session-context class created by acquire().
            directory: The directory to cache the webdrivers. Defaults to `None`.
                - If `None`, the webdrivers will be automatically cache in the following default directory:
                1. MacOS default: `'/Users/<user>/.aselenium'`.
                2. Windows default: `'C:\Users\<user>\.aselenium'`.
                3. Linux default: `'/home/<user>/.aselenium'`.
                - If specified, a folder named `'.aselenium'` will be created in the given directory.
            max_cache_size: The maximum cache size of the webdrivers. Defaults to `None`.
                - If `None`, all webdrivers will be cached to local storage without limit.
                - For value > 1, if the cached webdrivers exceed this limit, the oldest
                webdrivers will be deleted.
            request_timeout: The timeout in seconds for api requests. Defaults to `10`.
            download_timeout: The timeout in seconds for file download. Defaults to `300`.
            proxy: The proxy for http requests. Defaults to `None`.
                This might be needed for some users that cannot access the webdriver api directly
                due to internet restrictions. Only accepts proxy startswith `'http://'`.
            service_timeout: Timeout in seconds for starting/stopping the webdriver service. Defaults to `10`.
            *service_args: Additional arguments for the webdriver service.
            **service_kwargs: Additional keyword arguments for the webdriver service.
        """
        # Driver Manager
        self._manager = manager_cls(
            directory=directory,
            max_cache_size=max_cache_size,
            request_timeout=request_timeout,
            download_timeout=download_timeout,
            proxy=proxy,
        )
        # Driver Service
        self._service_cls: type[BaseService] = service_cls
        self._service_timeout: int = service_timeout
        self._service_args: tuple[Any, ...] = service_args
        self._service_kwargs: dict[str, Any] = service_kwargs
        # Browser Options
        self._options: BaseOptions = options_cls()
        # Session
        self._session_context_cls: type[SessionContext] = session_context_cls

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> DriverManager:
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return self._manager

    @property
    def options(self) -> BaseOptions:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(self, *args: Any, **kwargs: Any) -> SessionContext:
        """Acquire a new browser session.

        Args:
            *args: Positional arguments forwarded to the wrapped operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.

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
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False


# Chromium Base Webdriver -------------------------------------------------------------------------
class ChromiumBaseWebDriver(WebDriver):
    """The base class of the webdriver for the Chromium based browser."""

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> ChromiumDriverManager:
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return cast("ChromiumDriverManager", self._manager)

    @property
    def options(self) -> ChromiumBaseOptions:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return cast("ChromiumBaseOptions", self._options)
