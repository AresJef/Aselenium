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

from typing import (
    TYPE_CHECKING,
    Any,
)

from aselenium.chromium.options import ChromiumOptions
from aselenium.chromium.service import ChromiumService
from aselenium.chromium.session import ChromiumSession
from aselenium.manager.driver import ChromiumDriverManager
from aselenium.webdriver import ChromiumBaseWebDriver, SessionContext

if TYPE_CHECKING:
    from aselenium.manager.version import ChromiumVersion

__all__ = ["Chromium"]


# Chromium Session Context ------------------------------------------------------------------------
class ChromiumSessionContext(SessionContext):
    """The context manager for a Chromium session."""

    _SESSION_CLS: type[ChromiumSession] = ChromiumSession

    async def __aenter__(self) -> ChromiumSession:
        """Start the owned asynchronous context and return its managed value.

        Returns:
            The ChromiumSession value produced by this operation.
        """
        return await self.start()


# Chromium Webdriver ------------------------------------------------------------------------------
class Chromium(ChromiumBaseWebDriver):
    """The webdriver for Chromium."""

    def __init__(
        self,
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
        service_timeout: int = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            directory: Cache parent directory; None uses the default per-user cache location.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit provisioning proxy URL, or None for a direct connection.
            service_timeout: Positive timeout in seconds for service startup and shutdown.
            *service_args: Additional positional arguments forwarded to the service constructor.
            **service_kwargs: Additional keyword arguments forwarded to the service constructor.
        """
        super().__init__(
            ChromiumDriverManager,
            ChromiumService,
            ChromiumOptions,
            ChromiumSessionContext,
            directory,
            max_cache_size,
            request_timeout,
            download_timeout,
            proxy,
            service_timeout,
            *service_args,
            **service_kwargs,
        )

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> ChromiumDriverManager:
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return self._manager

    @property
    def options(self) -> ChromiumOptions:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: ChromiumVersion | str = "build",
        binary: str | None = None,
    ) -> ChromiumSessionContext:
        """Acquire a new Chromium session.

        Args:
            version: Defaults to `'build'`. Accepts the following values:
                - `'major'`: Install webdriver that has the same major version as the browser.
                - `'build'`: Install webdriver that has the same major & build version as the browser.
                - `'patch'`: Install webdriver that has the same major, build & patch version as the browser.
                - `'118.0.5982.0'`: Install the exact webdriver version regardless of the browser version.
            binary: The path to a specific browser binary. Defaults to `None`.
                - If `None`, will try to locate the Chromium browser binary installed
                in the system and use it to determine the webdriver version.
                - If specified, will use the given browser binary to determine the
                webdriver version and start the session.

        Returns:
            A new single-use session context with an acquisition-time options snapshot.

        Example:
            >>> from aselenium import Chromium

            >>> driver = Chromium(max_cache_size=10)
            >>> try:
            ...     async with driver.acquire(version="build") as session:
            ...         await session.load("https://example.com")
            ... finally:
            ...     driver.options.close()
        """
        return super().acquire(version=version, binary=binary)
