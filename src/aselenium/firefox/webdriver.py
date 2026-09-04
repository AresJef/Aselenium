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

from aselenium._paths import PathInput
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.service import FirefoxService
from aselenium.firefox.session import FirefoxSession
from aselenium.manager.driver import FirefoxDriverManager
from aselenium.webdriver import SessionContext, WebDriver

if TYPE_CHECKING:
    from aselenium.manager.version import GeckoVersion

__all__ = ["Firefox"]


# Firefox Session Context --------------------------------------------------------------------------
class FirefoxSessionContext(SessionContext):
    """The context manager for a Firefox session."""

    _SESSION_CLS: type[FirefoxSession] = FirefoxSession

    async def __aenter__(self) -> FirefoxSession:
        """Start the owned asynchronous context and return its managed value.

        Returns:
            The FirefoxSession value produced by this operation.
        """
        return await self.start()


# Firefox Webdriver --------------------------------------------------------------------------------
class Firefox(WebDriver):
    """The webdriver for Firefox."""

    def __init__(
        self,
        directory: PathInput | None = None,
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
            FirefoxDriverManager,
            FirefoxService,
            FirefoxOptions,
            FirefoxSessionContext,
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
    def manager(self) -> FirefoxDriverManager:
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return self._manager

    @property
    def options(self) -> FirefoxOptions:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: GeckoVersion | str = "latest",
        binary: PathInput | None = None,
    ) -> FirefoxSessionContext:
        """Acquire a new Firefox session.

        Args:
            version: Defaults to `'latest'`. Accepts the following values:
                - `'latest'`: Always install the latest available geckodriver that is
                compatible with the Firefox browser from the [Mozilla Github]
                repository.
                - `'auto'`:   Install the latest cached geckodriver that is compatible
                with the Firefox browser. If compatible geckodriver does
                not exist in cache, will install the latest compatible
                geckodriver from the [Mozilla Github] repository.
                - `'0.32.1'`: Install the exact geckodriver version regardless of the
                Firefox browser version.
            binary: The path to a specific Firefox binary. Defaults to `None`.
                - If `None`, will try to locate the Firefox binary installed in the
                system and use it to determine the compatible webdriver version.
                - If specified, will use this given Firefox binary to determine the
                compatible webdriver version and start the session.

        Returns:
            A new single-use session context with an acquisition-time options snapshot.

        Example:
            >>> from aselenium import Firefox

            >>> driver = Firefox(max_cache_size=10)
            >>> try:
            ...     async with driver.acquire(version="auto") as session:
            ...         await session.load("https://example.com")
            ... finally:
            ...     driver.options.close()
        """
        return super().acquire(version=version, binary=binary)
