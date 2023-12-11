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
from typing import Any, Literal
from aselenium.chromium.options import ChromiumOptions
from aselenium.chromium.service import ChromiumService
from aselenium.chromium.session import ChromiumSession
from aselenium.manager.version import ChromiumVersion
from aselenium.manager.driver import ChromiumDriverManager
from aselenium.webdriver import ChromiumBaseWebDriver, SessionContext

__all__ = ["Chromium"]


# Chromium Session Context ------------------------------------------------------------------------
class ChromiumSessionContext(SessionContext):
    """The context manager for a Chromium session."""

    _SESSION_CLS: type[ChromiumSession] = ChromiumSession

    async def __aenter__(self) -> ChromiumSession:
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
        """Access the driver manager `<ChromiumDriverManager>`."""
        return self._manager

    @property
    def options(self) -> ChromiumOptions:
        """Access the webdriver options for the browser `<ChromiumOptions>`."""
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: ChromiumVersion | Literal["major", "build", "patch"] = "build",
        binary: str | None = None,
    ) -> ChromiumSessionContext:
        """Acquire a new Chromium session `<ChromiumSession>`.

        :param version: `<str>` Defaults to `'build'`. Accepts the following values:
            - `'major'`: Install webdriver that has the same major version as the browser.
            - `'build'`: Install webdriver that has the same major & build version as the browser.
            - `'patch'`: Install webdriver that has the same major, build & patch version as the browser.
            - `'118.0.5982.0'`: Install the excat webdriver version regardless of the browser version.

        :param binary: `<str/None>` The path to a specific browser binary. Defaults to `None`.
            - If `None`, will try to locate the Chromium browser binary installed
              in the system and use it to determine the webdriver version.
            - If specified, will use the given browser binary to determine the
              webdriver version and start the session.

        ### Example:
        >>> from aselenium import Chromium
            driver = Chromium(
                # optional: the directory to store the webdrivers.
                directory="/path/to/driver/cache/directory"
                # optional: the maximum amount of webdrivers to maintain.
                max_cache_size=10
            )
        >>> # . acquire a chromium session
            async with driver.acquire("build") as session:
                # explain: install webdriver that has the same major & build
                # version as the Chromium browser installed in the system,
                # and start a new session with the browser.
                await session.load("https://www.google.com")
                # . do some automated tasks
                ...
        """
        return super().acquire(version=version, binary=binary)
