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
"""Aselenium utils implementation and supporting types."""

from __future__ import annotations

from base64 import b64encode
from io import BytesIO
from os import walk as walk_path
from os.path import join as join_path
from os.path import relpath
from typing import (
    Any,
)
from zipfile import ZIP_DEFLATED, ZipFile, is_zipfile

from orjson import loads

from aselenium import errors
from aselenium.utils import CustomDict, is_path_dir, is_path_file, validate_dir


# Utils: addon ------------------------------------------------------------------------------------
class FirefoxAddon(CustomDict):
    """Represent the detail of a Firefox add-on."""

    def __init__(self, **details: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            **details: The detail of the add-on.
        """
        super().__init__(**details)

    # Properties --------------------------------------------------------------------------
    @property
    def id(self) -> str | None:
        """Return the identifier of the add-on.

        Returns:
            The add-on identifier, or None before a temporary add-on receives an ID.
        """
        return self["id"]

    @id.setter
    def id(self, value: str) -> None:
        """Set the identifier of the add-on.

        Args:
            value: New id value.
        """
        self["id"] = value

    @property
    def name(self) -> str:
        """Return the name of the add-on.

        Returns:
            The name of the add-on.
        """
        return self["name"]

    @property
    def version(self) -> str:
        """Return the version of the add-on.

        Returns:
            The version of the add-on.
        """
        return self["version"]

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (id='%s', name='%s', version='%s')>" % (
            self.__class__.__name__,
            self.id,
            self.name,
            self.version,
        )

    def copy(self) -> FirefoxAddon:
        """Copy the Firefox Addon object.

        Returns:
            An independent copy of this value object.
        """
        return FirefoxAddon(**self._dict)


def extract_firefox_addon_details(path: str) -> FirefoxAddon:
    """Extract the details of a Firefox addon.

    Args:
        path: The absolute path to the addon file (//.xpi) or folder.

    Returns:
        The details of the addon.

    Example:
        >>> details = extract_firefox_addon_details("/path/to/extension.xpi")
    """

    def parse_manifest_json(content: str | bytes) -> FirefoxAddon:
        """Validate a WebExtension manifest and extract its identity fields.

        Args:
            content: Manifest or downloaded resource content to decode.

        Returns:
            An add-on containing the validated name, version, and optional Gecko ID.
        """
        manifest = loads(content)
        if (
            not isinstance(manifest, dict)
            or type(manifest.get("manifest_version")) is not int
            or manifest["manifest_version"] not in (2, 3)
        ):
            raise ValueError("Expected a WebExtension manifest_version of 2 or 3")
        if "applications" in manifest:
            raise ValueError(
                "Use browser_specific_settings instead of the removed applications key"
            )
        for key in ("name", "version"):
            if not isinstance(manifest.get(key), str) or not manifest[key].strip():
                raise ValueError("Manifest %s must be a nonempty string" % key)
        settings = manifest.get("browser_specific_settings", {})
        if not isinstance(settings, dict) or not isinstance(
            settings.get("gecko", {}), dict
        ):
            raise ValueError("browser_specific_settings.gecko must be an object")
        # Temporary add-ons can receive their identifier from Firefox.
        id = settings.get("gecko", {}).get("id")
        if id is not None and (not isinstance(id, str) or not id.strip()):
            raise ValueError("The Gecko add-on id must be a nonempty string")
        return FirefoxAddon(
            id=id,
            name=manifest["name"],
            version=manifest["version"],
        )

    # Extract add-on details
    try:
        if is_path_file(path) and is_zipfile(path):
            with ZipFile(path, "r") as zip:
                return parse_manifest_json(zip.read("manifest.json"))
        elif is_path_dir(path):
            with open(join_path(path, "manifest.json"), "r", encoding="utf-8") as file:
                return parse_manifest_json(file.read())
        else:
            raise errors.InvalidExtensionError(
                "Invalid Firefox add-on path: {}. Must either be a .xpi "
                "add-on file or a folder containing the unpacked add-on "
                "data.".format(repr(path))
            )
    except errors.InvalidExtensionError:
        raise
    except Exception as err:
        raise errors.InvalidExtensionError(
            f"Invalid Firefox WebExtension: {repr(path)}. A valid manifest.json is required. Error: {err}"
        ) from err


def encode_dir_to_firefox_wire_protocol(directory: str) -> str:
    """Encode a directory as a base64 ZIP with paths relative to its root.

    Args:
        directory: Existing directory path; relative paths and trailing separators
            are normalized before deriving archive member names.

    Returns:
        The ZIP bytes encoded as base64 text for Firefox's profile/add-on protocol.

    Raises:
        AseleniumInvalidPathError: If the path is invalid or the directory is missing.
        OSError: If a contained file cannot be read.
    """
    directory = validate_dir(directory)
    fp = BytesIO()
    with ZipFile(fp, "w", ZIP_DEFLATED) as zip:
        for base, _, files in walk_path(directory):
            for fyle in files:
                filename = join_path(base, fyle)
                zip.write(filename, relpath(filename, directory))
    return b64encode(fp.getvalue()).decode("utf-8")
