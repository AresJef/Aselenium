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
from aselenium.safari.options import SafariOptions
from aselenium.safari.service import SafariService
from aselenium.safari.session import SafariSession
from aselenium.manager.version import SafariVersion
from aselenium.manager.driver import SafariDriverManager
from aselenium.webdriver import WebDriver, SessionContext

__all__ = ["Safari"]


# Firefox Session Context -------------------------------------------------------------------------
class SafariSessionContext(SessionContext):
    """The context manager for a Safari session."""

    _SESSION_CLS: type[SafariSession] = SafariSession

    def _extra_options_updates(self) -> None:
        """(Internal) Extra updates to the browser options."""
        self._options: SafariOptions
        tech_preview = self._manager.channel == "dev"
        if self._options.technology_preview != tech_preview:
            self._options.technology_preview = tech_preview

    async def __aenter__(self) -> SafariSession:
        return await self.start()


# Safari Webdriver --------------------------------------------------------------------------------
class Safari(WebDriver):
    """The webdriver for Safari."""

    def __init__(
        self,
        service_timeout: int = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        super().__init__(
            SafariDriverManager,
            SafariService,
            SafariOptions,
            SafariSessionContext,
            directory=None,
            max_cache_size=None,
            request_timeout=10,
            download_timeout=300,
            proxy=None,
            service_timeout=service_timeout,
            *service_args,
            **service_kwargs,
        )

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> SafariDriverManager:
        """Access the driver manager `<SafariDriverManager>`."""
        return self._manager

    @property
    def options(self) -> SafariOptions:
        """Access the webdriver options for the browser `<SafariOptions>`."""
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        channel: SafariVersion | Literal["stable", "dev"] = "stable",
        driver: str | None = None,
        binary: str | None = None,
    ) -> SafariSessionContext:
        """Acquire a new Safari session `<SafariSession>`.

        :param channel: `<str>` Defaults to `'stable'`. Accepts the following values:
            - `'stable'`: Locate the `STABLE` (normal) Safari binary in the system
                          and use it to determine the webdriver executable.
            - `'dev'`:    Locate the `DEV` Safari [Technology Preview] binary in the
                          system and use it to determine the webdriver executable.

        :param driver: `<str>` The path to a specific webdriver executable. Defaults to `None`.
            If specified, will use this given webdriver executable instead of
            trying to locate the webdriver executable in the system.

        :param binary: `<str>` The path to a specific Safari binary. Defaults to `None`.
            If specified, will use this given browser binary to determine
            the webdriver executable.

        ### Example:
        >>> from aselenium import Safari
            driver = Safari()
        >>> # . acquire a safari session
            async with driver.acquire("dev") as session:
                # explain: use the Safari Technology Preview binary
                # and the corresponding webdriver executable to start
                # the session.
                await session.get("https://www.google.com")
                # . do some sutomated tasks
                ...
        """
        return super().acquire(channel=channel, driver=driver, binary=binary)
