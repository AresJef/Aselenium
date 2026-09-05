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

"""SafariDriver session behavior and Safari-specific permission commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from aselenium import errors
from aselenium.command import Command
from aselenium.logs import logger
from aselenium.session import Session

if TYPE_CHECKING:
    from aselenium.actions import Actions
    from aselenium.element import Element
    from aselenium.manager.version import SafariVersion
    from aselenium.safari.options import SafariOptions
    from aselenium.safari.service import SafariService

__all__ = ["SafariSession"]


# Safari Session ----------------------------------------------------------------------------------
class SafariSession(Session):
    """Represent a session of the Safari browser."""

    def __init__(self, options: SafariOptions, service: SafariService) -> None:
        """Create a not-yet-started Safari session.

        Args:
            options: Safari capability snapshot owned by this session.
            service: SafariDriver service owned by this session.
        """
        super().__init__(options, service)

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> SafariOptions:
        """Return the Safari options.

        Returns:
            The browser options owned by this facade or session.
        """
        return cast("SafariOptions", super().options)

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
        return cast("SafariService", super().service)

    @property
    def driver_version(self) -> SafariVersion:
        """Return the WebDriver binary version of the session.

        Returns:
            The WebDriver binary version of the session.
        """
        return cast("SafariVersion", super().driver_version)

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
    ) -> bytes:
        """Reject PDF printing, which SafariDriver does not implement.

        Args:
            orientation: Requested page orientation; retained for API compatibility.
            scale: Requested page scale; retained for API compatibility.
            background: Whether backgrounds should print; retained for compatibility.
            page_width: Requested page width in centimeters.
            page_height: Requested page height in centimeters.
            margin_top: Requested top margin in centimeters.
            margin_bottom: Requested bottom margin in centimeters.
            margin_left: Requested left margin in centimeters.
            margin_right: Requested right margin in centimeters.
            shrink_to_fit: Whether content should shrink to fit the page.
            page_ranges: Requested page ranges.

        Raises:
            errors.InvalidMethodError: Always; SafariDriver exposes no W3C print
                endpoint.
        """
        raise errors.InvalidMethodError(
            "SafariDriver does not support the W3C print-page command"
        )

    # Disable - Frame ---------------------------------------------------------------------
    async def switch_frame(
        self,
        value: str | Element | int,
        by: Literal["css", "xpath", "index"] = "css",
        timeout: int | float | None = None,
    ) -> bool:
        """Leave the current frame unchanged because this facade disables switching.

        Args:
            value: Frame selector, element, or index that would be selected by
                the shared session API.
            by: Selector strategy for string values: ``css``, ``xpath``, or
                ``index``.
            timeout: Optional lookup budget in seconds.

        Returns:
            Always ``False`` because no frame switch was attempted.
        """
        logger.warning(
            "<{}>\nSafari automation does not support frame switching.".format(
                self.__class__.__name__
            )
        )
        return False

    async def default_frame(self) -> bool:
        """Report the default frame as unchanged because frame commands are disabled.

        Returns:
            Always ``True`` for compatibility with the shared session API.
        """
        logger.warning(
            "<{}>\nSafari automation does not support frame switching.".format(
                self.__class__.__name__
            )
        )
        return True

    async def parent_frame(self) -> bool:
        """Report the parent frame as unchanged because frame commands are disabled.

        Returns:
            Always ``True`` for compatibility with the shared session API.
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
    ) -> Actions:
        """Reject low-level actions, which this Safari facade does not implement.

        Args:
            pointer: Requested pointer source type; retained for API compatibility.
            duration: Requested default pointer-move duration in seconds.

        Raises:
            errors.InvalidMethodError: Always; actions are intentionally disabled
                until SafariDriver support is validated.
        """
        raise errors.InvalidMethodError(
            "Low-level actions are not supported by the Safari facade"
        )

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
        """Update one permission without overwriting concurrent permission changes.

        Read, merge, mutation, and observation share command ownership. Wrap
        additional page work in ``session.transaction()`` when it must use the
        same active window and permission state.

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
        async with self.transaction():
            permissions = await self.permissions
            await self.execute_command(
                Command.SAFARI_SET_PERMISSIONS,
                body={"permissions": permissions | {name: value}},
            )
            return await self.permissions
