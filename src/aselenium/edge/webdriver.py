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

"""High-level Microsoft Edge facade and its session context."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
)

from aselenium._paths import PathInput
from aselenium.edge.options import EdgeOptions
from aselenium.edge.service import EdgeService
from aselenium.edge.session import EdgeSession
from aselenium.manager.driver import EdgeDriverManager
from aselenium.webdriver import ChromiumBaseWebDriver, SessionContext

if TYPE_CHECKING:
    from aselenium.manager.version import ChromiumVersion

__all__ = ["Edge"]


# Edge Session Context ----------------------------------------------------------------------------
class EdgeSessionContext(SessionContext[EdgeSession]):
    """Provision, start, yield, and clean up one Microsoft Edge session."""

    _SESSION_CLS: type[EdgeSession] = EdgeSession

    async def __aenter__(self) -> EdgeSession:
        """Start and return the Edge session owned by this context.

        Returns:
            The running Microsoft Edge session.
        """
        return await self.start()


# Edge Webdriver ----------------------------------------------------------------------------------
class Edge(ChromiumBaseWebDriver[EdgeDriverManager, EdgeOptions, EdgeSessionContext]):
    """Configure and acquire independent asynchronous Edge sessions."""

    def __init__(
        self,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
        service_timeout: int | float = 10,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        """Create a reusable Edge facade without launching the browser.

        Args:
            directory: Cache parent directory. ``None`` uses the per-user default.
                Strings, ``Path`` objects, and ``os.PathLike[str]`` values are accepted.
            max_cache_size: Maximum retained artifact count, or ``None`` for no limit.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit HTTP provisioning proxy URL, or ``None`` for a direct connection.
            service_timeout: Positive timeout in seconds for service startup and shutdown.
            *service_args: Additional positional arguments forwarded to the service constructor.
            **service_kwargs: Additional keyword arguments forwarded to the service constructor.
        """
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
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return self._manager

    @property
    def options(self) -> EdgeOptions:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: ChromiumVersion | str = "build",
        channel: Literal["stable", "beta", "dev"] = "stable",
        binary: PathInput | None = None,
    ) -> EdgeSessionContext:
        """Create a single-use context for a new Edge session.

        Options are snapshotted when this method is called. Provisioning and browser
        startup occur on entering the context, whose exit awaits owned cleanup.

        Args:
            version: A ``ChromiumVersion``, numeric version string, or resolution
                selector. ``"build"`` matches the installed browser's build;
                ``"major"`` allows its major version, ``"patch"`` requests its
                exact version, and ``"offline"`` uses only local artifacts.
            channel: Installed Edge channel: ``"stable"``, ``"beta"``, or ``"dev"``.
            binary: Explicit installed-browser executable, or ``None`` for discovery.
                Strings, ``Path`` objects, and ``os.PathLike[str]`` values are accepted.

        Returns:
            A context yielding ``EdgeSession`` after successful startup.

        Example:
            >>> from aselenium import Edge
            >>> driver = Edge(max_cache_size=10)
            >>> try:
            ...     async with driver.acquire(version="build") as session:
            ...         await session.load("https://example.com")
            ... finally:
            ...     driver.options.close()
        """
        return super().acquire(version=version, channel=channel, binary=binary)
