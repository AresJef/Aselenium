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

"""High-level Chrome facade and its session context."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
)

from aselenium._paths import PathInput
from aselenium.chrome.options import ChromeOptions
from aselenium.chrome.service import ChromeService
from aselenium.chrome.session import ChromeSession
from aselenium.manager.driver import ChromeDriverManager
from aselenium.webdriver import ChromiumBaseWebDriver, SessionContext

if TYPE_CHECKING:
    from aselenium.manager.version import ChromiumVersion

__all__ = ["Chrome"]


# Chrome Session Context --------------------------------------------------------------------------
class ChromeSessionContext(SessionContext[ChromeSession]):
    """Provision, start, yield, and clean up one Chrome session."""

    _SESSION_CLS: type[ChromeSession] = ChromeSession

    async def __aenter__(self) -> ChromeSession:
        """Start and return the Chrome session owned by this context.

        Returns:
            The running Chrome session.
        """
        return await self.start()


# Chrome Webdriver --------------------------------------------------------------------------------
class Chrome(
    ChromiumBaseWebDriver[ChromeDriverManager, ChromeOptions, ChromeSessionContext]
):
    """Configure and acquire independent asynchronous Chrome sessions."""

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
        """Create a reusable Chrome facade without launching the browser.

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
        """Return the driver manager.

        Returns:
            The facade's browser-specific driver manager.
        """
        return self._manager

    @property
    def options(self) -> ChromeOptions:
        """Return the webdriver options for the browser.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    # Acquire ---------------------------------------------------------------------
    def acquire(
        self,
        version: ChromiumVersion | str = "build",
        channel: Literal["stable", "beta", "dev", "cft"] = "stable",
        binary: PathInput | None = None,
    ) -> ChromeSessionContext:
        """Create a single-use context for a new Chrome session.

        Options are snapshotted when this method is called. Provisioning and browser
        startup occur on entering the context, whose exit awaits owned cleanup.
        Concurrent tasks should acquire separate contexts.

        Args:
            version: A ChromiumVersion, numeric version string, or resolution selector.
                The default ``"build"`` matches the installed browser's build;
                ``"major"`` allows the same major version and ``"patch"`` requests
                its exact version. ``"offline"`` uses only available local artifacts.
                With ``channel="cft"``, supply a numeric version, not ``"build"``.
            channel: Installed Chrome channel: stable, beta, or dev. The special cft
                channel provisions both Chrome for Testing and its matching driver.
            binary: Explicit installed-browser executable, or None for discovery.
                This must be ``None`` for cft, which provisions its own browser binary.

        Returns:
            A context yielding ChromeSession after successful startup.

        Example:
            >>> from aselenium import Chrome
            >>> driver = Chrome()
            >>> driver.options.set_timeouts(implicit=0, pageLoad=20, script=5)
            >>> try:
            ...     async with driver.acquire(version="build") as session:
            ...         await session.load("https://example.com")
            ... finally:
            ...     driver.options.close()
        """
        return super().acquire(version=version, channel=channel, binary=binary)
