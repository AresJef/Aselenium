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
from __future__ import annotations
from typing import Any, Type
from aselenium.options import BaseOptions, ChromiumBaseOptions
from aselenium.service import BaseService, ChromiumBaseService
from aselenium.session import SessionContext, ChromiumBaseSessionContext


__all__ = ["WebDriver", "ChromiumBaseWebDriver"]


# Base Webdriver ----------------------------------------------------------------------------------
class WebDriver:
    """The base class of the webdriver for the browser."""

    def __init__(
        self,
        executable: str,
        options_cls: Type[BaseOptions],
        service_cls: Type[BaseService],
        service_timeout: int = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        """The webdriver for the browser.

        :param executable: `<str>` The absolute path to the webdriver executable file.
        :param options_cls: `<Type[BaseOptions]>` The options class for the webdriver.
        :param service_cls: `<Type[BaseService]>` The service class for the webdriver.
        :param service_timeout: `<int/float>` Timeout in seconds for starting/stopping the webdriver service. Defaults to `10`.
        :param service_args: `<Any>` Additional arguments for the webdriver service.
        :param service_kwargs: `<Any>` Additional keyword arguments for the webdriver service.
        """
        # Options
        self._options: BaseOptions = options_cls()
        # Service
        self._executable: str = executable
        self._service_cls: Type[BaseService] = service_cls
        self._service_timeout: int = service_timeout
        self._service_args: tuple[Any] = service_args
        self._service_kwargs: dict[str, Any] = service_kwargs

    @property
    def options(self) -> BaseOptions:
        """Access the webdriver options for the browser `<BaseOptions>`."""
        return self._options

    def acquire(self) -> SessionContext:
        """Acquire a new browser session `<Session>`.

        ### Example:
        >>> async with driver.acquire() as session:
                await session.load("https://www.google.com")
                # . some automated tasks
        """
        return SessionContext(
            self._options,
            self._service_cls(
                self._executable,
                self._service_timeout,
                *self._service_args,
                **self._service_kwargs,
            ),
        )

    # Special methods ----------------------------------------------------------
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

    def __init__(
        self,
        executable: str,
        options_cls: type[ChromiumBaseOptions],
        service_cls: type[ChromiumBaseService],
        service_timeout: int = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        """The webdriver for the Chromium based browser.

        :param executable: `<str>` The absolute path to the webdriver executable file.
        :param options_cls: `<Type[ChromiumBaseOptions]>` The options class for the webdriver.
        :param service_cls: `<Type[ChromiumBaseService]>` The service class for the webdriver.
        :param service_timeout: `<int/float>` Timeout in seconds for starting/stopping the webdriver service. Defaults to `10`.
        :param service_args: `<Any>` Additional arguments for the webdriver service.
        :param service_kwargs: `<Any>` Additional keyword arguments for the webdriver service.
        """
        super().__init__(
            executable,
            options_cls,
            service_cls,
            service_timeout,
            *service_args,
            **service_kwargs,
        )

    @property
    def options(self) -> ChromiumBaseOptions:
        """Access the webdriver options for the browser `<ChromiumBaseOptions>`."""
        return self._options

    def acquire(self) -> ChromiumBaseSessionContext:
        """Acquire a new browser session `<ChromiumBaseSession>`.

        ### Example:
        >>> async with driver.acquire() as session:
                await session.load("https://www.google.com")
                # . some automated tasks
        """
        return ChromiumBaseSessionContext(
            self._options,
            self._service_cls(
                self._executable,
                self._service_timeout,
                *self._service_args,
                **self._service_kwargs,
            ),
        )
