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
from __future__ import annotations
from typing import Any, Literal
from asyncio import Lock, gather
from os.path import join as join_path, dirname
from os import walk as walk_path, pathsep, environ
from platform import system, architecture, machine
from subprocess import Popen, PIPE, DEVNULL
from aiohttp import ClientSession, ClientTimeout, ClientConnectorError
from aselenium import errors
from aselenium.manager.version import Version, ChromiumVersion
from aselenium.manager.version import GeckoVersion, FirefoxVersion, SafariVersion
from aselenium.manager.file import EdgeFileManager, EdgeDriverFile
from aselenium.manager.file import FirefoxFileManager, GeckoDriverFile
from aselenium.manager.file import FileManager, ChromiumBaseFileManager, File
from aselenium.manager.file import ChromeFileManager, ChromeDriverFile, ChromeBinaryFile
from aselenium.utils import validate_file, is_path_file, load_json_file, load_plist_file

__all__ = [
    "EdgeDriverManager",
    "ChromeDriverManager",
    "ChromiumDriverManager",
    "FirefoxDriverManager",
    "SafariDriverManager",
]


# Constants ----------------------------------------------------------------------------------------
class OSType:
    LINUX = "linux"
    MAC = "mac"
    WIN = "win"


class BrowserType:
    EDGE = "edge"
    CHROME = "chrome"
    CHROMIUM = "chromium"
    FIREFOX = "firefox"


class ChannelType:
    STABLE = "stable"
    BETA = "beta"
    DEV = "dev"


# Driver Manager -----------------------------------------------------------------------------------
class DriverManager:
    """Represents the webdriver manager for a browser."""

    _installation_lock: Lock = Lock()
    """The lock to prevent multiple installation at the same time."""
    _MAC_BINARY_PATHS: dict[str, list[str]] = None
    """The partial paths to the browser binary on MacOS."""
    _WIN_BINARY_PATHS: dict[str, list[str]] = None
    """The partial paths to the browser binary on Windows."""
    _LINUX_BINARY_PATHS: dict[str, list[str]] = None
    """The partial paths to the browser binary on Linux."""

    def __init__(
        self,
        name: str,
        file_manager_cls: type[FileManager] | None,
        driver_file_cls: type[File] | None,
        binary_file_cls: type[File] | None,
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        """The webdriver manager.

        :param directory: `<str/None>` The directory to cache the webdrivers. Defaults to `None`.
            - If `None`, the webdrivers will be automatically cache in the following default directory:
              1. MacOS default: `'/Users/<user>/.aselenium'`.
              2. Windows default: `'C:\\Users\\<user>\\.aselenium'`.
              3. Linux default: `'/home/<user>/.aselenium'`.
            - If specified, a folder named `'.aselenium'` will be created in the given directory.

        :param max_cache_size: `<int/None>` The maximum cache size of the webdrivers. Defaults to `None`.
            - If `None`, all webdrivers will be cached to local storage without limit.
            - For value > 1, if the cached webdrivers exceed this limit, the oldest
              webdrivers will be deleted.

        :param request_timeout: `<int/float>` The timeout in seconds for api requests. Defaults to `10`.
        :param download_timeout: `<int/float>` The timeout in seconds for file download. Defaults to `300`.
        :param proxy: `<str/None>` The proxy for http requests. Defaults to `None`.
            This might be needed for some users that cannot access the webdriver api directly
            due to internet restrictions. Only accepts proxy startswith `'http://'`.
        """
        # Basic
        self._name: str = name
        # Installation
        self._channel: str = None
        # File manager
        self.max_cache_size = max_cache_size
        if file_manager_cls is not None:
            self._file_manager: FileManager = file_manager_cls(directory)
        else:
            self._file_manager: FileManager = None
        self._driver_file_cls: type[File] = driver_file_cls
        self._binary_file_cls: type[File] = binary_file_cls
        # Request
        self.requests_timeout = request_timeout
        self.download_timeout = download_timeout
        self.proxy = proxy
        # Target
        self._target_version: Version | None = None
        self._target_binary: str | None = None
        # Driver
        self._driver_version: Version = None
        self._driver_location: str = None
        # Browser
        self._browser_version: Version = None
        self._browser_location: str = None
        # Platform
        self.__os_name: str = None
        self.__os_arch: str = None
        self.__os_is_arm: bool = None
        self.__environ_paths: list[str] = None

    # Installation ------------------------------------------------------------------------
    async def install(self, *args: Any, **kwargs: Any) -> str:
        """Install a webdriver `<str>`."""
        raise NotImplementedError(
            "<DriverManager> `install()` method must be implemented in "
            "subclass: <{}>.".format(self.__class__.__name__)
        )

    def reset(self) -> None:
        """Reset a previously successfull webdriver installation."""
        self._channel = None
        self._driver_version = None
        self._driver_location = None
        self._browser_version = None
        self._browser_location = None

    # File manager ------------------------------------------------------------------------
    @property
    def max_cache_size(self) -> int | None:
        """Access the maximum webdriver cache size `<int/None>`."""
        return self._max_cache_size

    @max_cache_size.setter
    def max_cache_size(self, value: int | None) -> None:
        # Unlimit cache size
        if value is None:
            self._max_cache_size: int | None = None
            return None  # exit

        # Set cache size
        try:
            value = int(value)
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid webdriver max cache size: {} {}.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            ) from err
        if value < 1:
            raise errors.InvalidArgumentError(
                "<{}>\nWebdriver max cache size must be >= 1, "
                "instead got: {}.".format(self.__class__.__name__, value)
            )
        self._max_cache_size: int | None = value

    # Request -----------------------------------------------------------------------------
    @property
    def requests_timeout(self) -> int | float:
        """Access the timeout in seconds for api requests.
        Defaults to `10` seconds `<int/float>`.
        """
        return self._requests_timeout.total

    @requests_timeout.setter
    def requests_timeout(self, value: int | float) -> None:
        if not isinstance(value, (int, float)):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid requests timeout: {} {}. Must be an integer "
                "or float.".format(self.__class__.__name__, repr(value), type(value))
            )
        if value < 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid requests timeout: {}. Must be greater "
                "than 0.".format(self.__class__.__name__, repr(value))
            )
        self._requests_timeout: ClientTimeout = ClientTimeout(value)

    @property
    def download_timeout(self) -> int | float:
        """Access the timeout in seconds for file download.
        Defaults to `300` seconds `<int/float>`.
        """
        return self._download_timeout.total

    @download_timeout.setter
    def download_timeout(self, value: int | float) -> None:
        if not isinstance(value, (int, float)):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid download timeout: {} {}. Must be an integer "
                "or float.".format(self.__class__.__name__, repr(value), type(value))
            )
        if value < 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid download timeout: {}. Must be greater "
                "than 0.".format(self.__class__.__name__, repr(value))
            )
        self._download_timeout: ClientTimeout = ClientTimeout(value)

    @property
    def proxy(self) -> str | None:
        """Access the proxy for http requests `<str/None>`."""
        return self._proxy

    @proxy.setter
    def proxy(self, value: str | None) -> None:
        # Remove proxy
        if value is None:
            self._proxy: str | None = None
            return None  # exit
        # Set proxy
        if not isinstance(value, str) or not value.startswith("http://"):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid proxy: {} {}. Must be a string startswith "
                "'http://'".format(self.__class__.__name__, repr(value), type(value))
            )
        self._proxy: str | None = value

    async def _request_response_text(self, url: str) -> str | None:
        """(Internal) Returns the text of the response from a request `<str>`.
        Returns `None` is request failed.
        """
        try:
            async with ClientSession() as session:
                async with session.get(
                    url,
                    timeout=self._requests_timeout,
                    proxy=self._proxy,
                ) as res:
                    code = res.status
                    # . success
                    if code == 200:
                        try:
                            return await res.text(encoding="utf-8")
                        except UnicodeDecodeError:
                            return await res.text(encoding="utf-16")
                    # . rate limit
                    elif code == 403 or code == 401:
                        raise errors.DriverRequestRateLimitError(
                            "<{}>\nRequest rate limit reached for: "
                            "'{}'.".format(self.__class__.__name__, url)
                        )
                    # . failed
                    else:
                        return None
        except errors.DriverRequestFailedError:
            raise
        except TimeoutError as err:
            raise errors.DriverRequestTimeoutError(
                "<{}>\nTimeout when requesting text from: '{}'. Try to increase "
                "the `request_timeout` settings: {}s.".format(
                    self.__class__.__name__, url, self.requests_timeout
                )
            )
        except ClientConnectorError as err:
            if "Cannot connect to host" in str(err):
                raise errors.DriverRequestFailedError(
                    "<{}>\nFailed to connect: '{}'. If your internet cannot "
                    "access the url directly, try specifying a proxy for "
                    "the DriverManager.".format(self.__class__.__name__, url)
                )
            return None
        except Exception:
            return None

    async def _request_reponse_json(self, url: str) -> dict | None:
        """(Internal) Returns the json of the response from a request `<dict>`.
        Returns `None` is request failed.
        """
        try:
            async with ClientSession() as session:
                async with session.get(
                    url,
                    timeout=self._requests_timeout,
                    proxy=self._proxy,
                ) as res:
                    code = res.status
                    # . success
                    if code == 200:
                        try:
                            return await res.json(encoding="utf-8")
                        except UnicodeDecodeError:
                            return await res.json(encoding="utf-16")
                    # . rate limit
                    elif code == 403 or code == 401:
                        raise errors.DriverRequestRateLimitError(
                            "<{}>\nRequest rate limit reached for: "
                            "'{}'.".format(self.__class__.__name__, url)
                        )
                    # . failed
                    else:
                        return None
        except errors.DriverRequestFailedError:
            raise
        except TimeoutError as err:
            raise errors.DriverRequestTimeoutError(
                "<{}>\nTimeout when requesting json from: '{}'. Try to increase "
                "the `request_timeout` settings: {}s.".format(
                    self.__class__.__name__, url, self.requests_timeout
                )
            )
        except ClientConnectorError as err:
            if "Cannot connect to host" in str(err):
                raise errors.DriverRequestFailedError(
                    "<{}>\nFailed to connect: '{}'. If your internet cannot "
                    "access the url directly, try specifying a proxy for "
                    "the DriverManager.".format(self.__class__.__name__, url)
                )
            return None
        except Exception as err:
            return None

    async def _request_response_url(self, url: str) -> str | None:
        """(Internal) Returns the url of the response from a request `<str>`.
        Returns `None` is request failed.
        """
        try:
            async with ClientSession() as session:
                async with session.get(
                    url,
                    timeout=self._requests_timeout,
                    proxy=self._proxy,
                ) as res:
                    code = res.status
                    # . success
                    if code == 200:
                        return res.url.name
                    # . rate limit
                    elif code == 403 or code == 401:
                        raise errors.DriverRequestRateLimitError(
                            "<{}>\nRequest rate limit reached for: "
                            "'{}'.".format(self.__class__.__name__, url)
                        )
                    # . failed
                    else:
                        return None
        except errors.DriverRequestFailedError:
            raise
        except TimeoutError as err:
            raise errors.DriverRequestTimeoutError(
                "<{}>\nTimeout when requesting url from: '{}'. Try to increase "
                "the `request_timeout` settings: {}s.".format(
                    self.__class__.__name__, url, self.requests_timeout
                )
            )
        except ClientConnectorError as err:
            if "Cannot connect to host" in str(err):
                raise errors.DriverRequestFailedError(
                    "<{}>\nFailed to connect: '{}'. If your internet cannot "
                    "access the url directly, try specifying a proxy for "
                    "the DriverManager.".format(self.__class__.__name__, url)
                )
            return None
        except Exception as err:
            return None

    async def _request_response_file(self, url: str) -> dict | None:
        """(Internal) Returns the file of the response from a request `<dict>`.
        Returns `None` is request failed.
        """
        try:
            async with ClientSession() as session:
                async with session.get(
                    url,
                    timeout=self._download_timeout,
                    proxy=self._proxy,
                ) as res:
                    code = res.status
                    # . success
                    if code == 200:
                        return {"url": url, "content": await res.content.read()}
                    # . rate limit
                    elif code == 403 or code == 401:
                        raise errors.DriverRequestRateLimitError(
                            "<{}>\nRequest rate limit reached for: "
                            "'{}'.".format(self.__class__.__name__, url)
                        )
                    # . failed
                    else:
                        return None
        except errors.DriverRequestFailedError:
            raise
        except TimeoutError as err:
            raise errors.FileDownloadTimeoutError(
                "<{}>\nTimeout when downloading file from: '{}'. Try to increase "
                "the `download_timeout` settings: {}s.".format(
                    self.__class__.__name__, url, self.download_timeout
                )
            )
        except ClientConnectorError as err:
            if "Cannot connect to host" in str(err):
                raise errors.DriverRequestFailedError(
                    "<{}>\nFailed to connect: '{}'. If your internet cannot "
                    "access the url directly, try specifying a proxy for "
                    "the DriverManager.".format(self.__class__.__name__, url)
                )
            return None
        except Exception as err:
            return None

    # Target ------------------------------------------------------------------------------
    @property
    def channel(self) -> str:
        """Access the webdriver channel `<str>`.
        Please access this attribute after executing the `install()` method.
        """
        if self._channel is None:
            self._raise_installation_error("channel")
        return self._channel

    def _parse_target_version(self, version: Any) -> None:
        """(Internal) Parse the target version for the installation."""
        raise NotImplementedError(
            "<DriverManager> `_parse_target_version()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _parse_target_binary(self, binary: Any) -> None:
        """(Internal) Parse the target browser binary for the installation."""
        if binary is None:
            self._target_binary = None
            return None  # exit
        try:
            self._target_binary = validate_file(binary)
        except Exception:
            self._raise_invalid_browser_location_error(binary)

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> Version:
        """Access the version of the installed webdriver `<Version>`.
        Please access this attribute after executing the `install()` method.
        """
        if self._driver_version is None:
            self._raise_installation_error("driver_version")
        return self._driver_version

    def _match_driver_executable(
        self,
        version: Version,
        match_method: str,
    ) -> str | None:
        """(Internal) Match the webdriver executable from cache. Returns
        the driver location `<str>` if matched, otherwise returns `None`.
        """
        # Match driver from cache
        driver = self._file_manager.match_driver(version, match_method=match_method)
        if driver is None:
            return None

        # Set version & location
        self._driver_version = driver["version"]
        self._driver_location = driver["location"]

        # Return driver location
        return self._driver_location

    async def _request_driver_version(self, driver_version: Version) -> Version:
        """(Internal) Request the available webdriver version `<Version>`."""
        raise NotImplementedError(
            "<DriverManager> `_request_driver_version()` must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    @property
    def driver_location(self) -> str:
        """Access the path to the installed webdriver executable `<str>`.
        Please access this attribute after executing the `install()` method.
        """
        if self._driver_location is None:
            self._raise_installation_error("executable")
        return self._driver_location

    async def _install_driver_executable(self, driver_version: Version) -> str:
        """(Internal) Install & cache the webdriver executable.
        Returns the installed webdriver executable location `<str>`.
        """
        raise NotImplementedError(
            "<DriverManager> `_install_driver_executable()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _cache_driver_executable(self, version: Version, res: dict) -> str:
        """(Internal) Cache the downloaded webdriver executable, and
        returns the installed driver location `<str>`.
        """
        try:
            driver = self._file_manager.cache_driver(
                version,
                self._driver_file_cls(self._os_name, **res),
                max_cache_size=self._max_cache_size,
            )
            self._driver_version = driver["version"]
            self._driver_location = driver["location"]
            return self._driver_location

        finally:
            del res

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> Version:
        """Access the version of the browser that pairs with the installed driver `<Version>`.
        Please access this attribute after executing the `install()` method.
        """
        if self._browser_version is None:
            self._raise_installation_error("browser_version")
        return self._browser_version

    def _detect_browser_version(self, browser_location: str) -> Version:
        """(Internal) Detect the the version of the browser `<Version>`."""
        # Windows - Command
        if self._os_name == OSType.WIN:
            cmd = '%s -NoProfile "(Get-Item -Path %s).VersionInfo.FileVersion"' % (
                self._runs_powershell(),
                "'" + browser_location.replace("\\", "\\\\") + "'",
            )
        # MacOS & Linux - Command
        else:
            cmd = browser_location.replace(" ", "\ ") + " --version"

        # Read command version
        res = self._read_from_cmd(cmd)

        # Parse browser version
        try:
            return self._parse_browser_version(res)
        except errors.InvalidDriverVersionError:
            self._raise_invalid_browser_location_error(browser_location)

    @property
    def browser_location(self) -> str:
        """Access the loction of the browser binary that pairs with the
        installed driver `<str>`. Please access this attribute after
        executing the `install()` method.
        """
        if self._browser_location is None:
            self._raise_installation_error("browser_location")
        return self._browser_location

    def _match_browser_binary(
        self,
        version: Version,
        match_method: str,
    ) -> str | None:
        """(Internal) Match the browser binary from cache. Returns the
        binary location `<str>` if matched, otherwise returns `None`.
        """
        # Match driver from cache
        binary = self._file_manager.match_binary(version, match_method=match_method)
        if binary is None:
            return None

        # Set version & location
        self._browser_version = binary["version"]
        self._browser_location = binary["location"]

        # Return driver location
        return self._browser_location

    def _detect_browser_location(self) -> str:
        """(Internal) Automatically detect the location of browser
        binary on the system `<str>`.
        """
        # MacOS
        if self._os_name == OSType.MAC:
            try:
                paths = self._MAC_BINARY_PATHS[self._channel]
            except KeyError:
                self._raise_invalid_channel_error()
            except AttributeError:
                self._raise_attribute_implementation_error(
                    "_MAC_BINARY_PATHS",
                )
            location = self._find_mac_browser_location(*paths)

        # Windows
        elif self._os_name == OSType.WIN:
            try:
                paths = self._WIN_BINARY_PATHS[self._channel]
            except KeyError:
                self._raise_invalid_channel_error()
            except AttributeError:
                self._raise_attribute_implementation_error(
                    "_WIN_BINARY_PATHS",
                )
            location = self._find_win_browser_location(*paths)

        # Linux
        else:
            try:
                paths = self._LINUX_BINARY_PATHS[self._channel]
            except KeyError:
                self._raise_invalid_channel_error()
            except AttributeError:
                self._raise_attribute_implementation_error(
                    "_LINUX_BINARY_PATHS",
                )
            location = self._find_linux_browser_location(*paths)

        # Validate location
        if location is None:
            self._raise_invalid_browser_location_error(location)
        return location

    def _find_mac_browser_location(self, *paths: str) -> str | None:
        """(Internal) Find the path to the browser binary on MacOS `<str/None>`."""
        for path in paths:
            # Check default location
            location = join_path("/Applications", path)
            if is_path_file(location):
                return location
            # Check environ locations
            for env_path in self._environ_paths:
                location = join_path(env_path, path)
                if is_path_file(location):
                    return location
        return None

    def _find_win_browser_location(self, *paths: str) -> str | None:
        """(Internal) Find the path to the browser binary on Windows `<str/None>`."""
        for path in paths:
            for env_path in self._environ_paths:
                location = join_path(env_path, path)
                if is_path_file(location):
                    return location
        return None

    def _find_linux_browser_location(self, *paths: str) -> str | None:
        """(Internal) Find the path to the browser binary on Linux `<str/None>`."""
        for path in paths:
            # Check default location
            location = self._read_from_cmd("which " + path)
            if is_path_file(location):
                return location
            # Check environ locations
            for pe in self._environ_paths:
                location = join_path(pe, path)
                if is_path_file(location):
                    return location
        return None

    async def _install_browser_binary(self, browser_version: Version) -> str:
        """(Internal) Install & cache the browser binary and
        returns the installed browser binary location `<str>`.
        """
        raise NotImplementedError(
            "<DriverManager> `_install_browser_binary()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _cache_browser_binary(self, version: Version, res: dict) -> str:
        """(Internal) Cache the downloaded browser binary, and
        returns the installed binary location `<str>`.
        """
        try:
            binary = self._file_manager.cache_binary(
                version,
                self._binary_file_cls(self._os_name, **res),
                max_cache_size=self._max_cache_size,
            )
            self._browser_version = binary["version"]
            self._browser_location = binary["location"]
            return self._browser_location

        finally:
            del res

    # Platform Utils ----------------------------------------------------------------------
    @property
    def _os_name(self) -> Literal["linux", "mac", "win"]:
        """(Internal) Access the name of the operating system `<str>`.

        Excepted values: `'linux'`, `'mac'`, `'win'`.
        """
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
                    "<{}>\nUnsupported platform (Operating System): "
                    "'{}'".format(self.__class__.__name__, syst)
                )
        return self.__os_name

    @property
    def _os_arch(self) -> Literal["32", "64"]:
        """(Internal) Access the architecture bit of the platform `<str>`.

        Excepted values: `'32'`, `'64'`.
        """
        if self.__os_arch is None:
            if "64" in architecture()[0]:
                self.__os_arch = "64"
            else:
                self.__os_arch = "32"
        return self.__os_arch

    @property
    def _os_is_arm(self) -> bool:
        """(Internal) Access whether the platform is arm based `<bool>`."""
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
    def _environ_paths(self) -> list[str]:
        """(Internal) Access system environmental paths to find
        browser binary `<list[str]>`.
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
            else:
                paths = environ["PATH"].split(pathsep)
            self.__environ_paths = paths
        return self.__environ_paths

    # Command Utils -----------------------------------------------------------------------
    def _read_from_cmd(self, cmd: str) -> str:
        """(Internal) Read the response from a terminal command `<str>`."""
        # fmt: off
        with Popen(cmd, stdout=PIPE, stdin=DEVNULL, stderr=DEVNULL, shell=True) as stream:
            return stream.communicate()[0].decode()
        # fmt: on

    def _runs_powershell(self) -> str:
        """(Internal) Determine if windows command should run in Powershell `<str>`."""
        res = self._read_from_cmd("(dir 2>&1 *`|echo CMD);&<# rem #>echo powershell")
        return "" if res == "powershell" else "powershell"

    # Version Utils -----------------------------------------------------------------------
    def _parse_driver_version(self, version: Any) -> Version:
        """(Internal) Parse the driver version `<Version>`"""
        raise NotImplementedError(
            "<DriverManager> `_parse_driver_version()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _parse_browser_version(self, version: Any) -> Version:
        """(Internal) Parse the browser version `<Version>`"""
        raise NotImplementedError(
            "<DriverManager> `_parse_browser_version()` method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    # Exceptions --------------------------------------------------------------------------
    def _raise_installation_error(self, attr_name: str) -> str:
        """(Internal) Raise an installation error."""
        raise errors.DriverInstallationError(
            "<{}>\nCan't access '{}' attribute before executing "
            "the `install()` method.".format(self.__class__.__name__, attr_name)
        )

    def _raise_attribute_implementation_error(self, attr_name: str) -> None:
        """(Internal) Raise an attribute not implemented error."""
        raise NotImplementedError(
            "<DriverManager>\nCritial class attribute '{}' not implemented in "
            "subclass: <{}>.".format(attr_name, self.__class__.__name__)
        )

    def _raise_invalid_channel_error(self) -> None:
        """(Internal) Raise an invalid channel error."""
        raise errors.DriverManagerError(
            "<{}>\nInvalid {} webdriver channel: {}.".format(
                self.__class__.__name__, self._name, repr(self._channel)
            )
        )

    def _raise_invalid_driver_version_error(self, version: Any) -> None:
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

    def _raise_invalid_driver_location_error(self, path: Any) -> None:
        """(Internal) Raise an invalid webdriver location error."""
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

    def _raise_driver_request_failed_error(self, version: Version) -> None:
        """(Internal) Raise a driver version request failed error."""
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

    def _raise_driver_download_failed_error(self, version: Version, url: str) -> None:
        """(Internal) Raise a driver download failed error."""
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

    def _raise_invalid_browser_version_error(self, version: Any) -> None:
        raise errors.InvalidDriverVersionError(
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

    def _raise_invalid_browser_location_error(self, path: Any) -> None:
        """(Internal) Raise an invalid binary location error."""
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
            )
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
            )

    def _raise_browser_download_failed_error(self, version: Version, url: str) -> None:
        """(Internal) Raise a browser download failed error."""
        raise errors.BrowserDownloadFailedError(
            "<{}>\nFailed to download browser {} "
            "'{}' ({}{}{}) from url: '{}'.".format(
                self.__class__.__name__,
                self._name,
                version,
                self._os_name,
                self._os_arch,
                "_arm" if self._os_is_arm else "",
                url,
            )
        )


class ChromiumBaseDriverManager(DriverManager):
    """Represents the webdriver manager for the Chromium based browser."""

    # fmt: off
    _CHROMELABS_ENDPOINT_URL: str = "https://googlechromelabs.github.io/chrome-for-testing"
    """The chromelab url to request the Chrome webdriver."""
    _CHROMELABS_DRIVER_URL: str = "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing"
    """The chromelab url to download the Chrome webdriver."""
    _CHROMELABS_DRIVER_VERSION: ChromiumVersion = ChromiumVersion("115")
    """Version above this uses the chromelabs to request driver."""
    _CHROMELABS_CFT_VERSION: ChromiumVersion = ChromiumVersion("113.0.5672.0")
    """Version below this does not support CFT browser."""
    _GOOGLEAPIS_ENDPOINT_URL: str = "https://chromedriver.storage.googleapis.com"
    """The googleapis url to request the Chrome webdriver."""
    _GOOGLEAPIS_MACARM64_VERIONS: ChromiumVersion = ChromiumVersion("106.0.5249.61")
    """Version below this on MacOS use 'm1' arch instead of 'arm64'."""

    # fmt: on

    def __init__(
        self,
        name: str,
        file_manager_cls: type[FileManager],
        driver_file_cls: type[File] | None,
        binary_file_cls: type[File] | None,
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
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
        self._chromelabs_arch: str = None
        # Type hinting
        self._file_manager: ChromiumBaseFileManager
        self._target_version: ChromiumVersion
        self._driver_version: ChromiumVersion
        self._browser_version: ChromiumVersion

    # Installation ------------------------------------------------------------------------
    async def install(
        self,
        version: ChromiumVersion | Literal["major", "build", "patch"] = "build",
        channel: Literal["stable", "beta", "dev"] = "stable",
        binary: str | None = None,
    ) -> str:
        """Install a webdriver.

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
            the webdriver version.

        :return: `<str>` The path to the installed webdriver executable.

        ### Example:
        >>> from aselenium import EdgeDriverManager
            mgr = EdgeDriverManager()
            driver_executable = await mgr.install("build", "beta")
            # /Users/<user>/.aselenium/msedgedriver_119.0.2151.97/extracted/msedgedriver
            mgr.driver_version
            # 119.0.2151.97
            mgr.browser_location
            # /Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta
            mgr.browser_version
            # 119.0.2151.97
        """
        try:
            # Parse arguments
            self._channel = channel
            self._parse_target_version(version)
            self._parse_target_binary(binary)

            # Detect browser location
            if self._target_binary is None:
                self._browser_location = self._detect_browser_location()
            else:
                self._browser_location = self._target_binary

            # Detect browser version
            self._browser_version = self._detect_browser_version(self._browser_location)

            # Install webdriver
            async with self._installation_lock:
                # . match from cache - 1st
                if self._target_version is None:
                    driver_location = self._match_driver_executable(
                        self._browser_version, version or "build"
                    )
                else:
                    driver_location = self._match_driver_executable(
                        self._target_version, "patch"
                    )
                if driver_location is not None:
                    return driver_location

                # . request driver version
                driver_version = await self._request_driver_version(
                    self._target_version or self._browser_version
                )

                # . match from cache - 2rd
                driver_location = self._match_driver_executable(driver_version, "patch")
                if driver_location is not None:
                    return driver_location

                # . install driver executable
                return await self._install_driver_executable(driver_version)

        except BaseException:
            self.reset()
            raise

    # Target ------------------------------------------------------------------------------
    def _parse_target_version(self, version: Any) -> None:
        """(Internal) Parse the target version for the installation."""
        if version in ["major", "build", "patch", None]:
            self._target_version = None
        else:
            self._target_version = self._parse_driver_version(version)

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> ChromiumVersion:
        """Access the version of the installed webdriver `<ChromiumVersion>`.
        Please access this attribute after executing the `install()` method.
        """
        return super().driver_version

    async def _request_driver_version(self, driver_version: Version) -> ChromiumVersion:
        """(Internal) Request the available webdriver version `<ChromiumVersion>`."""
        # Construct check version url
        version = driver_version.build
        if driver_version > self._CHROMELABS_DRIVER_VERSION:
            url = self._CHROMELABS_ENDPOINT_URL + "/LATEST_RELEASE_%s" % version
        else:
            url = self._GOOGLEAPIS_ENDPOINT_URL + "/LATEST_RELEASE_%s" % version

        # Request driver version
        res = await self._request_response_text(url)

        # Parse driver version
        try:
            return self._parse_driver_version(res)
        except errors.InvalidDriverVersionError:
            self._raise_driver_request_failed_error(driver_version)

    async def _install_driver_executable(self, driver_version: Version) -> str:
        """(Internal) Install & cache the webdriver executable.
        Returns the installed webdriver executable location `<str>`.
        """
        # Url from chromelabs
        if driver_version > self._CHROMELABS_DRIVER_VERSION:
            driver_arch = self._generate_chromelabs_arch()
            url = self._CHROMELABS_DRIVER_URL + "/%s/%s/chromedriver-%s.zip" % (
                driver_version,
                driver_arch,
                driver_arch,
            )
        # Url from googleapis
        else:
            driver_arch = self._generate_googleapis_arch(driver_version)
            url = self._GOOGLEAPIS_ENDPOINT_URL + "/%s/chromedriver_%s.zip" % (
                driver_version,
                driver_arch,
            )

        # Download driver content
        res = await self._request_response_file(url)
        if res is None:
            self._raise_driver_download_failed_error(driver_version, url)

        # Cache driver executable
        return self._cache_driver_executable(driver_version, res)

    def _generate_chromelabs_arch(self) -> str:
        """(Internal) Generate the webdriver architecture for chromelabs
        endpoint. Use to construct webdriver download url `<str>`.

        For example: `'win64'`, `'mac-arm64'`, `'linux64'`.
        """
        if self._chromelabs_arch is None:
            if self._os_name == OSType.WIN:
                arch = "win" + self._os_arch
            elif self._os_name == OSType.MAC:
                arch = "mac-arm64" if self._os_is_arm else "mac-x64"
            else:
                arch = "linux" + self._os_arch
            self._chromelabs_arch = arch
        return self._chromelabs_arch

    def _generate_googleapis_arch(self, driver_version: ChromiumVersion) -> str:
        """(Internal) Generate the webdriver architecture for googleapis
        endpoint. Use to construct webdriver download url `<str>`.

        For example: `'win64'`, `'mac64_m1'`, `'linux64'`.
        """
        # Googleapis arch
        if self._os_name == OSType.WIN:
            return "win32"
        elif self._os_name == OSType.MAC:
            if self._os_is_arm:
                if driver_version < self._GOOGLEAPIS_MACARM64_VERIONS:
                    return "mac64_m1"
                else:
                    return "mac_arm64"
            else:
                return "mac" + self._os_arch
        else:
            return "linux" + self._os_arch

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> ChromiumVersion:
        """Access the version of the browser that pairs with the installed
        driver `<ChromiumVersion>`. Please access this attribute after
        executing the `install()` method.
        """
        return super().browser_version

    # Version Utils -----------------------------------------------------------------------
    def _parse_driver_version(self, version: Any) -> ChromiumVersion:
        """(Internal) Parse the driver version `<ChromiumVersion>`"""
        try:
            return ChromiumVersion(version)
        except Exception:
            self._raise_invalid_driver_version_error(version)

    def _parse_browser_version(self, version: Any) -> ChromiumVersion:
        """(Internal) Parse the browser version `<ChromiumVersion>`"""
        try:
            return ChromiumVersion(version)
        except Exception:
            self._raise_invalid_browser_version_error(version)


class EdgeDriverManager(ChromiumBaseDriverManager):
    """Represents the webdriver manager for the Edge browser."""

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
    _AZUREEDGE_ENDPOINT_URL: str = "https://msedgedriver.azureedge.net"
    """The azureedge url to request the Edge webdriver."""
    # fmt: on

    def __init__(
        self,
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
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
        self._azureedge_arch: str = None

    # Driver version ----------------------------------------------------------------------
    async def _request_driver_version(self, driver_version: Version) -> ChromiumVersion:
        """(Internal) Request the available webdriver version `<ChromiumVersion>`."""
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
    async def _install_driver_executable(self, driver_version: ChromiumVersion) -> str:
        """(Internal) Install & cache the webdriver executable.
        Returns the installed webdriver executable location `<str>`.
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
        return self._cache_driver_executable(driver_version, res)

    def _generate_azureedge_arch(self) -> str:
        """(Internal) Generate the webdriver architecture for azureedge
        endpoint. Use to construct webdriver download url `<str>`.

        For example: `'win64'`, `'mac64_m1'`, `'linux64'`.
        """
        if self._azureedge_arch is None:
            if self._os_name == OSType.WIN:
                arch = "arm64" if self._os_is_arm else "win" + self._os_arch
            elif self._os_name == OSType.MAC:
                arch = "mac64_m1" if self._os_is_arm else "mac" + self._os_arch
            else:
                arch = "linux" + self._os_arch
            self._azureedge_arch = arch
        return self._azureedge_arch


class ChromeDriverManager(ChromiumBaseDriverManager):
    """Represents the webdriver manager for the Chrome browser."""

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
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
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
    async def install(
        self,
        version: ChromiumVersion | Literal["major", "build", "patch"] = "build",
        channel: Literal["stable", "beta", "dev", "cft"] = "stable",
        binary: str | None = None,
    ) -> str:
        """### Webdriver Installation

        :param version: `<str>` Defaults to `'build'`. Accepts the following values:
            - `'major'`: Install webdriver that has the same major version as the browser.
            - `'build'`: Install webdriver that has the same major & build version as the browser.
            - `'patch'`: Install webdriver that has the same major, build & patch version as the browser.
            - `'118.0.5982.0'`: Install the excat webdriver version regardless of the browser version.
            - `'cft'`: For more information, please refer to the [Chrome for Testing Installation] section below.

        :param channel: `<str>` Defaults to `'stable'`. Accepts the following values:
            - `'stable'`: Locate the `STABLE` (normal) browser binary in the system
                          and use it to determine the webdriver version.
            - `'beta'`:   Locate the `BETA` browser binary in the system and use it to
                          determine the webdriver version.
            - `'dev'`:    Locate the `DEV` browser binary in the system and use it to
                          determine the webdriver version.

        :param binary: `<str>` The path to a specific browser binary. Defaults to `None`.
            If specified, will use this given browser binary to determine
            the webdriver version.

        :return: `<str>` The path to the installed webdriver executable.

        ### Example:
        >>> from aselenium import ChromeDriverManager
            mgr = ChromeDriverManager()
            driver_executable = await mgr.install("build", "beta")
            # /Users/<user>/.aselenium/chromedriver_120.0.6099.56/extracted/chromedriver
            mgr.driver_version
            # 120.0.6099.56
            mgr.browser_location
            # /Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta
            mgr.browser_version
            # 120.0.6099.56

        ### Chrome for Testing Installation

        :param version: `<str>` A valid Chrome for Testing version. e.g. `'113.0.5672.0'`, `'120'`, etc.
        :param channel: `<str>` Must set to `'cft'` (Chrome for Testing).
        :param binary: `<str>` This argument will be ignored once `channel='cft'`.
        :return: `<str>` The path to the installed webdriver executable.

        Once the webdriver and corresponding browser are installed, you can access
        the [CFT] browser binary location via the `browser_location` attribute.

        ### Example:
        >>> from aselenium import ChromeDriverManager
            mgr = ChromeDriverManager()
            driver_executable = await mgr.install("119.0.6045", "cft")
            # /Users/<user>/.aselenium/chromedriver_119.0.6045.105/extracted/chromedriver
            mgr.driver_version
            # 119.0.6045.105
            mgr.browser_location
            # /Users/<user>/.aselenium/chrome_119.0.6045.105/extracted
            # /Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
            mgr.browser_version
            # 119.0.6045.105
        """
        #### Driver installation
        if channel != "cft":
            return await super().install(version, channel, binary)

        #### Chrome for Testing installation
        try:
            # Parse arguments
            self._channel = channel
            self._parse_target_version(version)
            if self._target_version is None:
                raise errors.InvalidDriverVersionError(
                    "<{}>\nMust specific version for [cft] (Chrome for Testing) "
                    "channel. Instead of: {} {}.".format(
                        self.__class__.__name__, repr(version), type(version)
                    )
                )
            if self._target_version < self._CHROMELABS_CFT_VERSION:
                raise errors.InvalidDriverVersionError(
                    "<{}>\nVersion below '{}' is not supported by [cft] (Chrome "
                    "for Testing). Please try a different version.".format(
                        self.__class__.__name__, self._CHROMELABS_CFT_VERSION
                    )
                )

            # Install Chrome for Testing
            async with self._installation_lock:
                # . match from cache - 1st
                driver_location = self._match_cft_driver_and_binary(
                    self._target_version, self._target_version
                )
                if driver_location is not None:
                    return driver_location

                # . request CFT versions
                driver_version, binary_version = await self._request_cft_versions(
                    self._target_version
                )

                # . match from cache - 2rd
                driver_location = self._match_cft_driver_and_binary(
                    driver_version, binary_version
                )
                if driver_location is not None:
                    return driver_location

                # . install driver & browser
                driver_location, _ = await gather(
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
    ) -> str | None:
        """(Internal) Match the CFT driver & binary from cache. Returns
        the driver location if both driver & binary are matched, otherwise
        returns `None`.
        """
        # Match driver from cache
        driver_location = self._match_driver_executable(driver_version, "patch")
        if driver_location is None:
            return None

        # Match binary from cache
        binary_location = self._match_browser_binary(binary_version, "patch")
        if binary_location is None:
            return None

        # Return driver location
        return driver_location

    async def _request_cft_versions(
        self,
        cft_version: ChromiumVersion,
    ) -> tuple[ChromiumVersion, ChromiumVersion]:
        """(Internal) Request available Chrome for Testing version."""
        # Request from chromelabs
        major_version = cft_version.build
        if cft_version > self._CHROMELABS_DRIVER_VERSION:
            # . request cft version
            url = self._CHROMELABS_ENDPOINT_URL + "/LATEST_RELEASE_%s" % major_version
            res = await self._request_response_text(url)
            try:
                version = self._parse_driver_version(res)
            except Exception:
                self._raise_invalid_cft_version_error()
            # . return versions
            return version, version
        # Request from googleapis
        else:
            # . request driver version
            url = self._GOOGLEAPIS_ENDPOINT_URL + "/LATEST_RELEASE_%s" % major_version
            res = await self._request_response_text(url)
            try:
                driver_version = self._parse_driver_version(res)
            except Exception:
                self._raise_invalid_cft_version_error()
            # . request binary version
            major_version = driver_version.build
            url = self._CHROMELABS_ENDPOINT_URL + "/LATEST_RELEASE_%s" % major_version
            res = await self._request_response_text(url)
            try:
                binary_version = self._parse_browser_version(res)
            except Exception:
                self._raise_invalid_cft_version_error()
            # . return versions
            return driver_version, binary_version

    async def _install_browser_binary(self, binary_version: ChromiumVersion) -> str:
        """(Internal) Install & cache the browser binary and
        returns the installed browser binary location `<str>`.
        """
        # Generate browser architecture
        binary_arch = self._generate_chromelabs_arch()

        # Download from chromelabs
        url = self._CHROMELABS_DRIVER_URL + "/%s/%s/chrome-%s.zip" % (
            binary_version,
            binary_arch,
            binary_arch,
        )

        # Request browser data
        res = await self._request_response_file(url)
        if res is None:
            self._raise_browser_download_failed_error(binary_version, url)

        # Cache browser binary
        return self._cache_browser_binary(binary_version, res)

    # Exceptions --------------------------------------------------------------------------
    def _raise_invalid_cft_version_error(self) -> None:
        """(Internal) Raise an invalid CFT version error."""
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
    """Represents the webdriver manager for the Chromium browser."""

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
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
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
        version: ChromiumVersion | Literal["major", "build", "patch"] = "build",
        binary: str | None = None,
    ) -> str:
        """Install a webdriver.

        :param version: `<str>` Defaults to `'build'`. Accepts the following values:
            - `'major'`: Install webdriver that has the same major version as the browser.
            - `'build'`: Install webdriver that has the same major & build version as the browser.
            - `'patch'`: Install webdriver that has the same major, build & patch version as the browser.
            - `'118.0.5982.0'`: Install the excat webdriver version regardless of the browser version.

        :param binary: `<str/None>` The path to a specific browser binary. Defaults to `None`.
            - If `None`, will try to locate the Chromium browser binary installed
              in the system and use it to determine the webdriver version.
            - If specified, will use the given browser binary to determine the
              webdriver version.

        :return: `<str>` The path to the installed webdriver executable.

        ### Example:
        >>> from aselenium import ChromiumDriverManager
            mgr = ChromiumDriverManager()
            driver_executable = await mgr.install("build")
            # /Users/<user>/.aselenium/chromedriver_118.0.5982.0/extracted/chromedriver
            mgr.driver_version
            # 118.0.5982.0
            mgr.browser_location
            # /Applications/Chromium.app/Contents/MacOS/Chromium
            mgr.browser_version
            # 118.0.5982.0
        """
        return await super().install(version, "dev", binary)


class FirefoxDriverManager(DriverManager):
    """Represents the webdriver manager for Firefox browser."""

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
    """The github url to request the compatible Firefox webdriver version."""
    _MOZILLA_GITHUBAPI_URL: str = "https://api.github.com/repos/mozilla/geckodriver/releases"
    """The github api url to request the compatible Firefox webdriver version."""
    _GECKODRIVER_MACARM_VERSION: GeckoVersion = GeckoVersion("0.29.1")
    """Version below this does not provide arm64 driver for MacOS."""
    _GECKODRIVER_WINARM_VERSION: GeckoVersion = GeckoVersion("0.32.0")
    """Version below this does not provide arm64 driver for Windows."""
    _GECKODRIVER_LINUXARM_ARCH_VERSION: GeckoVersion = GeckoVersion("0.32.0")
    """Version below this does not provide arm64 driver for Linux."""
    _GECKODRIVER_MAX_VERSION: GeckoVersion = None
    """The maximum version of GeckoDriver available by the manager."""
    _GECKODRIVER_MIN_VERSION: GeckoVersion = GeckoVersion("0.30.0")
    """The minimum version of GeckoDriver supported by the manager."""
    _GECKODRIVER_TABLE: dict[GeckoVersion, dict[str, FirefoxVersion]] = None
    """The compatibility table between Firefox and GeckoDriver."""
    _GECKODRIVER_TABLE_MAX_VERSION: GeckoVersion = None
    """The maximum version of GeckoDriver recorded in the compatibility table."""
    _FIREFOX_MIN_VERSION: FirefoxVersion = FirefoxVersion("78.0.0")
    """Firefox version below this is not supported by the manager."""
    # fmt: on

    def __init__(
        self,
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
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
        self._target_version: GeckoVersion
        self._driver_version: GeckoVersion
        self._browser_version: FirefoxVersion

    # Class methods -----------------------------------------------------------------------
    @classmethod
    def load_driver_compatibility_table(cls) -> None:
        """(Class method) Load the compatibility table between Firefox
        and GeckoDriver int to memory.
        """
        # Already loaded
        if cls._GECKODRIVER_TABLE is not None:
            return None  # exit

        # Load json file
        json_file = join_path(dirname(__file__), "geckodriver", "compatibility.json")
        js = load_json_file(json_file)

        # Parse compatibility table
        cls._GECKODRIVER_TABLE = {
            GeckoVersion(key): {k: FirefoxVersion(v) for k, v in val.items()}
            for key, val in js.items()
        }

        # Set max version
        cls._GECKODRIVER_TABLE_MAX_VERSION = max(list(cls._GECKODRIVER_TABLE.keys()))
        cls._GECKODRIVER_MAX_VERSION = cls._GECKODRIVER_TABLE_MAX_VERSION

    # Installation ------------------------------------------------------------------------
    async def install(
        self,
        version: GeckoVersion | Literal["latest", "auto"] = "latest",
        binary: str | None = None,
    ) -> str:
        """Install a geckodriver.

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
            - If specified, will use the given Firefox binary to determine the
              compatible webdriver version.

        :return: `<str>` The path to the installed webdriver executable.

        ### Example:
        >>> from aselenium import FirefoxDriverManager
            mgr = FirefoxDriverManager()
            driver_executable = await mgr.install("auto")
            # /Users/<user>/.aselenium/geckodriver_0.33.0/extracted/geckodriver
            mgr.driver_version
            # 0.33.0
            mgr.browser_location
            # /Applications/Firefox.app/Contents/MacOS/firefox
            mgr.browser_version
            # 120.0.1
        """
        try:
            # Parse arguments
            self._channel: str = "stable"
            self._parse_target_version(version)
            self._parse_target_binary(binary)

            # Detect browser location
            if self._target_binary is None:
                self._browser_location = self._detect_browser_location()
            else:
                self._browser_location = self._target_binary

            # Detect browser version
            self._browser_version = self._detect_browser_version(self._browser_location)

            # Install webdriver
            async with self._installation_lock:
                # . determine driver version
                if self._target_version is None:
                    max_version = self._find_max_compatible_driver_version(
                        self._browser_version
                    )
                    if max_version == self._GECKODRIVER_TABLE_MAX_VERSION:
                        if version == "latest":  # request latest version from github
                            driver_version = await self._request_driver_version(None)
                        else:  # set to maximum recorded version
                            driver_version = self._GECKODRIVER_MAX_VERSION
                    else:
                        driver_version = max_version
                else:
                    driver_version = self._target_version

                # . match from cache
                driver_location = self._match_driver_executable(driver_version, "patch")
                if driver_location is not None:
                    return driver_location

                # . install driver executable
                return await self._install_driver_executable(driver_version)

        except BaseException:
            self.reset()
            raise

    # Target ------------------------------------------------------------------------------
    def _parse_target_version(self, version: Any) -> None:
        """(Internal) Parse the target version for the installation."""
        if version in ["latest", "auto", None]:
            self._target_version = None
        else:
            self._target_version = self._parse_driver_version(version)

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> GeckoVersion:
        """Access the version of the installed webdriver `<GeckoVersion>`.
        Please access this attribute after executing the `install()` method.
        """
        return super().driver_version

    async def _request_driver_version(self, version: Version | None) -> GeckoVersion:
        """(Internal) Request the available geckodriver version `<GeckoVersion>`."""

        async def request_from_api(version: GeckoVersion | None) -> str | None:
            # Request from github api
            if version is None:
                url = self._MOZILLA_GITHUBAPI_URL + "/latest"
            else:
                url = self._MOZILLA_GITHUBAPI_URL + "/tags/v" + version.patch
            res = await self._request_reponse_json(url)
            return await request_from_url(version) if res is None else res["tag_name"]

        async def request_from_url(version: GeckoVersion | None) -> GeckoVersion:
            # Request from github url
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
            version = self._parse_driver_version(res)
        except errors.InvalidDriverVersionError:
            self._raise_driver_request_failed_error(version)

        # Update max version
        if version > self._GECKODRIVER_MAX_VERSION:
            self._GECKODRIVER_MAX_VERSION = version

        # Return version
        return version

    async def _install_driver_executable(self, driver_version: GeckoVersion) -> str:
        """(Internal) Install & cache the webdriver executable.
        Returns the installed webdriver executable location `<str>`.
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
        return self._cache_driver_executable(driver_version, res)

    def _generate_mozilla_arch(self, driver_version: GeckoVersion) -> str:
        """(Internal) Generate the webdriver architecture for mozilla
        github repository. Use to construct webdriver download url `<str>`.

        For example: `'win64.zip'`, `'mac64-aarch64.tar.gz'`, `'linux64.tar.gz'`.
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
                if driver_version < self._GECKODRIVER_LINUXARM_ARCH_VERSION:
                    self._raise_driver_unavailable_error(driver_version)
                return "linux-aarch64.tar.gz"
            else:
                return "linux" + self._os_arch + ".tar.gz"

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> FirefoxVersion:
        """Access the version of the browser that pairs with the installed driver `<FirefoxVersion>`.
        Please access this attribute after executing the `install()` method.
        """
        return super().browser_version

    def _find_max_compatible_driver_version(
        self,
        browser_version: FirefoxVersion,
    ) -> GeckoVersion:
        """(Internal) Find browser's maximum compatible driver version
        based on the compatibility table `<GecoVersion>`.
        """
        for d_version, b_versions in self._GECKODRIVER_TABLE.items():
            if (
                b_versions["min_firefox_version"] <= browser_version
                and b_versions["max_firefox_version"] >= browser_version
            ):
                return d_version

        self._raise_browser_unsupported_error(browser_version)

    # Version Utils -----------------------------------------------------------------------
    def _parse_driver_version(self, version: Any) -> GeckoVersion:
        """(Internal) Parse the driver version `<GeckoVersion>`"""
        try:
            return GeckoVersion(version)
        except Exception:
            self._raise_invalid_driver_version_error(version)

    def _parse_browser_version(self, version: Any) -> FirefoxVersion:
        """(Internal) Parse the browser version `<FirefoxVersion>`"""
        try:
            return FirefoxVersion(version)
        except Exception:
            self._raise_invalid_browser_version_error(version)

    # Exceptions --------------------------------------------------------------------------
    def _raise_driver_unavailable_error(self, version: Version) -> None:
        """(Internal) Raise an unavailable driver error."""
        if version < self._GECKODRIVER_MIN_VERSION:
            raise errors.InvalidDriverVersionError(
                "<{}>\nGeokodriver version below '{}' is not supported "
                "by the manager. Target version: '{}'".format(
                    self.__class__.__name__, self._GECKODRIVER_MIN_VERSION, version
                )
            )
        else:
            raise errors.InvalidDriverVersionError(
                "<{}>\nGeokodriver version '{}' is not available for {} ({}{}{}).".format(
                    self.__class__.__name__,
                    version,
                    self._name,
                    self._os_name,
                    self._os_arch,
                    "_arm" if self._os_is_arm else "",
                )
            )

    def _raise_browser_unsupported_error(self, version: Version) -> None:
        """(Internal) Raise a failed to find compatible driver error."""
        if version < self._FIREFOX_MIN_VERSION:
            raise errors.InvalidBrowserVersionError(
                "<{}>\n{} ({}{}{}) version '{}' is not supported by the manager. "
                "Please upgrade the browser to version >= '{}'.".format(
                    self.__class__.__name__,
                    self.__name__,
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


class SafariDriverManager(DriverManager):
    """Represents the webdriver manager for the Safari."""

    # fmt: off
    _MAC_BINARY_PATHS: dict[str, list[str]] = {
        ChannelType.STABLE: ["/Applications/Safari.app/Contents/MacOS/Safari"],
        ChannelType.DEV: ["/Applications/Safari Technology Preview.app/Contents/MacOS/Safari Technology Preview"],
    }
    """The partial paths to the browser binary on MacOS."""
    _MAC_DRIVER_DEFAULT_PATH: str = "/usr/bin/safaridriver"
    """The default path to the webdriver executable on MacOS."""
    _DRIVER_EXECUTABLE_NAME: str = "safaridriver"
    """The name of the webdriver executable."""
    # fmt: on

    def __init__(
        self,
        directory: str | None = None,
        max_cache_size: int | None = None,
        request_timeout: int | float = 10,
        download_timeout: int | float = 300,
        proxy: str | None = None,
    ) -> None:
        super().__init__(
            "Safari",
            None,
            None,
            None,
            directory,
            max_cache_size,
            request_timeout,
            download_timeout,
            proxy,
        )
        # Target
        self._target_driver: str | None = None

    # Installation ------------------------------------------------------------------------
    async def install(
        self,
        channel: SafariVersion | Literal["stable", "dev"] = "stable",
        driver: str | None = None,
        binary: str | None = None,
    ) -> str:
        """Install a webdriver.

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

        :return: `<str>` The path to the webdriver executable.

        ### Example:
        >>> from aselenium import SafariDriverManager
            mgr = SafariDriverManager()
            driver_executable = await mgr.install("dev")
            # /Applications/Safari Technology Preview.app/Contents/MacOS/safaridriver
            mgr.driver_version
            # 17.4.1
            mgr.browser_location
            # /Applications/Safari Technology Preview.app/Contents/MacOS/Safari Technology Preview
            mgr.browser_version
            # 17.4.1
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
            # Prase arguments
            self._channel = channel
            self._parse_target_driver(driver)
            self._parse_target_binary(binary)

            # Detect browser location
            if self._target_binary is None:
                self._browser_location = self._detect_browser_location()
            else:
                self._browser_location = self._target_binary

            # Detect browser version
            self._browser_version = self._detect_browser_version(self._browser_location)

            # Detect driver location
            if self._target_driver is None:
                self._driver_location = self._detect_driver_location()
            else:
                self._driver_location = self._target_driver
            self._driver_version = self._browser_version

            # Return driver location
            return self._driver_location

        except BaseException:
            self.reset()
            raise

    # Target ------------------------------------------------------------------------------
    def _parse_target_driver(self, driver: Any) -> None:
        """(Internal) Prase the target webdriver executable for the installation."""
        if driver is None:
            self._target_driver = None
            return None  # exit
        try:
            driver: str = validate_file(driver)
        except Exception:
            self._raise_invalid_driver_location_error(driver)
        if not driver.endswith(self._DRIVER_EXECUTABLE_NAME):
            self._raise_invalid_driver_location_error(driver)
        self._target_driver = driver

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> SafariVersion:
        """Access the version of the installed webdriver `<SafariVersion>`.
        Please access this attribute after executing the `install()` method.
        """
        return super().driver_version

    def _detect_driver_location(self) -> str:
        """(Internal) Detect the driver location `<str>`."""
        # Stable channel - default location
        if self._channel == ChannelType.STABLE and self._target_binary is None:
            if is_path_file(self._MAC_DRIVER_DEFAULT_PATH):
                return self._MAC_DRIVER_DEFAULT_PATH

        # Application contents - default location
        base_folder = dirname(self._browser_location)
        location = join_path(base_folder, self._DRIVER_EXECUTABLE_NAME)
        if is_path_file(location):
            return location

        # Application contents - search
        base_folder = dirname(base_folder)
        for base_dir, _, files in walk_path(base_folder):
            if self._DRIVER_EXECUTABLE_NAME in files:
                return join_path(base_dir, self._DRIVER_EXECUTABLE_NAME)

        # Raise driver not found error
        if self._target_binary is None:
            self._raise_invalid_driver_location_error(None)

        # Return default driver location
        return self._MAC_DRIVER_DEFAULT_PATH

    # Browser -----------------------------------------------------------------------------
    @property
    def browser_version(self) -> SafariVersion:
        """Access the version of the browser that pairs with the installed
        driver `<SafariVersion>`. Please access this attribute after
        executing the `install()` method.
        """
        return super().browser_version

    def _detect_browser_version(self, browser_location: str) -> SafariVersion:
        """(Internal) Detect the browser version `<SafariVersion>`."""
        try:
            # Application folder
            app_dir = browser_location.split("/Contents/MacOS")[0]
            content_dir = join_path(app_dir, "Contents")
            # Load plist file
            try:
                plist = load_plist_file(join_path(content_dir, "version.plist"))
            except FileNotFoundError:
                plist = load_plist_file(join_path(content_dir, "Info.plist"))
            # Return version
            return SafariVersion(plist["CFBundleShortVersionString"])

        except Exception:
            self._raise_invalid_browser_location_error(browser_location)
