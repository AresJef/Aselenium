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
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.service import FirefoxService
from aselenium.firefox.session import FirefoxSession
from aselenium.manager.version import GeckoVersion
from aselenium.manager.driver import FirefoxDriverManager
from aselenium.webdriver import WebDriver, SessionContext

__all__ = ["Firefox"]


# Firefox Session Context --------------------------------------------------------------------------
class FirefoxSessionContext(SessionContext):
    """The context manager for a Firefox session."""

    _SESSION_CLS: type[FirefoxSession] = FirefoxSession

    async def __aenter__(self) -> FirefoxSession:
        return await self.start()


# Firefox Webdriver --------------------------------------------------------------------------------
class Firefox(WebDriver):
    """The webdriver for Firefox."""

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
        """Access the driver manager `<FirefoxDriverManager>`."""
        return self._manager

    @property
    def options(self) -> FirefoxOptions:
        """Access the webdriver options for the browser `<FirefoxOptions>`."""
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: GeckoVersion | Literal["latest", "auto"] = "latest",
        binary: str | None = None,
    ) -> FirefoxSessionContext:
        """Acquire a new Firefox session `<FirefoxSession>`.

        :param version: `<str>` Defaults to `'latest'`. Accepts the following values:
            - `'latest'`: Always install the latest available geckodriver that is
                          compatible with the Firefox browser from the [Mozilla Github]
                          repository.
            - `'auto'`:   Install the latest cached geckodriver that is compatible
                          with the Firefox browser. If compatible geckodriver does
                          not exist in cache, will install the latest compatible
                          geckodriver from the [Mozilla Github] repository.
            - `'0.32.1'`: Install the excat geckodriver version regardless of the
                          Firefox browser version.

        :param binary: `<str/None>` The path to a specific Firefox binary. Defaults to `None`.
            - If `None`, will try to locate the Firefox binary installed in the
              system and use it to determine the compatible webdriver version.
            - If specified, will use this given Firefox binary to determine the
              compatible webdriver version and start the session.

        ### Example:
        >>> from aselenium import Firefox
            driver = Firefox(
                # optional: the directory to store the webdrivers.
                directory="/path/to/driver/cache/directory"
                optional: the maximum amount of webdrivers to maintain.
                max_cache_size=10
            )
        >>> # . acquire a firefox session
            async with driver.acquire("latest") as session:
                # explain: install the latest geckodriver available at
                # [Mozilla Github] repository that is compatible with
                # the installed Firefox browser, and start a new session.
                await session.load("https://www.google.com")
                # . do some automated tasks
                ...
        """
        return super().acquire(version=version, binary=binary)
