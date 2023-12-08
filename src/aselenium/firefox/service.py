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
from typing import Any
from aselenium.service import BaseService
from aselenium.manager.version import GeckoVersion

__all__ = ["FirefoxService"]


# Firefox Service ---------------------------------------------------------------------------------
class FirefoxService(BaseService):
    """Firefox Service"""

    def __init__(
        self,
        driver_version: GeckoVersion,
        driver_location: str,
        timeout: int | float = 10,
        *args: Any,
        **kwargs: Any
    ) -> None:
        super().__init__(driver_version, driver_location, timeout, *args, **kwargs)
        # Process
        self._cdp_port: int = -1
        self._cdp_port_str: str = None
        # Setup CDP port
        if "--connect-existing" not in self._args:
            self._args.append("--websocket-port")
            self._args.append(self.cdp_port_str)

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> GeckoVersion:
        """Access the version of the webdriver executable `<GeckoVersion>`."""
        return self._driver_version

    # Socket ------------------------------------------------------------------------------
    @property
    def port_args(self) -> list[str]:
        """Access the part arguments for the service Process constructor.

        :return `<list[str]>`: `["--port=" + self.port_str]`
        """
        return ["--port=" + self.port_str]

    @property
    def cdp_port(self) -> int:
        """Access the socket port for DevTools Protocol of the service `<int>`."""
        if self._cdp_port == -1:
            self._cdp_port = self.get_free_port()
            self._cdp_port_str = str(self.cdp_port)
        return self._cdp_port

    @property
    def cdp_port_str(self) -> str:
        """Access the socket port for DevTools Protocol of the service
        in string format `<str>`.
        """
        if self._cdp_port == -1:
            self.cdp_port
        return self._cdp_port_str

    def _reset_port(self) -> None:
        """(Internal) Reset the socket port of the service."""
        super()._reset_port()
        self._remove_port(self._cdp_port)
        self._cdp_port = -1
        self._cdp_port_str = None
