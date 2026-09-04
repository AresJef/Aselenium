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
"""Aselenium service implementation and supporting types."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
)

from aselenium.service import BaseService

if TYPE_CHECKING:
    from aselenium.manager.version import GeckoVersion

__all__ = ["FirefoxService"]


# Firefox Service ---------------------------------------------------------------------------------
class FirefoxService(BaseService):
    """Firefox Service."""

    def __init__(
        self,
        driver_version: GeckoVersion,
        driver_location: str,
        timeout: int | float = 10,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            driver_version: Resolved browser-driver version.
            driver_location: Driver executable path used for probing or service startup.
            timeout: Total time budget in seconds; None follows the documented no-wait/default behavior.
            *args: Positional arguments forwarded to the wrapped operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.
        """
        super().__init__(driver_version, driver_location, timeout, *args, **kwargs)
        # Process
        self._cdp_port: int = -1
        self._cdp_port_str: str = None

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> GeckoVersion:
        """Return the version of the webdriver executable.

        Returns:
            The version of the webdriver executable.
        """
        return self._driver_version

    # Socket ------------------------------------------------------------------------------
    @property
    def port_args(self) -> list[str]:
        """Return the part arguments for the service Process constructor.

        Returns:
            `["--port=" + self.port_str]`
        """
        args = ["--port=" + self.port_str]
        if "--connect-existing" not in self._args and not any(
            argument == "--websocket-port"
            or (isinstance(argument, str) and argument.startswith("--websocket-port="))
            for argument in self._args
        ):
            args.extend(["--websocket-port", self.cdp_port_str])
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
        return self._cdp_port_str

    def _reset_port(self) -> None:
        """Reset the socket port of the service."""
        super()._reset_port()
        self._remove_port(self._cdp_port)
        self._cdp_port = -1
        self._cdp_port_str = None
