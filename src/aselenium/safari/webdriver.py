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

"""High-level Safari facade and its session context."""

from __future__ import annotations

from typing import Any, Literal, cast

from aselenium._paths import PathInput
from aselenium.manager.driver import SafariDriverManager
from aselenium.safari.options import SafariOptions
from aselenium.safari.service import SafariService
from aselenium.safari.session import SafariSession
from aselenium.webdriver import SessionContext, WebDriver

__all__ = ["Safari"]


# Safari Session Context --------------------------------------------------------------------------
class SafariSessionContext(SessionContext[SafariSession]):
    """Locate, start, yield, and clean up one Safari session."""

    _SESSION_CLS: type[SafariSession] = SafariSession

    def _extra_options_updates(self) -> None:
        """Match the Safari capability to the installed release channel."""
        installation = self._installation
        assert installation is not None
        tech_preview = installation.channel == "dev"
        options = cast(SafariOptions, self._options)
        if options.technology_preview != tech_preview:
            options.technology_preview = tech_preview

    async def __aenter__(self) -> SafariSession:
        """Start and return the Safari session owned by this context.

        Returns:
            The running Safari session.
        """
        return await self.start()


# Safari Webdriver --------------------------------------------------------------------------------
class Safari(WebDriver[SafariDriverManager, SafariOptions, SafariSessionContext]):
    """Configure and acquire independent asynchronous Safari sessions."""

    def __init__(
        self,
        service_timeout: int | float = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        """Create a reusable Safari facade without launching the browser.

        Args:
            service_timeout: Positive timeout in seconds for service startup and shutdown.
            *service_args: Additional positional arguments forwarded to the service constructor.
            **service_kwargs: Additional keyword arguments forwarded to the service constructor.
        """
        super().__init__(
            SafariDriverManager(),
            SafariService,
            SafariOptions,
            SafariSessionContext,
            None,
            None,
            10,
            300,
            None,
            service_timeout,
            *service_args,
            **service_kwargs,
        )

    # Properties ------------------------------------------------------------------
    @property
    def manager(self) -> SafariDriverManager:
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return self._manager

    @property
    def options(self) -> SafariOptions:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        channel: Literal["stable", "dev"] = "stable",
        driver: PathInput | None = None,
        binary: PathInput | None = None,
    ) -> SafariSessionContext:
        """Create a single-use context for a new Safari session.

        Options are snapshotted when this method is called. Executable discovery and
        browser startup occur on entering the context, whose exit awaits cleanup.

        Args:
            channel: Safari release channel: ``"stable"`` or Technology Preview
                ``"dev"``.
            driver: Explicit SafariDriver executable, or ``None`` for discovery.
                Strings, ``Path`` objects, and ``os.PathLike[str]`` values are accepted.
            binary: Explicit Safari application executable, or ``None`` for discovery.
                Strings, ``Path`` objects, and ``os.PathLike[str]`` values are accepted.

        Returns:
            A context yielding ``SafariSession`` after successful startup.

        Example:
            >>> from aselenium import Safari
            >>> driver = Safari()
            >>> try:
            ...     async with driver.acquire("stable") as session:
            ...         await session.load("https://www.google.com")
            ...         print(await session.title)
            ... finally:
            ...     driver.options.close()
        """
        return super().acquire(channel=channel, driver=driver, binary=binary)
