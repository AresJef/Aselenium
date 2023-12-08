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
from typing import Any, Literal
from aselenium import errors
from aselenium.logs import logger
from aselenium.element import Element
from aselenium.command import Command
from aselenium.session import Session
from aselenium.safari.options import SafariOptions
from aselenium.safari.service import SafariService
from aselenium.manager.version import SafariVersion

__all__ = ["SafariSession"]


# Safari Session ----------------------------------------------------------------------------------
class SafariSession(Session):
    """Represents a session of the Safari browser."""

    def __init__(self, options: SafariOptions, service: SafariService) -> None:
        super().__init__(options, service)

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> SafariOptions:
        """Access the Safari options `<SafariOptions>`."""
        return self._options

    @property
    def browser_version(self) -> SafariVersion:
        """Access the browser binary version of the session `<SafariVersion>`."""
        return super().browser_version

    @property
    def service(self) -> SafariService:
        """Access the Safari service `<SafariService>`."""
        return self._service

    @property
    def driver_version(self) -> SafariVersion:
        """Access the webdriver binary version of the session `<SafariVersion>`."""
        return super().driver_version

    # Execute -----------------------------------------------------------------------------
    async def execute_command(
        self,
        command: str,
        body: dict | None = None,
        keys: dict | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Executes a command from the session.

        :param command: `<str>` The command to execute.
        :param body: `<dict/None>` The body of the command. Defaults to `None`.
        :param keys: `<dict/None>` The keys to substitute in the command. Defaults to `None`.
        :param timeout: `<int/float/None>` Force timeout of the command. Defaults to `None`.
            For some webdriver versions, the browser will be frozen when
            executing certain commands. This parameter sets an extra
            timeout to throw the `SessionTimeoutError` exception if
            timeout is reached.
        :return: `<dict>` The response from the command.
        """
        return await self._conn.execute(
            self._base_url,
            command,
            body=body,
            keys=keys,
            timeout=timeout,
        )

    # Disable - Information ---------------------------------------------------------------
    async def print_page(
        self,
        orientation: Literal["portrait", "landscape"] | None = None,
        scale: int | float | None = None,
        background: bool | None = None,
        page_width: int | float | None = None,
        page_height: int | float | None = None,
        margin_top: int | float | None = None,
        margin_bottom: int | float | None = None,
        margin_left: int | float | None = None,
        margin_right: int | float | None = None,
        shrink_to_fit: bool | None = None,
        page_ranges: list[str] | None = None,
    ) -> None:
        """Safari automation does not support print page commands `None`."""
        logger.warning(
            "<{}>\nSafari automation does not support print page "
            "commands.".format(self.__class__.__name__)
        )
        return None

    # Disable - Frame ---------------------------------------------------------------------
    async def switch_frame(
        self,
        value: str | Element | int,
        by: Literal["css", "xpath", "index"] = "css",
        timeout: int | float | None = None,
    ) -> bool:
        """Safari automation does not support frame commands `False`."""
        logger.warning(
            "<{}>\nSafari automation does not support frame "
            "switching.".format(self.__class__.__name__)
        )
        return False

    async def default_frame(self) -> bool:
        """Safari automation does not support frame commands `True`."""
        logger.warning(
            "<{}>\nSafari automation does not support frame "
            "switching.".format(self.__class__.__name__)
        )
        return True

    async def parent_frame(self) -> bool:
        """Safari automation does not support frame commands `True`."""
        logger.warning(
            "<{}>\nSafari automation does not support frame "
            "switching.".format(self.__class__.__name__)
        )
        return True

    # Disable - Actions -------------------------------------------------------------------
    def actions(
        self,
        pointer: Literal["mouse", "pen", "touch"] = "mouse",
        duration: int | float = 0.25,
    ) -> None:
        """Safari automation does not support actions commands `None`."""
        logger.warning(
            "<{}>\nSafari automation does not support actions "
            "commands.".format(self.__class__.__name__)
        )
        return None

    # Safari - Permission -----------------------------------------------------------------
    @property
    async def permissions(self) -> dict[str, bool]:
        """Access all the permissions of the active page window `<dict[str, bool]>`.

        ### Example:
        >>> permissions = await session.permissions
            # {'getUserMedia': True}}
        """
        res = await self.execute_command(Command.SAFARI_GET_PERMISSIONS)
        try:
            return res["value"]["permissions"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse permissions from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def get_permission(self, name: str) -> bool:
        """Get a specific permission state from the active page window.

        :param name: `<str>` The name of the permission.
        :return `<bool>`: The state of the permission, or `None` if not found.

        ### Example:
        >>> await session.get_permission("getUserMedia") # True / False
        """
        return (await self.permissions).get(name, None)

    async def set_permission(self, name: str, value: bool) -> dict[str, bool]:
        """Set a specific permission of the active page window.

        :param name: `<str>` The name of the permission.
        :param value: `<bool>` The state for the permission.
        :return `<dict[str, bool]>`: All the permissions after update.

        ### Example:
        >>> await session.set_permission("getUserMedia", False)
            # {'getUserMedia': False}}
        """
        permissions = await self.permissions
        await self.execute_command(
            Command.SAFARI_SET_PERMISSIONS,
            body={"permissions": permissions | {name: bool(value)}},
        )
        return await self.permissions
