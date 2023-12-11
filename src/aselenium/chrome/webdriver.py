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
from aselenium.chrome.options import ChromeOptions
from aselenium.chrome.service import ChromeService
from aselenium.chrome.session import ChromeSession
from aselenium.manager.version import ChromiumVersion
from aselenium.manager.driver import ChromeDriverManager
from aselenium.webdriver import ChromiumBaseWebDriver, SessionContext


__all__ = ["Chrome"]


# Chrome Session Context --------------------------------------------------------------------------
class ChromeSessionContext(SessionContext):
    """The context manager for a Chrome session."""

    _SESSION_CLS: type[ChromeSession] = ChromeSession

    async def __aenter__(self) -> ChromeSession:
        return await self.start()


# Chrome Webdriver --------------------------------------------------------------------------------
class Chrome(ChromiumBaseWebDriver):
    """The webdriver for Chrome."""

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
            ChromeDriverManager,
            ChromeService,
            ChromeOptions,
            ChromeSessionContext,
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
    def manager(self) -> ChromeDriverManager:
        """Access the driver manager `<ChromeDriverManager>`."""
        return self._manager

    @property
    def options(self) -> ChromeOptions:
        """Access the webdriver options for the browser `<ChromeOptions>`."""
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: ChromiumVersion | Literal["major", "build", "patch"] = "build",
        channel: Literal["stable", "beta", "dev", "cft"] = "stable",
        binary: str | None = None,
    ) -> ChromeSessionContext:
        """Acquire a new Chrome session `<ChromeSession>`.

        ### Standard usage

        :param version: `<str>` Defaults to `'build'`. Accepts the following values:
            - `'major'`: Install webdriver that has the same major version as the browser.
            - `'build'`: Install webdriver that has the same major & build version as the browser.
            - `'patch'`: Install webdriver that has the same major, build & patch version as the browser.
            - `'118.0.5982.0'`: Install the excat webdriver version regardless of the browser version.
            - `'cft'`: For more information, please refer to the `[Chrome for Testing]` section below.

        :param channel: `<str>` Defaults to `'stable'`. Accepts the following values:
            - `'stable'`: Locate the `STABLE` (normal) browser binary in the system
                          and use it to determine the webdriver version.
            - `'beta'`:   Locate the `BETA` browser binary in the system and use it to
                          determine the webdriver version.
            - `'dev'`:    Locate the `DEV` browser binary in the system and use it to
                          determine the webdriver version.

        :param binary: `<str>` The path to a specific browser binary. Defaults to `None`.
            If specified, will use this given browser binary to determine
            the webdriver version and start the session.

        ### Example:
        >>> from aselenium import Chrome
            driver = Chrome(
                # optional: the directory to store the webdrivers.
                directory="/path/to/driver/cache/directory"
                # optional: the maximum amount of webdrivers (and CTF browsers) to maintain.
                max_cache_size=10
            )
        >>> # . acquire a chrome session
            async with driver.acquire("build", "dev") as session:
                # explain: install webdriver that has the same major & build
                # version as the Chrome [dev] browser installed in the system,
                # and start a new session with the dev browser.
                await session.load("https://www.google.com")
                # . do some automated tasks
                ...

        ### Chrome for Testing

        :param version: `<str>` A valid Chrome for Testing version. e.g. `'113.0.5672.0'`, `'120'`, etc.
        :param channel: `<str>` Must set to `'cft'` (Chrome for Testing).
        :param binary: `<str>` This argument will be ignored once `channel='cft'`.

        - Notice: The installation of a fresh Chrome for Testing browser will
          take much longer time than the installation of a webdriver. Please
          wait for the installation to complete with some patience.

        ### Example:
        >>> from aselenium import Chrome
            driver = Chrome()
        >>> # . acquire a Chrome for Testing session
            async with driver.acquire("119.0.6045", "cft") as session:
                # explain: install both the webdriver and CFT browser with the same build
                # version '119.0.6045', and start a new session with the CFT browser.
                await session.load("https://www.google.com")
                # . do some automated tasks
                ...
        """
        return super().acquire(version=version, channel=channel, binary=binary)
