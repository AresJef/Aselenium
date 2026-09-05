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

"""Discover browsers and resolve, download, cache, and validate WebDriver binaries."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable
from contextvars import ContextVar
from importlib import resources
from math import isfinite
from os import environ, pathsep
from pathlib import Path
from platform import architecture, machine, system
from re import fullmatch
from shutil import which
from subprocess import (
    DEVNULL,
    PIPE,
    CalledProcessError,
    Popen,
    SubprocessError,
    TimeoutExpired,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    NoReturn,
    TypeVar,
)
from urllib.parse import urlsplit
from xml.parsers.expat import ExpatError

from aiohttp import ClientSession, ClientTimeout
from orjson import loads

from aselenium import errors
from aselenium._async import run_blocking
from aselenium._paths import PathInput, file_path, parse_path
from aselenium.manager._http import request as vendor_request
from aselenium.manager._installation import (
    InstallationRequest as InstallationRequest,
)
from aselenium.manager._installation import (
    InstallationResult,
    Invocation,
    RequestField,
    artifact_install,
    installation_lock,
    isolated_install,
    owned_gather,
)
from aselenium.manager.file import (
    ChromeBinaryFile,
    ChromeDriverFile,
    ChromeFileManager,
    ChromiumBaseFileManager,
    EdgeDriverFile,
    EdgeFileManager,
    File,
    FileManager,
    FirefoxFileManager,
    GeckoDriverFile,
)
from aselenium.manager.version import (
    ChromiumVersion,
    FirefoxVersion,
    GeckoVersion,
    SafariVersion,
    Version,
)
from aselenium.utils import _load_plist_file

if TYPE_CHECKING:
    from asyncio import Lock

V = TypeVar("V", bound=Version)
DV = TypeVar("DV", bound=Version)
BV = TypeVar("BV", bound=Version)

__all__ = [
    "EdgeDriverManager",
    "ChromeDriverManager",
    "ChromiumDriverManager",
    "FirefoxDriverManager",
    "SafariDriverManager",
]


# Constants ----------------------------------------------------------------------------------------
class OSType:
    """Operating-system identifiers understood by driver vendors."""

    LINUX: Literal["linux"] = "linux"
    MAC: Literal["mac"] = "mac"
    WIN: Literal["win"] = "win"


class ChannelType:
    """Supported browser release-channel identifiers."""

    STABLE = "stable"
    BETA = "beta"
    DEV = "dev"


# Driver Manager -----------------------------------------------------------------------------------
class DriverManager(Generic[DV, BV]):
    """Coordinate request-local browser discovery and WebDriver provisioning."""

    _RESULT_FIELDS = (
        "_channel",
        "_driver_version",
        "_driver_location",
        "_browser_version",
        "_browser_location",
    )
    _channel: RequestField[str | None] = RequestField()
    _target_version: RequestField[DV | None] = RequestField()
    _target_binary: RequestField[Path | None] = RequestField()
    _target_driver: RequestField[Path | None] = RequestField()
    _driver_version: RequestField[DV | None] = RequestField()
    _driver_location: RequestField[Path | None] = RequestField()
    _browser_version: RequestField[BV | None] = RequestField()
    _browser_location: RequestField[Path | None] = RequestField()
    _max_cache_size: int | None
    _requests_timeout: ClientTimeout
    _download_timeout: ClientTimeout
    _proxy: str | None
    _PROBE_TIMEOUT: float = 10.0
    """Maximum seconds allowed for a browser version probe."""
    _PROBE_KILL_TIMEOUT: float = 1.0
    """Maximum seconds allowed to reap a failed or timed-out probe."""
    _MAC_BINARY_PATHS: dict[str, list[str]] | None = None
    """Channel-indexed application-relative browser paths for macOS discovery."""
    _WIN_BINARY_PATHS: dict[str, list[str]] | None = None
    """Channel-indexed installation-relative browser paths for Windows discovery."""
    _LINUX_BINARY_PATHS: dict[str, list[str]] | None = None
    """Channel-indexed executable names searched through Linux PATH entries."""

    def __init__(
        self,
        name: str,
        file_manager_cls: type[FileManager] | None,
        driver_file_cls: type[File] | None,
        binary_file_cls: type[File] | None,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        r"""Configure browser-specific cache, archive, timeout, and proxy collaborators.

        Args:
            name: Browser product name used for cache identity and diagnostics.
            file_manager_cls: Cache-manager class, or None for a system-managed driver.
            driver_file_cls: Downloaded driver-archive class, or None when downloads are unsupported.
            binary_file_cls: Downloaded browser-archive class, or None when downloads are unsupported.
            directory: Cache parent directory, or None for the user's home directory.
                Managed artifacts and the index live under .aselenium/v2.
            max_cache_size: Positive retained-artifact limit, or None for no limit.
                Eviction skips pinned and leased entries, so the limit can be
                temporarily exceeded while artifacts are protected.
            request_timeout: Positive finite total seconds for a vendor metadata GET,
                including retry delays. Defaults to 10.
            download_timeout: Positive finite total seconds for a download, including
                admission waits and retries. Defaults to 300; cleanup may take longer.
            proxy: Explicit HTTP provisioning proxy URL, or None for a direct
                connection. This does not configure the browser's browsing proxy.
        """
        # Basic
        self._invocation: ContextVar[Invocation | None] = ContextVar(
            "aselenium_installation", default=None
        )
        self._completed_result: ContextVar[InstallationResult | None] = ContextVar(
            "aselenium_completed_installation", default=None
        )
        self._policy_override: ContextVar[str | None] = ContextVar(
            "aselenium_policy_override", default=None
        )
        self._validate_pair: ContextVar[bool] = ContextVar(
            "aselenium_validate_pair", default=False
        )
        self._last_result: InstallationResult | None = None
        self._name: str = name
        # Installation
        self._channel = None
        # Validate all scalar configuration before constructing the file
        # manager, which may create the cache hierarchy on disk.
        self.max_cache_size = max_cache_size
        self.requests_timeout = request_timeout
        self.download_timeout = download_timeout
        self.proxy = proxy
        # File manager
        self._file_manager: FileManager | None = (
            file_manager_cls(directory) if file_manager_cls is not None else None
        )
        self._driver_file_cls: type[File] | None = driver_file_cls
        self._binary_file_cls: type[File] | None = binary_file_cls
        # Target
        self._target_version = None
        self._target_binary = None
        # Driver
        self._driver_version = None
        self._driver_location = None
        # Browser
        self._browser_version = None
        self._browser_location = None
        # Platform
        self.__os_name: Literal["linux", "mac", "win"] | None = None
        self.__os_arch: Literal["32", "64"] | None = None
        self.__os_is_arm: bool | None = None
        self.__environ_paths: list[Path] | None = None

    # Installation ------------------------------------------------------------------------
    @property
    def _cache_view(self) -> FileManager | None:
        """Bind the product cache to the current operating system and architecture.

        Returns:
            Platform-scoped cache manager, or None for a system-managed driver.
        """
        cache = self._file_manager
        if isinstance(cache, FileManager):
            return cache.for_platform(self._os_name, self._os_arch, self._os_is_arm)
        return cache

    async def pin(
        self, version: str, *, artifact: str = "driver", pinned: bool = True
    ) -> None:
        """Protect a cached version from eviction, or explicitly unpin it.

        Args:
            version: Numeric cached artifact version whose eviction pin is changed.
            artifact: Artifact kind: driver or binary.
            pinned: Whether the indexed artifact is protected from automatic eviction.

        Example:
            >>> await driver.manager.pin("120.0.6099.71", pinned=True)
            >>> await driver.manager.pin("120.0.6099.71", pinned=False)
        """
        if type(version) is not str or not version:
            raise errors.InvalidArgumentError(
                "Cached artifact version must be non-empty text"
            )
        if type(artifact) is not str or artifact not in {"driver", "binary"}:
            raise errors.InvalidArgumentError("Unsupported cached artifact")
        if type(pinned) is not bool:
            raise errors.InvalidArgumentError("pinned must be a boolean")
        if self._file_manager is None:
            raise errors.InvalidArgumentError("Unsupported cached artifact")
        parsed = (
            self._parse_driver_version(version)
            if artifact == "driver"
            else self._parse_browser_version(version)
        )
        cache = self._cache_view
        if cache is None:
            raise errors.InvalidArgumentError("Unsupported cached artifact")
        await run_blocking(cache.pin, parsed, artifact, pinned)

    async def install(self, *args: Any, **kwargs: Any) -> Path:
        """Resolve and install a WebDriver executable.

        Args:
            *args: Positional arguments forwarded to the wrapped operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.

        Returns:
            Absolute path to the installed WebDriver executable.
        """
        raise NotImplementedError(
            "<DriverManager> `install()` method must be implemented in "
            "subclass: <{}>.".format(self.__class__.__name__)
        )

    def reset(self) -> None:
        """Reset a previously successful webdriver installation."""
        self._channel = None
        self._driver_version = None
        self._driver_location = None
        self._browser_version = None
        self._browser_location = None
        if self._invocation.get() is None:
            self._last_result = None

    @property
    def _installation_lock(self) -> Lock:
        """Return the installation lock for this manager and event loop.

        Returns:
            The installation lock for this manager and event loop.
        """
        return installation_lock(self)

    async def install_result(
        self,
        *args: Any,
        policy: str | None = None,
        validate_compatibility: bool = False,
        **kwargs: Any,
    ) -> InstallationResult:
        """Install with a stable result and an optional explicit resolution policy.

        Policies: exact, compatible-build, compatible-major, latest-compatible,
        cached-compatible, offline. The existing install() selectors/defaults
        remain available when policy is omitted.

        Args:
            policy: Explicit cache/vendor resolution strategy, or None to derive it
                from the version selector.
            validate_compatibility: Whether to reject a resolved driver/browser pair
                that violates the manager's recorded compatibility rule.
            *args: Positional arguments forwarded to the wrapped operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.

        Returns:
            Immutable request, executable paths, versions, and channel snapshot.

        Example:
            >>> result = await driver.manager.install_result(
            ...     version="build", policy="compatible-build", validate_compatibility=True
            ... )
            >>> print(result.driver_version, result.browser_version)
        """
        if policy is not None and type(policy) is not str:
            raise errors.InvalidArgumentError("Resolution policy must be text or None")
        if policy not in {
            None,
            "exact",
            "compatible-build",
            "compatible-major",
            "latest-compatible",
            "cached-compatible",
            "offline",
        }:
            raise errors.InvalidArgumentError(
                "Unknown driver resolution policy: %r" % policy
            )
        if type(validate_compatibility) is not bool:
            raise errors.InvalidArgumentError(
                "validate_compatibility must be a boolean"
            )
        token = self._policy_override.set(policy)
        validation = self._validate_pair.set(validate_compatibility)
        completed = self._completed_result.set(None)
        try:
            await self.install(*args, **kwargs)
            result = self._completed_result.get()
            if result is None:
                raise errors.DriverInstallationError(
                    "Custom install() must provide an installation result"
                )
            return result
        finally:
            self._policy_override.reset(token)
            self._validate_pair.reset(validation)
            self._completed_result.reset(completed)

    def _resolution_policy(self, version: Version | str | None = None) -> str:
        """Resolve the active policy or derive it from the requested selector.

        Args:
            version: Original version selector used when no explicit policy is active.

        Returns:
            The active explicit policy or the policy implied by the version selector.
        """
        active = self._invocation.get()
        override = active.request.policy if active is not None else "default"
        if override != "default":
            return override
        if isinstance(version, str) and version in (
            "offline",
            "cached",
            "auto",
            "latest",
        ):
            return {
                "offline": "offline",
                "cached": "cached-compatible",
                "auto": "cached-compatible",
                "latest": "latest-compatible",
            }[version]
        if version == "major":
            return "compatible-major"
        if version == "patch" or (
            self._target_version is not None
            and len(self._target_version) == self._target_version._VERSION_SEGMENTS
        ):
            return "exact"
        return "compatible-build"

    def _require_online(self) -> None:
        """Reject a vendor request when the active installation is offline-only."""
        active = self._invocation.get()
        if active is not None and (
            active.request.policy == "offline" or active.request.version == "offline"
        ):
            raise errors.DriverRequestFailedError(
                "Offline resolution cannot make a vendor request"
            )

    def _offline_miss(self, version: Version | str | None) -> NoReturn:
        """Raise a diagnostic error for an offline cache miss without making a request.

        Args:
            version: Requested version or selector that could not be found in cache.
        """
        raise errors.DriverExecutableNotDetectedError(
            "No cached %s driver matches %s on %s/%s%s. Provision it online first using the same cache."
            % (
                self._name,
                version,
                self._os_name,
                self._os_arch,
                "-arm" if self._os_is_arm else "",
            )
        )

    def _strict_target_version(
        self, version: Version | str, parser: Callable[[str], V], segments: int
    ) -> V:
        """Validate a numeric selector before parsing it as a version object.

        Args:
            version: Numeric version text or an existing compatible Version instance.
            parser: Callable that constructs the requested version subtype from text.
            segments: Maximum number of numeric components accepted in the selector.

        Returns:
            The parsed version, retaining the subtype returned by parser.
        """
        value = str(version) if isinstance(version, Version) else version
        if (
            not isinstance(value, str)
            or fullmatch(
                r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){0,%d}" % (segments - 1),
                value,
            )
            is None
        ):
            self._raise_invalid_driver_version_error(version)
        return parser(value)

    def _validate_installed_pair(self) -> None:
        """Check the installed driver and browser against the active compatibility policy."""
        self._validate_version_pair(self._driver_version, self._browser_version)

    def _validate_version_pair(
        self, driver_version: DV | None, browser_version: BV | None
    ) -> None:
        """Validate one resolved driver/browser version pair.

        Args:
            driver_version: Resolved browser-driver version, or None when unavailable.
            browser_version: Detected or provisioned browser version, or None when unavailable.
        """
        if self._name != "Safari" and (
            driver_version is None
            or browser_version is None
            or driver_version.build != browser_version.build
        ):
            raise errors.InvalidDriverVersionError(
                "Installed driver/browser builds are incompatible"
            )

    @property
    def last_result(self) -> InstallationResult | None:
        """The last successful result; use install_result() for concurrent calls.

        Returns:
            Most recently published installation snapshot, or None after reset or
            before the first successful installation.
        """
        return self._last_result

    # File manager ------------------------------------------------------------------------
    @property
    def max_cache_size(self) -> int | None:
        """Return the configured retained-artifact count limit.

        Returns:
            Positive artifact limit, or None when count-based eviction is disabled.
        """
        return self._max_cache_size

    @max_cache_size.setter
    def max_cache_size(self, value: int | None) -> None:
        # Unlimit cache size
        """Set the retained-artifact count limit.

        Args:
            value: Positive artifact limit, or None to disable count-based eviction.
        """
        if value is None:
            self._max_cache_size = None
            return None  # exit

        if type(value) is not int:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid webdriver max cache size: {} {}.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        if value < 1:
            raise errors.InvalidArgumentError(
                "<{}>\nWebdriver max cache size must be >= 1, instead got: {}.".format(
                    self.__class__.__name__, value
                )
            )
        self._max_cache_size = value

    # Request -----------------------------------------------------------------------------
    @property
    def requests_timeout(self) -> int | float:
        """Return the total deadline for one vendor metadata request.

        Returns:
            Positive finite deadline in seconds, including retry delays.
        """
        total = self._requests_timeout.total
        if total is None:
            raise errors.DriverManagerError("Requests timeout has no total deadline")
        return total

    @requests_timeout.setter
    def requests_timeout(self, value: int | float) -> None:
        """Set the total vendor metadata request deadline.

        Args:
            value: Positive finite number of seconds, including retry delays.
        """
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid requests timeout: {} {}. Must be an integer "
                "or float.".format(self.__class__.__name__, repr(value), type(value))
            )
        if value <= 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid requests timeout: {}. Must be greater than 0.".format(
                    self.__class__.__name__, repr(value)
                )
            )
        self._requests_timeout: ClientTimeout = ClientTimeout(value)

    @property
    def download_timeout(self) -> int | float:
        """Return the total deadline for one artifact download.

        Returns:
            Positive finite deadline in seconds, including admission and retry waits.
        """
        total = self._download_timeout.total
        if total is None:
            raise errors.DriverManagerError("Download timeout has no total deadline")
        return total

    @download_timeout.setter
    def download_timeout(self, value: int | float) -> None:
        """Set the total artifact download deadline.

        Args:
            value: Positive finite number of seconds for download and retry work.
        """
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid download timeout: {} {}. Must be an integer "
                "or float.".format(self.__class__.__name__, repr(value), type(value))
            )
        if value <= 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid download timeout: {}. Must be greater than 0.".format(
                    self.__class__.__name__, repr(value)
                )
            )
        self._download_timeout: ClientTimeout = ClientTimeout(value)

    @property
    def proxy(self) -> str | None:
        """Return the provisioning-only HTTP proxy URL.

        Returns:
            Explicit HTTP proxy URL, or None for direct vendor connections.
        """
        return self._proxy

    @proxy.setter
    def proxy(self, value: str | None) -> None:
        # Remove proxy
        """Set or clear the provisioning-only HTTP proxy URL.

        Args:
            value: HTTP proxy URL, or None to use direct vendor connections.
        """
        if value is None:
            self._proxy = None
            return None  # exit
        # Set proxy
        if not isinstance(value, str) or not value.startswith("http://"):
            raise errors.InvalidArgumentError("Proxy must be an HTTP proxy URL")
        self._proxy = value

    async def _request_response_text(self, url: str) -> str | None:
        """Fetch bounded vendor metadata and decode it as text.

        Args:
            url: Validated vendor metadata URL to fetch.

        Returns:
            Decoded vendor response text.
        """
        return await vendor_request(self, url, "text", ClientSession)

    async def _request_response_json(self, url: str) -> dict[str, Any] | None:
        """Fetch and decode bounded vendor JSON metadata.

        Args:
            url: Validated vendor JSON metadata URL to fetch.

        Returns:
            The decoded JSON value; the vendor endpoint determines its shape.
        """
        return await vendor_request(self, url, "json", ClientSession)

    async def _request_response_url(self, url: str) -> str | None:
        """Resolve the final URL through validated vendor redirects.

        Args:
            url: Validated vendor URL whose redirect target is resolved.

        Returns:
            The final validated HTTPS URL's last path component, or None when
            the vendor resource is missing. Gecko release redirects use this
            component as their version tag.
        """
        return await vendor_request(self, url, "url", ClientSession)

    async def _request_response_file(self, url: str) -> dict[str, Any] | None:
        """Stream a vendor artifact into an owned temporary download.

        Args:
            url: Validated vendor artifact URL to stream.

        Returns:
            A mapping containing the requested URL and an owned Download object,
            or None when the vendor resource is missing. Redirect targets are
            validated before following them; the original URL retains the
            archive filename used by the unpacker.
        """
        return await vendor_request(self, url, "file", ClientSession)

    # Target ------------------------------------------------------------------------------
    @property
    def channel(self) -> str:
        """Return the browser release channel published by the last installation.

        Returns:
            Stable, beta, development, or Chrome-for-Testing channel identifier.

        Raises:
            errors.DriverInstallationError: No installation has published a channel.
        """
        if self._channel is None:
            self._raise_installation_error("channel")
        return self._channel

    def _parse_target_version(self, version: Any) -> None:
        """Validate and retain the subclass-specific driver version selector.

        Args:
            version: Public version object or selector to validate and store.
        """
        raise NotImplementedError(
            "<DriverManager> `_parse_target_version()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _parse_target_binary(self, binary: PathInput | None) -> None:
        """Normalize an explicit browser executable for request-local use.

        Args:
            binary: Explicit browser executable path, or None to enable discovery.
        """
        if binary is None:
            self._target_binary = None
            return None  # exit
        try:
            self._target_binary = self._normalize_file_location(binary)
        except (OSError, TypeError, ValueError, errors.AseleniumError) as err:
            self._raise_invalid_browser_location_error(binary, cause=err)

    @staticmethod
    def _normalize_file_location(path: PathInput) -> Path:
        """Validate an explicit string/PathLike path without changing its filename.

        Make the path absolute before it is saved for later installation work.
        Do not resolve symlinks: launchers and app bundles can depend on their
        lexical location. Empty and byte-valued paths are not supported.

        Args:
            path: Existing browser executable supplied at the public path boundary.

        Returns:
            Absolute path to the existing file without resolving symbolic links.
        """
        return file_path(path)

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> DV:
        """Return the driver version published by the last installation.

        Returns:
            Concrete driver-version subtype for this browser family.

        Raises:
            errors.DriverInstallationError: No installation has published a version.
        """
        if self._driver_version is None:
            self._raise_installation_error("driver_version")
        return self._driver_version

    def _match_driver_executable(
        self,
        version: DV,
        match_method: str,
    ) -> Path | None:
        """Match a cached WebDriver executable.

        Args:
            version: Parsed driver version whose cache entry is requested.
            match_method: Version match granularity: major, build, or patch.

        Returns:
            Absolute cached executable path, or None when no artifact matches.
        """
        # Match driver from cache
        cache = self._cache_view
        if cache is None:
            self._raise_attribute_implementation_error("_file_manager")
        driver = cache.match_driver(version, match_method=match_method)
        if driver is None:
            return None

        # Set version & location
        self._driver_version = self._parse_driver_version(driver["version"])
        self._driver_location = driver["location"]

        # Return driver location
        return self._driver_location

    async def _request_driver_version(self, driver_version: DV | None) -> DV:
        """Resolve an installable driver version from vendor metadata.

        Args:
            driver_version: Browser-derived or explicitly selected target version;
                None requests the latest release where the vendor supports it.

        Returns:
            Concrete driver version selected from the vendor response.
        """
        raise NotImplementedError(
            "<DriverManager> `_request_driver_version()` must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    @property
    def driver_location(self) -> Path:
        """Return the installed WebDriver executable path.

        Returns:
            Absolute path published by the last successful installation.
        """
        if self._driver_location is None:
            self._raise_installation_error("executable")
        return self._driver_location

    async def _install_driver_executable(self, driver_version: DV) -> Path:
        """Install and cache a WebDriver executable.

        Args:
            driver_version: Resolved browser-driver version.

        Returns:
            Absolute path to the cached executable.
        """
        raise NotImplementedError(
            "<DriverManager> `_install_driver_executable()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _cache_driver_executable(self, version: DV, res: dict[str, Any]) -> Path:
        """Cache a downloaded WebDriver executable.

        Args:
            version: Exact driver version assigned to the downloaded archive.
            res: Download metadata containing the source URL and owned archive content.

        Returns:
            Absolute path to the cached executable.
        """
        try:
            cache = self._cache_view
            driver_file_cls = self._driver_file_cls
            if cache is None:
                self._raise_attribute_implementation_error("_file_manager")
            if driver_file_cls is None:
                self._raise_attribute_implementation_error("_driver_file_cls")
            driver = cache.cache_driver(
                version,
                driver_file_cls(self._os_name, **res),
                max_cache_size=self._max_cache_size,
            )
            self._driver_version = self._parse_driver_version(driver["version"])
            self._driver_location = driver["location"]
            return self._driver_location

        finally:
            del res

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> BV:
        """Return the browser version published by the last installation.

        Returns:
            Concrete browser-version subtype paired with the resolved driver.

        Raises:
            errors.DriverInstallationError: No installation has published a version.
        """
        if self._browser_version is None:
            self._raise_installation_error("browser_version")
        return self._browser_version

    def _detect_browser_version(self, browser_location: Path) -> BV:
        """Probe a browser executable and parse its vendor-specific version output.

        Args:
            browser_location: Validated browser executable path used for the probe.

        Returns:
            Concrete browser version parsed from the executable's probe output.
        """
        try:
            # Subprocess arguments are an intentional text boundary. All
            # discovery and installation work before this point retains Path.
            location = str(browser_location)
            if self._os_name == OSType.WIN:
                # A fixed executable and an encoded script avoid cmd.exe parsing.
                # Single-quoted PowerShell literals escape apostrophes by doubling
                # them; -LiteralPath also disables wildcard interpretation.
                literal = location.replace("'", "''")
                script = (
                    "$ErrorActionPreference='Stop'; (Get-Item -LiteralPath '%s').VersionInfo.FileVersion"
                    % literal
                )
                powershell = (
                    parse_path(environ.get("SystemRoot", r"C:\Windows"))
                    / "System32"
                    / "WindowsPowerShell"
                    / "v1.0"
                    / "powershell.exe"
                )
                cmd = [
                    str(powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    b64encode(script.encode("utf-16le")).decode("ascii"),
                ]
            else:
                cmd = [location, "--version"]

            res = self._read_from_cmd(cmd)
            return self._parse_browser_version(res)
        except (
            OSError,
            TypeError,
            UnicodeError,
            SubprocessError,
            errors.AseleniumInvalidPathError,
            errors.InvalidBrowserVersionError,
        ) as err:
            self._raise_invalid_browser_location_error(browser_location, cause=err)

    @property
    def browser_location(self) -> Path:
        """Return the browser executable paired with the installed driver.

        Returns:
            Absolute browser executable path published by the last installation.
        """
        if self._browser_location is None:
            self._raise_installation_error("browser_location")
        return self._browser_location

    def _match_browser_binary(
        self,
        version: BV,
        match_method: str,
    ) -> Path | None:
        """Match a cached browser executable.

        Args:
            version: Parsed browser version whose cache entry is requested.
            match_method: Version match granularity: major, build, or patch.

        Returns:
            Absolute cached browser path, or None when no artifact matches.
        """
        # Match driver from cache
        cache = self._cache_view
        if cache is None:
            self._raise_attribute_implementation_error("_file_manager")
        binary = cache.match_binary(version, match_method=match_method)
        if binary is None:
            return None

        # Set version & location
        self._browser_version = self._parse_browser_version(binary["version"])
        self._browser_location = binary["location"]

        # Return driver location
        return self._browser_location

    def _detect_browser_location(self) -> Path:
        """Automatically detect the location of browser binary on the system.

        Returns:
            Absolute path to the detected browser executable.
        """
        paths = self._browser_paths_for_channel()
        if self._os_name == OSType.MAC:
            location = self._find_mac_browser_location(*paths)
        elif self._os_name == OSType.WIN:
            location = self._find_win_browser_location(*paths)
        else:
            location = self._find_linux_browser_location(*paths)

        # Validate location
        if location is None:
            self._raise_invalid_browser_location_error(location)
        return location

    def _browser_paths_for_channel(self) -> list[str]:
        """Return discovery candidates after validating platform and release channel.

        Returns:
            Relative executable paths or command names for the active platform/channel.
        """
        attribute = {
            OSType.MAC: "_MAC_BINARY_PATHS",
            OSType.WIN: "_WIN_BINARY_PATHS",
            OSType.LINUX: "_LINUX_BINARY_PATHS",
        }[self._os_name]
        paths = getattr(self, attribute)
        if not isinstance(paths, dict):
            self._raise_attribute_implementation_error(attribute)
        try:
            return paths[self._channel]
        except (KeyError, TypeError):
            self._raise_invalid_channel_error()

    def _find_mac_browser_location(self, *paths: str) -> Path | None:
        """Find the path to the browser binary on MacOS.

        Args:
            *paths: Application-relative executable paths to test under macOS roots.

        Returns:
            Absolute browser path, or None when no candidate exists.
        """
        for path in paths:
            # Check default location
            location = Path("/Applications") / path
            if location.is_file():
                return location
            # Check environ locations
            for env_path in self._environ_paths:
                location = env_path / path
                if location.is_file():
                    return location
        return None

    def _find_win_browser_location(self, *paths: str) -> Path | None:
        """Find the path to the browser binary on Windows.

        Args:
            *paths: Installation-relative executable paths to test under Windows roots.

        Returns:
            Absolute browser path, or None when no candidate exists.
        """
        for path in paths:
            for env_path in self._environ_paths:
                location = env_path / path
                if location.is_file():
                    return location
        return None

    def _find_linux_browser_location(self, *paths: str) -> Path | None:
        """Find the path to the browser binary on Linux.

        Args:
            *paths: Executable command names to search through validated PATH roots.

        Returns:
            Absolute browser path, or None when no executable candidate exists.
        """
        search_path = pathsep.join(str(path) for path in self._environ_paths)
        for path in paths:
            location = which(path, path=search_path)
            if location is not None:
                candidate = parse_path(location)
                if candidate.is_file():
                    return candidate
        return None

    async def _install_browser_binary(self, browser_version: BV) -> Path:
        """Install and cache a browser executable.

        Args:
            browser_version: Detected or explicitly selected browser version.

        Returns:
            Absolute path to the cached browser executable.
        """
        raise NotImplementedError(
            "<DriverManager> `_install_browser_binary()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _cache_browser_binary(self, version: BV, res: dict[str, Any]) -> Path:
        """Cache a downloaded browser executable.

        Args:
            version: Exact browser version assigned to the downloaded archive.
            res: Download metadata containing the source URL and owned archive content.

        Returns:
            Absolute path to the cached browser executable.
        """
        try:
            cache = self._cache_view
            binary_file_cls = self._binary_file_cls
            if cache is None:
                self._raise_attribute_implementation_error("_file_manager")
            if binary_file_cls is None:
                self._raise_attribute_implementation_error("_binary_file_cls")
            binary = cache.cache_binary(
                version,
                binary_file_cls(self._os_name, **res),
                max_cache_size=self._max_cache_size,
            )
            self._browser_version = self._parse_browser_version(binary["version"])
            self._browser_location = binary["location"]
            return self._browser_location

        finally:
            del res

    # Platform Utils ----------------------------------------------------------------------
    @property
    def _os_name(self) -> Literal["linux", "mac", "win"]:
        """Return the normalized operating-system identifier used by vendors.

        Returns:
            ``linux``, ``mac``, or ``win`` for the active installation request.
        """
        active = self._invocation.get()
        if active is not None:
            os_name = active.request.os_name
            if os_name == OSType.LINUX:
                return OSType.LINUX
            if os_name == OSType.MAC:
                return OSType.MAC
            if os_name == OSType.WIN:
                return OSType.WIN
            raise errors.UnsupportedPlatformError(
                "Invalid installation operating system: %r" % os_name
            )
        if self.__os_name is None:
            syst = system()
            if syst == "Darwin":
                self.__os_name = OSType.MAC
            elif syst == "Windows":
                self.__os_name = OSType.WIN
            elif syst == "Linux":
                self.__os_name = OSType.LINUX
            else:
                raise errors.UnsupportedPlatformError(
                    "<{}>\nUnsupported platform (Operating System): '{}'".format(
                        self.__class__.__name__, syst
                    )
                )
        return self.__os_name

    @property
    def _os_arch(self) -> Literal["32", "64"]:
        """Return the normalized process architecture width used by vendors.

        Returns:
            ``32`` or ``64`` for the active installation request.
        """
        active = self._invocation.get()
        if active is not None:
            architecture_name = active.request.architecture
            if architecture_name == "32":
                return "32"
            if architecture_name == "64":
                return "64"
            raise errors.UnsupportedPlatformError(
                "Invalid installation architecture: %r" % architecture_name
            )
        if self.__os_arch is None:
            if "64" in architecture()[0]:
                self.__os_arch = "64"
            else:
                self.__os_arch = "32"
        return self.__os_arch

    @property
    def _os_is_arm(self) -> bool:
        """Return whether vendor artifact selection targets an ARM architecture.

        Returns:
            True if the platform is arm based; otherwise False.
        """
        active = self._invocation.get()
        if active is not None:
            return active.request.arm
        if self.__os_is_arm is None:
            mach = machine().lower()
            if "arm" in mach:
                self.__os_is_arm = True
            elif "aarch" in mach:
                self.__os_is_arm = True
            else:
                self.__os_is_arm = False
        return self.__os_is_arm

    @property
    def _environ_paths(self) -> list[Path]:
        """Build validated, deduplicated browser discovery roots from the environment.

        Returns:
            Deduplicated absolute search roots in environment order.
        """
        if self.__environ_paths is None:
            if self._os_name == OSType.WIN:
                paths = []
                for env in [
                    "PROGRAMFILES",
                    "PROGRAMFILES(X86)",
                    "LOCALAPPDATA",
                    "PROGRAMFILES(ARM)",
                ]:
                    try:
                        paths.append(environ[env])
                    except KeyError:
                        pass
                # Preserve the vendor/channel-specific relative paths when
                # considering additional installation roots from PATH.
                paths.extend(environ.get("PATH", "").split(pathsep))
            else:
                paths = environ.get("PATH", "").split(pathsep)
            normalized: list[Path] = []
            seen: set[Path] = set()
            for path in paths:
                # An empty PATH component must not become an implicit cwd search.
                if not path:
                    continue
                try:
                    location = parse_path(path)
                except errors.AseleniumInvalidPathError:
                    # One malformed external environment entry must not prevent
                    # discovery through the remaining valid search roots.
                    continue
                if location not in seen:
                    normalized.append(location)
                    seen.add(location)
            self.__environ_paths = normalized
        return self.__environ_paths

    # Command Utils -----------------------------------------------------------------------
    def _read_from_cmd(self, cmd: list[str]) -> str:
        """Run literal arguments with a deadline; never evaluate a shell string.

        Args:
            cmd: Executable and literal argument vector for the version probe.

        Returns:
            Decoded executable probe output after the child process has been reaped.
        """
        if (
            not isinstance(cmd, list)
            or not cmd
            or not all(isinstance(arg, str) for arg in cmd)
        ):
            raise TypeError("Browser probes require a non-empty argument list")
        stream = Popen(cmd, stdout=PIPE, stdin=DEVNULL, stderr=DEVNULL, shell=False)
        try:
            try:
                output = stream.communicate(timeout=self._PROBE_TIMEOUT)[0]
            except BaseException:
                # Reap the direct child without an unbounded second communicate
                # (a descendant may still hold its inherited stdout pipe open).
                try:
                    stream.kill()
                except OSError:
                    # The child may have exited between the timeout and kill.
                    pass
                try:
                    stream.wait(timeout=self._PROBE_KILL_TIMEOUT)
                except (TimeoutExpired, OSError):
                    pass
                raise
            if stream.returncode:
                raise CalledProcessError(stream.returncode, cmd)
            return output.decode("utf-8")
        finally:
            stdout = getattr(stream, "stdout", None)
            if stdout is not None:
                stdout.close()

    # Version Utils -----------------------------------------------------------------------
    def _parse_driver_version(self, version: Any) -> DV:
        """Convert vendor or cached version data to the manager's driver subtype.

        Args:
            version: Vendor response text, cached version, or existing version object.

        Returns:
            Concrete driver-version subtype used by this manager.
        """
        raise NotImplementedError(
            "<DriverManager> `_parse_driver_version()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _parse_browser_version(self, version: Any) -> BV:
        """Convert probe or result data to the manager's browser-version subtype.

        Args:
            version: Probe output, result text, or existing version object.

        Returns:
            Concrete browser-version subtype used by this manager.
        """
        raise NotImplementedError(
            "<DriverManager> `_parse_browser_version()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    # Exceptions --------------------------------------------------------------------------
    def _raise_installation_error(self, attr_name: str) -> NoReturn:
        """Raise an installation error.

        Args:
            attr_name: Public result property accessed before installation completed.

        Raises:
            errors.DriverInstallationError: Always raised with the supplied diagnostic context.
        """
        raise errors.DriverInstallationError(
            "<{}>\nCan't access '{}' attribute before executing "
            "the `install()` method.".format(self.__class__.__name__, attr_name)
        )

    def _raise_attribute_implementation_error(self, attr_name: str) -> NoReturn:
        """Raise an attribute not implemented error.

        Args:
            attr_name: Required subclass attribute that has no implementation.

        Raises:
            NotImplementedError: Always raised with the supplied diagnostic context.
        """
        raise NotImplementedError(
            "<DriverManager>\nCritical class attribute '{}' not implemented in "
            "subclass: <{}>.".format(attr_name, self.__class__.__name__)
        )

    def _raise_invalid_channel_error(self) -> NoReturn:
        """Raise an invalid channel error.

        Raises:
            errors.DriverManagerError: Always raised with the supplied diagnostic context.
        """
        raise errors.DriverManagerError(
            "<{}>\nInvalid {} webdriver channel: {}.".format(
                self.__class__.__name__, self._name, repr(self._channel)
            )
        )

    def _raise_invalid_driver_version_error(self, version: Any) -> NoReturn:
        """Raise the invalid driver version error.

        Args:
            version: Rejected driver-version input included in the diagnostic.

        Raises:
            errors.InvalidDriverVersionError: Always raised with the supplied diagnostic context.
        """
        raise errors.InvalidDriverVersionError(
            "<{}>\nInvalid webdriver version {} {} for {} [{}] ({}{}{}).".format(
                self.__class__.__name__,
                repr(version),
                type(version),
                self._name,
                self._channel,
                self._os_name,
                self._os_arch,
                "_arm" if self._os_is_arm else "",
            )
        )

    def _raise_invalid_driver_location_error(self, path: object) -> NoReturn:
        """Raise an invalid webdriver location error.

        Args:
            path: Missing or invalid driver path included in the diagnostic.

        Raises:
            errors.DriverExecutableNotDetectedError: Always raised with the supplied diagnostic context.
        """
        if path is None:
            raise errors.DriverExecutableNotDetectedError(
                "<{}>\n{} [{}] ({}{}{}) webdriver is not detected in the system. Please make "
                "sure the webdriver exists or specify the webdriver location manually.".format(
                    self.__class__.__name__,
                    self._name,
                    self._channel,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                )
            )
        else:
            raise errors.DriverExecutableNotDetectedError(
                "<{}>\n{} [{}] ({}{}{}) webdriver location is invalid: {}. Please make "
                "sure the webdriver exists or specify the webdriver location manually.".format(
                    self.__class__.__name__,
                    self._name,
                    self._channel,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                    repr(path),
                )
            )

    def _raise_driver_request_failed_error(self, version: Version | None) -> NoReturn:
        """Raise a driver version request failed error.

        Args:
            version: Requested target version, or None for an unresolved latest request.

        Raises:
            errors.DriverRequestFailedError: Always raised with the supplied diagnostic context.
        """
        raise errors.DriverRequestFailedError(
            "<{}>\nFailed to request webdriver version '{}' for {} [{}] ({}{}{}).".format(
                self.__class__.__name__,
                version,
                self._name,
                self._channel,
                self._os_name,
                self._os_arch,
                "_arm" if self._os_is_arm else "",
            )
        )

    def _raise_driver_download_failed_error(
        self, version: Version, url: str
    ) -> NoReturn:
        """Raise a driver download failed error.

        Args:
            version: Driver version whose artifact could not be downloaded.
            url: Vendor artifact URL that exhausted the download policy.

        Raises:
            errors.DriverDownloadFailedError: Always raised with the supplied diagnostic context.
        """
        raise errors.DriverDownloadFailedError(
            "<{}>\nFailed to download webdriver '{}' "
            "for {} [{}] ({}{}{}) from url: '{}'.".format(
                self.__class__.__name__,
                version,
                self._name,
                self._channel,
                self._os_name,
                self._os_arch,
                "_arm" if self._os_is_arm else "",
                url,
            )
        )

    def _raise_invalid_browser_version_error(self, version: Any) -> NoReturn:
        """Raise the invalid browser version error.

        Args:
            version: Rejected browser-version input included in the diagnostic.

        Raises:
            errors.InvalidBrowserVersionError: Always raised with the supplied diagnostic context.
        """
        raise errors.InvalidBrowserVersionError(
            "<{}>\nInvalid browser version {} {} for {} [{}] ({}{}{}).".format(
                self.__class__.__name__,
                repr(version),
                type(version),
                self._name,
                self._channel,
                self._os_name,
                self._os_arch,
                "_arm" if self._os_is_arm else "",
            )
        )

    def _raise_invalid_browser_location_error(
        self, path: object, cause: BaseException | None = None
    ) -> NoReturn:
        """Raise an invalid binary location error.

        Args:
            path: Missing or invalid browser path included in the diagnostic.
            cause: Underlying validation or probe failure, when available.

        Raises:
            errors.BrowserBinaryNotDetectedError: Always raised with the supplied diagnostic context.
        """
        if path is None:
            raise errors.BrowserBinaryNotDetectedError(
                "<{}>\n{} [{}] ({}{}{}) binary is not detected in the system. Please make sure the "
                "browser has been installed correctly or specify the browser location manually.".format(
                    self.__class__.__name__,
                    self._name,
                    self._channel,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                )
            ) from cause
        else:
            raise errors.BrowserBinaryNotDetectedError(
                "<{}>\n{} [{}] ({}{}{}) binary location is invalid: {}. Please make sure the "
                "browser has been installed correctly or specify the browser location manually.".format(
                    self.__class__.__name__,
                    self._name,
                    self._channel,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                    repr(path),
                )
            ) from cause

    def _raise_browser_download_failed_error(
        self, version: Version, url: str
    ) -> NoReturn:
        """Raise a browser download failed error.

        Args:
            version: Browser version whose artifact could not be downloaded.
            url: Vendor artifact URL that exhausted the download policy.

        Raises:
            errors.BrowserDownloadFailedError: Always raised with the supplied diagnostic context.
        """
        raise errors.BrowserDownloadFailedError(
            "<{}>\nFailed to download browser {} '{}' ({}{}{}) from url: '{}'.".format(
                self.__class__.__name__,
                self._name,
                version,
                self._os_name,
                self._os_arch,
                "_arm" if self._os_is_arm else "",
                url,
            )
        )


class ChromiumBaseDriverManager(DriverManager[ChromiumVersion, ChromiumVersion]):
    """Share installed-browser discovery and CfT-era resolution across Chromium products."""

    # fmt: off
    _CHROMELABS_ENDPOINT_URL: str = "https://googlechromelabs.github.io/chrome-for-testing"
    """Chrome for Testing metadata endpoint used for release and asset lookup."""
    _MIN_CHROME_VERSION: ChromiumVersion = ChromiumVersion("115")
    """Chrome/Chromium driver provisioning requires the CfT release pipeline."""

    # fmt: on

    def __init__(
        self,
        name: str,
        file_manager_cls: type[FileManager],
        driver_file_cls: type[File] | None,
        binary_file_cls: type[File] | None,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        """Configure a Chromium-family product and its cache/archive implementations.

        Args:
            name: Chromium-family product name used in diagnostics and cache identity.
            file_manager_cls: Product-specific cache manager implementation.
            driver_file_cls: Product-specific driver archive implementation.
            binary_file_cls: Browser archive implementation, or None when the product
                cannot provision browser binaries.
            directory: Cache parent directory; None uses the default per-user cache location.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit provisioning proxy URL, or None for a direct connection.
        """
        super().__init__(
            name,
            file_manager_cls,
            driver_file_cls,
            binary_file_cls,
            directory=directory,
            max_cache_size=max_cache_size,
            request_timeout=request_timeout,
            download_timeout=download_timeout,
            proxy=proxy,
        )
        # Installation
        self._chromelabs_arch: str | None = None
        # Type hinting
        self._file_manager: ChromiumBaseFileManager
        self._target_version: ChromiumVersion | None
        self._driver_version: ChromiumVersion | None
        self._browser_version: ChromiumVersion | None

    # Installation ------------------------------------------------------------------------
    @isolated_install
    async def _install_chromium(
        self,
        version: ChromiumVersion | str = "build",
        channel: Literal["stable", "beta", "dev"] = "stable",
        binary: PathInput | None = None,
    ) -> Path:
        """Resolve a driver for an installed Chromium-family browser.

        Args:
            version: Numeric Chromium version or major, build, patch, latest, cached,
                or offline compatibility selector.
            channel: Installed browser release channel used for automatic discovery.
            binary: Explicit browser executable, or None to discover the selected channel.

        Returns:
            Absolute path to an integrity-checked cached driver executable.
        """
        try:
            # Parse arguments
            self._channel = channel
            self._browser_paths_for_channel()
            self._parse_target_version(version)
            self._parse_target_binary(binary)

            # Detect browser location
            browser_location = (
                self._detect_browser_location()
                if self._target_binary is None
                else self._target_binary
            )
            self._browser_location = browser_location

            # Detect browser version
            self._browser_version = await run_blocking(
                self._detect_browser_version, browser_location
            )
            self._validate_supported_version(self._browser_version, browser=True)

            # Install webdriver
            async with self._installation_lock:
                policy = self._resolution_policy(version)
                target = self._target_version or self._browser_version
                match_method = (
                    "major"
                    if policy == "compatible-major" or len(target) < 3
                    else "build"
                )
                if policy == "exact" or (
                    policy == "offline"
                    and self._target_version is not None
                    and len(target) == 4
                ):
                    if len(target) != 4:
                        raise errors.InvalidDriverVersionError(
                            "Exact Chromium versions require four numeric components"
                        )
                    match_method = "patch"
                # . match from cache - 1st
                driver_location = (
                    None
                    if policy == "latest-compatible"
                    else await run_blocking(
                        self._match_driver_executable, target, match_method
                    )
                )
                if driver_location is not None:
                    return driver_location
                if policy == "offline":
                    self._offline_miss(target)

                # . request driver version
                driver_version = (
                    target
                    if policy == "exact"
                    else await self._request_driver_version(target)
                )
                if policy != "exact" and (
                    driver_version.major != target.major
                    or (
                        match_method == "build" and driver_version.build != target.build
                    )
                ):
                    raise errors.InvalidDriverVersionError(
                        "Vendor returned an incompatible driver build: %s for %s"
                        % (driver_version, target)
                    )

                # . match exact resolved version from cache
                driver_location = await run_blocking(
                    self._match_driver_executable, driver_version, "patch"
                )
                if driver_location is not None:
                    return driver_location

                # . install driver executable
                return await self._install_driver_executable(driver_version)

        except BaseException:
            self.reset()
            raise

    # Target ------------------------------------------------------------------------------
    def _validate_supported_version(
        self, version: ChromiumVersion, *, browser: bool = False
    ) -> None:
        # Edge uses its own release pipeline, not Chrome for Testing.
        """Reject unsupported Chrome or Chromium versions before cache lookup.

        Args:
            version: Parsed Chrome or Chromium version to compare with the CfT floor.
            browser: Whether an unsupported value should raise a browser-version error.
        """
        if self._name != "Edge" and version < self._MIN_CHROME_VERSION:
            error = (
                errors.InvalidBrowserVersionError
                if browser
                else errors.InvalidDriverVersionError
            )
            raise error(
                "Chrome/Chromium 115 or newer is required; pre-CfT provisioning has been removed"
            )

    def _parse_target_version(self, version: Any) -> None:
        """Validate a Chromium driver version or compatibility selector.

        Args:
            version: Public Chromium version or compatibility selector to validate.
        """
        if version in ["major", "build", "patch", "latest", "cached", "offline", None]:
            self._target_version = None
        else:
            self._target_version = self._strict_target_version(
                version, self._parse_driver_version, 4
            )
            if len(self._target_version) == 2:
                raise errors.InvalidDriverVersionError(
                    "Chromium selectors must be a major, three-part build, or four-part exact version"
                )
            self._validate_supported_version(self._target_version)

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> ChromiumVersion:
        """Return the Chromium driver version published by the last installation.

        Returns:
            Parsed four-component Chromium driver version.
        """
        return super().driver_version

    async def _request_driver_version(
        self, driver_version: ChromiumVersion | None
    ) -> ChromiumVersion:
        """Resolve the newest vendor driver matching a Chromium major or build.

        Args:
            driver_version: Resolved browser-driver version.

        Returns:
            Full Chromium driver version returned by the CfT release endpoint.
        """
        if driver_version is None:
            self._raise_driver_request_failed_error(driver_version)

        # Construct check version url
        version = (
            driver_version.major
            if self._resolution_policy() == "compatible-major"
            or len(driver_version) < 3
            else driver_version.build
        )
        self._validate_supported_version(driver_version)
        url = self._CHROMELABS_ENDPOINT_URL + "/LATEST_RELEASE_%s" % version

        # Request driver version
        res = await self._request_response_text(url)

        # Parse driver version
        try:
            return self._parse_driver_version(res)
        except errors.InvalidDriverVersionError:
            self._raise_driver_request_failed_error(driver_version)

    @artifact_install("driver")
    async def _install_driver_executable(self, driver_version: ChromiumVersion) -> Path:
        """Install and cache a Chromium driver with cross-process ownership.

        Args:
            driver_version: Resolved browser-driver version.

        Returns:
            Absolute path to the cached Chromium driver executable.
        """
        url = await self._cft_asset_url(driver_version, "chromedriver")

        # Download driver content
        res = await self._request_response_file(url)
        if res is None:
            self._raise_driver_download_failed_error(driver_version, url)

        # Cache driver executable
        return await run_blocking(self._cache_driver_executable, driver_version, res)

    def _generate_chromelabs_arch(self) -> str:
        """Map the active platform to a Chrome for Testing artifact label.

        For example: `'win64'`, `'mac-arm64'`, `'linux64'`.

        Returns:
            Vendor platform label such as ``win64``, ``mac-arm64``, or ``linux64``.
        """
        if self._chromelabs_arch is None:
            if self._os_name == OSType.WIN:
                arch = "win-arm64" if self._os_is_arm else "win" + self._os_arch
            elif self._os_name == OSType.MAC:
                arch = "mac-arm64" if self._os_is_arm else "mac-x64"
            else:
                arch = "linux-arm64" if self._os_is_arm else "linux" + self._os_arch
            self._chromelabs_arch = arch
        return self._chromelabs_arch

    async def _cft_asset_url(self, version: ChromiumVersion, artifact: str) -> str:
        """Select an exact artifact/architecture from the vendor's version manifest.

        Args:
            version: Exact four-component CfT version whose manifest is requested.
            artifact: Manifest artifact key, either ``chromedriver`` or ``chrome``.

        Returns:
            Validated Google Storage HTTPS URL for the active vendor platform.
        """
        self._validate_supported_version(version)
        metadata = await self._request_response_json(
            self._CHROMELABS_ENDPOINT_URL + "/%s.json" % version
        )
        platform = self._generate_chromelabs_arch()
        if not isinstance(metadata, dict) or metadata.get("version") != str(version):
            raise errors.DriverRequestFailedError(
                "No valid CfT manifest for exact version %s" % version
            )
        downloads = metadata.get("downloads")
        if not isinstance(downloads, dict) or not isinstance(
            downloads.get(artifact), list
        ):
            raise errors.DriverRequestFailedError(
                "CfT manifest has no valid %s download list" % artifact
            )
        for asset in downloads[artifact]:
            if not isinstance(asset, dict):
                raise errors.DriverRequestFailedError(
                    "CfT manifest contains a malformed asset"
                )
            if asset.get("platform") != platform:
                continue
            url = asset.get("url", "")
            try:
                if not isinstance(url, str):
                    raise ValueError("Artifact URL must be text")
                parsed = urlsplit(url)
            except ValueError as cause:
                raise errors.DriverRequestFailedError(
                    "CfT manifest contains an unexpected artifact URL"
                ) from cause
            expected = "/chrome-for-testing-public/%s/%s/%s-%s.zip" % (
                version,
                platform,
                artifact,
                platform,
            )
            if (
                parsed.scheme != "https"
                or parsed.netloc != "storage.googleapis.com"
                or parsed.path != expected
                or parsed.query
                or parsed.fragment
            ):
                raise errors.DriverRequestFailedError(
                    "CfT manifest contains an unexpected artifact URL"
                )
            return url
        raise errors.DriverExecutableNotDetectedError(
            "CfT %s %s has no %s artifact" % (version, artifact, platform)
        )

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> ChromiumVersion:
        """Return the Chromium browser version published by the last installation.

        Returns:
            Parsed version of the discovered or provisioned Chromium-family browser.
        """
        return super().browser_version

    # Version Utils -----------------------------------------------------------------------
    def _parse_driver_version(self, version: Any) -> ChromiumVersion:
        """Parse Chromium driver metadata into a four-component-aware version.

        Args:
            version: Vendor response text, cached version, or ChromiumVersion instance.

        Returns:
            Parsed ChromiumVersion preserving the vendor's available components.
        """
        try:
            return ChromiumVersion(version)
        except Exception:
            self._raise_invalid_driver_version_error(version)

    def _parse_browser_version(self, version: Any) -> ChromiumVersion:
        """Parse Chromium browser probe output into a comparable version.

        Args:
            version: Browser probe text, result text, or ChromiumVersion instance.

        Returns:
            Parsed ChromiumVersion preserving the browser's available components.
        """
        try:
            return ChromiumVersion(version)
        except Exception:
            self._raise_invalid_browser_version_error(version)


class EdgeDriverManager(ChromiumBaseDriverManager):
    """Discover Microsoft Edge and provision its matching EdgeDriver."""

    # fmt: off
    _MAC_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        ChannelType.BETA: ["Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta"],
        ChannelType.DEV: ["Microsoft Edge Dev.app/Contents/MacOS/Microsoft Edge Dev"],
    }
    """The partial paths to the Edge binary on MacOS."""
    _WIN_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["Microsoft\\Edge\\Application\\msedge.exe"],
        ChannelType.BETA: ["Microsoft\\Edge Beta\\Application\\msedge.exe"],
        ChannelType.DEV: ["Microsoft\\Edge Dev\\Application\\msedge.exe"],
    }
    """The partial paths to the Edge binary on Windows."""
    _LINUX_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["microsoft-edge", "microsoft-edge-stable"],
        ChannelType.BETA: ["microsoft-edge-beta"],
        ChannelType.DEV: ["microsoft-edge-unstable", "microsoft-edge-dev"],
    }
    """The partial paths to the Edge binary on Linux."""
    _AZUREEDGE_ENDPOINT_URL: str = "https://msedgedriver.microsoft.com"
    """Microsoft endpoint used to resolve and download EdgeDriver releases."""
    # fmt: on

    def __init__(
        self,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        """Configure Edge discovery, provisioning, and cache retention.

        Args:
            directory: Cache parent directory; None uses the default per-user cache location.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit provisioning proxy URL, or None for a direct connection.
        """
        super().__init__(
            "Edge",
            EdgeFileManager,
            EdgeDriverFile,
            None,
            directory=directory,
            max_cache_size=max_cache_size,
            request_timeout=request_timeout,
            download_timeout=download_timeout,
            proxy=proxy,
        )
        # Installation
        self._azureedge_arch: str | None = None

    # Installation ------------------------------------------------------------------------
    async def install(
        self,
        version: ChromiumVersion | str = "build",
        channel: Literal["stable", "beta", "dev"] = "stable",
        binary: PathInput | None = None,
    ) -> Path:
        """Resolve and install an Edge WebDriver executable.

        Args:
            version: Driver version or compatibility selector.
            channel: Installed Edge release channel used for browser discovery.
            binary: Explicit Edge executable, or None for automatic discovery.

        Returns:
            Absolute path to the resolved Edge WebDriver executable.
        """
        return await self._install_chromium(version, channel, binary)

    # Driver version ----------------------------------------------------------------------
    async def _request_driver_version(
        self, driver_version: ChromiumVersion | None
    ) -> ChromiumVersion:
        """Resolve the EdgeDriver release for an installed Edge major version.

        Args:
            driver_version: Resolved browser-driver version.

        Returns:
            Full EdgeDriver version returned by Microsoft's platform endpoint.
        """
        if driver_version is None:
            self._raise_driver_request_failed_error(driver_version)

        # Construct check version url
        version = driver_version.major
        if self._os_name == OSType.WIN:
            url = self._AZUREEDGE_ENDPOINT_URL + "/LATEST_RELEASE_%s_WINDOWS" % version
        elif self._os_name == OSType.MAC:
            url = self._AZUREEDGE_ENDPOINT_URL + "/LATEST_RELEASE_%s_MACOS" % version
        else:
            url = self._AZUREEDGE_ENDPOINT_URL + "/LATEST_RELEASE_%s_LINUX" % version

        # Request driver version
        res = await self._request_response_text(url)

        # Parse driver version
        try:
            return self._parse_driver_version(res)
        except errors.InvalidDriverVersionError:
            self._raise_driver_request_failed_error(driver_version)

    # Driver executable -------------------------------------------------------------------
    @artifact_install("driver")
    async def _install_driver_executable(self, driver_version: ChromiumVersion) -> Path:
        """Download, validate, and publish one EdgeDriver archive.

        Args:
            driver_version: Resolved browser-driver version.

        Returns:
            Absolute path to the cached EdgeDriver executable.
        """
        # Generate download url
        driver_arch = self._generate_azureedge_arch()
        url = self._AZUREEDGE_ENDPOINT_URL + "/%s/edgedriver_%s.zip" % (
            driver_version,
            driver_arch,
        )

        # Download driver content
        res = await self._request_response_file(url)
        if res is None:
            self._raise_driver_download_failed_error(driver_version, url)

        # Cache driver executable
        return await run_blocking(self._cache_driver_executable, driver_version, res)

    def _generate_azureedge_arch(self) -> str:
        """Map the active platform to Microsoft's EdgeDriver archive label.

        For example: `'win64'`, `'mac64_m1'`, `'linux64'`.

        Returns:
            Vendor archive label such as ``win64``, ``mac64_m1``, or ``linux64``.
        """
        if self._azureedge_arch is None:
            if self._os_name == OSType.WIN:
                arch = "arm64" if self._os_is_arm else "win" + self._os_arch
            elif self._os_name == OSType.MAC:
                arch = "mac64_m1" if self._os_is_arm else "mac" + self._os_arch
            else:
                if self._os_is_arm or self._os_arch != "64":
                    raise errors.UnsupportedPlatformError(
                        "Microsoft Edge does not provide a native driver for this Linux architecture"
                    )
                arch = "linux" + self._os_arch
            self._azureedge_arch = arch
        return self._azureedge_arch


class ChromeDriverManager(ChromiumBaseDriverManager):
    """Discover Google Chrome or provision a matched Chrome-for-Testing pair."""

    # fmt: off
    _MAC_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["Google Chrome.app/Contents/MacOS/Google Chrome"],
        ChannelType.BETA: ["Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"],
        ChannelType.DEV: ["Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev"],
    }
    """The partial paths to the Chrome binary on MacOS."""
    _WIN_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["Google\\Chrome\\Application\\chrome.exe"],
        ChannelType.BETA: ["Google\\Chrome Beta\\Application\\chrome.exe"],
        ChannelType.DEV: ["Google\\Chrome Dev\\Application\\chrome.exe"],
    }
    """The partial paths to the Chrome binary on Windows."""
    _LINUX_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["google-chrome", "google-chrome-stable"],
        ChannelType.BETA: ["google-chrome-beta"],
        ChannelType.DEV: ["google-chrome-unstable", "google-chrome-dev"],
    }
    """The partial paths to the Chrome binary on Linux."""
    # fmt: on

    def __init__(
        self,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        """Configure Chrome discovery, CfT provisioning, and cache retention.

        Args:
            directory: Cache parent directory; None uses the default per-user cache location.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit provisioning proxy URL, or None for a direct connection.
        """
        super().__init__(
            "Chrome",
            ChromeFileManager,
            ChromeDriverFile,
            ChromeBinaryFile,
            directory=directory,
            max_cache_size=max_cache_size,
            request_timeout=request_timeout,
            download_timeout=download_timeout,
            proxy=proxy,
        )

    # Installation ------------------------------------------------------------------------
    @isolated_install
    async def install(
        self,
        version: ChromiumVersion | str = "build",
        channel: Literal["stable", "beta", "dev", "cft"] = "stable",
        binary: PathInput | None = None,
    ) -> Path:
        """Resolve and install a Chrome driver, optionally with Chrome for Testing.

        Each call owns isolated installation state. Prefer install_result when
        concurrent callers need an immutable record of their own resolved versions.
        Provisioning can contact vendor endpoints unless the policy is offline.

        Args:
            version: A ChromiumVersion, numeric version string, or installed-browser
                selector such as build, major, patch, or offline. A complete numeric
                version pins the artifact by default. CfT requires a numeric version.
            channel: Installed-browser channel stable, beta, or dev. Choose cft to
                provision both Chrome for Testing and its matching driver.
            binary: Installed Chrome executable used for version discovery, or None
                for automatic discovery. It must be None when channel is cft because
                that channel provisions its own matching browser executable.

        Returns:
            The validated driver executable path. With cft, browser_location also
            identifies the provisioned browser. Cache paths are implementation details.

        Raises:
            errors.InvalidArgumentError: ``binary`` is supplied with the cft channel.
            errors.DriverManagerError: Resolution, download, validation, or publication
                fails. More specific subclasses describe the failure category.

        Example:
            >>> from aselenium import ChromeDriverManager
            >>> manager = ChromeDriverManager()
            >>> result = await manager.install_result(
            ...     version="build",
            ...     policy="compatible-build",
            ...     validate_compatibility=True,
            ... )
            >>> print(result.driver_version, result.browser_version)
        """
        #### Driver installation
        if channel != "cft":
            return await self._install_chromium(version, channel, binary)

        #### Chrome for Testing installation
        try:
            if binary is not None:
                raise errors.InvalidArgumentError(
                    "binary cannot be supplied when channel='cft'"
                )
            # Parse arguments
            self._channel = channel
            self._parse_target_version(version)
            if self._target_version is None:
                raise errors.InvalidDriverVersionError(
                    "<{}>\nThe [cft] (Chrome for Testing) channel requires a "
                    "numeric version; received: {} {}.".format(
                        self.__class__.__name__, repr(version), type(version)
                    )
                )

            # Install Chrome for Testing
            async with self._installation_lock:
                policy = self._resolution_policy(version)
                if policy == "exact" and len(self._target_version) != 4:
                    raise errors.InvalidDriverVersionError(
                        "Exact Chromium versions require four numeric components"
                    )
                # . match from cache - 1st
                driver_location = (
                    None
                    if policy == "latest-compatible"
                    else await run_blocking(
                        self._match_cft_driver_and_binary,
                        self._target_version,
                        self._target_version,
                    )
                )
                if driver_location is not None:
                    return driver_location
                if policy == "offline":
                    self._offline_miss(self._target_version)

                # . request CFT versions
                driver_version, binary_version = await self._request_cft_versions(
                    self._target_version
                )

                # . match exact resolved pair from cache
                driver_location = await run_blocking(
                    self._match_cft_driver_and_binary, driver_version, binary_version
                )
                if driver_location is not None:
                    return driver_location

                # . install driver & browser
                driver_location, _ = await owned_gather(
                    self._install_driver_executable(driver_version),
                    self._install_browser_binary(binary_version),
                )
                return driver_location

        except BaseException:
            self.reset()
            raise

    # Chrome for Testing ------------------------------------------------------------------
    def _match_cft_driver_and_binary(
        self,
        driver_version: ChromiumVersion,
        binary_version: ChromiumVersion,
    ) -> Path | None:
        """Match a cached Chrome-for-Testing driver and browser pair.

        Args:
            driver_version: Resolved browser-driver version.
            binary_version: Required Chrome browser version for the cached pair.

        Returns:
            Cached driver path when both artifacts match, or None otherwise.
        """
        if len(driver_version) == 4:
            candidates = [driver_version]
        else:
            cache = self._cache_view
            if cache is None:
                self._raise_attribute_implementation_error("_file_manager")
            candidates = sorted(
                (
                    self._parse_driver_version(value)
                    for value in cache.cached_versions()
                ),
                reverse=True,
            )
            candidates = [
                value
                for value in candidates
                if value._versions_int[: len(driver_version)]
                == driver_version._versions_int[: len(driver_version)]
            ]
        for candidate in candidates:
            driver_location = self._match_driver_executable(candidate, "patch")
            if driver_location is None:
                continue
            wanted_browser = binary_version if len(binary_version) == 4 else candidate
            binary_location = self._match_browser_binary(wanted_browser, "patch")
            if binary_location is not None:
                return driver_location
        return None

    async def _request_cft_versions(
        self,
        cft_version: ChromiumVersion,
    ) -> tuple[ChromiumVersion, ChromiumVersion]:
        """Resolve an exact available Chrome-for-Testing driver/browser pair.

        Args:
            cft_version: Exact version or build prefix requested by the caller.

        Returns:
            Identical full versions for the matched Chrome and ChromeDriver assets.
        """
        self._validate_supported_version(cft_version)
        if (
            len(cft_version) == 4
            and self._resolution_policy(cft_version) != "latest-compatible"
        ):
            # Availability is checked by the exact per-version asset manifests
            # during download. Never substitute a latest patch for an exact pin.
            return cft_version, cft_version
        url = self._CHROMELABS_ENDPOINT_URL + "/LATEST_RELEASE_%s" % cft_version.build
        res = await self._request_response_text(url)
        try:
            version = self._parse_driver_version(res)
        except errors.InvalidDriverVersionError:
            self._raise_invalid_cft_version_error()
        if version.major != cft_version.major or (
            len(cft_version) >= 3 and version.build != cft_version.build
        ):
            self._raise_invalid_cft_version_error()
        return version, version

    @artifact_install("binary")
    async def _install_browser_binary(self, binary_version: ChromiumVersion) -> Path:
        """Download, validate, and publish one Chrome-for-Testing browser archive.

        Args:
            binary_version: Exact Chrome-for-Testing browser version to download.

        Returns:
            Absolute path to the cached Chrome executable.
        """
        # Generate browser architecture
        url = await self._cft_asset_url(binary_version, "chrome")

        # Request browser data
        res = await self._request_response_file(url)
        if res is None:
            self._raise_browser_download_failed_error(binary_version, url)

        # Cache browser binary
        return await run_blocking(self._cache_browser_binary, binary_version, res)

    # Exceptions --------------------------------------------------------------------------
    def _raise_invalid_cft_version_error(self) -> NoReturn:
        """Raise an invalid CFT version error.

        Raises:
            errors.InvalidDriverVersionError: Always raised with the supplied diagnostic context.
        """
        raise errors.InvalidDriverVersionError(
            "<{}>\n{} [{}] (Chrome for Testing) version '{}' ({}{}{}) "
            "is not available. Please try a different one.".format(
                self.__class__.__name__,
                self._name,
                self._channel,
                self._target_version,
                self._os_name,
                self._os_arch,
                "_arm" if self._os_is_arm else "",
            )
        )


class ChromiumDriverManager(ChromiumBaseDriverManager):
    """Discover a development-channel Chromium binary and provision ChromeDriver."""

    # fmt: off
    _MAC_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.DEV: ["Chromium.app/Contents/MacOS/Chromium"],
    }
    """The partial paths to the Chromium binary on MacOS."""
    _WIN_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.DEV: ["Chromium\\Application\\chrome.exe"],
    }
    """The partial paths to the Chromium binary on Windows."""
    _LINUX_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.DEV: ["chromium", "chromium-browser"],
    }
    """The partial paths to the Chromium binary on Linux."""
    # fmt: on

    def __init__(
        self,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        """Configure Chromium discovery, ChromeDriver provisioning, and cache retention.

        Args:
            directory: Cache parent directory; None uses the default per-user cache location.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit provisioning proxy URL, or None for a direct connection.
        """
        super().__init__(
            "Chromium",
            ChromeFileManager,
            ChromeDriverFile,
            None,
            directory=directory,
            max_cache_size=max_cache_size,
            request_timeout=request_timeout,
            download_timeout=download_timeout,
            proxy=proxy,
        )

    # Installation ------------------------------------------------------------------------
    async def install(
        self,
        version: ChromiumVersion | str = "build",
        binary: PathInput | None = None,
    ) -> Path:
        """Resolve ChromeDriver for an installed development-channel Chromium.

        Args:
            version: Numeric Chromium version or major, build, patch, latest, cached,
                or offline compatibility selector.
            binary: Explicit Chromium executable, or None for automatic discovery.

        Returns:
            Absolute path to the integrity-checked cached ChromeDriver executable.

        Example:
            >>> from aselenium import ChromiumDriverManager
            >>> mgr = ChromiumDriverManager()
            >>> driver_executable = await mgr.install("build")

            >>> mgr.driver_version

            >>> mgr.browser_location

            >>> mgr.browser_version
        """
        return await self._install_chromium(version, "dev", binary)


class FirefoxDriverManager(DriverManager[GeckoVersion, FirefoxVersion]):
    """Discover Firefox and resolve GeckoDriver through recorded compatibility bounds."""

    # fmt: off
    _MAC_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: [
            "Firefox.app/Contents/MacOS/firefox",
            "Firefox.app/Contents/MacOS/firefox-bin",
        ],
    }
    """The partial paths to the Firefox binary on MacOS."""
    _WIN_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["Mozilla Firefox\\firefox.exe"],
    }
    """The partial paths to the Firefox binary on Windows."""
    _LINUX_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["firefox", "iceweasel"],
    }
    """The partial paths to the Firefox binary on Linux."""
    _MOZILLA_GITHUB_URL: str = "https://github.com/mozilla/geckodriver/releases"
    """Mozilla GeckoDriver release endpoint used as the redirect fallback."""
    _MOZILLA_GITHUBAPI_URL: str = "https://api.github.com/repos/mozilla/geckodriver/releases"
    """GitHub API endpoint used to resolve GeckoDriver release tags."""
    _GECKODRIVER_MACARM_VERSION: GeckoVersion = GeckoVersion("0.29.1")
    """Version below this does not provide arm64 driver for MacOS."""
    _GECKODRIVER_WINARM_VERSION: GeckoVersion = GeckoVersion("0.32.0")
    """Version below this does not provide arm64 driver for Windows."""
    _GECKODRIVER_LINUXARM_ARCH_VERSION: GeckoVersion = GeckoVersion("0.32.0")
    """Version below this does not provide arm64 driver for Linux."""
    _GECKODRIVER_MAX_VERSION: GeckoVersion | None = None
    """Newest GeckoDriver observed in bundled data or a successful vendor response."""
    _GECKODRIVER_MIN_VERSION: GeckoVersion = GeckoVersion("0.30.0")
    """The minimum version of GeckoDriver supported by the manager."""
    _GECKODRIVER_TABLE: dict[GeckoVersion, dict[str, FirefoxVersion]] | None = None
    """Validated GeckoDriver-to-Firefox minimum and maximum version bounds."""
    _GECKODRIVER_TABLE_MAX_VERSION: GeckoVersion | None = None
    """The maximum version of GeckoDriver recorded in the compatibility table."""
    _FIREFOX_MIN_VERSION: FirefoxVersion = FirefoxVersion("78.0.0")
    """Firefox version below this is not supported by the manager."""
    # fmt: on

    def __init__(
        self,
        directory: PathInput | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        """Configure Firefox discovery, GeckoDriver resolution, and cache retention.

        Args:
            directory: Cache parent directory; None uses the default per-user cache location.
            max_cache_size: Maximum retained artifact count; None leaves retention unbounded.
            request_timeout: Positive timeout in seconds for vendor metadata requests.
            download_timeout: Positive total timeout in seconds for an artifact download.
            proxy: Explicit provisioning proxy URL, or None for a direct connection.
        """
        super().__init__(
            "Firefox",
            FirefoxFileManager,
            GeckoDriverFile,
            None,
            directory=directory,
            max_cache_size=max_cache_size,
            request_timeout=request_timeout,
            download_timeout=download_timeout,
            proxy=proxy,
        )
        # Driver compatibility
        self.load_driver_compatibility_table()
        # Type hinting
        self._file_manager: FirefoxFileManager
        self._target_version: GeckoVersion | None
        self._driver_version: GeckoVersion | None
        self._browser_version: FirefoxVersion | None

    # Class methods -----------------------------------------------------------------------
    @classmethod
    def load_driver_compatibility_table(cls) -> None:
        """Load and validate the bundled GeckoDriver compatibility resource once."""
        # Already loaded
        if cls._GECKODRIVER_TABLE is not None:
            return None  # exit

        resource_name = "geckodriver/compatibility.json"
        try:
            resource = (
                resources.files("aselenium.manager")
                .joinpath("geckodriver")
                .joinpath("compatibility.json")
            )
            data = loads(resource.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not data:
                raise ValueError("Compatibility data must be a non-empty object")

            # Validate into local state; failed reads must remain retryable.
            table = {}
            bound_keys = {"min_firefox_version", "max_firefox_version"}
            for key, bounds in data.items():
                if not isinstance(bounds, dict) or set(bounds) != bound_keys:
                    raise ValueError(
                        "Each driver must define minimum and maximum Firefox versions"
                    )
                if not all(isinstance(value, str) for value in bounds.values()):
                    raise ValueError("Firefox version bounds must be strings")
                version = GeckoVersion(key)
                parsed = {name: FirefoxVersion(value) for name, value in bounds.items()}
                if version.version != key or any(
                    parsed[name].version != value for name, value in bounds.items()
                ):
                    raise ValueError(
                        "Resource versions must be numeric version strings"
                    )
                if parsed["min_firefox_version"] > parsed["max_firefox_version"]:
                    raise ValueError("Minimum Firefox version exceeds maximum")
                if version in table:
                    raise ValueError("Duplicate normalized Gecko version")
                table[version] = parsed
            maximum = max(table)
        except (OSError, ValueError, TypeError, errors.InvalidVersionError) as err:
            raise errors.DriverManagerError(
                "<{}>\nCannot load bundled Firefox compatibility resource '{}': {}. "
                "Reinstall Aselenium from a complete distribution.".format(
                    cls.__name__, resource_name, err
                )
            ) from err

        cls._GECKODRIVER_TABLE_MAX_VERSION = maximum
        cls._GECKODRIVER_MAX_VERSION = maximum
        cls._GECKODRIVER_TABLE = table

    # Installation ------------------------------------------------------------------------
    @isolated_install
    async def install(
        self,
        version: GeckoVersion | str = "latest",
        binary: PathInput | None = None,
    ) -> Path:
        """Resolve and install a GeckoDriver compatible with the detected Firefox.

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
                - If specified, will use the given Firefox binary to determine the
                compatible webdriver version.

        Returns:
            Absolute path to the integrity-checked cached GeckoDriver executable.

        Example:
            >>> from aselenium import FirefoxDriverManager
            >>> mgr = FirefoxDriverManager()
            >>> driver_executable = await mgr.install("auto")

            >>> mgr.driver_version

            >>> mgr.browser_location

            >>> mgr.browser_version
        """
        try:
            # Parse arguments
            self._channel: str = "stable"
            self._browser_paths_for_channel()
            self._parse_target_version(version)
            self._parse_target_binary(binary)

            # Detect browser location
            browser_location = (
                self._detect_browser_location()
                if self._target_binary is None
                else self._target_binary
            )
            self._browser_location = browser_location

            # Detect browser version
            self._browser_version = await run_blocking(
                self._detect_browser_version, browser_location
            )

            # Install webdriver
            async with self._installation_lock:
                policy = self._resolution_policy(version)
                if self._target_version is not None:
                    if len(self._target_version) != 3:
                        raise errors.InvalidDriverVersionError(
                            "Exact Gecko versions require three numeric components"
                        )
                    driver_version = self._target_version
                    # An explicit version can prewarm a driver for a different Firefox
                    # binary when compatibility validation is explicitly disabled.
                    location = await run_blocking(
                        self._match_driver_executable, driver_version, "patch"
                    )
                    if location is not None:
                        return location
                else:
                    if policy == "exact":
                        raise errors.InvalidDriverVersionError(
                            "Exact Gecko policy requires an explicit version"
                        )
                    compatible = self._compatible_gecko_versions(self._browser_version)
                    if policy != "latest-compatible":
                        for candidate in compatible:
                            location = await run_blocking(
                                self._match_driver_executable, candidate, "patch"
                            )
                            if location is not None:
                                return location
                    driver_version = compatible[0]
                    if (
                        policy == "latest-compatible"
                        and driver_version == self._GECKODRIVER_TABLE_MAX_VERSION
                    ):
                        driver_version = await self._request_driver_version(None)
                        self._validate_gecko_pair(driver_version, self._browser_version)
                    location = (
                        None
                        if policy == "offline"
                        else await run_blocking(
                            self._match_driver_executable, driver_version, "patch"
                        )
                    )
                    if location is not None:
                        return location
                if policy == "offline":
                    self._offline_miss(self._target_version or self._browser_version)

                # . install driver executable
                return await self._install_driver_executable(driver_version)

        except BaseException:
            self.reset()
            raise

    # Target ------------------------------------------------------------------------------
    def _parse_target_version(self, version: Any) -> None:
        """Validate a GeckoDriver release or resolution selector.

        Args:
            version: Public GeckoDriver version or latest, auto, cached, or offline selector.
        """
        if version in ["latest", "auto", "cached", "offline", None]:
            self._target_version = None
        else:
            self._target_version = self._strict_target_version(
                version, self._parse_driver_version, 3
            )

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> GeckoVersion:
        """Return the GeckoDriver version published by the last installation.

        Returns:
            Parsed three-component GeckoDriver version.
        """
        return super().driver_version

    async def _request_driver_version(
        self, version: GeckoVersion | None
    ) -> GeckoVersion:
        """Resolve a GeckoDriver release tag through the GitHub API or redirect URL.

        Args:
            version: Exact GeckoDriver version, or None to request the latest release.

        Returns:
            Parsed GeckoDriver version returned by Mozilla's release metadata.
        """

        async def request_from_api(version: GeckoVersion | None) -> str | None:
            # Request from github api
            """Resolve the requested GeckoDriver version from the vendor API.

            Args:
                version: Exact GeckoDriver version, or None for the latest release.

            Returns:
                Release tag text, or None when both API and fallback resource are absent.
            """
            if version is None:
                url = self._MOZILLA_GITHUBAPI_URL + "/latest"
            else:
                url = self._MOZILLA_GITHUBAPI_URL + "/tags/v" + version.patch
            res = await self._request_response_json(url)
            if res is None:
                return await request_from_url(version)
            if (
                not isinstance(res, dict)
                or not isinstance(res.get("tag_name"), str)
                or not res["tag_name"]
            ):
                raise errors.DriverRequestFailedError(
                    "Gecko release metadata must contain a textual version tag"
                )
            return res["tag_name"]

        async def request_from_url(version: GeckoVersion | None) -> str | None:
            # Request from github url
            """Resolve the requested GeckoDriver version from the release URL.

            Args:
                version: Exact GeckoDriver version, or None for the latest redirect.

            Returns:
                The release URL's final path component, or None when the release
                resource is missing. The caller parses the component as a version.
            """
            if version is None:
                url = self._MOZILLA_GITHUB_URL + "/latest"
            else:
                url = self._MOZILLA_GITHUB_URL + "/tag/v" + version.patch
            return await self._request_response_url(url)

        # Request driver version response
        try:
            res = await request_from_api(version)
        except errors.DriverRequestRateLimitError:
            res = await request_from_url(version)

        # Parse driver version
        try:
            resolved = self._parse_driver_version(res)
        except errors.InvalidDriverVersionError:
            self._raise_driver_request_failed_error(version)

        # Update max version
        maximum = self._GECKODRIVER_MAX_VERSION
        if maximum is None or resolved > maximum:
            self._GECKODRIVER_MAX_VERSION = resolved

        # Return version
        return resolved

    @artifact_install("driver")
    async def _install_driver_executable(self, driver_version: GeckoVersion) -> Path:
        """Download, validate, and publish one GeckoDriver archive.

        Args:
            driver_version: Resolved browser-driver version.

        Returns:
            Absolute path to the cached GeckoDriver executable.
        """
        # Generate download url
        driver_arch = self._generate_mozilla_arch(driver_version)
        url = self._MOZILLA_GITHUB_URL + "/download/v%s/geckodriver-v%s-%s" % (
            driver_version,
            driver_version,
            driver_arch,
        )

        # Download driver content
        res = await self._request_response_file(url)
        if res is None:
            self._raise_driver_download_failed_error(driver_version, url)

        # Cache driver executable
        return await run_blocking(self._cache_driver_executable, driver_version, res)

    def _generate_mozilla_arch(self, driver_version: GeckoVersion) -> str:
        """Select Mozilla's GeckoDriver archive label for the active platform.

        For example: `'win64.zip'`, `'mac64-aarch64.tar.gz'`, `'linux64.tar.gz'`.

        Args:
            driver_version: Resolved browser-driver version.

        Returns:
            Version-aware archive label such as ``win64.zip`` or
            ``macos-aarch64.tar.gz``.
        """
        # Validate version
        if driver_version < self._GECKODRIVER_MIN_VERSION:
            self._raise_driver_unavailable_error(driver_version)

        # Generate arch
        if self._os_name == OSType.WIN:
            if self._os_is_arm:
                if driver_version < self._GECKODRIVER_WINARM_VERSION:
                    self._raise_driver_unavailable_error(driver_version)
                return "win-aarch64.zip"
            else:
                return "win" + self._os_arch + ".zip"
        elif self._os_name == OSType.MAC:
            if self._os_is_arm:
                if driver_version < self._GECKODRIVER_MACARM_VERSION:
                    self._raise_driver_unavailable_error(driver_version)
                return "macos-aarch64.tar.gz"
            else:
                return "macos.tar.gz"
        else:
            if self._os_is_arm:
                if self._os_arch != "64":
                    self._raise_driver_unavailable_error(driver_version)
                if driver_version < self._GECKODRIVER_LINUXARM_ARCH_VERSION:
                    self._raise_driver_unavailable_error(driver_version)
                return "linux-aarch64.tar.gz"
            else:
                return "linux" + self._os_arch + ".tar.gz"

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> FirefoxVersion:
        """Return the Firefox version published by the last installation.

        Returns:
            Parsed version of the discovered or explicitly selected Firefox binary.
        """
        return super().browser_version

    def _compatible_gecko_versions(
        self, browser_version: FirefoxVersion
    ) -> list[GeckoVersion]:
        """Return recorded compatible GeckoDriver versions in descending order.

        Args:
            browser_version: Detected or explicitly selected browser version.

        Returns:
            Recorded compatible geckodriver versions in descending order.
        """
        table = self._GECKODRIVER_TABLE
        if table is None:
            raise errors.DriverManagerError(
                "Firefox compatibility data has not been loaded"
            )
        candidates = sorted(
            (
                version
                for version, bounds in table.items()
                if version >= self._GECKODRIVER_MIN_VERSION
                and bounds["min_firefox_version"]
                <= browser_version
                <= bounds["max_firefox_version"]
            ),
            reverse=True,
        )
        if not candidates:
            self._raise_browser_unsupported_error(browser_version)
        return candidates

    def _validate_gecko_pair(
        self,
        driver_version: GeckoVersion | None,
        browser_version: FirefoxVersion | None,
    ) -> None:
        """Verify a GeckoDriver and Firefox pair against the recorded version ranges.

        Args:
            driver_version: Resolved browser-driver version.
            browser_version: Detected or explicitly selected browser version.
        """
        if driver_version is None or browser_version is None:
            raise errors.InvalidDriverVersionError(
                "Cannot validate an incomplete Gecko/Firefox version pair"
            )
        table = self._GECKODRIVER_TABLE
        if table is None:
            raise errors.DriverManagerError(
                "Firefox compatibility data has not been loaded"
            )
        bounds = table.get(driver_version)
        if bounds is None:
            raise errors.InvalidDriverVersionError(
                "No recorded Firefox compatibility bounds for Gecko %s; update compatibility data"
                % driver_version
            )
        if (
            not bounds["min_firefox_version"]
            <= browser_version
            <= bounds["max_firefox_version"]
        ):
            raise errors.InvalidDriverVersionError(
                "Gecko %s is incompatible with Firefox %s"
                % (driver_version, browser_version)
            )

    def _validate_version_pair(
        self,
        driver_version: GeckoVersion | None,
        browser_version: FirefoxVersion | None,
    ) -> None:
        """Validate a resolved GeckoDriver and Firefox version pair.

        Args:
            driver_version: Resolved GeckoDriver version, or None when unavailable.
            browser_version: Detected Firefox version, or None when unavailable.
        """
        self._validate_gecko_pair(driver_version, browser_version)

    # Version Utils -----------------------------------------------------------------------
    def _parse_driver_version(self, version: Any) -> GeckoVersion:
        """Parse GeckoDriver metadata into a comparable three-component version.

        Args:
            version: Vendor response text, cached version, or GeckoVersion instance.

        Returns:
            Parsed GeckoVersion preserving the available components.
        """
        try:
            return GeckoVersion(version)
        except Exception:
            self._raise_invalid_driver_version_error(version)

    def _parse_browser_version(self, version: Any) -> FirefoxVersion:
        """Parse Firefox probe output into a comparable browser version.

        Args:
            version: Browser probe text, result text, or FirefoxVersion instance.

        Returns:
            Parsed FirefoxVersion preserving the available components.
        """
        try:
            return FirefoxVersion(version)
        except Exception:
            self._raise_invalid_browser_version_error(version)

    # Exceptions --------------------------------------------------------------------------
    def _raise_driver_unavailable_error(self, version: Version) -> NoReturn:
        """Raise an unavailable driver error.

        Args:
            version: GeckoDriver version rejected by support or platform constraints.

        Raises:
            errors.InvalidDriverVersionError: Always raised with the supplied diagnostic context.
        """
        if version < self._GECKODRIVER_MIN_VERSION:
            raise errors.InvalidDriverVersionError(
                "<{}>\nGeckoDriver version below '{}' is not supported "
                "by the manager. Target version: '{}'".format(
                    self.__class__.__name__, self._GECKODRIVER_MIN_VERSION, version
                )
            )
        else:
            raise errors.InvalidDriverVersionError(
                "<{}>\nGeckoDriver version '{}' is not available for {} ({}{}{}).".format(
                    self.__class__.__name__,
                    version,
                    self._name,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                )
            )

    def _raise_browser_unsupported_error(self, version: Version) -> NoReturn:
        """Raise a failed to find compatible driver error.

        Args:
            version: Firefox version with no supported compatible GeckoDriver.

        Raises:
            errors.InvalidBrowserVersionError: Always raised with the supplied diagnostic context.
        """
        if version < self._FIREFOX_MIN_VERSION:
            raise errors.InvalidBrowserVersionError(
                "<{}>\n{} ({}{}{}) version '{}' is not supported by the manager. "
                "Please upgrade the browser to version >= '{}'.".format(
                    self.__class__.__name__,
                    self._name,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                    version,
                    self._FIREFOX_MIN_VERSION,
                )
            )
        else:
            raise errors.InvalidBrowserVersionError(
                "<{}>\nFailed to find compatible geckodriver for {} '{}' ({}{}{}).".format(
                    self.__class__.__name__,
                    self._name,
                    version,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                )
            )


class SafariDriverManager(DriverManager[SafariVersion, SafariVersion]):
    """Discover Safari and its operating-system-managed SafariDriver executable."""

    # fmt: off
    _MAC_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["Safari.app/Contents/MacOS/Safari"],
        ChannelType.DEV: ["Safari Technology Preview.app/Contents/MacOS/Safari Technology Preview"],
    }
    """Application-relative executables for Safari and Safari Technology Preview."""
    _MAC_DRIVER_DEFAULT_PATH: Path = Path("/usr/bin/safaridriver")
    """System SafariDriver path used for the stable browser channel."""
    _DRIVER_EXECUTABLE_NAME: str = "safaridriver"
    """Executable name searched inside a selected Safari application bundle."""
    # fmt: on

    def __init__(self) -> None:
        """Initialize Safari's system-managed driver resolver.

        Safari uses the operating system's browser and ``safaridriver`` binaries;
        it has no managed cache, vendor download, request timeout, or provisioning
        proxy configuration.
        """
        super().__init__("Safari", None, None, None)
        # Target
        self._target_driver: Path | None = None

    # Installation ------------------------------------------------------------------------
    @isolated_install
    async def install(
        self,
        channel: Literal["stable", "dev"] = "stable",
        driver: PathInput | None = None,
        binary: PathInput | None = None,
    ) -> Path:
        """Resolve the system Safari WebDriver executable.

        Args:
            channel: Defaults to `'stable'`. Accepts the following values:
                - `'stable'`: Locate the `STABLE` (normal) Safari binary in the system
                and use it to determine the webdriver executable.
                - `'dev'`:    Locate the `DEV` Safari [Technology Preview] binary in the
                system and use it to determine the webdriver executable.
            driver: The path to a specific webdriver executable. Defaults to `None`.
                If specified, will use this given webdriver executable instead of
                trying to locate the webdriver executable in the system.
            binary: The path to a specific Safari binary. Defaults to `None`.
                If specified, will use this given browser binary to determine
                the webdriver executable.

        Returns:
            Absolute path to the Safari WebDriver executable.

        Example:
            >>> from aselenium import SafariDriverManager
            >>> mgr = SafariDriverManager()
            >>> driver_executable = await mgr.install("dev")

            >>> mgr.driver_version

            >>> mgr.browser_location

            >>> mgr.browser_version
        """
        # Validate platform
        if self._os_name != OSType.MAC:
            raise errors.UnsupportedPlatformError(
                "<{}>\nSafari webdriver is only available on MacOS system. Please "
                "choose a different browser to continue automation for {} platform.".format(
                    self.__class__.__name__, self._os_name.title()
                )
            )

        try:
            # Parse arguments
            self._channel = channel
            self._browser_paths_for_channel()
            self._parse_target_driver(driver)
            self._parse_target_binary(binary)

            # Detect browser location
            browser_location = (
                self._detect_browser_location()
                if self._target_binary is None
                else self._target_binary
            )
            self._browser_location = browser_location

            # Detect browser version
            self._browser_version = await run_blocking(
                self._detect_browser_version, browser_location
            )

            # Detect driver location
            driver_location = (
                self._detect_driver_location(browser_location)
                if self._target_driver is None
                else self._target_driver
            )
            self._driver_location = driver_location
            self._driver_version = self._browser_version

            # Return driver location
            return self._driver_location

        except BaseException:
            self.reset()
            raise

    # Target ------------------------------------------------------------------------------
    def _parse_target_driver(self, driver: PathInput | None) -> None:
        """Validate and retain an explicit SafariDriver executable override.

        Args:
            driver: Existing SafariDriver path, or None to use bundle/system discovery.
        """
        if driver is None:
            self._target_driver = None
            return None  # exit
        try:
            location = self._normalize_file_location(driver)
        except Exception:
            self._raise_invalid_driver_location_error(driver)
        if location.name != self._DRIVER_EXECUTABLE_NAME:
            self._raise_invalid_driver_location_error(location)
        self._target_driver = location

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> SafariVersion:
        """Return the SafariDriver version published by the last installation.

        Returns:
            Safari browser version associated with the system-managed driver.
        """
        return super().driver_version

    def _detect_driver_location(self, browser_location: Path) -> Path:
        """Locate SafariDriver beside the app executable or at the system path.

        Args:
            browser_location: Validated Safari executable path.

        Returns:
            Absolute path to the detected Safari driver executable.
        """
        # Stable channel - default location
        default_driver = self._MAC_DRIVER_DEFAULT_PATH
        if (
            self._channel == ChannelType.STABLE
            and self._target_binary is None
            and default_driver.is_file()
        ):
            return default_driver

        # Application contents - default location
        base_folder = browser_location.parent
        location = base_folder / self._DRIVER_EXECUTABLE_NAME
        if location.is_file():
            return location

        # Application contents - search
        base_folder = base_folder.parent
        for location in base_folder.rglob(self._DRIVER_EXECUTABLE_NAME):
            if location.is_file():
                return location

        # Raise driver not found error
        if self._target_binary is not None and default_driver.is_file():
            return default_driver
        self._raise_invalid_driver_location_error(None)

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> SafariVersion:
        """Return the Safari version published by the last installation.

        Returns:
            Parsed version of Safari or Safari Technology Preview.
        """
        return super().browser_version

    def _detect_browser_version(self, browser_location: Path) -> SafariVersion:
        """Read Safari's bundle metadata and parse its short version string.

        Args:
            browser_location: Validated Safari executable path used for the probe.

        Returns:
            SafariVersion from ``version.plist`` or the bundle's ``Info.plist``.
        """
        try:
            # Application folder
            content_dir = browser_location.parent.parent
            # Load plist file
            try:
                plist = _load_plist_file(content_dir / "version.plist")
            except FileNotFoundError:
                plist = _load_plist_file(content_dir / "Info.plist")
            # Return version
            return SafariVersion(plist["CFBundleShortVersionString"])

        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            ExpatError,
            errors.AseleniumError,
        ) as err:
            self._raise_invalid_browser_location_error(browser_location, cause=err)

    def _parse_browser_version(self, version: Any) -> SafariVersion:
        """Reconstruct the Safari browser version from an installation result.

        Args:
            version: Numeric version text or an existing SafariVersion instance.

        Returns:
            A SafariVersion suitable for the acquisition-time options snapshot.

        Raises:
            errors.InvalidBrowserVersionError: The value cannot represent a Safari version.
        """
        try:
            return SafariVersion(version)
        except errors.InvalidVersionError:
            self._raise_invalid_browser_version_error(version)

    def _parse_driver_version(self, version: Any) -> SafariVersion:
        """Reconstruct the system driver's Safari version for service startup.

        Args:
            version: Numeric version text or an existing SafariVersion instance.

        Returns:
            A SafariVersion identifying the bundled system driver.

        Raises:
            errors.InvalidDriverVersionError: The value cannot represent a Safari version.
        """
        try:
            return SafariVersion(version)
        except errors.InvalidVersionError:
            self._raise_invalid_driver_version_error(version)
