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

from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Literal,
)
from zipfile import is_zipfile

from aselenium import errors
from aselenium._async import run_blocking
from aselenium._output import save_bytes
from aselenium._paths import PathInput, parse_path, save_file_path
from aselenium.command import Command
from aselenium.firefox.utils import (
    FirefoxAddon,
    encode_dir_to_firefox_wire_protocol,
    extract_firefox_addon_details,
)
from aselenium.session import Session

if TYPE_CHECKING:
    from aselenium.firefox.options import FirefoxOptions
    from aselenium.firefox.service import FirefoxService
    from aselenium.manager.version import GeckoVersion

__all__ = ["FirefoxSession"]


# Firefox Session ---------------------------------------------------------------------------------
class FirefoxSession(Session):
    """Represent a session of the Firefox browser."""

    def __init__(self, options: FirefoxOptions, service: FirefoxService) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            options: Options used by this operation.
            service: Service used by this operation.
        """
        super().__init__(options, service)
        # Add-ons
        self._addon_by_id: dict[str, FirefoxAddon] = {}
        if self.options.profile is not None:
            self._addon_by_id |= options.profile.extensions

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> FirefoxOptions:
        """Return the Firefox options.

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
    def service(self) -> FirefoxService:
        """Return the Firefox service.

        Returns:
            The driver service owned by the session.
        """
        return self._service

    @property
    def driver_version(self) -> GeckoVersion:
        """Return the webdriver binary version of the session.

        Returns:
            The webdriver binary version of the session.
        """
        return super().driver_version

    # Information -------------------------------------------------------------------------
    async def take_full_screenshot(self) -> bytes:
        """Take a FULL document screenshot of the active page window.

        Returns:
            Take a FULL document screenshot of the active page window.

        Example:
            >>> screenshot = await session.take_full_screenshot()
        """
        res = await self.execute_command(Command.FIREFOX_FULL_PAGE_SCREENSHOT)
        try:
            return self._decode_base64(res["value"], "ascii")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse full document screenshot data "
                "from response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid full document screenshot response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def save_full_screenshot(self, path: PathInput) -> bool:
        """Take & save the FULL document screenshot of the active page window into a local PNG file.

        Args:
            path: The path to save the screenshot. e.g. `~/path/to/screenshot.png`.

        Returns:
            True if the screenshot has been saved, False if failed.

        Example:
            >>> await session.save_full_screenshot("~/path/to/screenshot.png")
        """
        # Validate screenshot path
        try:
            destination = save_file_path(path, ".png")
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nSave full screenshot 'path' error: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

        # Take & save screenshot
        data = None
        try:
            # . take screenshot
            data = await self.take_full_screenshot()
            if not data:
                return False
            # . save screenshot
            return await save_bytes(destination, data)
        finally:
            del data

    # Firefox - Context -------------------------------------------------------------------
    @property
    async def context(self) -> Literal["content", "chrome"]:
        """Return the current context of the session. Expected values: `'content'` or `'chrome'`.

        Notice:
        Different from Selenium, the 'context' in this module is not a context
        manager, but an async property to access the current context of the
        session. For more information on how to switch context, please refer
        to the `set_context()` and `reset_context()` methods.

        Returns:
            The current context, either "content" or "chrome".

        Raises:
            InvalidResponseError: If GeckoDriver returns a missing or unsupported context.

        Example:
            >>> await session.context  # "content" / "chrome"
        """
        res = await self.execute_command(Command.FIREFOX_GET_CONTEXT)
        context = res.get("value") if isinstance(res, dict) else None
        if isinstance(context, str):
            if context == "content":
                return "content"
            if context == "chrome":
                return "chrome"
        raise errors.InvalidResponseError(
            f"<{self.__class__.__name__}>\nFirefox context response must contain "
            "value='content' or value='chrome'."
        )

    async def set_context(
        self,
        context: Literal["content", "chrome"],
    ) -> Literal["content", "chrome"]:
        """Set the context of the session.

        Args:
            context: The context to set. Accepts either `'content'` or `'chrome'`.

        Returns:
            The context of the session after update.

        Example:
            >>> await session.set_context("chrome")  # "chrome"
            >>> # ... do stuff in chrome context ...

            >>> await session.reset_context()  # "content"
        """
        if context not in ("content", "chrome"):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid Firefox context: {}. Available options: "
                "['content', 'chrome'].".format(self.__class__.__name__, repr(context))
            )
        await self.execute_command(
            Command.FIREFOX_SET_CONTEXT, body={"context": context}
        )
        return await self.context

    async def reset_context(self) -> Literal["content"]:
        """Reset the context of the session back to `'content'`.

        Returns:
            The context of the session after update.

        Example:
            >>> await session.set_context("chrome")  # "chrome"
            >>> # ... do stuff in chrome context ...

            >>> await session.reset_context()  # "content"
        """
        await self.execute_command(
            Command.FIREFOX_SET_CONTEXT, body={"context": "content"}
        )
        return await self.context

    # Firefox - Addons --------------------------------------------------------------------
    @property
    def addons(self) -> list[FirefoxAddon]:
        """Return the details of the installed add-ons. `(NOT an asynchronous attribute)`.

        Returns:
            The details of the installed add-ons. `(not an asynchronous attribute)`.

        Example:
            >>> await session.install_addons("~/path/to/addon.xpi")
            >>> addons = session.addons
        """
        return list(self._addon_by_id.values())

    async def install_addons(
        self,
        *paths: PathInput,
        temporary: bool = False,
    ) -> list[FirefoxAddon]:
        r"""Install Firefox add-ons.

        Args:
            temporary: Whether to install the add-ons temporarily. Defaults to `False`.
            *paths: The paths to the add-on files (\*.xpi) or unpacked folders.

        Returns:
            Metadata for add-ons installed by this call, excluding already-known IDs.
            Successfully confirmed installations remain cached if a later add-on fails.

        Raises:
            InvalidArgumentError: If temporary is not a bool.
            InvalidExtensionError: If an add-on cannot be read, encoded, or installed.
            InvalidResponseError: If GeckoDriver does not return a non-blank string ID.
                The remote installation may have succeeded even when its response is
                invalid; this method does not cache an unconfirmed add-on ID.

        Example:
            >>> # Install add-ons
            >>> addons = await session.install_addons(
            ...     "~/path/to/addon1.xpi",
            ...     "~/path/to/addon2",
            ... )
        """

        def encode_addon(path: Path) -> str:
            # . unpacked add-on folder
            """Read and base64-encode the validated local Firefox add-on archive.

            Args:
                path: Filesystem path to inspect or operate on.

            Returns:
                The base64-encoded archive string sent to GeckoDriver.
            """
            if path.is_dir():
                return encode_dir_to_firefox_wire_protocol(path)
            # . packed add-on file
            elif path.is_file() and is_zipfile(path):
                return self._encode_base64(path.read_bytes(), "utf-8")
            # . invalid add-on
            else:
                raise errors.InvalidExtensionError(
                    "<{}>\nInvalid Firefox add-on: {}. Must either be a .xpi file or "
                    "an unpacked folder".format(self.__class__.__name__, repr(path))
                )

        if not isinstance(temporary, bool):
            raise errors.InvalidArgumentError("temporary must be a bool")
        addons = []
        for path in paths:
            # . Validate add-on path
            try:
                addon_path = parse_path(path)
                if not (addon_path.is_dir() or addon_path.is_file()):
                    raise errors.InvalidExtensionError("Add-on path does not exist")
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nExtension 'path' error: {}".format(
                        self.__class__.__name__, err
                    )
                ) from err
            # . extract add-on details
            try:
                details = await run_blocking(extract_firefox_addon_details, addon_path)
            except Exception as err:
                raise errors.InvalidExtensionError(
                    f"<{self.__class__.__name__}>\n{err}"
                ) from err
            if details.id in self._addon_by_id:
                continue
            # . encode add-on data
            try:
                addon = await run_blocking(encode_addon, addon_path)
            except errors.InvalidExtensionError:
                raise
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nFailed to encode add-on: {}\nError: {}".format(
                        self.__class__.__name__, repr(addon_path), err
                    )
                ) from err
            # . install add-on
            try:
                res = await self._conn.execute(
                    self._base_url,
                    Command.FIREFOX_INSTALL_ADDON,
                    body={"addon": addon, "temporary": temporary},
                )
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nFailed to install add-on: {}\nError: {}".format(
                        self.__class__.__name__, repr(addon_path), err
                    )
                )
            # . parse add-on ID
            addon_id = res.get("value") if isinstance(res, dict) else None
            if not isinstance(addon_id, str) or not addon_id.strip():
                raise errors.InvalidResponseError(
                    f"<{self.__class__.__name__}>\nFirefox add-on installation "
                    "response must contain a non-blank string value ID."
                )
            # . cache add-on details
            details.id = addon_id
            self._addon_by_id[addon_id] = details
            addons.append(details)

        # Return add-on IDs
        return addons

    async def uninstall_addon(self, addon: str | FirefoxAddon) -> bool:
        """Uninstall a previously installed add-on.

        Args:
            addon: The add-on to uninstall, accepts both add-on ID and  instance.

        Returns:
            True if the add-on has been uninstalled, False if add-on not exists.

        Example:
            >>> # Install add-ons
            >>> addons = await session.install_addons(
            ...     "~/path/to/addon1.xpi",
            ...     "~/path/to/addon2",
            ... )
            >>> # [
            >>> #   <FirefoxAddon (id='addon1@id', name='Addon 1', version='1.0.0')>,
            >>> #   <FirefoxAddon (id='addon2@id', name='Addon 2', version='1.0.0')>
            >>> # ]

            >>> # Uninstall add-on by ID
            >>> await session.uninstall_addon("addon1@id")  # True

            >>> # Uninstall add-on by instance
            >>> await session.uninstall_addon(addons[1])  # True
        """
        # Validate add-on
        if isinstance(addon, str):
            id_ = addon
        elif isinstance(addon, FirefoxAddon):
            id_ = addon.id
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid addon: {} {}.".format(
                    self.__class__.__name__, repr(addon), type(addon)
                )
            )
        # Uninstall add-on
        await self._conn.execute(
            self._base_url, Command.FIREFOX_UNINSTALL_ADDON, body={"id": id_}
        )
        # Remove cached add-on details
        try:
            self._addon_by_id.pop(id_)
            return True
        except KeyError:
            return False

    # Special methods ---------------------------------------------------------------------
    def _collect_garbage(self) -> None:
        """Collect garbage."""
        super()._collect_garbage()
        # Add-ons
        self._addon_by_id = None
