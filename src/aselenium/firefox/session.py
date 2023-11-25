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
import os
from typing import Literal
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, is_zipfile
from aselenium import errors
from aselenium.logs import logger
from aselenium.command import Command
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.service import FirefoxService
from aselenium.firefox.utils import FirefoxAddon, extract_firefox_addon_details
from aselenium.session import Session, SessionContext
from aselenium.utils import is_path_file, is_path_dir, is_file_dir_exists

__all__ = ["FirefoxSession", "FirefoxSessionContext"]


# Firefox Session ---------------------------------------------------------------------------------
class FirefoxSession(Session):
    """Represents a session of the Firefox browser."""

    def __init__(self, options: FirefoxOptions, service: FirefoxService) -> None:
        super().__init__(options, service)
        # Add-ons
        self._addon_by_id: dict[str, FirefoxAddon] = {}
        if self.options.profile is not None:
            self._addon_by_id |= options.profile.extensions

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> FirefoxOptions:
        """Access the Firefox options `<FirefoxOptions>`."""
        return self._options

    @property
    def service(self) -> FirefoxService:
        """Access the Firefox service `<FirefoxService>`."""
        return self._service

    # Information -------------------------------------------------------------------------
    async def take_full_screenshot(self) -> bytes:
        """Take a FULL document screenshot of the active
        page window `<bytes>`.

        ### Example:
        >>> screenshot = await session.take_screenshot()
            # b'iVBORw0KGgoAAAANSUhEUgAA...'
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
                "<{}>\nInvalid full document screenshot response: "
                "{}".format(self.__class__.__name__, res)
            ) from err

    async def save_full_screenshot(self, path: str) -> bool:
        """Take & save the FULL document screenshot of the active
        page window into a local PNG file.

        :param path: `<str>` The path to save the screenshot. e.g. `~/path/to/screenshot.png`.
        :return `<bool>`: True if the screenshot has been saved, False if failed.

        ### Example:
        >>> await session.save_full_screenshot("~/path/to/screenshot.png")
            # True / False
        """
        # Validate screenshot path
        if not is_file_dir_exists(path):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid `save_full_screenshot()` path: {}. "
                "File directory might not exist.".format(
                    self.__class__.__name__, repr(path)
                )
            )
        if not path.endswith(".png"):
            path += ".png"

        # Take & save screenshot
        data = None
        try:
            # . take screenshot
            data = await self.take_full_screenshot()
            if not data:
                return False
            # . save screenshot
            try:
                with open(path, "wb") as file:
                    file.write(data)
                return True
            except Exception as err:
                logger.error(
                    "<{}> Failed to save FULL document screenshot: "
                    "{}".format(self.__class__.__name__, err)
                )
                return False
        finally:
            del data

    # Firefox - Context -------------------------------------------------------------------
    @property
    async def context(self) -> Literal["content", "chrome"]:
        """Access the current context of the session `<str>`.
        Expected values: `'content'` or `'chrome'`.

        ### Notice:
        Different from Selenium, the 'context' in this module is not a context
        manager, but an async property to access the current context of the
        session. For more information on how to switch context, please refer
        to the `set_context()` and `reset_context()` methods.

        ### Example:
        >>> await session.context  # "content" / "chrome"
        """
        res = await self.execute_command(Command.FIREFOX_GET_CONTEXT)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse context from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def set_context(
        self,
        context: Literal["content", "chrome"],
    ) -> Literal["content", "chrome"]:
        """Set the context of the session.

        :param context: `<str>` The context to set. Accepts either `'content'` or `'chrome'`.
        :return `<str>`: The context of the session after update.

        ### Example:
        >>> await session.set_context("chrome")  # "chrome"
            # ... do stuff in chrome context ...

        >>> await session.reset_context()  # "content"
            # Reset context back to "content"
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

        :return `<str>`: The context of the session after update.

        ### Example:
        >>> await session.set_context("chrome")  # "chrome"
            # ... do stuff in chrome context ...

        >>> await session.reset_context()  # "content"
            # Reset context back to "content"
        """
        await self.execute_command(
            Command.FIREFOX_SET_CONTEXT, body={"context": "content"}
        )
        return await self.context

    # Firefox - Addons --------------------------------------------------------------------
    @property
    def addons(self) -> list[FirefoxAddon]:
        """Access the details of the installed add-ons `<list[FirefoxAddon]>`.
        `(NOT an asyncronous attribute)`.

        ### Example:
        >>> await session.install_addons("~/path/to/addon.xpi")
            addons = session.addons
            # [<FirefoxAddon (id='addon1@id', name='Addon 1', version='1.0.0', unpack=False)>]
        """
        return list(self._addon_by_id.values())

    async def install_addons(
        self,
        *paths: str,
        temporary: bool = False,
    ) -> list[FirefoxAddon]:
        """Install Firefox add-ons.

        :param paths: `<str>` The paths to the add-on files (\\*.xpi) or unpacked folders.
        :param temporary: `<bool>` Whether to install the add-ons temporarily. Defaults to `False`.
        :return `<list[FirefoxAddon]>`: The details of the installed add-ons.

        ### Example:
        >>> # Install add-ons
            addons = await session.install_addons(
                "~/path/to/addon1.xpi",
                "~/path/to/addon2",
            )
            # [
            #   <FirefoxAddon (id='addon1@id', name='Addon 1', version='1.0.0', unpack=False)>,
            #   <FirefoxAddon (id='addon2@id', name='Addon 2', version='1.0.0', unpack=False)>
            # ]
        """

        def encode_addon(path: str) -> str:
            # . unpacked add-on folder
            if is_path_dir(path):
                fp = BytesIO()
                path_root = len(path) + 1  # account for trailing slash
                with ZipFile(fp, "w", ZIP_DEFLATED) as zip:
                    for base, _, files in os.walk(path):
                        for fyle in files:
                            filename = os.path.join(base, fyle)
                            zip.write(filename, filename[path_root:])
                return self._encode_base64(fp.getvalue(), "utf-8")
            # . packed add-on file
            elif is_path_file(path) and is_zipfile(path):
                with open(path, "rb") as file:
                    return self._encode_base64(file.read(), "utf-8")
            # . invalid add-on
            else:
                raise errors.InvalidExtensionError(
                    "<{}>\nInvalid Firefox add-on: {}. Must either be a .xpi file or "
                    "an unpacked folder".format(self.__class__.__name__, repr(path))
                )

        addons = []
        for path in paths:
            # . extract add-on details
            try:
                details = extract_firefox_addon_details(path)
            except Exception as err:
                raise errors.InvalidExtensionError(
                    f"<{self.__class__.__name__}>\n{err}"
                ) from err
            if details.id in self._addon_by_id:
                continue
            # . encode add-on data
            try:
                addon = encode_addon(path)
            except errors.InvalidExtensionError:
                raise
            except Exception as err:
                raise errors.InvalidExtensionError(
                    "<{}>\nFailed to encode add-on: {}\n"
                    "Error: {}".format(self.__class__.__name__, repr(path), err)
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
                    "<{}>\nFailed to install add-on: {}\n"
                    "Error: {}".format(self.__class__.__name__, repr(path), err)
                )
            # . parse add-on ID
            try:
                addon_id = res["value"]
            except KeyError as err:
                raise errors.InvalidResponseError(
                    "<{}>\nFailed to parse add-on ID from response: {}".format(
                        self.__class__.__name__, res
                    )
                ) from err
            # . cache add-on details
            details.id = addon_id
            self._addon_by_id[addon_id] = details
            addons.append(details)

        # Return add-on IDs
        return addons

    async def uninstall_addon(self, addon: str | FirefoxAddon) -> bool:
        """Uninstall a previously installed add-on.

        :param addon: `<str/FirefoxAddon>` The add-on to uninstall, accepts both add-on ID and `<FirefoxAddon>` instance.
        :return `<bool>`: True if the add-on has been uninstalled, False if add-on not exists.

        ### Example:
        >>> # Install add-ons
            addons = await session.install_addons(
                "~/path/to/addon1.xpi",
                "~/path/to/addon2",
            )
            # [
            #   <FirefoxAddon (id='addon1@id', name='Addon 1', version='1.0.0', unpack=False)>,
            #   <FirefoxAddon (id='addon2@id', name='Addon 2', version='1.0.0', unpack=False)>
            # ]

        >>> # Uninstall add-on by ID
            await session.uninstall_addon("addon1@id")  # True

        >>> # Uninstall add-on by instance
            await session.uninstall_addon(addons[1])  # True
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
        """(Internal) Collect garbage."""
        super()._collect_garbage()
        # Add-ons
        self._addon_by_id = None


class FirefoxSessionContext(SessionContext):
    """The context manager for the Firefox session."""

    def __init__(self, options: FirefoxOptions, service: FirefoxService) -> None:
        """The context manager for a Firefox session.

        :param options: `<FirefoxOptions>` The browser options.
        :param service: `<FirefoxService>` The browser service.
        """
        self._session = FirefoxSession(options, service)

    async def __aenter__(self) -> FirefoxSession:
        return await self.start()
