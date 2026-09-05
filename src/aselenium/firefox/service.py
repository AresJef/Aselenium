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

"""GeckoDriver service ports, subprocess arguments, and profile-root support."""

from __future__ import annotations

from os import fspath
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

from aselenium import errors
from aselenium._paths import PathInput, directory_path
from aselenium.service import BaseService

if TYPE_CHECKING:
    from pathlib import Path

    from aselenium.manager.version import GeckoVersion

__all__ = ["FirefoxService"]


# Firefox Service ---------------------------------------------------------------------------------
class FirefoxService(BaseService):
    """Launch and supervise a GeckoDriver process for Firefox."""

    _PROFILE_ROOT_MINIMUM = (0, 32, 0)

    def __init__(
        self,
        driver_version: GeckoVersion,
        driver_location: PathInput,
        timeout: int | float = 10,
        *args: Any,
        profile_root: PathInput | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize a Firefox service without starting its process.

        Args:
            driver_version: Resolved browser-driver version.
            driver_location: Driver executable path used for probing or service startup.
            timeout: Positive startup and shutdown budget in seconds.
            *args: Additional GeckoDriver command-line arguments.
            profile_root: Existing directory in which GeckoDriver may create
                temporary Firefox profiles. Both GeckoDriver and Firefox must be
                able to read and write it. This is useful when Firefox runs in a
                Snap, Flatpak, or another container with a private temporary
                directory. Requires GeckoDriver 0.32.0 or newer. None leaves
                GeckoDriver's default unchanged.
            **kwargs: Additional keyword arguments for ``subprocess.Popen``.

        Raises:
            errors.InvalidArgumentError: ``profile_root`` is used with an older
                GeckoDriver or is also supplied as a raw GeckoDriver argument.
            errors.AseleniumInvalidPathError: ``profile_root`` cannot be parsed
                as an unambiguous text path.
            errors.AseleniumDirectoryNotFoundError: ``profile_root`` is not an
                existing directory.
        """
        if profile_root is not None:
            for argument in args:
                try:
                    value = fspath(argument)
                except TypeError:
                    continue
                if (
                    value == "--profile-root"
                    or isinstance(value, str)
                    and value.startswith("--profile-root=")
                    or value == b"--profile-root"
                    or isinstance(value, bytes)
                    and value.startswith(b"--profile-root=")
                ):
                    raise errors.InvalidArgumentError(
                        "profile_root cannot be combined with a raw --profile-root argument"
                    )
            version = (
                driver_version.major_num,
                driver_version.build_num,
                driver_version.patch_num,
            )
            if version < self._PROFILE_ROOT_MINIMUM:
                raise errors.InvalidArgumentError(
                    "profile_root requires GeckoDriver 0.32.0 or newer"
                )
        parsed_profile_root = (
            directory_path(profile_root) if profile_root is not None else None
        )
        super().__init__(driver_version, driver_location, timeout, *args, **kwargs)
        self._profile_root: Path | None = parsed_profile_root
        # Process
        self._cdp_port: int = -1
        self._cdp_port_str: str | None = None

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> GeckoVersion:
        """Return the version of the webdriver executable.

        Returns:
            The version of the webdriver executable.
        """
        return cast("GeckoVersion", self._driver_version)

    # Socket ------------------------------------------------------------------------------
    @property
    def port_args(self) -> list[str]:
        """Return GeckoDriver arguments for the reserved service ports and profile root.

        Returns:
            Command-line arguments containing the WebDriver port, an automatically
            reserved WebSocket port when needed, and the configured profile root.
        """
        args = ["--port=" + self.port_str]
        if "--connect-existing" not in self._args and not any(
            argument == "--websocket-port"
            or (isinstance(argument, str) and argument.startswith("--websocket-port="))
            for argument in self._args
        ):
            args.extend(["--websocket-port", self.cdp_port_str])
        if self._profile_root is not None:
            args.extend(["--profile-root", str(self._profile_root)])
        return args

    @property
    def cdp_port(self) -> int:
        """Return the socket port for DevTools Protocol of the service.

        Returns:
            The socket port for devtools protocol of the service.
        """
        if self._cdp_port == -1:
            self._cdp_port = self.get_free_port()
            self._cdp_port_str = str(self.cdp_port)
        return self._cdp_port

    @property
    def cdp_port_str(self) -> str:
        """Return the socket port for DevTools Protocol of the service in string format.

        Returns:
            The socket port for devtools protocol of the service in string format.
        """
        if self._cdp_port == -1:
            self.cdp_port
        assert self._cdp_port_str is not None
        return self._cdp_port_str

    def _reset_port(self) -> None:
        """Reset the socket port of the service."""
        super()._reset_port()
        self._remove_port(self._cdp_port)
        self._cdp_port = -1
        self._cdp_port_str = None
