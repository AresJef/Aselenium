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

"""Validated W3C capabilities, proxy settings, timeouts, and profile clones."""

from __future__ import annotations

from base64 import b64encode
from copy import deepcopy
from math import isfinite
from pathlib import Path, PurePosixPath, PureWindowsPath
from platform import system
from shutil import copytree, ignore_patterns, rmtree
from tempfile import mkdtemp
from typing import (
    Any,
    Literal,
    TypeVar,
)

from aselenium import errors
from aselenium._paths import PathInput, _regular_tree_files, directory_path, file_path
from aselenium.manager._filesystem import checked_path, filesystem_operation
from aselenium.manager.version import Version
from aselenium.settings import Constraint, DefaultTimeouts

O = TypeVar("O", bound="BaseOptions")

__all__ = ["Proxy", "Timeouts", "ChromiumProfile"]

# Constants ---------------------------------------------------------------------------------------
_WINDOWS_PROFILE_DEVICE_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *("COM" + suffix for suffix in "123456789¹²³"),
        *("LPT" + suffix for suffix in "123456789¹²³"),
    }
)
_WINDOWS_PROFILE_RESERVED_CHARACTERS = frozenset(
    {chr(codepoint) for codepoint in range(32)} | set('"*:<>?|/\\')
)


def _validate_chromium_profile_folder(profile_folder: object) -> str:
    """Validate one portable Chromium profile-directory basename.

    Args:
        profile_folder: Candidate child-directory name supplied by a public
            Chromium options API.

    Returns:
        The unchanged profile-folder name after validation.

    Raises:
        errors.InvalidProfileError: The value is not a nonempty string or can
            be interpreted as anything other than one portable child-directory
            name.
    """
    if not isinstance(profile_folder, str) or not profile_folder:
        raise errors.InvalidProfileError(
            "<ChromiumProfile> 'profile_folder' must be a nonempty portable "
            "directory basename: {} {}.".format(
                repr(profile_folder), type(profile_folder)
            )
        )

    posix_path = PurePosixPath(profile_folder)
    windows_path = PureWindowsPath(profile_folder)
    device_stem = profile_folder.partition(".")[0].rstrip(" ").upper()
    if (
        profile_folder in {".", ".."}
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.parts != (profile_folder,)
        or windows_path.parts != (profile_folder,)
        or bool(_WINDOWS_PROFILE_RESERVED_CHARACTERS.intersection(profile_folder))
        or profile_folder.endswith((" ", "."))
        or device_stem in _WINDOWS_PROFILE_DEVICE_NAMES
    ):
        raise errors.InvalidProfileError(
            "<ChromiumProfile> 'profile_folder' must be a nonempty portable "
            "directory basename without path syntax or reserved filesystem "
            "semantics: {} {}.".format(repr(profile_folder), type(profile_folder))
        )
    return profile_folder


# Option Objects ----------------------------------------------------------------------------------
class Proxy:
    """Configure browser traffic independently of driver-provisioning requests.

    Use keyword arguments with explicit URL schemes. A manual setting takes
    precedence over PAC or autodetection when multiple modes are supplied.
    ``to_capabilities()`` produces the WebDriver proxy capability; the browser
    determines whether a particular authentication scheme is supported.
    """

    def __init__(
        self,
        *,
        auto_detect: bool = False,
        pac_url: str | None = None,
        http_proxy: str | None = None,
        https_proxy: str | None = None,
        socks_proxy: str | None = None,
        socks_username: str | None = None,
        socks_password: str | None = None,
        no_proxy: str | list[str] | None = None,
    ) -> None:
        """Initialize browser proxy settings without opening a connection.

        With no settings, use a direct connection on Windows and the system
        proxy configuration elsewhere. Credentials are redacted from repr(),
        but remain present in the capability data sent to the driver.

        Args:
            auto_detect: If `True`, the proxy type will be
                set to `'AUTODETECT'`. This is often used when the system has its
                own proxy settings that should be used. Defaults to `False`.
            pac_url: The URL to the PAC (Proxy Auto-Configuration)
                file. If `pac_url` is provided, the proxy type will be set to `'PAC'`.
                This is often used when the network environment has a configuration
                script to handle traffic routing. Defaults to `None`.
            http_proxy: HTTP proxy URL, or ``None`` for no HTTP route.
            https_proxy: HTTPS proxy URL, or ``None`` for no HTTPS route.
            socks_proxy: SOCKS4 or SOCKS5 proxy URL, or ``None`` for no SOCKS route.
            socks_username: The username to use for SOCKS authentication. Defaults to `None`.
            socks_password: The password to use for SOCKS authentication. Defaults to `None`.
            no_proxy: The addresses that bypass the proxy configuration. Each address is
                either a domain name, a hostname, or an IP address. Defaults to `None`.

        Raises:
            errors.InvalidProxyError: A proxy value has an unsupported type or scheme.

        Example:
            >>> from aselenium import Proxy
            >>> proxy = Proxy(http_proxy="http://localhost:8080", no_proxy=["localhost"])
            >>> proxy.to_capabilities()
            {'proxyType': 'manual', 'httpProxy': 'localhost:8080', 'noProxy': ['localhost']}
        """
        self.__caps: dict[str, Any] = {}
        self.__status: int = 1
        self._auto_detect = False
        self._pac_url: str | None = None
        self._http_proxy: str | None = None
        self._https_proxy: str | None = None
        self._socks_proxy: str | None = None
        self._socks_version: int | None = None
        self._socks_username: str | None = None
        self._socks_password: str | None = None
        self._no_proxy: str | None = None
        self._proxy_type: str = "DEFAULT"
        self.auto_detect = auto_detect
        self.pac_url = pac_url
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.socks_proxy = socks_proxy
        self.socks_username = socks_username
        self.socks_password = socks_password
        self.no_proxy = no_proxy

    def _refresh_proxy_type(self) -> None:
        """Derive the effective proxy mode from all retained configuration fields."""
        manual = any(
            value
            for value in (
                self._http_proxy,
                self._https_proxy,
                self._socks_proxy,
                self._socks_username,
                self._socks_password,
                self._no_proxy,
            )
        )
        if manual:
            self._proxy_type = "MANUAL"
        elif self._pac_url is not None:
            self._proxy_type = "PAC"
        elif self._auto_detect:
            self._proxy_type = "AUTODETECT"
        else:
            self._proxy_type = "DEFAULT"
        self.__status = 1

    # Proxy: type ----------------------------------------------------------------------
    @property
    def proxy_type(self) -> str:
        """Return the type of the proxy.

        - `'DEFAULT'`: If the platform is windows, means direct connection
            `{"ff_value": 0, "string": "DIRECT"}`. On other platforms, this
            means use the system proxy settings `{"ff_value": 5, "string": "SYSTEM"}`.

        - `'AUTODETECT'`: Proxy auto detection (presumably with WPAD)
            `{"ff_value": 4, "string": "AUTODETECT"}`.

        - `'MANUAL'`: Manual proxy settings (e.g., for httpProxy)
            `{"ff_value": 1, "string": "MANUAL"}`.

        - `'PAC'`: Proxy autoconfiguration from URL.
            `{"ff_value": 2, "string": "PAC"}`.

        Notice
        The 'proxy_type' should not be adjusted manually. Changing
        other proxy properties will change this 'proxy_type' to
        the corresponding value automatically.

        Returns:
            The type of the proxy.
        """
        if self._proxy_type == "DEFAULT":
            return "DIRECT" if system() == "Windows" else "SYSTEM"
        else:
            return self._proxy_type

    # Config: auto detect --------------------------------------------------------------
    @property
    def auto_detect(self) -> bool:
        """Return whether proxy autodetection remains enabled as a fallback.

        Returns:
            ``True`` when autodetection is configured. A retained manual route
            or PAC URL can take precedence in the effective proxy type.
        """
        return self._auto_detect

    @auto_detect.setter
    def auto_detect(self, value: bool) -> None:
        """Enable or disable proxy autodetection without clearing other modes.

        Args:
            value: Whether to retain autodetection as a fallback mode.

        Raises:
            errors.InvalidProxyError: ``value`` is not a bool.
        """
        if not isinstance(value, bool):
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `auto_detect`, must be type of `<'bool'>`.".format(
                    self.__class__.__name__
                )
            )
        self._auto_detect = value
        self._refresh_proxy_type()

    # Config: PAC ----------------------------------------------------------------------
    @property
    def pac_url(self) -> str | None:
        """Return the configured proxy auto-configuration URL.

        Returns:
            PAC URL, or ``None`` when no script is configured.
        """
        return self._pac_url

    @pac_url.setter
    def pac_url(self, value: str | None) -> None:
        """Set the pac url.

        Args:
            value: PAC URL, or ``None`` to remove the configured URL.
        """
        if not isinstance(value, str) and value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `pac_url`, must be type of `<'str'>` or `None`.".format(
                    self.__class__.__name__
                )
            )
        self._pac_url = value
        self._refresh_proxy_type()

    # Config: http ---------------------------------------------------------------------
    @property
    def http_proxy(self) -> str | None:
        """Return the normalized HTTP proxy authority.

        Returns:
            Proxy host and optional port without its URL scheme, or ``None``.
        """
        return self._http_proxy

    @http_proxy.setter
    def http_proxy(self, value: str | None) -> None:
        """Set the http proxy.

        Args:
            value: HTTP proxy URL, or ``None`` to disable this route.
        """
        if isinstance(value, str):
            if not value.startswith("http://") and not value.startswith("https://"):
                raise errors.InvalidProxyError(
                    "<{}>\n`http_proxy` must start with 'http://' or 'https://', "
                    "instead got: {}.".format(self.__class__.__name__, repr(value))
                )
            value = value.split("://", 1)[1]
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `http_proxy`, must be type of "
                "`<'str'>` or `None`.".format(self.__class__.__name__)
            )
        self._http_proxy = value
        self._refresh_proxy_type()

    # Config: ssl ----------------------------------------------------------------------
    @property
    def https_proxy(self) -> str | None:
        """Return the normalized HTTPS proxy authority.

        Returns:
            Proxy host and optional port without its URL scheme, or ``None``.
        """
        return self._https_proxy

    @https_proxy.setter
    def https_proxy(self, value: str | None) -> None:
        """Set the https proxy.

        Args:
            value: HTTPS proxy URL, or ``None`` to disable this route.
        """
        if isinstance(value, str):
            if not value.startswith("https://") and not value.startswith("http://"):
                raise errors.InvalidProxyError(
                    "<{}>\n`https_proxy` must start with 'https://' or 'http://', "
                    "instead got: {}.".format(self.__class__.__name__, repr(value))
                )
            value = value.split("://", 1)[1]
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `https_proxy`, must be type of "
                "`<'str'>` or `None`.".format(self.__class__.__name__)
            )
        self._https_proxy = value
        self._refresh_proxy_type()

    # Config: socks --------------------------------------------------------------------
    @property
    def socks_proxy(self) -> str | None:
        """Return the normalized SOCKS proxy authority.

        Returns:
            SOCKS host and optional port without its URL scheme, or ``None``.
        """
        return self._socks_proxy

    @socks_proxy.setter
    def socks_proxy(self, value: str | None) -> None:
        """Set the socks proxy.

        Args:
            value: SOCKS4 or SOCKS5 proxy URL, or ``None`` to clear SOCKS
                routing and credentials.
        """
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
        elif value is None:
            self._socks_version = None
            self._socks_username = None
            self._socks_password = None
        else:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `socks_proxy`, must be type of "
                "`<'str'>` or `None`.".format(self.__class__.__name__)
            )
        self._socks_proxy = value
        self._refresh_proxy_type()

    @property
    def socks_username(self) -> str | None:
        """Return the optional SOCKS authentication username.

        Returns:
            Configured username, or ``None``.
        """
        return self._socks_username

    @socks_username.setter
    def socks_username(self, value: str | None) -> None:
        """Set the socks username.

        Args:
            value: SOCKS username, or ``None`` to remove it.
        """
        if not isinstance(value, str) and value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `socks_username`, must be type of "
                "`<'str'>` or `None`.".format(self.__class__.__name__)
            )
        self._socks_username = value
        self._refresh_proxy_type()

    @property
    def socks_password(self) -> str | None:
        """Return the optional SOCKS authentication password.

        Returns:
            Configured password, or ``None``.
        """
        return self._socks_password

    @socks_password.setter
    def socks_password(self, value: str | None) -> None:
        """Set the socks password.

        Args:
            value: SOCKS password, or ``None`` to remove it.
        """
        if not isinstance(value, str) and value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `socks_password`, must be type of "
                "`<'str'>` or `None`.".format(self.__class__.__name__)
            )
        self._socks_password = value
        self._refresh_proxy_type()

    # Config: no proxy -----------------------------------------------------------------
    @property
    def no_proxy(self) -> str | None:
        """Return the comma-separated proxy-bypass hosts.

        Returns:
            Normalized comma-separated bypass list, or ``None``.
        """
        return self._no_proxy

    @no_proxy.setter
    def no_proxy(self, value: str | list[str] | None) -> None:
        """Set the no proxy.

        Args:
            value: Comma-separated hosts, a list of hosts, or ``None`` to clear
                the bypass list.
        """
        if isinstance(value, list):
            try:
                value = ",".join(value)
            except Exception as err:
                raise errors.InvalidProxyError(
                    "<{}>\nInvalid `no_proxy`, list of addresses items must "
                    "all be type of `<'str'>`.".format(self.__class__.__name__)
                ) from err
        elif isinstance(value, str):
            pass
        elif value is not None:
            raise errors.InvalidProxyError(
                "<{}>\nInvalid `no_proxy`, must be type of `<'str'>`, "
                "`<list[str>]>` or `None`.".format(self.__class__.__name__)
            )
        self._no_proxy = value
        self._refresh_proxy_type()

    # Capabilities ---------------------------------------------------------------------
    def to_capabilities(self) -> dict[str, Any]:
        """Create the capabilities representation of the proxy configuration.

        Returns:
            A defensive copy of the W3C proxy capability payload.
        """
        # Already converted
        if self.__caps and self.__status == 0:
            return deepcopy(self.__caps)

        # Convert to capabilities
        caps: dict[str, Any] = {"proxyType": self.proxy_type.lower()}

        # . DEFAULT
        if self._proxy_type == "DEFAULT":
            pass
        # . AUTODETECT
        elif self._proxy_type == "AUTODETECT":
            pass
        # . PAC
        elif self._proxy_type == "PAC":
            caps["proxyAutoconfigUrl"] = self._pac_url
        # . MANUAL
        else:
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
                caps["noProxy"] = [
                    address.strip()
                    for address in self._no_proxy.split(",")
                    if address.strip()
                ]

        # Set & return capabilities
        self.__caps = caps
        self.__status = 0
        return deepcopy(self.__caps)

    # Special methods ------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (config=%s)>" % (
            self.__class__.__name__,
            "<redacted>",
        )


class Timeouts:
    """Store WebDriver timeouts in milliseconds with seconds-based accessors.

    The constructor defaults to milliseconds. Public option/session timeout
    setters use seconds, so pass ``unit="s"`` when constructing this object
    directly from seconds-based configuration. Encoded milliseconds must be
    between zero and the WebDriver maximum safe integer, 2**53 - 1.
    """

    def __init__(
        self,
        implicit: int | float | None = None,
        pageLoad: int | float | None = None,
        script: int | float | None = None,
        unit: Literal["s", "ms"] = "ms",
    ) -> None:
        """Store WebDriver timeout values as protocol milliseconds.

        Args:
            implicit: The time to wait when searching for
                an element if not immediately present. If `None`, set to default
                timeout value.
            pageLoad: The time to wait for a page load to
                complete. If `None`, set to default timeout value.
            script: The time to wait for an asynchronous
                script execution. If `None`, set to default timeout value.
            unit: The unit of the timeouts, accepts `s` or `ms`.
                Defaults to `'ms'`.

        Raises:
            InvalidOptionsError: If the unit is unsupported or a timeout cannot
                be represented within the protocol's safe millisecond range.

        Example:
            >>> from aselenium import Timeouts
            >>> Timeouts(implicit=0, pageLoad=20, script=5, unit="s").dict
            {'implicit': 0, 'pageLoad': 20000, 'script': 5000}
        """
        if not isinstance(unit, str) or unit not in ("s", "ms"):
            raise errors.InvalidOptionsError("Timeout unit must be 's' or 'ms'")
        self._implicit = DefaultTimeouts.IMPLICIT
        self._pageLoad = DefaultTimeouts.PAGE_LOAD
        self._script = DefaultTimeouts.SCRIPT
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
        """Return the timeouts in milliseconds as a dictionary.

        Returns:
            The timeouts in milliseconds as a dictionary.

        Example:
            >>> Timeouts().dict
            {'implicit': 0, 'pageLoad': 300000, 'script': 30000}
        """
        return {
            "implicit": self._implicit,
            "pageLoad": self._pageLoad,
            "script": self._script,
        }

    # Implicit timeout --------------------------------------------------------------------
    @property
    def implicit(self) -> float:
        """Return implicit timeout in seconds.

        Total seconds to wait when searching for an element
        if not immediately present.

        Returns:
            Implicit timeout in seconds.
        """
        return self._implicit / 1000

    @implicit.setter
    def implicit(self, value: int | float | None) -> None:
        # Value is None
        """Set the implicit.

        Args:
            value: Seconds to wait for element lookup, or ``None`` to keep the
                current value.
        """
        if value is None:
            if self._implicit is None:
                self._implicit = DefaultTimeouts.IMPLICIT
        # Set implicit
        else:
            self._implicit = self._validate_timeout(value, scale=1000)

    @property
    def implicit_ms(self) -> int:
        """Return implicit timeout in milliseconds.

        Total milliseconds to wait when searching for an
        element if not immediately present.

        Returns:
            Implicit timeout in milliseconds.
        """
        return self._implicit

    @implicit_ms.setter
    def implicit_ms(self, value: int | float | None) -> None:
        # Value is None
        """Set the implicit ms.

        Args:
            value: Milliseconds to wait for element lookup, or ``None`` to keep
                the current value.
        """
        if value is None:
            if self._implicit is None:
                self._implicit = DefaultTimeouts.IMPLICIT
        # Set implicit ms
        else:
            self._implicit = self._validate_timeout(value)

    # PageLoad timeout --------------------------------------------------------------------
    @property
    def pageLoad(self) -> float:
        """Return pageLoad timeout in seconds.

        Total seconds to wait for a page load to complete.

        Returns:
            Pageload timeout in seconds.
        """
        return self._pageLoad / 1000

    @pageLoad.setter
    def pageLoad(self, value: int | float | None) -> None:
        # Value is None
        """Set the pageLoad.

        Args:
            value: Page-load timeout in seconds, or ``None`` to keep the current
                value.
        """
        if value is None:
            if self._pageLoad is None:
                self._pageLoad = DefaultTimeouts.PAGE_LOAD
        # Set pageLoad
        else:
            self._pageLoad = self._validate_timeout(value, scale=1000)

    @property
    def pageLoad_ms(self) -> int:
        """Return pageLoad timeout in milliseconds.

        Total milliseconds to wait for a page load to complete.

        Returns:
            Pageload timeout in milliseconds.
        """
        return self._pageLoad

    @pageLoad_ms.setter
    def pageLoad_ms(self, value: int | float | None) -> None:
        # Value is None
        """Set the pageLoad ms.

        Args:
            value: Page-load timeout in milliseconds, or ``None`` to keep the
                current value.
        """
        if value is None:
            if self._pageLoad is None:
                self._pageLoad = DefaultTimeouts.PAGE_LOAD
        # Set pageLoad ms
        else:
            self._pageLoad = self._validate_timeout(value)

    # Script timeout ----------------------------------------------------------------------
    @property
    def script(self) -> float:
        """Return script timeout in seconds.

        Total seconds to wait for an asynchronous script execution.

        Returns:
            Script timeout in seconds.
        """
        return self._script / 1000

    @script.setter
    def script(self, value: int | float | None) -> None:
        # Value is None
        """Set the script.

        Args:
            value: Asynchronous-script timeout in seconds, or ``None`` to keep
                the current value.
        """
        if value is None:
            if self._script is None:
                self._script = DefaultTimeouts.SCRIPT
        # Set script
        else:
            self._script = self._validate_timeout(value, scale=1000)

    @property
    def script_ms(self) -> int:
        """Return script timeout in milliseconds.

        Total milliseconds to wait for an asynchronous script execution.

        Returns:
            Script timeout in milliseconds.
        """
        return self._script

    @script_ms.setter
    def script_ms(self, value: int | float | None) -> None:
        # Value is None
        """Set the script ms.

        Args:
            value: Asynchronous-script timeout in milliseconds, or ``None`` to
                keep the current value.
        """
        if value is None:
            if self._script is None:
                self._script = DefaultTimeouts.SCRIPT
        # Set script ms
        else:
            self._script = self._validate_timeout(value)

    # Utils -------------------------------------------------------------------------------
    def _validate_timeout(self, value: Any, *, scale: int = 1) -> int:
        """Convert a finite nonnegative timeout to safe integer milliseconds.

        Args:
            value: Numeric timeout value; bool is not accepted as a number.
            scale: Milliseconds per input unit, either 1 or 1000.

        Returns:
            Integer milliseconds, truncating a fractional millisecond as before.

        Raises:
            InvalidOptionsError: If the input or its converted value is outside
                the WebDriver range from zero through 2**53 - 1 milliseconds.
        """
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not isfinite(value))
        ):
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
        # Check before integer conversion: multiplying a finite float can overflow,
        # and isfinite() itself cannot convert arbitrarily large Python integers.
        milliseconds = value * scale
        if milliseconds > 2**53 - 1:
            raise errors.InvalidOptionsError(
                "Timeout exceeds the WebDriver maximum of 2**53 - 1 milliseconds"
            )
        return int(milliseconds)

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (implicit=%d, pageLoad=%d, script=%d, unit='ms')>" % (
            self.__class__.__name__,
            self._implicit,
            self._pageLoad,
            self._script,
        )

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        if isinstance(__o, Timeouts):
            return (
                self._implicit == __o._implicit
                and self._pageLoad == __o._pageLoad
                and self._script == __o._script
            )
        else:
            return False

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self) -> Timeouts:
        """Copy the timeouts object.

        Returns:
            An independent copy of this value object.
        """
        return Timeouts(self._implicit, self._pageLoad, self._script, unit="ms")


class Profile:
    """Represent the user profile for a browser."""

    def __init__(self, directory: PathInput, profile_folder: str | None = None) -> None:
        """Validate a source profile directory and create its owned clone.

        Explanation
        - When creating a `Profile` instance, a cloned temporary profile
          will be created based on the given profile 'directory'. The
          automated session will use this temporary profile leaving the
          original profile untouched. Call close() on the owning options
          after use to release its temporary profile deterministically.
          Garbage-collection cleanup is only a best-effort fallback.

        Args:
            directory: The directory of the user profile.
            profile_folder: The name of the profile folder inside of the 'directory'.
        """
        # Profile directory
        self._profile_folder: str | None = profile_folder
        self._profile_dir: Path | None = None
        self._temp_directory: Path | None = None
        self._owned_temp_directory: Path | None = None
        self._temp_profile_folder: str = "TEMP_PROFILE"
        self._temp_profile_dir: Path | None = None
        try:
            self._directory = directory_path(directory)
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
        """Create the temporary profile."""
        # Temporary profile already created
        if self._temp_directory is not None:
            return None  # exit

        # Determine profile directory
        if self._profile_folder is not None:
            try:
                self._profile_dir = self._directory / self._profile_folder
            except Exception as err:
                raise errors.InvalidProfileError(
                    "<{}> Invalid profile folder: {} {}.".format(
                        self.__class__.__name__,
                        repr(self._profile_folder),
                        type(self._profile_folder),
                    )
                ) from err
            if not self._profile_dir.is_dir():
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
            self._temp_directory = Path(mkdtemp(prefix="aselenium-")).resolve()
            self._owned_temp_directory = self._temp_directory
            self._temp_profile_dir = self._temp_directory / self._temp_profile_folder
            if self._profile_dir is None:
                raise errors.InvalidProfileError("Profile directory was not selected")
            _regular_tree_files(
                self._profile_dir,
                ignored_names={"parent.lock", "lock", ".parentlock"},
            )
            copytree(
                self._profile_dir,
                self._temp_profile_dir,
                ignore=ignore_patterns("parent.lock", "lock", ".parentlock"),
            )
            self._temp_profile_dir.chmod(0o755)
        except Exception as err:
            self._delete_temp_profile()
            raise errors.InvalidProfileError(
                "<{}> Failed to clone profile at: '{}'\nError:{}".format(
                    self.__class__.__name__, self._profile_dir, err
                )
            ) from err

    def _delete_temp_profile(self) -> None:
        """Delete the temporary profile."""
        # Temporary profile already deleted
        if self._temp_directory is None:
            return None  # exit

        # Delete temporary profile
        path = self._temp_directory
        if self._temp_directory != getattr(self, "_owned_temp_directory", None):
            raise errors.InvalidProfileError(
                "Refusing to remove an unowned temporary profile"
            )
        checked_path(path.parent, path)
        if path.exists():
            filesystem_operation(
                lambda: rmtree(checked_path(path.parent, path)),
                "Remove temporary browser profile",
            )
        self._temp_directory = None
        self._owned_temp_directory = None
        self._temp_profile_dir = None

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (profile_directory='%s', temp_directory='%s')>" % (
            self.__class__.__name__,
            self._profile_dir,
            self._temp_profile_dir,
        )

    def __hash__(self) -> int:
        """Return the identity hash of this owned profile clone.

        Returns:
            A stable identity hash for the clone's lifetime.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return self is __o

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def __del__(self) -> None:
        """Release references during finalization; explicit cleanup remains preferred."""
        try:
            if getattr(self, "_temp_directory", None) is not None:
                self._delete_temp_profile()
        except Exception:
            # Finalizers must never loop or hide an active exception.
            pass


class ChromiumProfile(Profile):
    """Represent the user profile for Chromium based browser. Such as: Edge, Chrome, Chromium, etc."""

    def __init__(self, directory: PathInput, profile_folder: str) -> None:
        r"""Clone one Chromium profile into an isolated temporary user-data root.

        Explanation
        - When creating a `Profile` instance, a cloned temporary profile
          will be created based on the given profile 'directory'. The
          automated session will use this temporary profile leaving the
          original profile untouched. Call close() on the owning options
          after use to release its temporary profile deterministically.
          Garbage-collection cleanup is only a best-effort fallback.

        macOS Default Profile Location:
        - Chrome: '~/Library/Application Support/Google/Chrome' & 'Default'
        - Chromium: '~/Library/Application Support/Chromium' & 'Default'
        - Edge: '~/Library/Application Support/Microsoft Edge' & 'Default'

        Windows Default Profile Location:
        - Chrome: 'C:\Users\<username>\AppData\Local\Google\Chrome\User Data' & 'Default'
        - Chromium: 'C:\Users\<username>\AppData\Local\Chromium\User Data' & 'Default'
        - Edge: 'C:\Users\<username>\AppData\Local\Microsoft\Edge\User Data' & 'Default'

        Linux Default Profile Location:
        - Chrome: '~/.config/google-chrome' & 'Default'
        - Chromium: '~/.config/chromium' & 'Default'
        - Edge: '~/.config/microsoft-edge' & 'Default'

        Args:
            directory: The directory of the user profile.
            profile_folder: Nonempty name of exactly one child directory inside
                `directory`, such as `Default` or `Profile 1`. Paths, `.` and
                `..`, separators, drive prefixes, control characters, colons
                or other Windows-reserved punctuation, trailing spaces or dots,
                and Windows device names are rejected.

        Raises:
            errors.InvalidProfileError: The directory is invalid or
                `profile_folder` is not a portable single-directory name.
        """
        validated_profile_folder = _validate_chromium_profile_folder(profile_folder)
        super().__init__(directory, validated_profile_folder)

    # Properties --------------------------------------------------------------------------
    @property
    def directory(self) -> Path:
        """Return the main directory of the original profile.

        Returns:
            Validated absolute user-data directory of the original profile.
        """
        return self._directory

    @property
    def directory_temp(self) -> Path | None:
        """Return the main directory of the temporary profile.

        Returns:
            Owned temporary user-data directory, or ``None`` after cleanup.
        """
        return self._temp_directory

    @property
    def profile_folder(self) -> str:
        """Return the profile folder name of the original profile.

        Returns:
            The profile folder name of the original profile.
        """
        assert self._profile_folder is not None
        return self._profile_folder

    @property
    def profile_folder_temp(self) -> str:
        """Return the profile folder name of the temporary profile.

        Returns:
            The profile folder name of the temporary profile.
        """
        return self._temp_profile_folder


# Base Options ------------------------------------------------------------------------------------
class BaseOptions:
    """Provide shared validation and state management for browser options.

    Concrete subclasses define nonempty ``DEFAULT_CAPABILITIES`` and implement
    ``construct()`` to return an independent W3C session-capability mapping.

    Attributes:
        DEFAULT_CAPABILITIES: Baseline W3C capabilities for the target browser.
        VENDOR_PREFIX: Vendor namespace prefix used by extension capabilities.
    """

    DEFAULT_CAPABILITIES: dict[str, Any] = {}
    VENDOR_PREFIX: str = ""
    _profile: Profile | None

    def snapshot(self: O) -> O:
        """Create an independent configuration snapshot, cloning temporary profiles when needed.

        Returns:
            An independent options object of the same concrete class.

        Example:
            >>> snapshot = driver.options.snapshot()
            >>> try:
            ...     snapshot.set_timeouts(implicit=0, pageLoad=20, script=5)
            ... finally:
            ...     snapshot.close()
        """
        result = type(self).__new__(type(self))
        result.__dict__ = deepcopy(
            {
                key: value
                for key, value in self.__dict__.items()
                if key not in {"_profile", "_pending_profile_cleanup"}
            }
        )
        result._profile = None
        result._pending_profile_cleanup = []
        profile = getattr(self, "_profile", None)
        if profile is not None:
            if isinstance(profile, ChromiumProfile):
                if profile._temp_directory is None:
                    raise errors.InvalidProfileError(
                        "Cannot snapshot a profile whose temporary clone is closed"
                    )
                set_profile = getattr(result, "set_profile")
                set_profile(profile._temp_directory, profile._temp_profile_folder)
            else:
                if profile._temp_profile_dir is None:
                    raise errors.InvalidProfileError(
                        "Cannot snapshot a profile whose temporary clone is closed"
                    )
                set_profile = getattr(result, "set_profile")
                set_profile(profile._temp_profile_dir)
        result._caps_changed()
        return result

    def close(self) -> None:
        """Release owned profile clones and invalidate profile capabilities.

        Original source profiles and independent snapshots are never removed.
        A failed removal retains ownership for a later close() retry. The options
        instance can be configured with a new profile after successful cleanup.

        Example:
            >>> try:
            ...     async with driver.acquire() as session:
            ...         await session.load("https://example.com")
            ... finally:
            ...     driver.options.close()
        """
        for pending in tuple(self._pending_profile_cleanup):
            pending._delete_temp_profile()
            self._pending_profile_cleanup.remove(pending)
        profile = getattr(self, "_profile", None)
        if profile is not None:
            profile._delete_temp_profile()
            self._profile = None
            self._caps_changed()

    def _replace_profile(self, profile: Profile) -> None:
        """Replace an owned clone without losing either resource on cleanup failure.

        Args:
            profile: Fully constructed replacement clone owned by this operation.

        Raises:
            Exception: If old-profile cleanup fails. The old configuration remains
                selected; a replacement that also fails cleanup is retained for retry.
        """
        try:
            self.close()
        except BaseException:
            try:
                profile._delete_temp_profile()
            except BaseException:
                self._pending_profile_cleanup.append(profile)
            raise
        self._profile = profile
        self._caps_changed()

    def __init__(self) -> None:
        """Initialize mutable configuration from concrete browser defaults.

        Raises:
            errors.InvalidOptionsError: The concrete class does not define a
                nonempty capability mapping.
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
        for capability_name, capability_value in self._capabilities.items():
            self._validate_standard_capability(capability_name, capability_value)
        self._capabilities["pageLoadStrategy"] = "normal"
        self._capabilities["timeouts"] = Timeouts().dict
        self.__caps_status: int = 0
        self.__caps: dict[str, Any] = {}
        # Session timeout
        self._session_timeout: int | float = 360
        # Arguments
        self._arguments: list[str] = []
        # Proxy
        self._proxy: Proxy | None = None
        # Options
        self._experimental_options: dict[str, Any] = {}
        self._preferences: dict[str, Any] = {}
        self._browser_location: Path | None = None
        self._profile = None
        self._pending_profile_cleanup: list[Profile] = []

    # Session timeout ---------------------------------------------------------------------
    @property
    def session_timeout(self) -> int | float:
        """Return the per-command transport deadline in seconds.

        This bounds one request to the driver, including its response, independently
        of the driver's implicit, page-load, and script timeouts. It does not limit
        the total lifetime of a session. A stalled command raises SessionTimeoutError.

        An exception escaping ``async with driver.acquire()`` triggers that context's
        owned cleanup. Catching the exception inside the context does not itself
        close the session. Manual sessions still require ``await session.quit()``.

        Returns:
            The positive finite request deadline; the default is 360 seconds.
            Prefer a value larger than the driver's page-load and script timeouts.

        Example:
            >>> driver.options.set_timeouts(implicit=0, pageLoad=20, script=5)
            >>> driver.options.session_timeout = 30
        """
        return self._session_timeout

    @session_timeout.setter
    def session_timeout(self, value: int | float) -> None:
        """Set a positive transport deadline representable as a finite number.

        Args:
            value: Per-command transport timeout in seconds; bool is not accepted.

        Raises:
            InvalidOptionsError: If value is not positive, finite, and representable
                by the underlying asynchronous transport's numeric deadline.
        """
        try:
            finite = isinstance(value, (int, float)) and isfinite(value)
        except OverflowError:
            finite = False
        if isinstance(value, bool) or not finite:
            raise errors.InvalidOptionsError(
                "<{}>\nInvalid session_timeout ({} {}), must be a positive finite integer "
                "or float.".format(self.__class__.__name__, repr(value), type(value))
            )
        if value <= 0:
            raise errors.InvalidOptionsError(
                "<{}>\nInvalid session_timeout ({}), must be greater than `0`.".format(
                    self.__class__.__name__, value
                )
            )
        self._session_timeout = value

    # Caps: basic -------------------------------------------------------------------------
    @property
    def capabilities(self) -> dict[str, Any]:
        """Return the final browser capabilities.

        Returns:
            The final browser capabilities.
        """
        if self._proxy is not None:
            proxy = self._proxy.to_capabilities()
            if self._capabilities.get("proxy") != proxy:
                self._capabilities["proxy"] = deepcopy(proxy)
                self._caps_changed()
        if not self.__caps or self.__caps_status == 1:
            self.__caps = deepcopy(self.construct())
            self.__caps_status = 0
        return deepcopy(self.__caps)

    def construct(self) -> dict[str, Any]:
        """Construct capabilities for the concrete browser implementation.

        Returns:
            Final W3C capabilities produced by the concrete browser subclass.
        """
        raise NotImplementedError(
            "<{}> Browser-specific construct() is not implemented.".format(
                self.__class__.__name__
            )
        )

    def get_capability(self, name: str) -> Any:
        """Get a capability of the browser.

        Args:
            name: The name of the capability.

        Returns:
            The value of the capability.

        Raises:
            OptionsNotSetError: If the capability is not set.
        """
        try:
            return deepcopy(self._capabilities[name])
        except KeyError as err:
            raise errors.OptionsNotSetError(
                "<{}>\nCapability {} has not been set.".format(
                    self.__class__.__name__, repr(name)
                )
            ) from err

    def set_capability(self, name: str, value: Any) -> None:
        """Set a validated standard or unrestricted extension capability.

        Args:
            name: Nonempty capability name. Recognized W3C standard names are
                validated according to their documented scalar or container
                contract; extension names retain arbitrary values.
            value: Capability value copied into this options instance.

        Raises:
            errors.InvalidOptionsError: The name is invalid or a recognized
                standard capability has an invalid value.
        """
        value = self._validate_standard_capability(name, value)
        if name == "proxy":
            # A low-level proxy capability replaces, rather than competes with,
            # the typed Proxy object. The property setter restores ownership
            # immediately after it stores that object's serialized payload.
            self._proxy = None
        self._capabilities[name] = deepcopy(value)
        self._caps_changed()

    def _validate_standard_capability(self, name: object, value: object) -> object:
        """Validate and normalize capabilities exposed by typed properties.

        Args:
            name: Candidate capability name.
            value: Candidate capability value.

        Raises:
            errors.InvalidOptionsError: The name or recognized standard value
                would violate the corresponding public property's contract.

        Returns:
            The unchanged value, except timeout mappings are normalized to a
            complete integer-millisecond WebDriver payload.
        """
        if not isinstance(name, str) or not name:
            raise errors.InvalidOptionsError("Capability name must be nonempty text")
        if name == "browserName":
            if not isinstance(value, str) or not value:
                raise errors.InvalidOptionsError(
                    "browserName capability must be nonempty text"
                )
        elif name in {"browserVersion", "platformName"}:
            if not isinstance(value, str):
                raise errors.InvalidOptionsError(f"{name} capability must be text")
        elif name in {"acceptInsecureCerts", "strictFileInteractability"}:
            if not isinstance(value, bool):
                raise errors.InvalidOptionsError(f"{name} capability must be a bool")
        elif name == "pageLoadStrategy":
            if (
                not isinstance(value, str)
                or value not in Constraint.PAGE_LOAD_STRATEGIES
            ):
                raise errors.InvalidOptionsError(
                    "pageLoadStrategy capability must be one of: %s"
                    % ", ".join(sorted(Constraint.PAGE_LOAD_STRATEGIES))
                )
        elif name == "unhandledPromptBehavior":
            if (
                not isinstance(value, str)
                or value not in Constraint.UNHANDLED_PROMPT_BEHAVIORS
            ):
                raise errors.InvalidOptionsError(
                    "unhandledPromptBehavior capability must be one of: %s"
                    % ", ".join(sorted(Constraint.UNHANDLED_PROMPT_BEHAVIORS))
                )
        elif name == "timeouts":
            if not isinstance(value, dict):
                raise errors.InvalidOptionsError(
                    "timeouts capability must be a mapping"
                )
            try:
                return Timeouts(**value, unit="ms").dict
            except (TypeError, errors.InvalidOptionsError) as cause:
                raise errors.InvalidOptionsError(
                    "timeouts capability must contain valid implicit, pageLoad, "
                    "and script millisecond values"
                ) from cause
        elif name == "proxy" and not isinstance(value, dict):
            raise errors.InvalidOptionsError("proxy capability must be a mapping")
        return value

    def rem_capability(self, name: str) -> None:
        """Remove an optional capability or restore a required default.

        Args:
            name: Capability name. Removing ``pageLoadStrategy`` or ``timeouts``
                restores its package default because their public getters are
                non-optional.

        Raises:
            errors.InvalidOptionsError: ``name`` is not nonempty text.
        """
        if not isinstance(name, str) or not name:
            raise errors.InvalidOptionsError("Capability name must be nonempty text")
        if name == "pageLoadStrategy":
            self._capabilities[name] = "normal"
            self._caps_changed()
            return
        if name == "timeouts":
            self._capabilities[name] = Timeouts().dict
            self._caps_changed()
            return
        if name == "proxy":
            self._proxy = None
        try:
            self._capabilities.pop(name)
            self._caps_changed()
        except KeyError:
            pass

    def _caps_changed(self) -> None:
        """Mark cached final capabilities for reconstruction on their next read."""
        self.__caps_status = 1

    def _validate_bool(self, value: Any, name: str) -> bool:
        """Validate a boolean option without truthiness coercion.

        Args:
            value: New option value to validate before mutating configuration.
            name: Public option name used in the diagnostic.

        Returns:
            The unchanged bool value.

        Raises:
            InvalidOptionsError: If value is not an actual bool.
        """
        if not isinstance(value, bool):
            raise errors.InvalidOptionsError(f"{name} must be a bool")
        return value

    # Caps: browser name ------------------------------------------------------------------
    @property
    def browser_name(self) -> str:
        """Return the name of the browser agent.

        Returns:
            The name of the browser agent.
        """
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
    def browser_version(self) -> str | None:
        """Return the browser version string recorded for this configuration or session.

        Returns:
            The version string, or None when no browser version has been recorded.
            This property does not probe the browser or return a Version object.
        """
        return self._capabilities.get("browserVersion")

    @browser_version.setter
    def browser_version(self, value: Version | None) -> None:
        """Set the browser version.

        Args:
            value: Parsed browser version, or ``None`` to remove the capability.
        """
        self._set_browser_version(value)

    def _set_browser_version(self, value: Version | None) -> None:
        """Store a parsed browser version for capability generation.

        Args:
            value: Parsed version, or ``None`` to remove the capability.

        Raises:
            errors.InvalidOptionsError: ``value`` is neither a Version nor ``None``.
        """
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
                f"<{self.__class__.__name__}>\n`browser_version` must be type of `<'Version'>`."
            )
        self.set_capability("browserVersion", value.patch)

    # Options: binary location ------------------------------------------------------------
    @property
    def browser_location(self) -> Path | None:
        """Return the configured browser executable path.

        Returns:
            The validated absolute executable path, or ``None`` when no binary
            override is configured.
        """
        return self._browser_location

    @browser_location.setter
    def browser_location(self, value: PathInput | None) -> None:
        """Validate and retain an explicit browser executable.

        Args:
            value: Existing executable supplied as text, ``Path``, or another
                string-valued ``os.PathLike`` object. ``None`` removes the override.

        Raises:
            errors.InvalidOptionsError: The value is not a valid existing file path.
        """
        if value is None:
            self._set_browser_location_path(None)
            return

        try:
            location = file_path(value)
        except Exception as err:
            raise errors.InvalidOptionsError(
                "<{}>\nOptions 'browser_location' error: {}".format(
                    self.__class__.__name__, err
                )
            ) from err
        self._set_browser_location_path(location)

    def _set_browser_location_path(self, location: Path | None) -> None:
        """Retain a previously validated browser path and update wire capabilities.

        This internal handoff deliberately performs no filesystem parsing or
        validation. Callers must supply a ``Path`` obtained from ``file_path``
        or a trusted installation result.

        Args:
            location: Validated browser executable, or ``None`` to clear it.
        """
        if location is None:
            self.rem_experimental_option("binary")
            self._browser_location = None
            return
        if location == self._browser_location:
            return
        self._browser_location = location
        # WebDriver capabilities are JSON, so paths cross this boundary as text.
        self.add_experimental_options(binary=str(location))

    # Caps: platform name -----------------------------------------------------------------
    @property
    def platform_name(self) -> str | None:
        """Return the name of the platform.

        e.g. "windows", "mac", "linux".

        Returns:
            The name of the platform.
        """
        return self._capabilities.get("platformName")

    @platform_name.setter
    def platform_name(self, value: str | None) -> None:
        # Remove platform name
        """Set the platform name.

        Args:
            value: W3C platform name, or ``None`` to remove the capability.
        """
        if value is None:
            self.rem_capability("platformName")
            return None  # exit

        # Set platform name
        if not isinstance(value, str):
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\n`platform_name` must be type of `<'str'>`."
            )
        self.set_capability("platformName", value)

    # Caps: accept insecure certs ---------------------------------------------------------
    @property
    def accept_insecure_certs(self) -> bool:
        """Return whether navigation accepts untrusted TLS certificates.

        Returns:
            ``True`` when WebDriver should trust otherwise invalid certificates;
            otherwise ``False``.
        """
        return self._capabilities.get("acceptInsecureCerts", False)

    @accept_insecure_certs.setter
    def accept_insecure_certs(self, value: bool) -> None:
        # Set acceptInsecureCerts to False (remove cap)
        """Set the accept insecure certs.

        Args:
            value: True explicitly permits untrusted certificates; False disables it.

        Raises:
            InvalidOptionsError: If value is not a bool, including strings such as "false".
        """
        value = self._validate_bool(value, "accept_insecure_certs")
        if not value:
            self.rem_capability("acceptInsecureCerts")
        # Set acceptInsecureCerts to True (add cap)
        else:
            self.set_capability("acceptInsecureCerts", True)

    # Caps: page load strategy ------------------------------------------------------------
    @property
    def page_load_strategy(self) -> str:
        """Return the page-load completion strategy; the default is ``normal``.

        Available options:
        - `'normal'`: Waits for all resources to be downloaded.
        - `'eager'`:  Waits for DOM access to be ready, other resources like images may still be loading.
        - `'none'`:   Does not wait for any events, not blocking browser at all.

        Returns:
            The page load strategy string.
        """
        return self._capabilities["pageLoadStrategy"]

    @page_load_strategy.setter
    def page_load_strategy(self, value: str | None) -> None:
        # Reset to default
        """Set the page load strategy.

        Args:
            value: ``normal``, ``eager``, or ``none``; ``None`` restores
                ``normal``.
        """
        if value is None:
            self.set_capability("pageLoadStrategy", "normal")
            return None  # exit

        # Set pageLoadStrategy
        if not isinstance(value, str) or value not in Constraint.PAGE_LOAD_STRATEGIES:
            raise errors.InvalidOptionsError(
                "<{}>\n`page_load_strategy` {} is not valid, "
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
        """Return browser proxy configurations.

        Returns:
            Browser proxy configurations.
        """
        return self._proxy

    @proxy.setter
    def proxy(self, value: Proxy | None) -> None:
        # Remove proxy
        """Set the proxy.

        Args:
            value: Proxy configuration, or ``None`` to disable proxy capabilities.
        """
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

    # Caps: timeouts ----------------------------------------------------------------------
    @property
    def timeouts(self) -> Timeouts:
        """Return a snapshot of default WebDriver timeouts for new sessions.

        - implicit: Total seconds all acquired sessions will wait when
        searching for an element if it is not immediately present.

        - pageLoad: Total seconds all acquired sessions will wait for a
        page load to complete before returning an error.

        - script: Total seconds all acquired sessions will wait for an
        asynchronous script to finish execution before returning an error.

        Returns:
            Independent timeout configuration with seconds-based accessors and
            millisecond wire values.

        Example:
            >>> timeouts = options.timeouts
        """
        return Timeouts(**self._capabilities["timeouts"], unit="ms")

    def set_timeouts(
        self,
        implicit: int | float | None = None,
        pageLoad: int | float | None = None,
        script: int | float | None = None,
    ) -> Timeouts:
        """Update default session timeouts expressed in seconds.

        Individual sessions can override these defaults with
        ``session.set_timeouts()``. Values are converted to the WebDriver
        protocol's millisecond representation.

        Args:
            implicit: Seconds subsequently acquired sessions wait when an
                element is not immediately present. ``None`` keeps the current
                default.
            pageLoad: Seconds subsequently acquired sessions wait for page
                loading to complete. ``None`` keeps the current default.
            script: Seconds subsequently acquired sessions wait for an
                asynchronous script. ``None`` keeps the current default.

        Returns:
            The timeouts after update.

        Example:
            >>> timeouts = options.set_timeouts(implicit=0.1, pageLoad=30, script=3)
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
        """Return whether file inputs require strict interactability checks.

        Returns:
            ``True`` when strict checks are enabled; otherwise ``False``.
        """
        return self._capabilities.get("strictFileInteractability", False)

    @strict_file_interactability.setter
    def strict_file_interactability(self, value: bool) -> None:
        # Set strictFileInteractability to False (remove cap)
        """Set the strict file interactability.

        Args:
            value: True enables strict file interactability; False disables it.

        Raises:
            InvalidOptionsError: If value is not a bool.
        """
        value = self._validate_bool(value, "strict_file_interactability")
        if not value:
            self.rem_capability("strictFileInteractability")
        # Set strictFileInteractability to True (add cap)
        else:
            self.set_capability("strictFileInteractability", True)

    # Caps: prompt behavior ---------------------------------------------------------------
    @property
    def unhandled_prompt_behavior(self) -> str:
        """Return the configured behavior for an unexpected user prompt.

        Returns:
            One of ``dismiss``, ``dismiss and notify``, ``accept``,
            ``accept and notify``, or ``ignore``. The default is
            ``dismiss and notify``.
        """
        return self._capabilities.get("unhandledPromptBehavior", "dismiss and notify")

    @unhandled_prompt_behavior.setter
    def unhandled_prompt_behavior(self, value: str) -> None:
        """Set how WebDriver handles an unexpected user prompt.

        Args:
            value: One of the supported W3C prompt-handling behaviors.

        Raises:
            errors.InvalidOptionsError: ``value`` is unsupported.
        """
        if (
            not isinstance(value, str)
            or value not in Constraint.UNHANDLED_PROMPT_BEHAVIORS
        ):
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
        """Return the experimental options of the browser.

        Returns:
            The experimental options of the browser.
        """
        return deepcopy(self._experimental_options)

    def add_experimental_options(self, **options: Any) -> None:
        """Add experimental options of the browser.

        Args:
            **options: The experimental options to add.

        Example:
            >>> options.add_experimental_options(
            ...     excludeSwitches=["enable-automation"],
            ...     useAutomationExtension=False,
            ... )
        """
        # Add options
        self._experimental_options |= deepcopy(options)
        self._caps_changed()

    def rem_experimental_option(self, name: str) -> None:
        """Remove an experimental option of the browser.

        Args:
            name: The name of the experimental option.

        Example:
            >>> options.rem_experimental_option("excludeSwitches")
        """
        if name == "binary":
            self._browser_location = None
        try:
            self._experimental_options.pop(name)
            self._caps_changed()
        except KeyError:
            pass

    def get_experimental_option(self, name: str) -> Any:
        """Get an experimental option of the browser.

        Args:
            name: The name of the experimental option.

        Returns:
            The value of the experimental option.

        Raises:
            OptionsNotSetError: If the experimental option is not set.
        """
        try:
            return deepcopy(self._experimental_options[name])
        except KeyError as err:
            raise errors.OptionsNotSetError(
                "<{}>\nExperimental option {} has not been set.".format(
                    self.__class__.__name__, repr(name)
                )
            ) from err

    # Caps: arguments ---------------------------------------------------------------------
    @property
    def arguments(self) -> list[str]:
        """Return specified browser arguments.

        Returns:
            Specified browser arguments.
        """
        return self._arguments.copy()

    def add_arguments(self, *args: str) -> None:
        """Append unique command-line arguments to browser capabilities.

        Args:
            *args: The arguments to add.

        Example:
            >>> options.add_arguments(
            ...     "--headless=new",
            ...     "--disable-gpu",
            ... )
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
        for arg in args:
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
        """Return the preferences of the browser.

        Returns:
            The preferences of the browser.
        """
        return deepcopy(self._preferences)

    def set_preferences(self, **prefs: Any) -> None:
        """Set preferences of the browser.

        Args:
            **prefs: The preferences to set.

        Example:
            >>> options.set_preferences(
            ...     **{
            ...     "download.default_directory": "/path/to/download/directory",
            ...     "download.prompt_for_download": False,
            ...     "download.directory_upgrade": True,
            ...     "safebrowsing.enabled": True
            ... }
            ... )
        """
        # Set preferences
        self._preferences |= deepcopy(prefs)
        self._caps_changed()

    def get_preference(self, name: str) -> Any:
        """Get a preference value of the browser.

        Args:
            name: The name of the preference.

        Returns:
            The value of the preference.

        Raises:
            OptionsNotSetError: If the preference is not set.

        Example:
            >>> options.get_preference("media.navigator.permission.disabled")
        """
        try:
            return deepcopy(self._preferences[name])
        except KeyError as err:
            raise errors.OptionsNotSetError(
                "<{}>\nPreference {} has not been set.".format(
                    self.__class__.__name__, repr(name)
                )
            ) from err

    def rem_preference(self, name: str) -> None:
        """Remove a preference of the browser.

        Args:
            name: The name of the preference.

        Example:
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
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (capabilities=%s)>" % (
            self.__class__.__name__,
            "<redacted>",
        )

    def __eq__(self, __o: Any) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        if isinstance(__o, BaseOptions):
            return self.capabilities == __o.capabilities
        else:
            return False


# Chromium Base Options ---------------------------------------------------------------------------
class ChromiumBaseOptions(BaseOptions):
    """Add Chromium-family launch arguments, preferences, and profiles.

    Concrete subclasses supply browser defaults, a nonempty vendor prefix, and
    the vendor-options capability key.

    Attributes:
        KEY: Fully qualified vendor-options key, such as
            ``goog:chromeOptions`` or ``ms:edgeOptions``.
    """

    KEY: str = ""

    def __init__(self) -> None:
        """Initialize Chromium state and validate concrete vendor metadata.

        Raises:
            errors.InvalidOptionsError: The concrete class omits its vendor
                prefix or vendor-options key.
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
        self._extensions: list[str] = []

    # Caps: basic -------------------------------------------------------------------------
    def construct(self) -> dict[str, Any]:
        """Construct the final capabilities for the browser.

        Returns:
            Final W3C capabilities including the browser's vendor options.
        """
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

    # Options: debugger -------------------------------------------------------------------
    @property
    def debugger_address(self) -> str | None:
        """Return the address of the remote devtools for debugging.

        A configured address asks ChromeDriver to attach to an existing
        DevTools endpoint at session startup, for example "127.0.0.1:9222".
        None leaves attachment disabled. The endpoint must be trusted and private.

        Returns:
            The address of the remote devtools for debugging.
        """
        return self._experimental_options.get("debuggerAddress")

    @debugger_address.setter
    def debugger_address(self, value: str | None) -> None:
        # Remove debugger address
        """Set the debugger address.

        Args:
            value: Trusted DevTools endpoint, or ``None`` to disable attachment.
        """
        if value is None:
            self.rem_experimental_option("debuggerAddress")
            return None  # exit

        # Set debugger address
        if not isinstance(value, str):
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\n'debugger_address' must be type of `<'str'>`."
            )
        self.add_experimental_options(debuggerAddress=value)

    # Options: profile --------------------------------------------------------------------
    def close(self) -> None:
        """Release owned profile clones and their automatically added launch arguments.

        Other arguments, original profile data, and independent snapshots remain
        unchanged. Failed cleanup retains the configuration for a later retry.
        """
        had_profile = self._profile is not None
        super().close()
        if had_profile:
            self._remove_profile_arguments()
            self._caps_changed()

    @property
    def profile(self) -> ChromiumProfile | None:
        """Return the profile of the browser. Returns `None` if profile is not configured.

        Notice
        - Please use `set_profile()` method to configure the profile.

        Returns:
            The profile of the browser. returns `none` if profile is not configured.
        """
        return self._profile if isinstance(self._profile, ChromiumProfile) else None

    def set_profile(self, directory: PathInput, profile: str) -> ChromiumProfile:
        r"""Set the user profile for the Chromium based browser. Such as: Edge, Chrome, Chromium, etc.

        Explanation
        - When setting the profile through this method, a cloned temporary
          profile will be created based on the given profile 'directory'.
          The automated session will use the temporary profile leaving the
          original profile untouched. Call options.close() after all uses of
          the facade to release its template clone. Acquisition contexts own
          and clean up their independent snapshot clones.

        macOS Default Profile Location:
        - Chrome: '~/Library/Application Support/Google/Chrome' & 'Default'
        - Chromium: '~/Library/Application Support/Chromium' & 'Default'
        - Edge: '~/Library/Application Support/Microsoft Edge' & 'Default'

        Windows Default Profile Location:
        - Chrome: 'C:\Users\<username>\AppData\Local\Google\Chrome\User Data' & 'Default'
        - Chromium: 'C:\Users\<username>\AppData\Local\Chromium\User Data' & 'Default'
        - Edge: 'C:\Users\<username>\AppData\Local\Microsoft\Edge\User Data' & 'Default'

        Linux Default Profile Location:
        - Chrome: '~/.config/google-chrome' & 'Default'
        - Chromium: '~/.config/chromium' & 'Default'
        - Edge: '~/.config/microsoft-edge' & 'Default'

        Args:
            directory: The directory of the user profile.
            profile: Nonempty name of exactly one child directory inside
                `directory`, such as `Default` or `Profile 1`. Paths, `.` and
                `..`, separators, drive prefixes, control characters, colons
                or other Windows-reserved punctuation, trailing spaces or dots,
                and Windows device names are rejected.

        Returns:
            The profile instance.

        Raises:
            errors.InvalidProfileError: The directory is invalid or `profile`
                is not a portable single-directory name.
        """
        # Create profile
        value = ChromiumProfile(directory, profile)
        # Set new profile
        self._replace_profile(value)
        self._remove_profile_arguments()
        temp_directory = value._temp_directory
        if temp_directory is None:
            raise errors.InvalidProfileError(
                "Temporary Chromium profile is unavailable"
            )
        self.add_arguments(
            "--user-data-dir=%s" % temp_directory,
            "--profile-directory=%s" % value.profile_folder_temp,
        )
        self._caps_changed()
        return value

    def rem_profile(self) -> None:
        """Release the owned profile clone and remove its browser launch arguments.

        Example:
            >>> # . set a new profile
            >>> options.set_profile(directory, profile)

            >>> # . remove the profile
            >>> options.rem_profile()
        """
        self.close()
        self._remove_profile_arguments()
        self._caps_changed()

    def _remove_profile_arguments(self) -> None:
        """Remove launch arguments previously generated for an owned profile."""
        self._arguments = [
            arg
            for arg in self._arguments
            if not arg.startswith("--user-data-dir=")
            and not arg.startswith("--profile-directory=")
        ]

    # Options: extensions -----------------------------------------------------------------
    @property
    def extensions(self) -> list[str]:
        """Return the extensions for the browser.

        Each item in the list corresponds to the encoded base64
        value of the extension file.

        Returns:
            The extensions for the browser.
        """
        return self._extensions.copy()

    def add_extensions(self, *paths: PathInput) -> None:
        r"""Add extensions to the browser (through local file).

        Args:
            *paths: The paths to the extension files (\*.crx).

        Example:
            >>> options.add_extensions(
            ...     "/path/to/extension1.crx",
            ...     "/path/to/extension2.crx",
            ... )
        """
        # Read and validate the entire batch before committing any update.
        pending = []
        for path in paths:
            # . validate ext path
            try:
                extension_path = file_path(path)
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nExtension 'path' error: {}".format(
                        self.__class__.__name__, err
                    )
                ) from err
            # . load ext data
            try:
                data = b64encode(extension_path.read_bytes()).decode("utf-8")
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nFailed to encode extension at: {}\nError: {}".format(
                        self.__class__.__name__, repr(extension_path), err
                    )
                ) from err
            # . add ext data
            pending.append(data)
        self.add_extensions_base64(*pending)

    def add_extensions_base64(self, *extensions: str | bytes) -> None:
        """Add extensions to the browser (through encoded Base64 data). (For extensions that have already been encoded into Base64.).

        Args:
            *extensions: The Base64 encoded extension data.
        """
        # Validate all extension payloads before changing the current batch.
        pending = []
        for ext in extensions:
            # . validate ext data
            if isinstance(ext, bytes):
                try:
                    ext = ext.decode("utf-8")
                except UnicodeError as cause:
                    raise errors.InvalidExtensionError(
                        "Extension data must be UTF-8 text"
                    ) from cause
            elif not isinstance(ext, str):
                raise errors.InvalidExtensionError(
                    "<{}>\nExtension data is not valid: {} {}".format(
                        self.__class__.__name__, type(ext), repr(ext)
                    )
                )
            pending.append(ext)
        added = False
        for ext in pending:
            # . add ext data
            if ext and ext not in self._extensions:
                self._extensions.append(ext)
                added = True

        # Update caps status
        if added:
            self._caps_changed()
