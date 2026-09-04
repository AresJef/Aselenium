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
"""Aselenium session implementation and supporting types."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
)

from aselenium import errors
from aselenium.command import Command
from aselenium.logs import logger
from aselenium.session import Session

if TYPE_CHECKING:
    from aselenium.element import Element
    from aselenium.manager.version import SafariVersion
    from aselenium.safari.options import SafariOptions
    from aselenium.safari.service import SafariService

__all__ = ["SafariSession"]


# Safari Session ----------------------------------------------------------------------------------
class SafariSession(Session):
    """Represent a session of the Safari browser."""

    def __init__(self, options: SafariOptions, service: SafariService) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            options: Options used by this operation.
            service: Service used by this operation.
        """
        super().__init__(options, service)

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> SafariOptions:
        """Return the Safari options.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    @property
    def browser_version(self) -> str | None:
        """Return the browser version string recorded for this configuration or session.

        Returns:
            The version string, or None when no browser version has been recorded.
            This property does not probe the browser or return a Version object.
        """
        return super().browser_version

    @property
    def service(self) -> SafariService:
        """Return the Safari service.

        Returns:
            The driver service owned by the session.
        """
        return self._service

    @property
    def driver_version(self) -> SafariVersion:
        """Return the webdriver binary version of the session.

        Returns:
            The webdriver binary version of the session.
        """
        return super().driver_version

    # Execute -----------------------------------------------------------------------------
    async def execute_command(
        self,
        command: str,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Executes a command from the session.

        Args:
            command: The command to execute.
            body: The body of the command. Defaults to `None`.
            keys: The keys to substitute in the command. Defaults to `None`.
            timeout: Force timeout of the command. Defaults to `None`.
                For some webdriver versions, the browser will be frozen when
                executing certain commands. This parameter sets an extra
                timeout to throw the `SessionTimeoutError` exception if
                timeout is reached.

        Returns:
            The response from the command.
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
        """Safari automation does not support print page commands `None`.

        Args:
            orientation: Orientation used by this operation.
            scale: Scale used by this operation.
            background: Background used by this operation.
            page_width: Page width used by this operation.
            page_height: Page height used by this operation.
            margin_top: Margin top used by this operation.
            margin_bottom: Margin bottom used by this operation.
            margin_left: Margin left used by this operation.
            margin_right: Margin right used by this operation.
            shrink_to_fit: Shrink to fit used by this operation.
            page_ranges: Page ranges used by this operation.
        """
        logger.warning(
            "<{}>\nSafari automation does not support print page commands.".format(
                self.__class__.__name__
            )
        )
        return None

    # Disable - Frame ---------------------------------------------------------------------
    async def switch_frame(
        self,
        value: str | Element | int,
        by: Literal["css", "xpath", "index"] = "css",
        timeout: int | float | None = None,
    ) -> bool:
        """Safari automation does not support frame commands `False`.

        Args:
            value: Value to inspect, normalize, or assign as described above.
            by: By used by this operation.
            timeout: Total time budget in seconds; None follows the documented no-wait/default behavior.

        Returns:
            True when the checked condition is satisfied; otherwise False.
        """
        logger.warning(
            "<{}>\nSafari automation does not support frame switching.".format(
                self.__class__.__name__
            )
        )
        return False

    async def default_frame(self) -> bool:
        """Safari automation does not support frame commands `True`.

        Returns:
            True when the checked condition is satisfied; otherwise False.
        """
        logger.warning(
            "<{}>\nSafari automation does not support frame switching.".format(
                self.__class__.__name__
            )
        )
        return True

    async def parent_frame(self) -> bool:
        """Safari automation does not support frame commands `True`.

        Returns:
            True when the checked condition is satisfied; otherwise False.
        """
        logger.warning(
            "<{}>\nSafari automation does not support frame switching.".format(
                self.__class__.__name__
            )
        )
        return True

    # Disable - Actions -------------------------------------------------------------------
    def actions(
        self,
        pointer: Literal["mouse", "pen", "touch"] = "mouse",
        duration: int | float = 0.25,
    ) -> None:
        """Safari automation does not support actions commands `None`.

        Args:
            pointer: Pointer used by this operation.
            duration: Duration used by this operation.
        """
        logger.warning(
            "<{}>\nSafari automation does not support actions commands.".format(
                self.__class__.__name__
            )
        )
        return None

    # Safari - Permission -----------------------------------------------------------------
    @property
    async def permissions(self) -> dict[str, bool]:
        """Return all the permissions of the active page window.

        Returns:
            Permission names mapped to their boolean states. An empty mapping is valid.

        Raises:
            InvalidResponseError: If the response lacks a permission mapping with
                string names and bool values.

        Example:
            >>> permissions = await session.permissions
        """
        res = await self.execute_command(Command.SAFARI_GET_PERMISSIONS)
        value = res.get("value") if isinstance(res, dict) else None
        permissions = value.get("permissions") if isinstance(value, dict) else None
        if not isinstance(permissions, dict) or not all(
            isinstance(name, str) and isinstance(state, bool)
            for name, state in permissions.items()
        ):
            raise errors.InvalidResponseError(
                f"<{self.__class__.__name__}>\nSafari permission response must "
                "contain value.permissions as a mapping of string names to bool values."
            )
        return permissions

    async def get_permission(self, name: str) -> bool | None:
        """Get a specific permission state from the active page window.

        Args:
            name: The name of the permission.

        Returns:
            The state of the permission, or `None` if not found.

        Example:
            >>> await session.get_permission("getUserMedia") # True / False
        """
        return (await self.permissions).get(name, None)

    async def set_permission(self, name: str, value: bool) -> dict[str, bool]:
        """Set a specific permission of the active page window.

        Args:
            name: The name of the permission.
            value: The state for the permission.

        Returns:
            All the permissions after update.

        Raises:
            InvalidPermissionNameError: If name is not a nonempty string.
            InvalidPermissionStateError: If value is not a bool.

        Example:
            >>> await session.set_permission("getUserMedia", False)
        """
        if not isinstance(name, str) or not name:
            raise errors.InvalidPermissionNameError(
                "Permission name must be a nonempty string"
            )
        if not isinstance(value, bool):
            raise errors.InvalidPermissionStateError("Permission state must be a bool")
        permissions = await self.permissions
        await self.execute_command(
            Command.SAFARI_SET_PERMISSIONS,
            body={"permissions": permissions | {name: value}},
        )
        return await self.permissions
