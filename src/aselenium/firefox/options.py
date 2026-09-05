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

"""Firefox capabilities and isolated profile encoding for GeckoDriver."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from aselenium import errors
from aselenium._paths import PathInput
from aselenium.firefox.utils import (
    FirefoxAddon,
    _encode_dir_to_firefox_wire_protocol,
    _extract_firefox_addon_details,
)
from aselenium.options import BaseOptions, Profile

__all__ = ["FirefoxProfile", "FirefoxOptions"]


# Option Objects ----------------------------------------------------------------------------------
class FirefoxProfile(Profile):
    """Own an isolated clone of a Firefox profile directory."""

    def __init__(self, directory: PathInput) -> None:
        r"""Clone an existing Firefox profile into an owned temporary directory.

        Explanation
        - When creating a `Profile` instance, a cloned temporary profile
          will be created based on the given profile 'directory'. The
          automated session will use this temporary profile leaving the
          original profile untouched. The owning options releases its clone
          on close(), rem_profile(), or successful replacement. A retained
          profile reference does not extend that ownership lifetime.

        Default Profile Location:
        - macOS: '~/Library/Application Support/Firefox/Profiles/<profile_folder>'
        - Windows: 'C:\Users\<username>\AppData\Roaming\Mozilla\Firefox\Profiles\<profile_folder>'
        - Linux: '~/.mozilla/firefox/<profile_folder>'

        Args:
            directory: The directory of the Firefox profile.
        """
        super().__init__(directory, None)
        # Extensions
        self._extension_details: dict[str, FirefoxAddon] = {}
        if self._temp_profile_dir is None:
            raise errors.InvalidProfileError(
                "Temporary Firefox profile was not created"
            )
        self._extensions_dir: Path | None = self._temp_profile_dir / "extensions"
        if self._extensions_dir.is_dir():
            self._load_user_extensions()
        # Profile Encode
        self._encode: str | None = None

    # Properties --------------------------------------------------------------------------
    @property
    def directory(self) -> Path:
        """Return the directory of the original profile.

        Returns:
            Validated absolute directory of the original Firefox profile.
        """
        assert self._profile_dir is not None
        return self._profile_dir

    @property
    def directory_temp(self) -> Path | None:
        """Return the directory of the temporary profile.

        Returns:
            Owned temporary Firefox profile directory, or ``None`` after cleanup.
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
            profile_dir = self._temp_profile_dir
            if profile_dir is None:
                raise errors.InvalidProfileError(
                    "Temporary Firefox profile is unavailable"
                )
            # The profile directory is already a validated, retained ``Path``.
            self._encode = _encode_dir_to_firefox_wire_protocol(profile_dir)
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
        """Return a snapshot of valid add-ons discovered in the cloned profile.

        Returns:
            Add-on identifiers mapped to independent metadata objects.
        """
        return {key: value.copy() for key, value in self._extension_details.items()}

    def _load_user_extensions(self) -> None:
        """Cache valid extension metadata found in the retained profile clone."""
        extensions_dir = self._extensions_dir
        if extensions_dir is None:
            return
        for path in extensions_dir.iterdir():
            try:
                # ``path`` is derived from the retained clone; do not send it
                # back through the public path parser.
                details = _extract_firefox_addon_details(path)
                addon_id = details.id
                if addon_id is not None:
                    self._extension_details[addon_id] = details
            except errors.InvalidExtensionError:
                pass

    def _delete_temp_profile(self) -> None:
        """Delete the owned clone and clear Firefox-specific derived state."""
        super()._delete_temp_profile()
        self._extensions_dir = None
        self._encode = None


# Firefox Options ---------------------------------------------------------------------------------
class FirefoxOptions(BaseOptions):
    """Build W3C capabilities and an optional isolated profile for Firefox.

    Attributes:
        DEFAULT_CAPABILITIES: Firefox's baseline session capabilities.
        KEY: GeckoDriver's ``moz:firefoxOptions`` capability key.
    """

    DEFAULT_CAPABILITIES: dict[str, Any] = {
        "browserName": "firefox",
        "acceptInsecureCerts": False,
        "moz:debuggerAddress": True,
    }
    KEY: str = "moz:firefoxOptions"

    # Caps: basic -------------------------------------------------------------------------
    def construct(self) -> dict[str, Any]:
        """Construct an independent Firefox W3C capability mapping.

        Returns:
            Base capabilities plus ``moz:firefoxOptions`` preferences,
            arguments, and an encoded profile when configured.
        """
        # Base caps
        caps = deepcopy(self._capabilities)

        # Experimental Options
        options = self.experimental_options
        if self._preferences:
            options["prefs"] = self.preferences
        if self._arguments:
            options["args"] = self.arguments
        profile = self.profile
        if profile is not None:
            options["profile"] = profile.encode
        caps[self.KEY] = options

        # Return caps
        return caps

    # Options: accept insecure certs ------------------------------------------------------
    @property
    def accept_insecure_certs(self) -> bool:
        """Return whether navigation accepts untrusted TLS certificates.

        Returns:
            ``True`` when WebDriver should trust otherwise invalid certificates;
            otherwise ``False``.
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
        """Return the currently owned Firefox profile clone.

        Returns:
            The configured profile, or ``None`` when no profile is selected.
        """
        return self._profile if isinstance(self._profile, FirefoxProfile) else None

    def set_profile(self, directory: PathInput) -> FirefoxProfile:
        r"""Set the user profile for Firefox.

        Explanation
        - When setting the profile through this method, a cloned temporary
          profile will be created based on the given profile 'directory'.
          The automated session will use the temporary profile leaving the
          original profile untouched. Replacing or removing the profile releases
          the previous clone, even if its returned profile object is still referenced.
          Call options.close() after the last use to release the selected clone.

        Default Profile Location:
        - macOS: '~/Library/Application Support/Firefox/Profiles/<profile_folder>'
        - Windows: 'C:\Users\<username>\AppData\Roaming\Mozilla\Firefox\Profiles\<profile_folder>'
        - Linux: '~/.mozilla/firefox/<profile_folder>'

        Args:
            directory: The directory of the Firefox profile.

        Returns:
            The new owned profile clone selected by these options.
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
