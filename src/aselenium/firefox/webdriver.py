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

"""High-level Firefox facade and its session context."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
)

from aselenium._paths import PathInput, directory_path
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.service import FirefoxService
from aselenium.firefox.session import FirefoxSession
from aselenium.manager.driver import FirefoxDriverManager
from aselenium.webdriver import SessionContext, WebDriver

if TYPE_CHECKING:
    from aselenium.manager.version import GeckoVersion

__all__ = ["Firefox"]


# Firefox Session Context --------------------------------------------------------------------------
class FirefoxSessionContext(SessionContext[FirefoxSession]):
    """Provision, start, yield, and clean up one Firefox session."""

    _SESSION_CLS: type[FirefoxSession] = FirefoxSession

    async def __aenter__(self) -> FirefoxSession:
        """Start and return the Firefox session owned by this context.

        Returns:
            The running Firefox session.
        """
        return await self.start()


# Firefox Webdriver --------------------------------------------------------------------------------
class Firefox(WebDriver[FirefoxDriverManager, FirefoxOptions, FirefoxSessionContext]):
    """Configure and acquire independent asynchronous Firefox sessions."""

    def __init__(
        self,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
        service_timeout: int | float = 10,
        *service_args: Any,
        profile_root: PathInput | None = None,
        **service_kwargs: Any,
    ) -> None:
        """Initialize a reusable Firefox facade without launching a browser.

        Args:
            directory: Cache parent directory. ``None`` uses the per-user default.
                Strings, ``Path`` objects, and ``os.PathLike[str]`` values are accepted.
            max_cache_size: Maximum retained artifact count, or ``None`` for no limit.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit HTTP provisioning proxy URL, or ``None`` for a direct connection.
            service_timeout: Positive timeout in seconds for service startup and shutdown.
            *service_args: Additional GeckoDriver command-line arguments.
            profile_root: Existing directory in which GeckoDriver may create
                temporary Firefox profiles. Use a non-hidden, shared writable
                directory when a Snap or Flatpak Firefox cannot access the host
                temporary directory. Requires GeckoDriver 0.32.0 or newer. None
                uses GeckoDriver's default.
            **service_kwargs: Additional keyword arguments for the GeckoDriver
                ``subprocess.Popen`` call.

        Example:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from aselenium import Firefox
            >>> with tempfile.TemporaryDirectory(
            ...     prefix="aselenium-firefox-", dir=Path.home()
            ... ) as directory:
            ...     driver = Firefox(profile_root=Path(directory))
            ...     driver.options.close()
        """
        if profile_root is not None:
            # This reusable facade is the public filesystem boundary. Preserve
            # the parsed Path across every acquisition instead of repeatedly
            # invoking a caller's os.PathLike protocol.
            service_kwargs["profile_root"] = directory_path(profile_root)
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
        """Create a single-use context for a new Firefox session.

        Options are snapshotted when this method is called. Provisioning and browser
        startup occur on entering the context, whose exit awaits owned cleanup.

        Args:
            version: A ``GeckoVersion``, numeric GeckoDriver version, or selector.
                ``"latest"`` resolves online, ``"auto"`` prefers a compatible cached
                artifact, and ``"offline"`` uses only available local artifacts.
            binary: Explicit installed-browser executable, or ``None`` for discovery.
                Strings, ``Path`` objects, and ``os.PathLike[str]`` values are accepted.

        Returns:
            A context yielding ``FirefoxSession`` after successful startup.

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
