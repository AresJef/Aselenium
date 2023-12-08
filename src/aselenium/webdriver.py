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
from typing import Any
from aselenium.session import Session
from aselenium.service import BaseService
from aselenium.options import BaseOptions, ChromiumBaseOptions
from aselenium.manager.driver import DriverManager, ChromiumDriverManager


# Base Webdriver ----------------------------------------------------------------------------------
class SessionContext:
    """The base context manager for a session."""

    _SESSION_CLS: type[Session] | None = None

    def __init__(
        self,
        manager: DriverManager,
        manager_install_args: tuple[Any],
        manager_install_kwargs: dict[str, Any],
        service_cls: type[BaseService],
        service_timeout: int | float,
        service_args: tuple[Any],
        service_kwargs: dict[str, Any],
        options: BaseOptions,
    ) -> None:
        """The context manager for a browser session.

        :param manager: `<DriverManager>` The driver manager.
        :param manager_install_args: `<tuple[Any]>` The arguments for installing the webdriver.
        :param manager_install_kwargs: `<dict[str, Any]>` The keyword arguments for installing the webdriver.
        :param service_cls: `<type[BaseService]>` The webdriver service class.
        :param service_timeout: `<int/float>` Timeout in seconds for starting/stopping the service.
        :param service_args: `<tuple[Any]>` Additional arguments for service `subprocess.Popen` constructor.
        :param service_kwargs: `<dict[str, Any]>` Additional keyword arguments for service `subprocess.Popen` constructor.
        :param options: `<BaseOptions>` The browser options.
        """
        # Session
        self._session: Session | None = None
        # Driver Manager
        self._manager = manager
        self._manager_install_args = manager_install_args
        self._manager_install_kwargs = manager_install_kwargs
        # Driver Service
        self._service_cls = service_cls
        self._service_timeout = service_timeout
        self._service_args = service_args
        self._service_kwargs = service_kwargs
        # Browser options
        self._options = options

    def _extra_options_updates(self) -> None:
        """(Internal) Extra updates to the browser options."""
        pass

    async def start(self) -> Session:
        """Start & return the session `<Session>`."""
        try:
            # Install webdriver
            await self._manager.install(
                *self._manager_install_args,
                **self._manager_install_kwargs,
            )
            # Update options
            self._options.browser_version = self._manager.browser_version
            self._options.browser_location = self._manager.browser_location
            self._extra_options_updates()
            # Create service
            service = self._service_cls(
                self._manager.driver_version,
                self._manager.driver_location,
                self._service_timeout,
                *self._service_args,
                **self._service_kwargs,
            )
            # Create session
            try:
                self._session = self._SESSION_CLS(self._options, service)
            except TypeError:
                if self._SESSION_CLS is None:
                    raise NotImplementedError(
                        "<SessionContext> Class attribute `_SESSION_CLS` must be "
                        "implemented in the subclass: <{}>.".format(
                            self.__class__.__name__
                        )
                    )
                raise
            # Start session
            await self._session.start()
            return self._session
        except BaseException as err:
            try:
                await self.quit()
            except BaseException:
                pass
            raise err

    async def quit(self) -> None:
        """Quit the session."""
        try:
            if self._session is not None:
                await self._session.quit()
        finally:
            self._manager = None
            self._manager_install_args = None
            self._manager_install_kwargs = None
            self._service_cls = None
            self._service_timeout = None
            self._service_args = None
            self._service_kwargs = None
            self._options = None
            self._session = None

    async def __aenter__(self) -> Session:
        return await self.start()

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        if exc is not None:
            try:
                await self.quit()
            except BaseException:
                pass
            raise exc
        else:
            await self.quit()


class WebDriver:
    """The base class of the webdriver for the browser."""

    def __init__(
        self,
        manager_cls: type[DriverManager],
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
        """The webdriver for the browser.

        ### Driver Manager Arguments:

        :param directory: `<str/None>` The directory to cache the webdrivers. Defaults to `None`.
            - If `None`, the webdrivers will be automatically cache in the following default directory:
              1. MacOS default: `'/Users/<user>/.aselenium'`.
              2. Windows default: `'C:\\Users\\<user>\\.aselenium'`.
              3. Linux default: `'/home/<user>/.aselenium'`.
            - If specified, a folder named `'.aselenium'` will be created in the given directory.

        :param max_cache_size: `<int/None>` The maximum cache size of the webdrivers. Defaults to `None`.
            - If `None`, all webdrivers will be cached to local storage without limit.
            - For value > 1, if the cached webdrivers exceed this limit, the oldest
              webdrivers will be deleted.

        :param request_timeout: `<int/float>` The timeout in seconds for api requests. Defaults to `10`.
        :param download_timeout: `<int/float>` The timeout in seconds for file download. Defaults to `300`.
        :param proxy: `<str/None>` The proxy for http requests. Defaults to `None`.
            This might be needed for some users that cannot access the webdriver api directly
            due to internet restrictions. Only accepts proxy startswith `'http://'`.

        ### Driver Service Arguments:

        :param service_timeout: `<int/float>` Timeout in seconds for starting/stopping the webdriver service. Defaults to `10`.
        :param service_args: `<Any>` Additional arguments for the webdriver service.
        :param service_kwargs: `<Any>` Additional keyword arguments for the webdriver service.
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
        self._service_args: tuple[Any] = service_args
        self._service_kwargs: dict[str, Any] = service_kwargs
        # Browser Options
        self._options: BaseOptions = options_cls()
        # Session
        self._session_context_cls: type[SessionContext] = session_context_cls

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> DriverManager:
        """Access the driver manager `<DriverManager>`."""
        return self._manager

    @property
    def options(self) -> BaseOptions:
        """Access the webdriver options for the browser `<BaseOptions>`."""
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(self, *args, **kwargs) -> SessionContext:
        """Acquire a new browser session `<Session>`."""
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
        return "<%s>" % self.__class__.__name__

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: Any) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __del__(self):
        # Options
        self._options = None
        # Service
        self._executable = None
        self._service_cls = None
        self._service_args = None
        self._service_kwargs = None


# Chromium Base Webdriver -------------------------------------------------------------------------
class ChromiumBaseWebDriver(WebDriver):
    """The base class of the webdriver for the Chromium based browser."""

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> ChromiumDriverManager:
        """Access the driver manager `<ChromiumDriverManager>`."""
        return self._manager

    @property
    def options(self) -> ChromiumBaseOptions:
        """Access the webdriver options for the browser `<ChromiumBaseOptions>`."""
        return self._options
