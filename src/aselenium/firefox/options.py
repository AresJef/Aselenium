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
from io import BytesIO
from copy import deepcopy
import os, tempfile, shutil
from base64 import b64encode
from zipfile import ZipFile, ZIP_DEFLATED
from aselenium import errors
from aselenium.options import BaseOptions
from aselenium.utils import is_path_file, is_path_dir
from aselenium.firefox.utils import FirefoxAddon, extract_firefox_addon_details


__all__ = ["FirefoxProfile", "FirefoxOptions"]


# Option Objects ----------------------------------------------------------------------------------
class FirefoxProfile:
    """Represents the user profile for Firefox."""

    def __init__(self, directory: str, temporary: bool = True) -> None:
        """The user profile for Firefox.

        :param directory: `<str>` The directory of the Firefox profile.
        :param temporary: `<bool>` Whether to create a temporary profile. Defaults to `True`.
            - If `True`, a cloned temporary profile will be created based on the given
              'directory'. After all related sessions are closed, the temporary profile
              will be deleted automatically, leaving the original profile untouched.
            - If `False`, the original profile will be used directly. Any changes made
              (e.g. `add_extension()`, `set_preference()`) will be saved to the profile.
            - *Notice*: In some rare cases (such as KeyboardInterrupt exception), the
              temporary profile might not be deleted properly. In this case, a warning
              message will be printed to the console, warning user to manually delete
              the remaining temporary files if necessary (The temporary profile is always
              located in the 'Standard Location for Temporary Files' in the system, and
              most systems should delete these temporary files after a system reboot).

        ### Location:
        >>> # . the default profile directory for Firefox on MacOS:
            directory="/Users/<username>/Library/Application Support/Firefox/Profiles/<profile_folder>"

        >>> # . the default profile directory for Firefox on Windows:
            directory="C:\\Users\\<username>\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\<profile_folder>"

        >>> # . the default profile directory for Firefox on Linux:
            directory="/home/<username>/.mozilla/firefox/<profile_folder>"
        """
        # Profile directory
        if not is_path_dir(directory):
            raise errors.InvalidProfileError(
                "<{}>\nInvalid profile directory: {} {}".format(
                    self.__class__.__name__, repr(directory), type(directory)
                )
            )
        self._directory: str = directory
        # Temporary profile
        self._temp_directory: str = None
        self._temp_profile_dir: str = None
        if temporary:
            self._create_temp_profile()
        # Extensions
        self._extension_details: dict[str, FirefoxAddon] = {}
        self._extensions_dir = os.path.join(self.directory_for_driver, "extensions")
        if is_path_dir(self._extensions_dir):
            self._load_user_extensions()
        # Profile Encode
        self.__encode: str = None

    # Properties --------------------------------------------------------------------------
    @property
    def directory(self) -> str | None:
        """Access the directory of the profile folder `<str>`."""
        return self._directory

    @property
    def directory_for_driver(self) -> str:
        """Access the directory to be used by the webdriver `<str>`.

        - If temporary mode (`temporary=True` or `directory=None`), returns
          the temporary directory instead of the original profile directory.
        - If the profile is in normal mode (`temporary=False`), returns the
          original profile directory (equivalent to the 'directory' attribute).
        """
        if self._temp_directory is not None:
            return self._temp_profile_dir
        else:
            return self._directory

    @property
    def encode(self) -> str:
        """A zipped, base64 encoded string of profile directory for use with
        remote WebDriver JSON wire protocol `<str>`.
        """
        # Already encoded
        if self.__encode is not None:
            return self.__encode

        # Encode profile
        fp = BytesIO()
        with ZipFile(fp, "w", ZIP_DEFLATED) as zip:
            path_root = len(self.directory_for_driver) + 1
            for base, _, files in os.walk(self.directory_for_driver):
                for fyle in files:
                    filename = os.path.join(base, fyle)
                    zip.write(filename, filename[path_root:])
        self.__encode = b64encode(fp.getvalue()).decode("utf-8")
        return self.__encode

    # Temporary profile -------------------------------------------------------------------
    def _create_temp_profile(self) -> None:
        """(Internal) Create a temporary profile
        based on the original profile.
        """
        # Temporary profile already created
        if self._temp_directory is not None:
            return None  # exit

        # Create temporary directory
        self._temp_directory = tempfile.mkdtemp()

        # Create temporary profile
        self._temp_profile_dir = os.path.join(self._temp_directory, "TEMP_PROFILE")
        if self._directory is not None:
            shutil.copytree(
                self._directory,
                self._temp_profile_dir,
                ignore=shutil.ignore_patterns("parent.lock", "lock", ".parentlock"),
            )
        else:
            os.makedirs(self._temp_profile_dir)
        os.chmod(self._temp_profile_dir, 0o755)

    def _delete_temp_profile(self) -> None:
        """(Internal) Delete the temporary profile
        without affecting the original profile.
        """
        # Temporary profile not created
        if self._temp_directory is None:
            return None  # exit

        # Delete temporary profile
        warning = False
        while is_path_dir(self._temp_directory):
            try:
                shutil.rmtree(self._temp_directory)
            except OSError:
                warning = True
        if warning:
            print(
                "\n<{}> Encountered unexpected error when deleting temporary profile, "
                "there might be some files left in the temporary directory: '{}'\n".format(
                    self.__class__.__name__, self._temp_directory
                )
            )
        self._temp_directory = None

    # Extensions --------------------------------------------------------------------------
    @property
    def extensions(self) -> dict[str, FirefoxAddon]:
        """Access the extension details of the profile `<dict[str, FirefoxAddon]>`."""
        return self._extension_details

    def _load_user_extensions(self) -> None:
        """(Internal) Load the user extension details from the profile directory."""
        for file in os.listdir(self._extensions_dir):
            try:
                details = extract_firefox_addon_details(
                    os.path.join(self._extensions_dir, file)
                )
                self._extension_details[details.id] = details
            except errors.InvalidExtensionError:
                pass

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (directory='%s', temporary=%s)>" % (
            self.__class__.__name__,
            self.directory_for_driver,
            self._temp_directory is not None,
        )

    def __hash__(self) -> int:
        return hash(self.__repr__())

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __bool__(self) -> bool:
        return True

    def __del__(self):
        self._delete_temp_profile()


# Firefox Options ---------------------------------------------------------------------------------
class FirefoxOptions(BaseOptions):
    """Firefox options."""

    DEFAULT_CAPABILITIES: dict[str, Any] = {
        "browserName": "firefox",
        "acceptInsecureCerts": True,
        "moz:debuggerAddress": True,
    }
    "the default capabilities of the firefox browser `dict[str, Any]`"
    KEY: str = "moz:firefoxOptions"
    "The unique option key for the firefox browser `str`"

    def __init__(self) -> None:
        super().__init__()
        # Settings
        self._experimental_options: dict[str, Any] = {}
        self._profile: FirefoxProfile | None = None
        self._preferences: dict[str, Any] = {}
        self._extensions: list[str] = []

    # Caps: basic -------------------------------------------------------------------------
    def construct(self) -> dict[str, Any]:
        """Construct the final capabilities for the browser."""
        # Base caps
        caps = deepcopy(self._capabilities)

        # Experimental Options
        options = deepcopy(self._experimental_options)
        if self._preferences:
            options["prefs"] = self.preferences
        if self._profile:
            options["profile"] = self._profile.encode
        if self._arguments:
            options["args"] = self.arguments
        caps[self.KEY] = options

        # Return caps
        return caps

    # Options: binary location ------------------------------------------------------------
    @property
    def binary_location(self) -> str | None:
        """Access the binary location of the Brwoser executable `<str>`."""
        return self._experimental_options.get("binary", None)

    @binary_location.setter
    def binary_location(self, value: str | None) -> None:
        # Remove binary location
        if value is None:
            try:
                self._experimental_options.pop("binary")
                self._caps_changed()
            except KeyError:
                pass
            return None  # exit

        # Set binary location
        if not is_path_file(value):
            raise errors.InvalidOptionsError(
                "<{}>\nBrowser 'binary_location' not found at: "
                "{}".format(self.__class__.__name__, repr(value))
            )
        self._experimental_options["binary"] = value
        self._caps_changed()

    # Options: accept insecure certs ------------------------------------------------------
    @property
    def accept_insecure_certs(self) -> bool:
        """Access whether untrusted and self-signed TLS certificates
        are implicitly trusted on navigation. Defaults to `False <bool>`.
        """
        return self._capabilities.get("acceptInsecureCerts", False)

    @accept_insecure_certs.setter
    def accept_insecure_certs(self, value: bool) -> None:
        self.set_capability("acceptInsecureCerts", bool(value))

    # Options: profile --------------------------------------------------------------------
    @property
    def profile(self) -> FirefoxProfile | None:
        """Access the profile of the browser `<FirefoxProfile>`.
        Returns `None` if profile is not configured.
        """
        return self._profile

    @profile.setter
    def profile(self, value: FirefoxProfile | None) -> None:
        # Remove profile
        if value is None:
            if self._profile is not None:
                self._profile = None
                self._caps_changed()
            return None  # exit

        # Set profile
        if not isinstance(value, FirefoxProfile):
            raise errors.InvalidProfileError(
                "<{}>\nInvalid 'profile' ({} {}), must be an "
                "instance of `<FirefoxProfile>'.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        self._profile = value
        self._caps_changed()

    def set_profile(self, directory: str, temporary: bool = True) -> FirefoxProfile:
        """Set the user profile for Firefox.

        :param directory: `<str>` The directory of the Firefox profile.
        :param temporary: `<bool>` Whether to create a temporary profile. Defaults to `True`.
            - If `True`, a cloned temporary profile will be created based on the given
              'directory'. After all related sessions are closed, the temporary profile
              will be deleted automatically, leaving the original profile untouched.
            - If `False`, the original profile will be used directly. Any changes made
              (e.g. `add_extension()`, `set_preference()`) will be saved to the profile.
            - *Notice*: In some rare cases (such as KeyboardInterrupt exception), the
              temporary profile might not be deleted properly. In this case, a warning
              message will be printed to the console, warning user to manually delete
              the remaining temporary files if necessary (The temporary profile is always
              located in the 'Standard Location for Temporary Files' in the system, and
              most systems should delete these temporary files after a system reboot).

        :return `<FirefoxProfile>`: The profile instance.

        ### Location:
        >>> # . the default profile directory for Firefox on MacOS:
            directory="/Users/<username>/Library/Application Support/Firefox/Profiles/<profile_folder>"

        >>> # . the default profile directory for Firefox on Windows:
            directory="C:\\Users\\<username>\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\<profile_folder>"

        >>> # . the default profile directory for Firefox on Linux:
            directory="/home/<username>/.mozilla/firefox/<profile_folder>"

        ### Example:
        >>> # . set profile
            options.set_profile(directory, True)
        """
        self.profile = FirefoxProfile(directory, temporary)
        return self._profile

    def rem_profile(self) -> None:
        """Remove the previously configured profile for Firefox.

        ### Example:
        >>> # . set profile
            options.set_profile(directory, True)

        >>> # . remove the profile
            options.rem_profile()
        """
        self.profile = None

    # Options: preferences ----------------------------------------------------------------
    @property
    def preferences(self) -> dict[str, Any]:
        """Access the preferences of the browser `<dict[str, Any]>`."""
        return deepcopy(self._preferences)

    def set_preference(self, name: str, value: Any) -> None:
        """Set a preference of the browser.

        :param name: `<str>` The name of the preference.
        :param value: `<Any>` The value of the preference.

        ### Example:
        >>> options.set_preference("media.navigator.permission.disabled", False)
        """
        # Set preference
        if not isinstance(name, str) or not name:
            raise errors.InvalidOptionsError(
                "<{}>\nInvalid 'preferences' name: {} {}.".format(
                    self.__class__.__name__, repr(name), type(name)
                )
            )
        self._preferences[name] = value
        self._caps_changed()

    def get_preference(self, name: str) -> Any:
        """Get a preference value of the browser.

        :param name: `<str>` The name of the preference.
        :raises `OptionsNotSetError`: If the preference is not set.
        :return `<Any>` The value of the preference.
        """
        try:
            return self._preferences[name]
        except KeyError as err:
            raise errors.OptionsNotSetError(
                "<{}>\nPreference {} has not been set.".format(
                    self.__class__.__name__, repr(name)
                )
            ) from err

    def rem_preference(self, name: str) -> None:
        """Remove a preference of the browser.

        :param name: `<str>` The name of the preference.

        ### Example:
        >>> options.rem_preference("media.navigator.permission.disabled")
        """
        # Remove preference
        try:
            self._preferences.pop(name)
            self._caps_changed()
        except KeyError:
            pass
