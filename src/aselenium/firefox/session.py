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

"""Firefox-specific session commands, contexts, screenshots, and add-ons."""

from __future__ import annotations

from base64 import b64encode
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
    _encode_dir_to_firefox_wire_protocol,
    _extract_firefox_addon_details,
)
from aselenium.session import Session

if TYPE_CHECKING:
    from aselenium.firefox.options import FirefoxOptions
    from aselenium.firefox.service import FirefoxService
    from aselenium.manager.version import GeckoVersion

__all__ = ["FirefoxSession"]


def _encode_addon_path(path: Path) -> str:
    """Encode one validated add-on path for GeckoDriver.

    Args:
        path: Existing ZIP archive or unpacked add-on directory.

    Returns:
        Base64-encoded ZIP data accepted by GeckoDriver.

    Raises:
        errors.InvalidExtensionError: If `path` is not a directory or ZIP archive.
    """
    if path.is_dir():
        return _encode_dir_to_firefox_wire_protocol(path)
    if path.is_file() and is_zipfile(path):
        return b64encode(path.read_bytes()).decode("ascii")
    raise errors.InvalidExtensionError(
        f"Invalid Firefox add-on: {path!r}. Must be a ZIP archive "
        "(normally .xpi) or an unpacked directory"
    )


# Firefox Session ---------------------------------------------------------------------------------
class FirefoxSession(Session):
    """Represent a session of the Firefox browser."""

    def __init__(self, options: FirefoxOptions, service: FirefoxService) -> None:
        """Initialize a Firefox session around owned options and service objects.

        Args:
            options: Firefox configuration snapshot for the session.
            service: GeckoDriver service owned by the session.
        """
        super().__init__(options, service)
        self._options: FirefoxOptions | None = options
        self._service: FirefoxService | None = service
        # Add-ons
        self._addon_by_id: dict[str, FirefoxAddon] = {}
        profile = options.profile
        if profile is not None:
            self._addon_by_id |= profile.extensions

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> FirefoxOptions:
        """Return the Firefox options.

        Returns:
            The browser options owned by this facade or session.
        """
        options = self._options
        if options is None:
            raise errors.InvalidSessionError("Session options have been released")
        return options

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
        service = self._service
        if service is None:
            raise errors.InvalidSessionError("Session service has been released")
        return service

    @property
    def driver_version(self) -> GeckoVersion:
        """Return the WebDriver binary version of the session.

        Returns:
            The WebDriver binary version of the session.
        """
        return self.service.driver_version

    # Information -------------------------------------------------------------------------
    async def take_full_screenshot(self) -> bytes:
        """Capture the entire active document as PNG data.

        Returns:
            Decoded PNG bytes for the full document.

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
        """Capture the entire active document and save it as PNG.

        Args:
            path: Destination supplied as a string, `pathlib.Path`, or compatible
                `os.PathLike[str]`. Relative paths are resolved from the current
                working directory, `~` is expanded, and `.png` is appended unless
                the filename already ends with that exact suffix.

        Returns:
            `True` if nonempty screenshot data was written; otherwise `False`.

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
        """Return the current Firefox command context.

        This async property reports either the normal page-content context or
        Firefox's privileged chrome context. Use `set_context()` and
        `reset_context()` to change it.

        Returns:
            The current context, either "content" or "chrome".

        Raises:
            errors.InvalidResponseError: If GeckoDriver returns a missing or unsupported context.

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
        """Set and observe the Firefox context under shared command ownership.

        Use ``session.transaction()`` around the context change and dependent
        commands when they must run before another task changes the context.

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
        async with self.transaction():
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
        async with self.transaction():
            await self.execute_command(
                Command.FIREFOX_SET_CONTEXT, body={"context": "content"}
            )
            context = await self.context
            if context != "content":
                raise errors.InvalidResponseError(
                    "GeckoDriver did not reset the session to content context"
                )
            return context

    # Firefox - Addons --------------------------------------------------------------------
    @property
    def addons(self) -> list[FirefoxAddon]:
        """Return a snapshot of add-ons known to this session.

        Returns:
            Cached add-on metadata in installation order.

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
            *paths: Add-on ZIP archives (normally `.xpi` files) or unpacked add-on
                directories, supplied as strings, `pathlib.Path` objects, or
                compatible `os.PathLike[str]` values. Relative paths are resolved
                from the current working directory and `~` is expanded.

        Returns:
            Metadata for add-ons installed by this call, excluding already-known IDs.
            Successfully confirmed installations remain cached if a later add-on fails.

        Raises:
            errors.InvalidArgumentError: If `temporary` is not a boolean.
            errors.InvalidExtensionError: If an add-on cannot be read, encoded, or installed.
            errors.InvalidResponseError: If GeckoDriver does not return a non-blank string ID.
                The remote installation may have succeeded even when its response is
                invalid; this method does not cache an unconfirmed add-on ID.

        Example:
            >>> # Install add-ons
            >>> addons = await session.install_addons(
            ...     "~/path/to/addon1.xpi",
            ...     "~/path/to/addon2",
            ... )
        """
        if not isinstance(temporary, bool):
            raise errors.InvalidArgumentError("temporary must be a bool")
        addons: list[FirefoxAddon] = []
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
                details = await run_blocking(_extract_firefox_addon_details, addon_path)
            except Exception as err:
                raise errors.InvalidExtensionError(
                    f"<{self.__class__.__name__}>\n{err}"
                ) from err
            if details.id in self._addon_by_id:
                continue
            # . encode add-on data
            try:
                addon = await run_blocking(_encode_addon_path, addon_path)
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
                res = await self.execute_command(
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
            addon: Installed `FirefoxAddon` object or its GeckoDriver add-on ID.

        Returns:
            `True` if cached add-on metadata was removed; `False` if the ID was
            not present in the local cache. A `False` result does not mean the
            GeckoDriver uninstall command failed.

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
        id_: str | None
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
        if not id_:
            raise errors.InvalidArgumentError("Firefox add-on ID must be nonempty")
        # Uninstall add-on
        await self.execute_command(Command.FIREFOX_UNINSTALL_ADDON, body={"id": id_})
        # Remove cached add-on details
        try:
            self._addon_by_id.pop(id_)
            return True
        except KeyError:
            return False

    # Special methods ---------------------------------------------------------------------
    def _collect_garbage(self) -> None:
        """Release cached add-on metadata after base session cleanup."""
        super()._collect_garbage()
        addons = getattr(self, "_addon_by_id", None)
        if addons is not None:
            addons.clear()
