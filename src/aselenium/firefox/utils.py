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

"""Validate Firefox add-ons and serialize unpacked directories for WebDriver."""

from __future__ import annotations

from base64 import b64encode
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, is_zipfile

from orjson import loads

from aselenium import errors
from aselenium._paths import (
    PathInput,
    _regular_tree_files,
    directory_path,
    is_link,
    parse_path,
)
from aselenium.utils import CustomDict

__all__ = [
    "FirefoxAddon",
    "encode_dir_to_firefox_wire_protocol",
    "extract_firefox_addon_details",
]


# Utils: addon ------------------------------------------------------------------------------------
class FirefoxAddon(CustomDict):
    """Validated identity metadata for an installed Firefox WebExtension."""

    def __init__(self, *, id: str | None, name: str, version: str) -> None:
        """Create add-on metadata from validated manifest fields.

        Args:
            id: Gecko add-on identifier, or ``None`` before Firefox assigns one.
            name: Nonempty display name from ``manifest.json``.
            version: Nonempty version text from ``manifest.json``.

        Raises:
            errors.InvalidExtensionError: A supplied field has an invalid type
                or is blank.
        """
        if id is not None and (not isinstance(id, str) or not id.strip()):
            raise errors.InvalidExtensionError("Firefox add-on id must be nonempty")
        if not isinstance(name, str) or not name.strip():
            raise errors.InvalidExtensionError("Firefox add-on name must be nonempty")
        if not isinstance(version, str) or not version.strip():
            raise errors.InvalidExtensionError(
                "Firefox add-on version must be nonempty"
            )
        super().__init__(id=id, name=name, version=version)

    # Properties --------------------------------------------------------------------------
    @property
    def id(self) -> str | None:
        """Return the Gecko add-on identifier assigned or declared for this add-on.

        Returns:
            The add-on identifier, or ``None`` before a temporary add-on receives
            one from Firefox.
        """
        return self["id"]

    @id.setter
    def id(self, value: str) -> None:
        """Store the nonempty identifier returned by geckodriver.

        Args:
            value: Nonempty identifier returned by GeckoDriver.

        Raises:
            errors.InvalidExtensionError: ``value`` is not nonempty text.
        """
        if not isinstance(value, str) or not value.strip():
            raise errors.InvalidExtensionError("Firefox add-on id must be nonempty")
        self["id"] = value

    @property
    def name(self) -> str:
        """Return the display name declared by ``manifest.json``.

        Returns:
            Validated, nonempty manifest name.
        """
        return self["name"]

    @property
    def version(self) -> str:
        """Return the version text declared by ``manifest.json``.

        Returns:
            Validated, nonempty manifest version.
        """
        return self["version"]

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return add-on identity fields in a compact diagnostic representation.

        Returns:
            Class name followed by the identifier, display name, and version.
        """
        return "<%s (id='%s', name='%s', version='%s')>" % (
            self.__class__.__name__,
            self.id,
            self.name,
            self.version,
        )

    def copy(self) -> FirefoxAddon:
        """Copy the validated manifest identity into an independent value object.

        Returns:
            An independent copy of this value object.
        """
        return FirefoxAddon(**self._dict)


def _parse_manifest_json(content: str | bytes) -> FirefoxAddon:
    """Validate a WebExtension manifest and extract its identity fields.

    Args:
        content: UTF-8 JSON manifest content.

    Returns:
        Validated add-on name, version, and optional Gecko identifier.

    Raises:
        orjson.JSONDecodeError: ``content`` is not valid JSON.
        ValueError: The decoded object is not a supported WebExtension manifest.
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
    addon_id = settings.get("gecko", {}).get("id")
    if addon_id is not None and (not isinstance(addon_id, str) or not addon_id.strip()):
        raise ValueError("The Gecko add-on id must be a nonempty string")
    return FirefoxAddon(
        id=addon_id,
        name=manifest["name"],
        version=manifest["version"],
    )


def extract_firefox_addon_details(path: PathInput) -> FirefoxAddon:
    """Read and validate identity metadata from a Firefox WebExtension.

    Args:
        path: Existing packed ``.xpi`` file or unpacked add-on directory,
            supplied as text or a string-valued path-like object. Relative paths
            and ``~`` are accepted.

    Returns:
        Validated add-on name, version, and optional Gecko identifier.

    Raises:
        errors.InvalidExtensionError: The path is missing, the archive or
            manifest cannot be read, or ``manifest.json`` is not a supported
            WebExtension manifest.

    Example:
        >>> import json
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from aselenium.firefox.utils import extract_firefox_addon_details
        >>> with TemporaryDirectory() as temporary:
        ...     addon = Path(temporary)
        ...     manifest = {"manifest_version": 3, "name": "Demo", "version": "1.0"}
        ...     _ = (addon / "manifest.json").write_text(json.dumps(manifest))
        ...     details = extract_firefox_addon_details(addon)
        >>> (details.name, details.version)
        ('Demo', '1.0')
    """
    try:
        addon_path = parse_path(path)
    except Exception as err:
        raise errors.InvalidExtensionError(
            f"Invalid Firefox WebExtension path {path!r}: {err}"
        ) from err
    return _extract_firefox_addon_details(addon_path)


def _extract_firefox_addon_details(addon_path: Path) -> FirefoxAddon:
    """Extract manifest metadata from an already parsed add-on path.

    Args:
        addon_path: Host-native path retained by the surrounding workflow.

    Returns:
        Validated add-on identity metadata.

    Raises:
        errors.InvalidExtensionError: ``addon_path`` is neither a readable ZIP
            archive nor an unpacked add-on directory, or its manifest is
            missing, unreadable, or invalid.
    """
    try:
        if is_link(addon_path):
            raise errors.InvalidExtensionError(
                f"Firefox add-on paths may not be links or reparse points: {addon_path}"
            )
        if addon_path.is_file() and is_zipfile(addon_path):
            with ZipFile(addon_path, "r") as archive:
                return _parse_manifest_json(archive.read("manifest.json"))
        if addon_path.is_dir():
            manifest = addon_path / "manifest.json"
            if is_link(manifest):
                raise errors.InvalidExtensionError(
                    f"Firefox manifest may not be a link or reparse point: {manifest}"
                )
            return _parse_manifest_json(manifest.read_text(encoding="utf-8"))
        raise errors.InvalidExtensionError(
            "Expected a ZIP archive (normally .xpi) or an unpacked add-on directory"
        )
    except errors.InvalidExtensionError:
        raise
    except Exception as err:
        raise errors.InvalidExtensionError(
            f"Invalid Firefox WebExtension {addon_path!r}: a valid manifest.json "
            f"is required. Error: {err}"
        ) from err


def encode_dir_to_firefox_wire_protocol(directory: PathInput) -> str:
    """Encode regular files below a directory as a deterministic base64 ZIP.

    Args:
        directory: Existing directory path; relative paths and trailing separators
            are normalized before deriving archive member names.

    Returns:
        ZIP bytes encoded as base64 text for Firefox's profile/add-on protocol.
        Members are sorted and use relative POSIX names; empty directories are
        omitted.

    Raises:
        errors.AseleniumInvalidPathError: The input cannot be parsed safely.
        errors.AseleniumDirectoryNotFoundError: The path is not an existing directory.
        errors.InvalidExtensionError: The directory contains a symbolic link,
            Windows reparse point, or special filesystem entry, which is not
            copied into the wire archive.
        OSError: If a contained file cannot be read.
    """
    root = directory_path(directory)
    return _encode_dir_to_firefox_wire_protocol(root)


def _encode_dir_to_firefox_wire_protocol(root: Path) -> str:
    """Encode an already validated directory for Firefox's wire protocol.

    Args:
        root: Existing host-native directory retained by the caller.

    Returns:
        Base64 text containing a ZIP whose member names are relative POSIX paths.

    Raises:
        errors.InvalidExtensionError: ``root`` contains a symbolic link,
            Windows reparse point, or special filesystem entry.
        OSError: A contained file cannot be read or archived.
    """
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        try:
            members = _regular_tree_files(root)
        except ValueError as cause:
            raise errors.InvalidExtensionError(str(cause)) from cause
        members.sort(key=lambda path: path.relative_to(root).as_posix())
        for filename in members:
            # ZIP member names always use POSIX separators, including on Windows.
            archive.write(filename, filename.relative_to(root).as_posix())
    return b64encode(buffer.getvalue()).decode("utf-8")
