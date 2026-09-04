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
"""Aselenium options implementation and supporting types."""

from __future__ import annotations

from copy import deepcopy
from os import listdir
from os.path import join as join_path
from typing import (
    TYPE_CHECKING,
    Any,
)

from aselenium import errors
from aselenium.firefox.utils import (
    FirefoxAddon,
    encode_dir_to_firefox_wire_protocol,
    extract_firefox_addon_details,
)
from aselenium.options import BaseOptions, Profile
from aselenium.utils import is_path_dir

if TYPE_CHECKING:
    from aselenium.manager.version import FirefoxVersion

__all__ = ["FirefoxProfile", "FirefoxOptions"]


# Option Objects ----------------------------------------------------------------------------------
class FirefoxProfile(Profile):
    """Represent the user profile for Firefox."""

    def __init__(self, directory: str) -> None:
        r"""Initialize the instance with the supplied configuration.

        Explanation
        - When creating a `Profile` instance, a cloned temporary profile
          will be created based on the given profile 'directory'. The
          automated session will use this temporary profile leaving the
          original profile untouched. The owning options releases its clone
          on close(), rem_profile(), or successful replacement. A retained
          profile reference does not extend that ownership lifetime.

        Default Profile Location:
        - MacOS: '~/Library/Application Support/Firefox/Profiles/<profile_folder>'
        - Windows: 'C:\Users\<username>\AppData\Roaming\Mozilla\Firefox\Profiles\<profile_folder>'
        - Linux: '~/.mozilla/firefox/<profile_folder>'

        Args:
            directory: The directory of the Firefox profile.
        """
        super().__init__(directory, None)
        # Extensions
        self._extension_details: dict[str, FirefoxAddon] = {}
        self._extensions_dir = join_path(self._temp_profile_dir, "extensions")
        if is_path_dir(self._extensions_dir):
            self._load_user_extensions()
        # Profile Encode
        self._encode: str | None = None

    # Properties --------------------------------------------------------------------------
    @property
    def directory(self) -> str:
        """Return the directory of the original profile.

        Returns:
            The directory of the original profile.
        """
        return self._profile_dir

    @property
    def directory_temp(self) -> str:
        """Return the directory of the temporary profile.

        Returns:
            The directory of the temporary profile.
        """
        return self._temp_profile_dir

    @property
    def encode(self) -> str:
        """A zipped, base64 encoded string of the temporary profile for the remote W3C WebDriver protocol.

        Returns:
            The protocol representation of this value.
        """
        # Already encoded
        if self._encode is not None:
            return self._encode

        # Encode profile
        try:
            self._encode = encode_dir_to_firefox_wire_protocol(self._temp_profile_dir)
        except Exception as err:
            raise errors.InvalidProfileError(
                "<{}>\nFailed to encode the Firefox profile: {}".format(
                    self.__class__.__name__, err
                )
            ) from err
        return self._encode

    # Extensions --------------------------------------------------------------------------
    @property
    def extensions(self) -> dict[str, FirefoxAddon]:
        """Return the extension details of the profile.

        Returns:
            The extension details of the profile.
        """
        return self._extension_details

    def _load_user_extensions(self) -> None:
        """Load the user extension details from the profile."""
        for file in listdir(self._extensions_dir):
            try:
                details = extract_firefox_addon_details(
                    join_path(self._extensions_dir, file)
                )
                self._extension_details[details.id] = details
            except errors.InvalidExtensionError:
                pass


# Firefox Options ---------------------------------------------------------------------------------
class FirefoxOptions(BaseOptions):
    """Firefox options."""

    DEFAULT_CAPABILITIES: dict[str, Any] = {
        "browserName": "firefox",
        "acceptInsecureCerts": False,
        "moz:debuggerAddress": True,
    }
    "the default capabilities of the firefox browser `dict[str, Any]`"
    KEY: str = "moz:firefoxOptions"
    "The unique option key for the firefox browser `str`"

    def __init__(self) -> None:
        """Initialize the instance."""
        super().__init__()
        # Options
        self._profile: FirefoxProfile | None = None
        self._extensions: list[str] = []

    # Caps: basic -------------------------------------------------------------------------
    def construct(self) -> dict[str, Any]:
        """Construct the final capabilities for the browser.

        Returns:
            A mapping containing the construct data.
        """
        # Base caps
        caps = deepcopy(self._capabilities)

        # Experimental Options
        options = self.experimental_options
        if self._preferences:
            options["prefs"] = self.preferences
        if self._arguments:
            options["args"] = self.arguments
        if self._profile is not None:
            options["profile"] = self._profile.encode
        caps[self.KEY] = options

        # Return caps
        return caps

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
    def browser_version(self, value: FirefoxVersion | None) -> None:
        """Set the browser version.

        Args:
            value: New browser version value. None is handled according to the property's reset/ignore semantics.
        """
        self._set_browser_version(value)

    # Options: accept insecure certs ------------------------------------------------------
    @property
    def accept_insecure_certs(self) -> bool:
        """Return whether untrusted and self-signed TLS certificates are implicitly trusted on navigation. Defaults to `False <bool>`.

        Returns:
            True if untrusted and self-signed TLS certificates are implicitly trusted on navigation. Defaults to `False <bool>`; otherwise False.
        """
        return self._capabilities.get("acceptInsecureCerts", False)

    @accept_insecure_certs.setter
    def accept_insecure_certs(self, value: bool) -> None:
        """Set the accept insecure certs.

        Args:
            value: True explicitly permits untrusted certificates; False disables it.

        Raises:
            InvalidOptionsError: If value is not a bool.
        """
        self.set_capability(
            "acceptInsecureCerts", self._validate_bool(value, "accept_insecure_certs")
        )

    # Options: profile --------------------------------------------------------------------
    @property
    def profile(self) -> FirefoxProfile | None:
        """Return the profile of the browser. Returns `None` if profile is not configured.

        Notice
        - Please use `set_profile()` method to configure the profile.

        Returns:
            The profile of the browser. returns `none` if profile is not configured.
        """
        return self._profile

    def set_profile(self, directory: str) -> FirefoxProfile:
        r"""Set the user profile for Firefox.

        Explanation
        - When setting the profile through this method, a cloned temporary
          profile will be created based on the given profile 'directory'.
          The automated session will use the temporary profile leaving the
          original profile untouched. Replacing or removing the profile releases
          the previous clone, even if its returned profile object is still referenced.
          Call options.close() after the last use to release the selected clone.

        Default Profile Location:
        - MacOS: '~/Library/Application Support/Firefox/Profiles/<profile_folder>'
        - Windows: 'C:\Users\<username>\AppData\Roaming\Mozilla\Firefox\Profiles\<profile_folder>'
        - Linux: '~/.mozilla/firefox/<profile_folder>'

        Args:
            directory: The directory of the Firefox profile.

        Returns:
            The FirefoxProfile value produced by this operation.
        """
        # Create profile
        value = FirefoxProfile(directory)
        # Set profile
        self._replace_profile(value)
        return value

    def rem_profile(self) -> None:
        """Release the previously configured Firefox clone and its encoded capability.

        Example:
            >>> # . set a new profile
            >>> options.set_profile(directory)

            >>> # . remove the profile
            >>> options.rem_profile()
        """
        self.close()
