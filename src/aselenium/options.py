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
from copy import deepcopy
from platform import system
from tempfile import mkdtemp
from base64 import b64encode
from typing import Any, Literal
from os import chmod
from os.path import join as join_path
from shutil import copytree, ignore_patterns, rmtree
from aselenium import errors
from aselenium.settings import Constraint, DefaultTimeouts
from aselenium.manager.version import Version, ChromiumVersion
from aselenium.utils import validate_file, validate_dir, is_path_dir, prettify_dict

__all__ = ["Proxy", "Timeouts", "ChromiumProfile"]

# Constants ---------------------------------------------------------------------------------------
PROXY_TYPES: set[str] = {"DEFAULT", "AUTODETECT", "MANUAL", "PAC"}


# Option Objects ----------------------------------------------------------------------------------
class Proxy:
    """Represents the proxy configuration for the browser."""

    def __init__(
        self,
        auto_detect: bool = False,
        pac_url: str | None = None,
        ftp_proxy: str | None = None,
        http_proxy: str | None = None,
        https_proxy: str | None = None,
        socks_proxy: str | None = None,
        socks_username: str | None = None,
        socks_password: str | None = None,
        no_proxy: str | list[str] | None = None,
    ) -> None:
        """The proxy configuration for the browser.

        ### Proxy Type: `'DEFAULT'`
        If the Proxy is created with the default settings, the proxy
        type will set to `'DEFAULT'`. On Windows, this means `'DIRECT'`
        connection. On other platforms, this means use the `'SYSTEM'`
        proxy settings.

        ### Proxy Type: `'AUTODETECT'`
        :param auto_detect: `<bool>` If `True`, the proxy type will be set
        to `'AUTODETECT'`. This is often used when the system has its own
        proxy settings that should be used. Defaults to `False`.

        ### Proxy Type: `'PAC'`
        :param pac_url: `<str/None>` The URL to the PAC (Proxy Auto-Configuration)
        file. If `pac_url` is provided, the proxy type will be set to `'PAC'`.
        This is often used when the network environment has a configuration
        script to handle traffic routing. Defaults to `None`.

        ### Proxy Type: `'MANUAL'`
        If any of the following proxy properties is specified, the proxy type
        will be set to `'MANUAL'`.

        :param ftp_proxy: `<str/None>` The proxy address to route the FTP (File
        Transfer Protocol) traffics. Defaults to `None`.

        :param http_proxy: `<str/None>` The proxy address to route the HTTP
        traffics. Defaults to `None`.

        :param https_proxy: `<str/None>` The proxy address to route the encrypted
        HTTPS traffics. Defaults to `None`.

        :param socks_proxy: `<str/None>` The proxy address to route the SOCKS
        traffics. Defaults to `None`.

        :param socks_username: `<str/None>` The username to use for SOCKS
        authentication. Defaults to `None`.

        :param socks_password: `<str/None>` The password to use for SOCKS
        authentication. Defaults to `None`.

        :param no_proxy: `<str/list/None>` The addresses that bypass the proxy
        configuration. Each address is either a domain name, a hostname, or an
        IP address. Defaults to `None`.
        """
        # Set proxy type
        self._proxy_type: str = "DEFAULT"
        # Proxy configuration
        if auto_detect:
            self.auto_detect = True
        self.pac_url = pac_url
        self.ftp_proxy = ftp_proxy
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.socks_proxy = socks_proxy
        self.socks_username = socks_username
        self.socks_password = socks_password
        self.no_proxy = no_proxy
        # Capabilities
        self.__caps: dict[str, Any] = {}
        self.__status: int = 0

    # Proxy: type ----------------------------------------------------------------------
    @property
    def proxy_type(self) -> str:
        """Access the type of the proxy `<str>`.

        - `'DEFAULT'`: If the platform is windows, means direct connection
            `{"ff_value": 0, "string": "DIRECT"}`. On other platforms, this
            means use the system proxy settings `{"ff_value": 5, "string": "SYSTEM"}`.

        - `'AUTODETECT'`: Proxy auto detection (presumably with WPAD)
            `{"ff_value": 4, "string": "AUTODETECT"}`.

        - `'MANUAL'`: Manual proxy settings (e.g., for httpProxy)
            `{"ff_value": 1, "string": "MANUAL"}`.

        - `'PAC'`: Proxy autoconfiguration from URL.
            `{"ff_value": 2, "string": "PAC"}`.

        ### Notice
        The 'proxy_type' should not be adjusted manually. Changing
        other proxy properties will change this 'proxy_type' to
        the corresponding value automatically.
        """
        if self._proxy_type == "DEFAULT":
            return "DIRECT" if system() == "Windows" else "SYSTEM"
        else:
            return self._proxy_type

    # Config: auto detect --------------------------------------------------------------
    @property
    def auto_detect(self) -> bool:
        """Whether the proxy settings should be automatically
        detected. This is often used when the system has its
        own proxy settings or configurations `<bool>`.
        """
        return self._proxy_type == "AUTODETECT"

    @auto_detect.setter
    def auto_detect(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `auto_detect`, must be type of "
                "`<bool>`.".format(self.__class__.__name__)
            )
        if value:
            self._proxy_type = "AUTODETECT"
        else:
            self._proxy_type = "DEFAULT"
        self.__status = 1

    # Config: PAC ----------------------------------------------------------------------
    @property
    def pac_url(self) -> str:
        """The URL to the PAC (Proxy Auto-Configuration) file.
        This is often used when the network environment has a
        configuration script to handle traffic routing `<str>`.
        """
        return self._pac_url

    @pac_url.setter
    def pac_url(self, value: str | None) -> None:
        if isinstance(value, str):
            self._proxy_type = "PAC"
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `pac_url`, must be type of "
                "`<str>` or `None`.".format(self.__class__.__name__)
            )
        self._pac_url = value
        self.__status = 1

    # Config: ftp ----------------------------------------------------------------------
    @property
    def ftp_proxy(self) -> str:
        """The proxy address to route the FTP (File Transfer Protocol)
        traffics `<str>`.
        """
        return self._ftp_proxy

    @ftp_proxy.setter
    def ftp_proxy(self, value: str | None) -> None:
        if isinstance(value, str):
            if not value.startswith("ftp://"):
                raise errors.InvalidProxyError(
                    "<{}>\n`ftp_proxy` must start with 'ftp://', "
                    "instead got: {}.".format(self.__class__.__name__, repr(value))
                )
            value = value.split("://", 1)[1]
            self._proxy_type = "MANUAL"
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `ftp_proxy`, must be type of "
                "`<str>` or `None`.".format(self.__class__.__name__)
            )
        self._ftp_proxy = value
        self.__status = 1

    # Config: http ---------------------------------------------------------------------
    @property
    def http_proxy(self) -> str:
        """The proxy address to route the HTTP traffics `<str>`."""
        return self._http_proxy

    @http_proxy.setter
    def http_proxy(self, value: str | None) -> None:
        if isinstance(value, str):
            if not value.startswith("http://") and not value.startswith("https://"):
                raise errors.InvalidProxyError(
                    "<{}>\n`http_proxy` must start with 'http://' or 'https://', "
                    "instead got: {}.".format(self.__class__.__name__, repr(value))
                )
            value = value.split("://", 1)[1]
            self._proxy_type = "MANUAL"
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `http_proxy`, must be type of "
                "`<str>` or `None`.".format(self.__class__.__name__)
            )
        self._http_proxy = value
        self.__status = 1

    # Config: ssl ----------------------------------------------------------------------
    @property
    def https_proxy(self) -> str:
        """The proxy address to route the encrypted HTTPS traffics `<str>`."""
        return self._https_proxy

    @https_proxy.setter
    def https_proxy(self, value: str | None) -> None:
        if isinstance(value, str):
            if not value.startswith("https://") and not value.startswith("http://"):
                raise errors.InvalidProxyError(
                    "<{}>\n`https_proxy` must start with 'https://' or 'http://', "
                    "instead got: {}.".format(self.__class__.__name__, repr(value))
                )
            value = value.split("://", 1)[1]
            self._proxy_type = "MANUAL"
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `https_proxy`, must be type of "
                "`<str>` or `None`.".format(self.__class__.__name__)
            )
        self._https_proxy = value
        self.__status = 1

    # Config: socks --------------------------------------------------------------------
    @property
    def socks_proxy(self) -> str:
        """The proxy address to route the SOCKS traffics `<str>`."""
        return self._socks_proxy

    @socks_proxy.setter
    def socks_proxy(self, value: str | None) -> None:
        if isinstance(value, str):
            if value.startswith("socks5://"):
                self._socks_version = 5
            elif value.startswith("socks4://"):
                self._socks_version = 4
            else:
                raise errors.InvalidProxyError(
                    "<{}>\n`socks_proxy` must start with 'socks5://' or 'socks4://', "
                    "instead got: {}.".format(self.__class__.__name__, repr(value))
                )
            value = value.split("://", 1)[1]
            self._proxy_type = "MANUAL"
        elif value is None:
            self._socks_version = None
            self._socks_username = None
            self._socks_password = None
        else:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `socks_proxy`, must be type of "
                "`<str>` or `None`.".format(self.__class__.__name__)
            )
        self._socks_proxy = value
        self.__status = 1

    @property
    def socks_username(self) -> str:
        """The username to use for SOCKS authentication `<str>`."""
        return self._socks_username

    @socks_username.setter
    def socks_username(self, value: str | None) -> None:
        if isinstance(value, str):
            self._proxy_type = "MANUAL"
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `socks_username`, must be type of "
                "`<str>` or `None`.".format(self.__class__.__name__)
            )
        self._socks_username = value
        self.__status = 1

    @property
    def socks_password(self) -> str:
        """The password to use for SOCKS authentication `<str>`."""
        return self._socks_password

    @socks_password.setter
    def socks_password(self, value: str | None) -> None:
        if isinstance(value, str):
            self._proxy_type = "MANUAL"
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `socks_password`, must be type of "
                "`<str>` or `None`.".format(self.__class__.__name__)
            )
        self._socks_password = value
        self.__status = 1

    # Config: no proxy -----------------------------------------------------------------
    @property
    def no_proxy(self) -> str:
        """The addresses that bypass the proxy configuration.
        Each address is either a domain name, a hostname, or
        an IP address, and separated by a comma `<str>`."""
        return self._no_proxy

    @no_proxy.setter
    def no_proxy(self, value: str | list[str] | None) -> None:
        if isinstance(value, str):
            self._proxy_type = "MANUAL"
        elif isinstance(value, list):
            try:
                value = ",".join(value)
            except Exception as err:
                raise errors.InvalidProxyError(
                    "<{}>\nInvalid `no_proxy`, list of addresses items must "
                    "all be type of `<str>`.".format(self.__class__.__name__)
                ) from err
            self._proxy_type = "MANUAL"
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `no_proxy`, must be type of `<str>`, "
                "`<list[str>]>` or `None`.".format(self.__class__.__name__)
            )
        self._no_proxy = value
        self.__status = 1

    # Capabilities ---------------------------------------------------------------------
    def to_capabilities(self) -> dict[str, Any]:
        """Create the capabilities representation of the
        proxy configuration `<dict[str, Any]>`.
        """
        # Already converted
        if self.__caps and self.__status == 0:
            return self.__caps.copy()

        # Convert to capabilities
        caps = {"proxyType": self.proxy_type.lower()}

        # . DEFAULT
        if self._proxy_type == "DEFAULT":
            pass
        # . AUTODETECT
        elif self._proxy_type == "AUTODETECT":
            caps["autodetect"] = True
        # . PAC
        elif self._proxy_type == "PAC":
            caps["proxyAutoconfigUrl"] = self._pac_url
        # . MANUAL
        else:
            if self._ftp_proxy:
                caps["ftpProxy"] = self._ftp_proxy
            if self._http_proxy:
                caps["httpProxy"] = self._http_proxy
            if self._https_proxy:
                caps["sslProxy"] = self._https_proxy
            if self._socks_proxy:
                caps["socksProxy"] = self._socks_proxy
                caps["socksVersion"] = self._socks_version
            if self._socks_username:
                caps["socksUsername"] = self._socks_username
            if self._socks_password:
                caps["socksPassword"] = self._socks_password
            if self._no_proxy:
                caps["noProxy"] = self._no_proxy

        # Set & return capabilities
        self.__caps = caps
        self.__status = 0
        return self.__caps.copy()

    # Special methods ------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (config=%s)>" % (
            self.__class__.__name__,
            prettify_dict(self.to_capabilities()),
        )


class Timeouts:
    """Represents the timeouts parameters for the browser."""

    def __init__(
        self,
        implicit: int | float | None = None,
        pageLoad: int | float | None = None,
        script: int | float | None = None,
        unit: Literal["s", "ms"] = "ms",
    ) -> None:
        """The timeouts parameters for the browser.

        :param implicit: `<int/float>` The time to wait when searching for
        an element if not immediately present. If `None`, set to default
        timeout value.

        :param pageLoad: `<int/float>` The time to wait for a page load to
        complete. If `None`, set to default timeout value.

        :param script: `<int/float>` The time to wait for an asynchronous
        script execution. If `None`, set to default timeout value.

        :param unit: `<'str'>` The unit of the timeouts, accepts `s` or `ms`.
        Defaults to `'ms'`.
        """
        self._implicit: int = None
        self._pageLoad: int = None
        self._script: int = None
        if unit == "ms":
            self.implicit_ms = implicit
            self.pageLoad_ms = pageLoad
            self.script_ms = script
        else:
            self.implicit = implicit
            self.pageLoad = pageLoad
            self.script = script

    # Dict --------------------------------------------------------------------------------
    @property
    def dict(self) -> dict[str, int]:
        """Access the timeouts in miliseconds as
        a dictionary `<dict[str, int]>`.

        Excepted format:
        >>> {"implicit": 0, "pageLoad": 300_000, "script": 30_000}
        """
        return {
            "implicit": self._implicit,
            "pageLoad": self._pageLoad,
            "script": self._script,
        }

    # Implicit timeout --------------------------------------------------------------------
    @property
    def implicit(self) -> float:
        """Access implicit timeout in seconds `<float>`.

        Total seconds to wait when searching for an element
        if not immediately present.
        """
        return self._implicit / 1000

    @implicit.setter
    def implicit(self, value: int | float | None) -> None:
        # Value is None
        if value is None:
            if self._implicit is None:
                self._implicit: int = DefaultTimeouts.IMPLICIT
        # Set implicit
        else:
            value = self._validate_timeout(value)
            self._implicit: int = int(value * 1000)

    @property
    def implicit_ms(self) -> int:
        """Access implicit timeout in milliseconds `<int>`.

        Total milliseconds to wait when searching for an
        element if not immediately present.
        """
        return self._implicit

    @implicit_ms.setter
    def implicit_ms(self, value: int | float | None) -> None:
        # Value is None
        if value is None:
            if self._implicit is None:
                self._implicit: int = DefaultTimeouts.IMPLICIT
        # Set implicit ms
        else:
            self._implicit: int = int(self._validate_timeout(value))

    # PageLoad timeout --------------------------------------------------------------------
    @property
    def pageLoad(self) -> float:
        """Access pageLoad timeout in seconds `<float>`.

        Total seconds to wait for a page load to complete.
        """
        return self._pageLoad / 1000

    @pageLoad.setter
    def pageLoad(self, value: int | float | None) -> None:
        # Value is None
        if value is None:
            if self._pageLoad is None:
                self._pageLoad: int = DefaultTimeouts.PAGE_LOAD
        # Set pageLoad
        else:
            value = self._validate_timeout(value)
            self._pageLoad: int = int(value * 1000)

    @property
    def pageLoad_ms(self) -> int:
        """Access pageLoad timeout in milliseconds `<int>`.

        Total milliseconds to wait for a page load to complete.
        """
        return self._pageLoad

    @pageLoad_ms.setter
    def pageLoad_ms(self, value: int | float | None) -> None:
        # Value is None
        if value is None:
            if self._pageLoad is None:
                self._pageLoad: int = DefaultTimeouts.PAGE_LOAD
        # Set pageLoad ms
        else:
            self._pageLoad: int = int(self._validate_timeout(value))

    # Script timeout ----------------------------------------------------------------------
    @property
    def script(self) -> float:
        """Access script timeout in seconds `<float>`.

        Total seconds to wait for an asynchronous script execution.
        """
        return self._script / 1000

    @script.setter
    def script(self, value: int | float | None) -> None:
        # Value is None
        if value is None:
            if self._script is None:
                self._script: int = DefaultTimeouts.SCRIPT
        # Set script
        else:
            value = self._validate_timeout(value)
            self._script: int = int(value * 1000)

    @property
    def script_ms(self) -> int:
        """Access script timeout in milliseconds `<int>`.

        Total milliseconds to wait for an asynchronous script execution.
        """
        return self._script

    @script_ms.setter
    def script_ms(self, value: int | float | None) -> None:
        # Value is None
        if value is None:
            if self._script is None:
                self._script: int = DefaultTimeouts.SCRIPT
        # Set script ms
        else:
            self._script: int = int(self._validate_timeout(value))

    # Utils -------------------------------------------------------------------------------
    def _validate_timeout(self, value: Any) -> int | float:
        """(internal) Validate the timeout value `<int/float>`"""
        if not isinstance(value, (int, float)):
            raise errors.InvalidOptionsError(
                "<{}>\nInvalid timeout ({}), must be an integer or float.".format(
                    self.__class__.__name__, repr(value)
                )
            )
        if value < 0:
            raise errors.InvalidOptionsError(
                "<{}>\nInvalid timeout ({}), must >= 0.".format(
                    self.__class__.__name__, repr(value)
                )
            )
        return value

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (implicity=%d, pageLoad=%d, script=%d, unit='ms')>" % (
            self.__class__.__name__,
            self._implicit,
            self._pageLoad,
            self._script,
        )

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, Timeouts):
            return (
                self._implicit == __o.implicit
                and self._pageLoad == __o.pageLoad
                and self._script == __o.script
            )
        else:
            return False

    def __bool__(self) -> bool:
        return True

    def copy(self) -> Timeouts:
        """Copy the timeouts object."""
        return Timeouts(self._implicit, self._pageLoad, self._script, unit="ms")


class Profile:
    """Represents the user profile for a browser."""

    def __init__(self, directory: str, profile_folder: str | None) -> None:
        """The user profile for the browser.

        :param directory [REQUIRED]: `<st>` The directory of the user profile.
        :param profile_folder [OPTIONAL]: `<str/None>` The name of the profile folder inside of the 'directory'.

        ### Explaination
        - When creating a `Profile` instance, a cloned temporary profile
          will be created based on the given profile 'directory'. The
          automated session will use this temporary profile leaving the
          original profile untouched. When this profile is no longer
          used by the program, the temporary profile will be deleted
          automatically.
        """
        # Profile directory
        self._profile_folder: str | None = profile_folder
        self._profile_dir: str = None
        self._temp_directory: str = None
        self._temp_profile_folder: str = "TEMP_PROFILE"
        self._temp_profile_dir: str = None
        try:
            self._directory = validate_dir(directory)
        except Exception as err:
            raise errors.InvalidProfileError(
                "<{}>\nProfile 'directory' error: {}".format(
                    self.__class__.__name__, err
                )
            ) from err
        # Create temporary profile
        self._create_temp_profile()

    # Temporary profile -------------------------------------------------------------------
    def _create_temp_profile(self) -> None:
        """(Internal) Create the temporary profile."""
        # Temporary profile already created
        if self._temp_directory is not None:
            return None  # exit

        # Determine profile directory
        if self._profile_folder is not None:
            try:
                self._profile_dir = join_path(self._directory, self._profile_folder)
            except Exception as err:
                raise errors.InvalidProfileError(
                    "<{}> Invalid profile folder: {} {}.".format(
                        self.__class__.__name__,
                        repr(self._profile_folder),
                        type(self._profile_folder),
                    )
                ) from err
            if not is_path_dir(self._profile_dir):
                raise errors.InvalidProfileError(
                    "<{}> Invalid profile directory: {} {}.".format(
                        self.__class__.__name__,
                        repr(self._profile_dir),
                        type(self._profile_dir),
                    )
                )
        else:
            self._profile_dir = self._directory

        # Clone profile to temporary directory
        try:
            self._temp_directory = mkdtemp()
            self._temp_profile_dir = join_path(
                self._temp_directory, self._temp_profile_folder
            )
            copytree(
                self._profile_dir,
                self._temp_profile_dir,
                ignore=ignore_patterns("parent.lock", "lock", ".parentlock"),
            )
            chmod(self._temp_profile_dir, 0o755)
        except Exception as err:
            self._delete_temp_profile()
            raise errors.InvalidProfileError(
                "<{}> Failed to clone profile at: '{}'\nError:{}".format(
                    self.__class__.__name__, self._profile_dir, err
                )
            ) from err

    def _delete_temp_profile(self) -> None:
        """(Internal) Delete the temporary profile."""
        # Temporary profile already deleted
        if self._temp_directory is None:
            return None  # exit

        # Delete temporary profile
        while is_path_dir(self._temp_directory):
            try:
                rmtree(self._temp_directory)
            except OSError:
                continue
        self._temp_directory = None

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (profile_directory='%s', temp_directory='%s')>" % (
            self.__class__.__name__,
            self._profile_dir,
            self._temp_profile_dir,
        )

    def __hash__(self) -> int:
        return hash(self.__repr__())

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __bool__(self) -> bool:
        return True

    def __del__(self):
        self._delete_temp_profile()


class ChromiumProfile(Profile):
    """Represents the user profile for Chromium based browser.
    Such as: Edge, Chrome, Chromium, etc.
    """

    def __init__(self, directory: str, profile_folder: str) -> None:
        """The user profile for Chromium based browser.
        Such as: Edge, Chrome, Chromium, etc.

        :param directory: `<st>` The directory of the user profile.
        :param profile_folder: `<str>` The name of the profile folder inside of the 'directory'.

        ### Explaination
        - When creating a `Profile` instance, a cloned temporary profile
          will be created based on the given profile 'directory'. The
          automated session will use this temporary profile leaving the
          original profile untouched. When this profile is no longer
          used by the program, the temporary profile will be deleted
          automatically.

        ### MacOS Default Profile Location:
        - Chrome: '~/Library/Application Support/Google/Chrome' & 'Default'
        - Chromium: '~/Library/Application Support/Chromium' & 'Default'
        - Edge: '~/Library/Application Support/Microsoft Edge' & 'Default'

        ### Windows Default Profile Location:
        - Chrome: 'C:\\Users\\<username>\\AppData\\Local\\Google\\Chrome\\User Data' & 'Default'
        - Chromium: 'C:\\Users\\<username>\\AppData\\Local\\Chromium\\User Data' & 'Default'
        - Edge: 'C:\\Users\\<username>\\AppData\\Local\\Microsoft\\Edge\\User Data' & 'Default'

        ### Linux Default Profile Location:
        - Chrome: '~/.config/google-chrome' & 'Default'
        - Chromium: '~/.config/chromium' & 'Default'
        - Edge: '~/.config/microsoft-edge' & 'Default'
        """
        # Pre-validation
        if not isinstance(profile_folder, str):
            raise errors.InvalidProfileError(
                "<ChromiumProfile> Invalid profile folder name: {} {}".format(
                    repr(profile_folder), type(profile_folder)
                )
            )
        super().__init__(directory, profile_folder)

    # Properties --------------------------------------------------------------------------
    @property
    def directory(self) -> str:
        """Access the main directory of the original profile `<str>`."""
        return self._directory

    @property
    def directory_temp(self) -> str:
        """Access the main directory of the temporary profile `<str>`."""
        return self._temp_directory

    @property
    def profile_folder(self) -> str:
        """Access the profile folder name of the original profile `<str>`."""
        return self._profile_folder

    @property
    def profile_folder_temp(self) -> str:
        """Access the profile folder name of the temporary profile `<str>`."""
        return self._temp_profile_folder


# Base Options ------------------------------------------------------------------------------------
class BaseOptions:
    """The base class for browser options.

    Each subclass of `Options` must implement the following:
    - `DEFAULT_CAPABILITIES`: `dict[str, Any]` Class attribute that
       contains the default capabilities of the target browser.

    - `construct()`: class instance method, which complete the final
       capabilities for the browser.
    """

    DEFAULT_CAPABILITIES: dict[str, Any] = None
    "the default capabilities of the target browser `dict[str, Any]`"
    VENDOR_PREFIX: str = None
    "the vendor prefix of the target browser `str`"

    def __init__(self) -> None:
        """The options for the browser.

        Each subclass of `Options` must implement the following:
        - `DEFAULT_CAPABILITIES`: `dict[str, Any]` Class attribute that
           contains the default capabilities of the target browser.

        - `construct()`: class instance method, which complete the final
           capabilities for the browser.
        """
        # Capabilities
        if (
            not isinstance(self.DEFAULT_CAPABILITIES, dict)
            or not self.DEFAULT_CAPABILITIES
        ):
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\nmust define its "
                "own class attribute: `DEFAULT_CAPABILITIES`. For "
                "more information, please refer to class docs."
            )
        self._capabilities: dict[str, Any] = deepcopy(self.DEFAULT_CAPABILITIES)
        self._capabilities["pageLoadStrategy"] = "normal"
        self._capabilities["timeouts"] = Timeouts().dict
        self.__caps_status: int = 0
        """Capabilities status:
        - 0: not changes have been made.
        - 1: changes have been made.
        """
        self.__caps: dict[str, Any] = {}
        "The final browser capabilities."
        # Session timeout
        self._session_timeout: int | float = 360
        # Arguments
        self._arguments: list[str] = []
        # Proxy
        self._proxy: Proxy | None = None
        # Options
        self._experimental_options: dict[str, Any] = {}
        self._preferences: dict[str, Any] = {}

    # Session timeout ---------------------------------------------------------------------
    @property
    def session_timeout(self) -> int | float:
        """Access the hard session timeout (seconds) for the browser `<int/float>`.

        This timeout is not a native timeout settings provided by
        the webdriver, but a hard timeout over the connection to
        the webdriver server. It is used to prevent the webdriver
        from frozen for unknown reasons and blocking the main thread
        from receiving any response (including timeout errors).

        For example, in some `rare` cases, the webdriver might be stuck
        when loading a webpage (sometimes due to the network issues,
        sometime due to conflicting actions from the pop-up alerts, etc).
        Even with a properly configured 'pageLoad' timeout, the webdriver
        might still not yeild any responses. In this case, this hard
        session timeout will be triggered and raise a `SessionTimeoutError`
        error. If user does not intercepet this error, the webdriver will
        be terminated and the session will be closed properly (including
        the browser process).

        The `SessionTimeoutError` exception is a subclass of `TimeoutError`
        and `AseleniumTimeout`, but different from `WebDriverTimeoutError`,
        which is raised when a native webdriver timeout (implicit, pageLoad,
        and script) is triggered.

        The session timeout defaults to `360` seconds, which is 1 min longer
        than the default `pageLoad` timeout. In most cases, this timeout will
        not be triggered but act as a last resort to prevent the webdriver
        from frozen. When settings this timeout, it is highly recommended be
        larger than all the native webdriver timeouts (implicit, pageLoad,
        and script).
        """
        return self._session_timeout

    @session_timeout.setter
    def session_timeout(self, value: int | float) -> None:
        if not isinstance(value, (int, float)):
            raise errors.InvalidOptionsError(
                "<{}>\nInvalid session_timeout ({} {}), must be a postive integer "
                "or float.".format(self.__class__.__name__, repr(value), type(value))
            )
        if value <= 0:
            raise errors.InvalidOptionsError(
                "<{}>\nInvalid session_timeout ({}), must be "
                "greater than `0`.".format(self.__class__.__name__, value)
            )
        self._session_timeout = value

    # Caps: basic -------------------------------------------------------------------------
    @property
    def capabilities(self) -> dict[str, Any]:
        """Access the final browser capabilities `<dict[str, Any]>`."""
        if not self.__caps or self.__caps_status == 1:
            self.__caps = deepcopy(self.construct())
            self.__caps_status = 0
        return self.__caps

    def construct(self) -> dict[str, Any]:
        """Construct the final capabilities of the browser.
        Must be implemented in subclass.
        """
        raise NotImplementedError(
            "<{}> Class instance method `construct()` has not been "
            "implemented in subclass.".format(self.__class__.__name__)
        )

    def get_capability(self, name: str) -> Any:
        """Get a capability of the browser.

        :param name: `<str>` The name of the capability.
        :raises `OptionsNotSetError`: If the capability is not set.
        :return `<Any>` The value of the capability.
        """
        try:
            return self._capabilities[name]
        except KeyError as err:
            raise errors.OptionsNotSetError(
                "<{}>\nCapability {} has not been set.".format(
                    self.__class__.__name__, repr(name)
                )
            ) from err

    def set_capability(self, name: str, value: Any) -> None:
        """Set a capability of the browser.

        :param name: `<str>` The name of the capability.
        :param value: `<Any>` The value of the capability.
        """
        self._capabilities[name] = value
        self._caps_changed()

    def rem_capability(self, name: str) -> None:
        """Remove a capability of the browser.

        :param name: `<str>` The name of the capability.
        """
        try:
            self._capabilities.pop(name)
            self._caps_changed()
        except KeyError:
            pass

    def _caps_changed(self) -> None:
        """Switch the capabilities status to `changed`, which will
        trigger a re-construction of the browser capabilites.
        """
        self.__caps_status = 1

    # Caps: browser name ------------------------------------------------------------------
    @property
    def browser_name(self) -> str:
        """Access the name of the browser agent `<str>`."""
        try:
            return self._capabilities["browserName"]
        except KeyError as err:
            raise errors.InvalidOptionsError(
                "<{}>\nDefault 'browserName' is not defined in "
                "class attribute `DEFAULT_CAPABILITIES`: {}".format(
                    self.__class__.__name__, self.DEFAULT_CAPABILITIES
                )
            ) from err

    # Caps: browser version ---------------------------------------------------------------
    @property
    def browser_version(self) -> Version | None:
        """Access the version of the browser `<Version/None>`."""
        return self._capabilities.get("browserVersion")

    @browser_version.setter
    def browser_version(self, value: Version | None) -> None:
        self._set_browser_version(value)

    def _set_browser_version(self, value: Version | None) -> None:
        # Same browser version
        if value == self.browser_version:
            return None

        # Remove browser version
        if value is None:
            self.rem_capability("browserVersion")
            return None

        # Set browser version
        if not isinstance(value, Version):
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\n`browser_version` must be type of `<Version>`."
            )
        self.set_capability("browserVersion", value.patch)

    # Options: binary location ------------------------------------------------------------
    @property
    def browser_location(self) -> str | None:
        """Access the location of the Brwoser binary `<str>`."""
        return self._experimental_options.get("binary")

    @browser_location.setter
    def browser_location(self, value: str | None) -> None:
        # Same binary location
        if value == self.browser_location:
            return None  # exit

        # Remove binary location
        if value is None:
            self.rem_experimental_option("binary")
            return None  # exit

        # Set binary location
        try:
            value = validate_file(value)
        except Exception as err:
            raise errors.InvalidOptionsError(
                "<{}>\nOptions 'browser_location' error: {}".format(
                    self.__class__.__name__, err
                )
            ) from err
        self.add_experimental_options(binary=value)

    # Caps: platform name -----------------------------------------------------------------
    @property
    def platform_name(self) -> str | None:
        """Access the name of the platform `<str>`.

        e.g. "windows", "mac", "linux".
        """
        return self._capabilities.get("platformName")

    @platform_name.setter
    def platform_name(self, value: str | None) -> None:
        # Remove platform name
        if value is None:
            self.rem_capability("platformName")
            return None  # exit

        # Set platform name
        if not isinstance(value, str):
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\n`platform_name` must be type of `<str>`."
            )
        self.set_capability("platformName", value)

    # Caps: accept insecure certs ---------------------------------------------------------
    @property
    def accept_insecure_certs(self) -> bool:
        """Access whether untrusted and self-signed TLS certificates
        are implicitly trusted on navigation. Defaults to `False <bool>`.
        """
        return self._capabilities.get("acceptInsecureCerts", False)

    @accept_insecure_certs.setter
    def accept_insecure_certs(self, value: bool) -> None:
        # Set acceptInsecureCerts to False (remove cap)
        if not value:
            self.rem_capability("acceptInsecureCerts")
        # Set acceptInsecureCerts to True (add cap)
        else:
            self.set_capability("acceptInsecureCerts", True)

    # Caps: page load strategy ------------------------------------------------------------
    @property
    def page_load_strategy(self) -> str:
        """The strategy to use when waiting for the page load
        event to fire. Defaults to `'normal' <str>`.

        Available options:
        - `'normal'`: Waits for all resources to be downloaded.
        - `'eager'`:  Waits for DOM access to be ready, other resources like images may still be loading.
        - `'none'`:   Does not wait for any events, not blocking browser at all.
        """
        return self._capabilities["pageLoadStrategy"]

    @page_load_strategy.setter
    def page_load_strategy(self, value: str | None) -> None:
        # Reset to default
        if value is None:
            self.set_capability("pageLoadStrategy", "normal")
            return None  # exit

        # Set pageLoadStrategy
        if value not in Constraint.PAGE_LOAD_STRATEGIES:
            raise errors.InvalidOptionsError(
                "<{}>\n`page_load_stragety` {} is not valid, "
                "available options: {}".format(
                    self.__class__.__name__,
                    repr(value),
                    sorted(Constraint.PAGE_LOAD_STRATEGIES),
                )
            )
        self.set_capability("pageLoadStrategy", value)

    # Caps: proxy -------------------------------------------------------------------------
    @property
    def proxy(self) -> Proxy | None:
        """Access browser proxy configurations `<Proxy>`."""
        return self._proxy

    @proxy.setter
    def proxy(self, value: Proxy | None) -> None:
        # Remove proxy
        if value is None:
            self.rem_capability("proxy")
            self._proxy = None
            return None  # exit

        # Set proxy
        if not isinstance(value, Proxy):
            raise errors.InvalidProxyError(
                f"<{self.__class__.__name__}>\n`proxy` "
                "must be an instance of `<class 'Proxy'>`."
            )
        self.set_capability("proxy", value.to_capabilities())
        self._proxy = value

    # # Caps: window rect -------------------------------------------------------------------
    # @property
    # def set_window_rect(self) -> bool:
    #     """Access whether the browser supports all of the resizing
    #     and repositioning commands. Defaults to `False <bool>`.
    #     """
    #     return self._capabilities.get("setWindowRect", False)

    # @set_window_rect.setter
    # def set_window_rect(self, value: bool) -> None:
    #     # Set setWindowRect to False (remove cap)
    #     if not value:
    #         self.rem_capability("setWindowRect")
    #     # Set setWindowRect to True (add cap)
    #     else:
    #         self.set_capability("setWindowRect", True)

    # Caps: timeouts ----------------------------------------------------------------------
    @property
    def timeouts(self) -> Timeouts:
        """Access the timeouts parameters of the browser `<Timeouts>`.

        - implicit: Total seconds all acquired sessions will wait when
        searching for an element if it is not immediately present.

        - pageLoad: Total seconds all acquired sessions will wait for a
        page load to complete before returning an error.

        - script: Total seconds all acquired sessions will wait for an
        asynchronous script to finish execution before returning an error.

        ### Example:
        >>> timeouts = options.timeouts
            # <Timeouts (implicity=0, pageLoad=300000, script=30000, unit='ms')>
        """
        return Timeouts(**self._capabilities["timeouts"], unit="ms")

    def set_timeouts(
        self,
        implicit: int | float | None = None,
        pageLoad: int | float | None = None,
        script: int | float | None = None,
    ) -> Timeouts:
        """Set the default timeouts for the sessions. Each session can
        override this default value by calling `session.set_timeouts()`
        method.

        ### Notice
        All of the timeout values should be in `SECONDS` instead of milliseconds
        (as the webdriver protocol requires). The values will be converted to
        milliseconds automatically.

        :param implicit: `<int/float/None>` Total `seconds` the current session
        should wait when searching for an element if not immediately present.
        If `None (default)`, keep the current implicit timeout.

        :param pageLoad: `<int/float/None>` Total `seconds` the current session
        should wait for a page load to complete before returning an error. if
        `None (default)`, keep the current pageLoad timeout.

        :param script: `<int/float/None>` Total `seconds` the current session
        should wait for an asynchronous script to finish execution before
        returning an error. if `None (default)`, keep the current script timeout.

        :return `<Timeouts>`: The timeouts after update.

        ### Example:
        >>> timeouts = options.set_timeouts(implicit=0.1, pageLoad=30, script=3)
            # <Timeouts (implicity=100, pageLoad=30000, script=3000, unit='ms')>
        """
        # Set timeouts
        timeouts = self.timeouts
        if implicit is not None:
            timeouts.implicit = implicit
        if pageLoad is not None:
            timeouts.pageLoad = pageLoad
        if script is not None:
            timeouts.script = script
        self.set_capability("timeouts", timeouts.dict)
        # Return timeouts
        return self.timeouts

    # Caps: strict file interactability ---------------------------------------------------
    @property
    def strict_file_interactability(self) -> bool:
        """Access whether browser is strict about file
        interactability. Defaults to `False <bool>`.
        """
        return self._capabilities.get("strictFileInteractability", False)

    @strict_file_interactability.setter
    def strict_file_interactability(self, value: bool) -> None:
        # Set strictFileInteractability to False (remove cap)
        if not value:
            self.rem_capability("strictFileInteractability")
        # Set strictFileInteractability to True (add cap)
        else:
            self.set_capability("strictFileInteractability", True)

    # Caps: prompt behavior ---------------------------------------------------------------
    @property
    def unhandled_prompt_behavior(self) -> str:
        """Access what action the browser must take when a user prompt
        is encountered. Defaults to `'dismiss and notify' <str>`.

        Available options:
        - `'dismiss'`: All simple dialogs encountered should be dismissed.

        - `'dismiss and notify'`: All simple dialogs encountered should be
            dismissed, and notify that the dialog was handled.

        - `'accept'`: All simple dialogs encountered should be accepted.

        - `'accept and notify'`: All simple dialogs encountered should be
            accepted, and notify that the dialog was handled.

        - `'ignore'`: All simple dialogs encountered should be left to the
            user to handle.
        """
        return self._capabilities.get("unhandledPromptBehavior", "dismiss and notify")

    @unhandled_prompt_behavior.setter
    def unhandled_prompt_behavior(self, value: str) -> None:
        if value not in Constraint.UNHANDLED_PROMPT_BEHAVIORS:
            raise errors.InvalidOptionsError(
                "<{}>\n`unhandled_prompt_behavior` {} is not valid, "
                "available options: {}".format(
                    self.__class__.__name__,
                    repr(value),
                    sorted(Constraint.UNHANDLED_PROMPT_BEHAVIORS),
                )
            )
        self.set_capability("unhandledPromptBehavior", value)

    # Options: experimental options -------------------------------------------------------
    @property
    def experimental_options(self) -> dict[str, Any]:
        """Access the experimental options of the browser `<dict>`."""
        return deepcopy(self._experimental_options)

    def add_experimental_options(self, **options: Any) -> None:
        """Add experimental options of the browser.

        :param options [Keywords]: `<Any>` The experimental options to add.

        ### Example:
        >>> options.add_experimental_options(
                excludeSwitches=["enable-automation"],
                useAutomationExtension=False,
                ...
            )
        """
        # Add options
        self._experimental_options |= options
        self._caps_changed()

    def rem_experimental_option(self, name: str) -> None:
        """Remove an experimental option of the browser.

        :param name: `<str>` The name of the experimental option.

        ### Example:
        >>> options.rem_experimental_options("excludeSwitches")
        """
        try:
            self._experimental_options.pop(name)
            self._caps_changed()
        except KeyError:
            pass

    def get_experimental_option(self, name: str) -> Any:
        """Get an experimental option of the browser.

        :param name: `<str>` The name of the experimental option.
        :raises `OptionsNotSetError`: If the experimental option is not set.
        :return `<Any>` The value of the experimental option.
        """
        try:
            return self._experimental_options[name]
        except KeyError as err:
            raise errors.OptionsNotSetError(
                "<{}>\nExperimental option {} has not been set.".format(
                    self.__class__.__name__, repr(name)
                )
            ) from err

    # Caps: arguments ---------------------------------------------------------------------
    @property
    def arguments(self) -> list[str]:
        """Access specified browser arguments `<list>`."""
        return self._arguments.copy()

    def add_arguments(self, *args: str) -> None:
        """Add arguments to browser capabilites.

        :param args: `<str>` The arguments to add.

        ### Example:
        >>> options.add_arguments(
                "--headless",
                "--disable-gpu",
                ...
            )
        """
        # Add arguments
        added = False
        for arg in args:
            if not isinstance(arg, str) or not arg:
                raise errors.InvalidOptionsError(
                    "<{}>\nSpecifed 'argument' is not valid: {} {}.".format(
                        self.__class__.__name__, type(arg), repr(arg)
                    )
                )
            if arg not in self._arguments:
                self._arguments.append(arg)
                added = True

        # Update caps status
        if added:
            self._caps_changed()

    def reset_arguments(self) -> None:
        """Reset browser arguments to default (no arguments)."""
        if self._arguments:
            self._arguments.clear()
            self._caps_changed()

    # Options: preferences ----------------------------------------------------------------
    @property
    def preferences(self) -> dict[str, Any]:
        """Access the preferences of the browser `<dict[str, Any]>`."""
        return deepcopy(self._preferences)

    def set_preferences(self, **prefs: Any) -> None:
        """Set preferences of the browser.

        :param prefs [Keywords]: `<Any>` The preferences to set.

        ### Example:
        >>> options.set_preferences(
                **{
                "download.default_directory": "/path/to/download/directory",
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True
            }
        )
        """
        # Set preferences
        self._preferences |= prefs
        self._caps_changed()

    def get_preference(self, name: str) -> Any:
        """Get a preference value of the browser.

        :param name: `<str>` The name of the preference.
        :raises `OptionsNotSetError`: If the preference is not set.
        :return `<Any>` The value of the preference.

        ### Example:
        >>> options.get_preference("media.navigator.permission.disabled")
            # False
        """
        try:
            return self._preferences[name]
        except KeyError as err:
            raise errors.OptionsNotSetError(
                "<{}>\nPreference {} has not been set.".format(
                    self.__class__.__name__, repr(name)
                )
            ) from err

    def rem_preference(self, name: str) -> None:
        """Remove a preference of the browser.

        :param name: `<str>` The name of the preference.

        ### Example:
        >>> options.rem_preference("media.navigator.permission.disabled")
        """
        # Remove preference
        try:
            self._preferences.pop(name)
            self._caps_changed()
        except KeyError:
            pass

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (capabilities=%s)>" % (
            self.__class__.__name__,
            prettify_dict(self.capabilities),
        )

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: Any) -> bool:
        if isinstance(__o, BaseOptions):
            return self.capabilities == __o.capabilities
        else:
            return False

    def __del__(self):
        self._capabilities = None
        self.__caps = None
        self._arguments = None
        self._proxy = None


# Chromium Base Options ---------------------------------------------------------------------------
class ChromiumBaseOptions(BaseOptions):
    """Base class for Chromium based browser options.

    Each subclass of `ChromiumOptions` must implement the following:
    - `DEFAULT_CAPABILITIES`: `dict[str, Any]` Class attribute that
       contains the default capabilities of the target browser.

    - `VENDOR_PREFIX`: `str` Class attribute that corresponds to the
       unique vendor prefix for the target browser. e.g. `moz`, `goog`.

    - `KEY`: `str` Class attribute that corresponds to the unique
       option key for the chromium browser. e.g. `goog:chromeOptions`.

    - `construct()`: class instance method, which complete the final
       capabilities for the browser.
    """

    KEY: str = None
    "The unique option key for the chromium browser `str`"

    def __init__(self) -> None:
        """The options for the browser.

        Each subclass of `ChromiumOptions` must implement the following:
        - `DEFAULT_CAPABILITIES`: `dict[str, Any]` Class attribute that
           contains the default capabilities of the target browser.

        - `VENDOR_PREFIX`: `str` Class attribute that corresponds to the
           unique vendor prefix for the target browser. e.g. `moz`, `goog`.

        - `KEY`: `str` Class attribute that corresponds to the unique
           option key for the chromium browser. e.g. `goog:chromeOptions`.

        - `construct()`: class instance method, which complete the final
           capabilities for the browser.
        """
        super().__init__()
        # Vendor Prefix
        if not isinstance(self.VENDOR_PREFIX, str) or not self.VENDOR_PREFIX:
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\nmust define its "
                "own class attribute: `VENDOR_PREFIX`. For more "
                "information, please refer to class docs."
            )
        # Brwoser Key
        if not isinstance(self.KEY, str) or not self.KEY:
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\nmust define its "
                "own class attribute: `KEY`. For more information, "
                "please refer to class docs."
            )
        # Options
        self._profile: ChromiumProfile | None = None
        self._extensions: list[str] = []

    # Caps: basic -------------------------------------------------------------------------
    def construct(self) -> dict[str, Any]:
        """Construct the final capabilities for the browser."""
        # Base caps
        caps = deepcopy(self._capabilities)

        # Experimental Options
        options = self.experimental_options
        if self._preferences:
            options["prefs"] = self.preferences
        if self._arguments:
            options["args"] = self.arguments
        if self._extensions:
            options["extensions"] = self.extensions
        caps[self.KEY] = options

        # Return caps
        return caps

    # Caps: browser version ---------------------------------------------------------------
    @property
    def browser_version(self) -> ChromiumVersion | None:
        """Access the version of the browser `<ChromiumVersion/None>`."""
        return self._capabilities.get("browserVersion")

    @browser_version.setter
    def browser_version(self, value: ChromiumVersion | None) -> None:
        self._set_browser_version(value)

    # Options: debugger -------------------------------------------------------------------
    @property
    def debugger_address(self) -> str:
        """Access the address of the remote devtools for debugging `<str>`.

        ChromeDriver will try to connect to this devtools instance
        during an active wait. For example: `"hostname:port"`.
        """
        return self._experimental_options.get("debuggerAddress")

    @debugger_address.setter
    def debugger_address(self, value: str | None) -> None:
        # Remove debugger address
        if value is None:
            self.rem_experimental_option("debuggerAddress")
            return None  # exit

        # Set debugger address
        if not isinstance(value, str):
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\n'debugger_address' must be type of `<str>`."
            )
        self.add_experimental_options(debuggerAddress=value)

    # Options: profile --------------------------------------------------------------------
    @property
    def profile(self) -> ChromiumProfile | None:
        """Access the profile of the browser `<ChromiumProfile>`.
        Returns `None` if profile is not configured.

        ### Notice
        - Please use `set_profile()` method to configure the profile.
        """
        return self._profile

    def set_profile(self, directory: str, profile: str) -> ChromiumProfile:
        """Set the user profile for the Chromium based browser.
        Such as: Edge, Chrome, Chromium, etc.

        :param directory: `<st>` The directory of the user profile.
        :param profile_folder: `<str>` The name of the profile folder inside of the 'directory'.
        :return `<ChromiumProfile>`: The profile instance.

        ### Explaination
        - When setting the profile through this method, a cloned temporary 
          profile will be created based on the given profile 'directory'. 
          The automated session will use the temporary profile leaving the
          original profile untouched. When the driver is no longer used by
          the program, the temporary profile will be deleted automatically.

        ### MacOS Default Profile Location:
        - Chrome: '~/Library/Application Support/Google/Chrome' & 'Default'
        - Chromium: '~/Library/Application Support/Chromium' & 'Default'
        - Edge: '~/Library/Application Support/Microsoft Edge' & 'Default'

        ### Windows Default Profile Location:
        - Chrome: 'C:\\Users\\<username>\\AppData\\Local\\Google\\Chrome\\User Data' & 'Default'
        - Chromium: 'C:\\Users\\<username>\\AppData\\Local\\Chromium\\User Data' & 'Default'
        - Edge: 'C:\\Users\\<username>\\AppData\\Local\\Microsoft\\Edge\\User Data' & 'Default'

        ### Linux Default Profile Location:
        - Chrome: '~/.config/google-chrome' & 'Default'
        - Chromium: '~/.config/chromium' & 'Default'
        - Edge: '~/.config/microsoft-edge' & 'Default'
        """
        # Create profile
        value = ChromiumProfile(directory, profile)
        # Set new profile
        self._remove_profile_arguments()
        self.add_arguments(
            "--user-data-dir=%s" % value.directory_temp,
            "--profile-directory=%s" % value.profile_folder_temp,
        )
        self._profile = value
        self._caps_changed()
        return value

    def rem_profile(self) -> None:
        """Remove the previously configured profile of the browser.

        ### Example:
        >>> # . set a new profile
            options.set_profile(directory, profile)

        >>> # . remove the profile
            options.rem_profile()
        """
        self._remove_profile_arguments()
        self._profile = None
        self._caps_changed()

    def _remove_profile_arguments(self) -> None:
        """(Internal) Remove previously setted profile arguments."""
        self._arguments = [
            arg
            for arg in self._arguments
            if not arg.startswith("--user-data-dir=")
            and not arg.startswith("--profile-directory=")
        ]

    # Options: extensions -----------------------------------------------------------------
    @property
    def extensions(self) -> list[str]:
        """Access the extensions for the browser `<list[str]>`.

        Each item in the list corresponds to the encoded base64
        value of the extension file.
        """
        return self._extensions.copy()

    def add_extensions(self, *paths: str) -> None:
        """Add extensions to the browser (through local file).

        :param paths: `<str>` The paths to the extension files (\\*.crx).

        ### Example:
        >>> options.add_extensions(
                "/path/to/extension1.crx",
                "/path/to/extension2.crx",
                ...
            )
        """
        # Add extionsions
        added = False
        for path in paths:
            # . validate ext path
            try:
                path = validate_file(path)
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nExtension 'path' error: {}".format(
                        self.__class__.__name__, err
                    )
                ) from err
            # . load ext data
            try:
                with open(path, "rb") as f:
                    data = b64encode(f.read()).decode("utf-8")
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nFailed to encode extension at: {}\n"
                    "Error: {}".format(self.__class__.__name__, repr(path), err)
                ) from err
            # . add ext data
            if data not in self._extensions:
                self._extensions.append(data)
                added = True

        # Update caps status
        if added:
            self._caps_changed()

    def add_extensions_base64(self, *extensions: str | bytes) -> None:
        """Add extensions to the browser (through encoded Base64 data).
        (For extensions that have already been encoded into Base64 `<str/bytes>`.)

        :param extensions: `<str/bytes>` The Base64 encoded extension data.
        """
        # Add extionsions
        added = False
        for ext in extensions:
            # . validate ext data
            if isinstance(ext, bytes):
                ext = ext.decode("utf-8")
            elif not isinstance(ext, str):
                raise errors.InvalidExtensionError(
                    "<{}>\nExtension data is not valid: {} {}".format(
                        self.__class__.__name__, type(ext), repr(ext)
                    )
                )
            # . add ext data
            if ext and ext not in self._extensions:
                self._extensions.append(ext)
                added = True

        # Update caps status
        if added:
            self._caps_changed()
