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
from io import BytesIO
from typing import Any
from orjson import loads
from xml.dom import minidom
from base64 import b64encode
from os import walk as walk_path
from os.path import join as join_path
from zipfile import ZipFile, ZIP_DEFLATED, is_zipfile
from aselenium import errors
from aselenium.utils import CustomDict, is_path_file, is_path_dir


# Utils: addon ------------------------------------------------------------------------------------
class FirefoxAddon(CustomDict):
    """Represents the detail of a Firefox add-on."""

    def __init__(self, **details: Any) -> None:
        """The detail of a Firefox add-on.

        :param details [keywords]: `<Any>` The detail of the add-on.
        """
        super().__init__(**details)

    # Properties --------------------------------------------------------------------------
    @property
    def id(self) -> str:
        """Access the identifier of the add-on `<str>`."""
        return self["id"]

    @id.setter
    def id(self, value: str) -> None:
        """Set the identifier of the add-on `<str>`."""
        self["id"] = value

    @property
    def name(self) -> str:
        """Access the name of the add-on `<str>`."""
        return self["name"]

    @property
    def version(self) -> str:
        """Access the version of the add-on `<str>`."""
        return self["version"]

    @property
    def unpack(self) -> bool:
        """Access whether the add-on requires to be unpacked `<bool>`."""
        return self["unpack"]

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (id='%s', name='%s', version='%s', unpack=%s)>" % (
            self.__class__.__name__,
            self.id,
            self.name,
            self.version,
            self.unpack,
        )

    def copy(self) -> FirefoxAddon:
        """Copy the Firefox Addon object `<Firefix Addon>`."""
        return FirefoxAddon(**self._dict)


def extract_firefox_addon_details(path: str) -> FirefoxAddon:
    """Extract the details of a Firefox addon.

    :param path: `<str>` The absolute path to the addon file (//.xpi) or folder.
    :return `<FirefoxAddon>`: The details of the addon.

    ### Example:
    >>> details = extract_firefox_addon_details("/path/to/extension.xpi")
        # <FirefoxAddon (id='extension@name', name='Extension Name', version='1.0.0', unpack=False)>
    """

    def parse_manifest_json(content):
        manifest = loads(content)
        try:
            id = manifest["applications"]["gecko"]["id"]
        except KeyError:
            id = manifest["name"].replace(" ", "") + "@" + manifest["version"]
        return FirefoxAddon(
            id=id,
            name=manifest["name"],
            version=manifest["version"],
            unpack=False,
        )

    def parse_namespace(doc: minidom.Document, url: str) -> str:
        attributes: minidom.NamedNodeMap = doc.documentElement.attributes
        for i in range(attributes.length):
            if attributes.item(i).value == url:
                if ":" in attributes.item(i).name:
                    # If the namespace is not the default one remove 'xlmns:'
                    return attributes.item(i).name.split(":")[1] + ":"
        return ""

    def parse_node_text(element: minidom.Element) -> str:
        return "".join(
            [
                node.data
                for node in element.childNodes
                if node.nodeType == node.TEXT_NODE
            ]
        ).strip()

    # Extract add-on details
    try:
        if is_path_file(path) and is_zipfile(path):
            with ZipFile(path, "r") as zip:
                if "manifest.json" in zip.namelist():
                    return parse_manifest_json(zip.read("manifest.json"))  # exit
                install_rdf = zip.read("install.rdf")
        elif is_path_dir(path):
            manifest_js = join_path(path, "manifest.json")
            if is_path_file(manifest_js):
                with open(manifest_js, "r", encoding="utf-8") as file:
                    return parse_manifest_json(file.read())  # exit
            install_rdf = join_path(path, "install.rdf")
            with open(install_rdf, "r", encoding="utf-8") as file:
                install_rdf = file.read()
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
            f"Invalid Firefox add-on: {repr(path)}. Error: {err}"
        ) from err

    # Parse from install.rdf
    details = {"id": None, "name": None, "version": None, "unpack": False}
    try:
        # . parse the xml document
        doc = minidom.parseString(install_rdf)

        # . parse the namespaces
        em = parse_namespace(doc, "http://www.mozilla.org/2004/em-rdf#")
        rdf = parse_namespace(doc, "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
        description = doc.getElementsByTagName(rdf + "Description")[0]
        if not description:
            description = doc.getElementsByTagName("Description").item(0)
        for node in description.childNodes:
            # Remove the namespace prefix from the tag for comparison
            entry = node.nodeName.replace(em, "")
            if entry in details:
                details[entry] = parse_node_text(node)
        if not details["id"]:
            for i in range(description.attributes.length):
                attribute = description.attributes.item(i)
                if attribute.name == em + "id":
                    details["id"] = attribute.value
    except Exception as err:
        raise errors.InvalidExtensionError(
            f"Invalid Firefox add-on file: {repr(path)}. {err}"
        )

    # Validate addon id
    if not details["id"]:
        raise errors.InvalidExtensionError(
            f"Invalid Firefox add-on file: {repr(path)}. Add-on id not found."
        )

    # Adjust unpack boolean
    if isinstance(details["unpack"], str):
        details["unpack"] = details["unpack"].lower() == "true"

    # Return details
    return FirefoxAddon(**details)


def encode_dir_to_firefox_wire_protocol(directory: str) -> str:
    """Encodes a directory to the Firefox wire protocol format.

    :param directory: `<str>` The directory to be encoded.
    :return `<str>`: The encoded directory in the Firefox wire protocol format.
    """
    fp = BytesIO()
    path_root = len(directory) + 1  # account for trailing slash
    with ZipFile(fp, "w", ZIP_DEFLATED) as zip:
        for base, _, files in walk_path(directory):
            for fyle in files:
                filename = join_path(base, fyle)
                zip.write(filename, filename[path_root:])
    return b64encode(fp.getvalue()).decode("utf-8")
