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
from aselenium.edge.options import EdgeOptions
from aselenium.edge.service import EdgeService
from aselenium.edge.session import EdgeSession
from aselenium.manager.version import ChromiumVersion
from aselenium.manager.driver import EdgeDriverManager
from aselenium.webdriver import ChromiumBaseWebDriver, SessionContext

__all__ = ["Edge"]


# Edge Session Context ----------------------------------------------------------------------------
class EdgeSessionContext(SessionContext):
    """The context manager for the Edge session."""

    _SESSION_CLS: type[EdgeSession] = EdgeSession

    async def __aenter__(self) -> EdgeSession:
        return await self.start()


# Edge Webdriver ----------------------------------------------------------------------------------
class Edge(ChromiumBaseWebDriver):
    """The webdriver for Edge."""

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
            EdgeDriverManager,
            EdgeService,
            EdgeOptions,
            EdgeSessionContext,
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
    def manager(self) -> EdgeDriverManager:
        """Access the driver manager `<EdgeDriverManager>`."""
        return self._manager

    @property
    def options(self) -> EdgeOptions:
        """Access the webdriver options for the browser `<EdgeOptions>`."""
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: ChromiumVersion | Literal["major", "build", "patch"] = "build",
        channel: Literal["stable", "beta", "dev"] = "stable",
        binary: str | None = None,
    ) -> EdgeSessionContext:
        """Acquire a new Edge session `<EdgeSession>`.

        :param version: `<str>` Defaults to `'build'`. Accepts the following values:
            - `'major'`: Install webdriver that has the same major version as the browser.
            - `'build'`: Install webdriver that has the same major & build version as the browser.
            - `'patch'`: Install webdriver that has the same major, build & patch version as the browser.
            - `'118.0.5982.0'`: Install the excat webdriver version regardless of the browser version.

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
        >>> from aselenium import Edge
            driver = Edge(
                # optional: the directory to store the webdrivers.
                directory="/path/to/driver/cache/directory"
                optional: the maximum amount of webdrivers to maintain.
                max_cache_size=10
            )
        >>> # . acquire an edge session
            async with driver.acquire("build", "beta") as session:
                # explain: install webdriver that has the same major & build
                # version as the Edge [beta] browser installed in the system,
                # and start a new session with the beta browser.
                await session.load("https://www.google.com")
                # . do some automated tasks
                ...
        """
        return super().acquire(version=version, channel=channel, binary=binary)
