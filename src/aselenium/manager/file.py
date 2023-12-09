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
from shutil import rmtree
from typing import Literal
from subprocess import call
from datetime import datetime
from zipfile import ZipFile, ZipInfo
from os import makedirs, chmod, getcwd
from os.path import join as join_path, expanduser
from tarfile import open as tarfile_open, ReadError
from pandas import DataFrame, read_feather
from aselenium import errors
from aselenium.utils import validate_dir, is_path_dir, is_path_file
from aselenium.manager.version import ChromiumVersion, GeckoVersion


# File manager -------------------------------------------------------------------------------------
class FileManager:
    """Responsible for managing the webdriver executables & browser binaries."""

    # Singleton
    __instances: dict[str, FileManager] = {}
    """A dictionary of all instanciated file managers."""
    __instanciated: bool = False
    """Whether the instance has been instanciated."""
    # Driver Metadata
    _DIRVER_METADATA_FILE: str = None
    """The name of the driver metadata file `<str>`. e.g. `'chrome_driver_metadata'`."""
    _DRIVER_METADATA_COLUMNS: list[str] = None
    """The columns of the driver metadata `<list[str]>`. e.g. `['time', 'version', 'location']`."""
    _DRIVER_METADATA_SORTING: list[str] = None
    """The sorting order of the driver metadata `<list[str]>`. e.g. `['time', 'version']`."""
    # Binary Metadata
    _BINARY_METADATA_FILE: str = None
    """The name of the browser binary metadata file `<str>`. e.g. `'chrome_binary_metadata'`."""
    _BINARY_METADATA_COLUMNS: list[str] = None
    """The columns of the browser binary metadata `<list[str]>`. e.g. `['time', 'version', 'location']`."""
    _BINARY_METADATA_SORTING: list[str] = None
    """The sorting order of the browser binary metadata `<list[str]>`. e.g. `['time', 'version']`."""

    @classmethod
    def _validate_base_dir(cls, base_dir: str | None = None) -> str:
        """(Class method) Validate the base directory."""
        if base_dir is None:
            return expanduser("~")
        try:
            return validate_dir(base_dir)
        except Exception as err:
            raise errors.DriverManagerError(
                "<{}>\nInvalid driver manager cache directory: "
                "{} {}.".format(cls.__name__, repr(base_dir), type(base_dir))
            ) from err

    @classmethod
    def _gen_instance_key(cls, base_dir: str) -> str:
        """(Class method) Generate a unique instance key for the instance."""
        return cls.__name__ + "|" + base_dir

    def __new__(cls, base_dir: str | None = None) -> FileManager:
        # Validate base directory
        base_dir = cls._validate_base_dir(base_dir)

        # Create new instance
        key = cls._gen_instance_key(base_dir)
        if key not in cls.__instances:
            inst = super(FileManager, cls).__new__(cls)
            cls.__instances[key] = inst
            return inst
        # Access existing instance
        else:
            return cls.__instances[key]

    def __init__(self, base_dir: str | None = None) -> None:
        """Manager for the webdriver executables & browser binaries.

        :param base_dir: `<str/None>` The base directory to store the cached files. Defaults to `None`.
            - If `None`, the files will be automatically cache in the following default directory:
              1. MacOS default: `'/Users/<user>/.aselenium'`.
              2. Windows default: `'C:\\Users\\<user>\\.aselenium'`.
              3. Linux default: `'/home/<user>/.aselenium'`.
            - If specified, a folder named `'.aselenium'` will be created in the given directory.
        """
        # Already instanciated
        if self.__instanciated:
            return None  # exit

        # Directory
        self._base_dir = self._validate_base_dir(base_dir)
        self._directory: str = join_path(self._base_dir, ".aselenium")
        if not is_path_dir(self._directory):
            makedirs(self._directory)
            chmod(self._directory, 0o755)
        # Unique instance key
        self._inst_key = self._gen_instance_key(self._base_dir)
        # Driver Metadata
        try:
            self._driver_metadata_file: str = join_path(
                self._directory, self._DIRVER_METADATA_FILE + ".feather"
            )
        except Exception:
            raise self._raise_attribute_implementation_error("_DIRVER_METADATA_FILE")
        self._driver_metadata: DataFrame = None
        self._load_driver_metadata()
        # Binary Metadata
        try:
            self._binary_metadata_file: str = join_path(
                self._directory, self._BINARY_METADATA_FILE + ".feather"
            )
        except Exception:
            raise self._raise_attribute_implementation_error("_BINARY_METADATA_FILE")
        self._binary_metadata: DataFrame = None
        self._load_binary_metadata()
        # Instanciated
        self.__instanciated = True

    # Driver cache ------------------------------------------------------------------------
    def match_driver(self, *args) -> dict | None:
        """Match the cached webdriver. Returns the location and version
        of the webdriver if matched `<dict>`, or `None` if not found.
        """
        raise NotImplementedError(
            "<DriverManager>\n'match_driver' method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _match_driver(self, query: str) -> dict | None:
        """(Internal) Match cached webdriver by a query. Returns the
        location and version of the webdriver if matched `<dict>`, or
        `None` if not found.
        """
        invalid_idx = []
        for idx, row in self._driver_metadata.query(query).iterrows():
            location = row["location"]
            if not is_path_file(location):
                invalid_idx.append(idx)
                continue
            self._remove_driver_metadata(invalid_idx)
            return {"location": location, "version": row["version"]}

        # No valid match
        return self._remove_driver_metadata(invalid_idx)

    def cache_driver(self, *args) -> dict:
        """Cache the downloaded webdriver. Returns the location and
        version of the cached webdriver `<dict>`.
        """
        raise NotImplementedError(
            "<DriverManager>\n'cache_driver' method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    # Driver Metadata ---------------------------------------------------------------------
    def _load_driver_metadata(self) -> None:
        """(Internal) Load the local driver metadata file into memory.
        Create blank driver metadata file if not exists.
        """
        # Already loaded
        if self._driver_metadata is not None:
            return None  # exit: success

        # Load from file
        self._driver_metadata = self._load_metadata(self._driver_metadata_file)
        if self._driver_metadata is not None:
            return None  # exit: success

        # Create blank metadata file
        try:
            self._driver_metadata = DataFrame(columns=self._DRIVER_METADATA_COLUMNS)
        except Exception:
            self._raise_attribute_implementation_error("_DRIVER_METADATA_COLUMNS")
        self._save_driver_metadata()

    def _remove_driver_metadata(self, index: list[int]) -> None:
        """(Internal) Remove driver metadata by index.
        Local files will be deleted along with the metadata.
        """
        if index:
            self._driver_metadata = self._remove_metadata(self._driver_metadata, index)
            self._save_driver_metadata()

    def _release_driver_metadata(self, max_cache_size: int | None) -> None:
        """(Internal) Release oldest driver metadata that exceeds the max cache size.
        Local files will be deleted along with the metadata.
        """
        self._driver_metadata = self._release_metadata(
            self._driver_metadata, max_cache_size
        )

    def _sort_driver_metadata(self) -> None:
        """(Internal) Sort the driver metadata by version."""
        self._driver_metadata = self._sort_metadata(
            self._driver_metadata, self._DRIVER_METADATA_SORTING
        )

    def _save_driver_metadata(self) -> None:
        """(Internal) Save the current driver metadata to local file."""
        self._sort_driver_metadata()
        self._save_metadata(self._driver_metadata, self._driver_metadata_file)

    # Binary cache ------------------------------------------------------------------------
    def match_binary(self, *args) -> dict | None:
        """Match the cached browser binary. Returns the location and version
        of the binary if matched `<dict>`, or `None` if not found.
        """
        raise NotImplementedError(
            "<DriverManager>\n'match_binary' method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    def _match_binary(self, query: str) -> dict | None:
        """(Internal) Match cached browser binary by a query. Returns the
        location and version of the binary if matched `<dict>`, or `None`
        if not found.
        """
        invalid_idx = []
        for idx, row in self._binary_metadata.query(query).iterrows():
            location = row["location"]
            if not is_path_file(location):
                invalid_idx.append(idx)
                continue
            self._remove_binary_metadata(invalid_idx)
            return {"location": location, "version": row["version"]}

        # No valid match
        return self._remove_binary_metadata(invalid_idx)

    def cache_binary(self, *args) -> dict:
        """Cache the downloaded browser binary. Returns the location
        and version of the cached binary `<dict>`.
        """
        raise NotImplementedError(
            "<DriverManager>\n'cache_binary' method must be "
            "implemented in subclass: <{}>.".format(self.__class__.__name__)
        )

    # Binary Metadata ---------------------------------------------------------------------
    def _load_binary_metadata(self) -> None:
        """(Internal) Load the local browser binary metadata file into
        memory. Create blank binary metadata file if not exists.
        """
        # Already loaded
        if self._binary_metadata is not None:
            return None  # exit: success

        # Load from file
        self._binary_metadata = self._load_metadata(self._binary_metadata_file)
        if self._binary_metadata is not None:
            return None  # exit: success

        # Create blank metadata file
        try:
            self._binary_metadata = DataFrame(columns=self._BINARY_METADATA_COLUMNS)
        except Exception:
            self._raise_attribute_implementation_error("_BINARY_METADATA_COLUMNS")
        self._save_binary_metadata()

    def _remove_binary_metadata(self, index: list[int]) -> None:
        """(Internal) Remove browser binary metadata by index.
        Local files will be deleted along with the metadata.
        """
        if index:
            self._binary_metadata = self._remove_metadata(self._binary_metadata, index)
            self._save_binary_metadata()

    def _release_binary_metadata(self, max_cache_size: int | None) -> None:
        """(Internal) Release oldest browser binary metadata that exceeds the
        max cache size. Local files will be deleted along with the metadata.
        """
        self._binary_metadata = self._release_metadata(
            self._binary_metadata, max_cache_size
        )

    def _sort_binary_metadata(self) -> None:
        """(Internal) Sort the browser binary metadata by version."""
        self._binary_metadata = self._sort_metadata(
            self._binary_metadata, self._BINARY_METADATA_SORTING
        )

    def _save_binary_metadata(self) -> None:
        """(Internal) Save the current browser binary metadata to local file."""
        self._sort_binary_metadata()
        self._save_metadata(self._binary_metadata, self._binary_metadata_file)

    # Metadata utils  ---------------------------------------------------------------------
    def _load_metadata(self, path: str) -> DataFrame | None:
        """(Internal) Load local metadata file into memory `<DataFrame>`.
        Returns `None` if the file does not exist."""
        while True:
            try:
                return read_feather(path)
            except FileNotFoundError:
                return None
            except OSError:
                if not is_path_file(path):
                    return None
                continue

    def _sort_metadata(self, meta: DataFrame, sort_columns: list[str]) -> DataFrame:
        """(Internal) Sort the metadata by columns in
        desending orders `<DataFrame>`.
        """
        try:
            return meta.sort_values(sort_columns, ascending=False, ignore_index=True)
        except Exception:
            self._raise_attribute_implementation_error("_METADATA_SORTING")

    def _remove_metadata(self, meta: DataFrame, index: list[int]) -> DataFrame:
        """(Internal) Remove metadata by index `<DataFrame>`.
        Local files will be deleted along with the metadata.
        """
        # Remove local folders
        for _, row in meta[meta.index.isin(index)].iterrows():
            folder: str = row["folder"]
            while is_path_dir(folder):
                try:
                    rmtree(folder)
                except OSError:
                    continue

        # Remove metadata
        return meta[~meta.index.isin(index)].copy()

    def _release_metadata(
        self,
        meta: DataFrame,
        max_cache_size: int | None,
    ) -> DataFrame:
        """(Internal) Release oldest metadata that exceeds the max cache size.
        Local files will be deleted along with the metadata `<DataFrame>`.
        """
        # Unlimited cache size
        if max_cache_size is None:
            return meta  # exit: unlimited

        # Check if within limit
        if len(meta) <= max_cache_size:
            return meta  # exit: within limit

        # Remove expired cache
        meta = meta.sort_values("time", ascending=False, ignore_index=True)
        for _, row in meta[meta.index >= max_cache_size].iterrows():
            folder: str = row["folder"]
            while is_path_dir(folder):
                try:
                    rmtree(folder)
                except OSError:
                    continue

        # Drop expired metadata
        return meta.iloc[:max_cache_size].copy()

    def _save_metadata(self, meta: DataFrame, path: str) -> None:
        """(Internal) Save the metadata to local file."""
        while True:
            try:
                return meta.to_feather(path)
            except OSError:
                makedirs(self._directory, exist_ok=True)

    # Exceptions --------------------------------------------------------------------------
    def _raise_attribute_implementation_error(self, attr_name: str) -> None:
        """(Internal) Raise an attribute not implemented error."""
        raise NotImplementedError(
            "<DriverManager>\nCritial class attribute '{}' not implemented in "
            "subclass: <{}>.".format(attr_name, self.__class__.__name__)
        )

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (directory='%s')>" % (self.__class__.__name__, self._directory)

    def __hash__(self) -> int:
        return hash(self._inst_key)

    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, self.__class__):
            return self._inst_key == __o._inst_key
        else:
            return False


class ChromiumBaseFileManager(FileManager):
    """Responsible for managing the webdriver executables &
    browser binaries for the Chromium based browser.
    """

    # Driver Metadata
    # fmt: off
    _DRIVER_METADATA_COLUMNS: list[str] = [
        "time", "major", "minor", "build", "patch", "version", "location", "folder"
    ]
    _DRIVER_METADATA_SORTING: list[str] = ["major", "minor", "build", "patch"]
    # Binary Metadata
    _BINARY_METADATA_COLUMNS: list[str] = _DRIVER_METADATA_COLUMNS
    _BINARY_METADATA_SORTING: list[str] = _DRIVER_METADATA_SORTING
    # fmt: on

    # Driver cache ------------------------------------------------------------------------
    def match_driver(
        self,
        version: ChromiumVersion,
        match_method: Literal["major", "build", "patch"] = "patch",
    ) -> dict | None:
        """Match the cached webdriver.

        :param version: `<ChromiumVersion>` The version of the webdriver.
        :param match_method: `<str>` How to match the version, accepts:
            - `'major'`: Match the latest available webdriver with the same major version.
            - `'build'`: Match the latest available webdriver with the same major & build version.
            - `'patch'`: Match the latest available webdriver with the same major, build & patch version.

        :return: `<dict/None>` The webdriver location & version, or `None` if not found.
        """
        driver = self._match_driver(self._generate_match_query(version, match_method))
        if driver is not None:
            driver["version"] = ChromiumVersion(driver["version"])
        return driver

    def cache_driver(
        self,
        version: ChromiumVersion,
        driver: File,
        max_cache_size: int | None = None,
    ) -> dict:
        """Cache the downloaded webdriver.

        :param version: `<ChromiumVersion>` The version of the webdriver.
        :param driver: `<File>` The downloaded webdriver file.
        :param max_cache_size: `<int/None>` The maximum cache size of the webdrivers. Defaults to `None`.
            - If `None`, all webdrivers will be cached to local storage without limit.
            - For value > 1, if the cached webdrivers exceed this limit, the oldest
              webdrivers will be deleted.

        :return: `<str>` The location & version of the webdriver.
        """
        try:
            # Check if already cached
            cache = self.match_driver(version, match_method="patch")
            if cache is not None:
                return cache

            # Determine driver folder
            folder = "%s_%s" % (driver.name, version.version)
            folder = join_path(self._directory, folder)

            # Unpack the driver
            location = driver.unpack(folder)

            # Save to metadata
            self._driver_metadata.loc[len(self._driver_metadata)] = [
                datetime.now().replace(microsecond=0),
                version.major_num,
                version.minor_num,
                version.build_num,
                version.patch_num,
                version.version,
                location,
                folder,
            ]

            # Release & save
            self._release_driver_metadata(max_cache_size)
            self._save_driver_metadata()

            # Return
            return {"location": location, "version": version}

        finally:
            del driver

    # Binary cache ------------------------------------------------------------------------
    def match_binary(
        self,
        version: ChromiumVersion,
        match_method: Literal["major", "build", "patch"] = "patch",
    ) -> dict | None:
        """Match the cached browser binary.

        :param version: `<ChromiumVersion>` The version of the browser.
        :param match_method: `<str>` How to match the version, accepts:
            - `'major'`: Match the latest available webdriver with the same major version.
            - `'build'`: Match the latest available webdriver with the same major & build version.
            - `'patch'`: Match the latest available webdriver with the same major, build & patch version.

        :return: `<dict/None>` The browser binary location & version, or `None` if not found.
        """
        binary = self._match_binary(self._generate_match_query(version, match_method))
        if binary is not None:
            binary["version"] = ChromiumVersion(binary["version"])
        return binary

    def cache_binary(
        self,
        version: ChromiumVersion,
        binary: File,
        max_cache_size: int | None = None,
    ) -> dict:
        """Cache the downloaded browser binary.

        :param version: `<ChromiumVersion>` The version of the browser.
        :param binary: `<File>` The downloaded browser binary file.
        :param max_cache_size: `<int/None>` The maximum cache size of the binaries. Defaults to `None`.
            - If `None`, all browser binaries will be cached to local storage without limit.
            - For value > 1, if the cached binaries exceed this limit, the oldest browser
              binaries will be deleted.

        :return: `<str>` The location and version of the browser binary.
        """
        try:
            # Check if already cached
            cache = self.match_binary(version, match_method="patch")
            if cache is not None:
                return cache

            # Determine binary folder
            folder = "%s_%s" % (binary.name, version.version)
            folder = join_path(self._directory, folder)

            # Unpack the binary
            location = binary.unpack(folder)

            # Save to metadata
            self._binary_metadata.loc[len(self._binary_metadata)] = [
                datetime.now().replace(microsecond=0),
                version.major_num,
                version.minor_num,
                version.build_num,
                version.patch_num,
                version.version,
                location,
                folder,
            ]

            # Release & save
            self._release_binary_metadata(max_cache_size)
            self._save_binary_metadata()

            # Return
            return {"location": location, "version": version}

        finally:
            del binary

    # Cache utils  ------------------------------------------------------------------------
    def _generate_match_query(
        self,
        version: ChromiumVersion,
        match_method: Literal["major", "build", "patch"] = "patch",
    ) -> str:
        """(Internal) Generate the query to match webdriver/binary from cache `<str>`."""
        # Construct query
        length = version._length
        if length == 4 and match_method == "patch":
            return "major == %d and minor == %d and build == %d and patch == %d" % (
                version.major_num,
                version.minor_num,
                version.build_num,
                version.patch_num,
            )
        elif length >= 3 and match_method != "major":
            return "major == %d and minor == %d and build == %d" % (
                version.major_num,
                version.minor_num,
                version.build_num,
            )
        else:
            return "major == %d" % version.major_num


class EdgeFileManager(ChromiumBaseFileManager):
    """Responsible for managing the webdriver executables &
    browser binaries for the Edge browser.
    """

    # Driver Metadata
    _DIRVER_METADATA_FILE: str = "edge_driver_metadata"
    # Binary Metadata
    _BINARY_METADATA_FILE: str = "edge_binary_metadata"


class ChromeFileManager(ChromiumBaseFileManager):
    """Responsible for managing the webdriver executables &
    browser binaries for the Chrome/Chromium browser.
    """

    # Driver Metadata
    _DIRVER_METADATA_FILE: str = "chrome_driver_metadata"
    # Binary Metadata
    _BINARY_METADATA_FILE: str = "chrome_binary_metadata"


class FirefoxFileManager(FileManager):
    """Responsible for managing the webdriver executables &
    browser binaries for the Firefox browser.
    """

    # Driver Metadata
    # fmt: off
    _DIRVER_METADATA_FILE: str = "gecko_driver_metadata"
    _DRIVER_METADATA_COLUMNS: list[str] = [
        "time", "major", "build", "patch", "version", "location", "folder"
    ]
    _DRIVER_METADATA_SORTING: list[str] = ["major", "build", "patch"]
    # Binary Metadata
    _BINARY_METADATA_FILE: str = "firefox_binary_metadata"
    _BINARY_METADATA_COLUMNS: list[str] = _DRIVER_METADATA_COLUMNS
    _BINARY_METADATA_SORTING: list[str] = _DRIVER_METADATA_SORTING
    # fmt: on

    # Driver cache ------------------------------------------------------------------------
    def match_driver(
        self,
        version: GeckoVersion,
        match_method: Literal["major", "build", "patch"] = "patch",
    ) -> dict | None:
        """Match the cached webdriver.

        :param version: `<GeckoVersion>` The version of the webdriver.
        :param match_method: `<str>` How to match the version, accepts:
            - `'major'`: Match the latest available webdriver with the same major version.
            - `'build'`: Match the latest available webdriver with the same major & build version.
            - `'patch'`: Match the latest available webdriver with the same major, build & patch version.

        :return: `<dict/None>` The webdriver location & version, or `None` if not found.
        """
        driver = self._match_driver(self._generate_match_query(version, match_method))
        if driver is not None:
            driver["version"] = GeckoVersion(driver["version"])
        return driver

    def cache_driver(
        self,
        version: GeckoVersion,
        driver: File,
        max_cache_size: int | None = None,
    ) -> dict:
        """Cache the downloaded webdriver.

        :param version: `<GeckoVersion>` The version of the webdriver.
        :param driver: `<File>` The downloaded webdriver file.
        :param max_cache_size: `<int/None>` The maximum cache size of the webdrivers. Defaults to `None`.
            - If `None`, all webdrivers will be cached to local storage without limit.
            - For value > 1, if the cached webdrivers exceed this limit, the oldest
              webdrivers will be deleted.

        :return: `<str>` The location & version of the webdriver.
        """
        try:
            # Check if already cached
            cache = self.match_driver(version, match_method="patch")
            if cache is not None:
                return cache

            # Determine driver folder
            folder = "%s_%s" % (driver.name, version.version)
            folder = join_path(self._directory, folder)

            # Unpack the driver
            location = driver.unpack(folder)

            # Save to metadata
            self._driver_metadata.loc[len(self._driver_metadata)] = [
                datetime.now().replace(microsecond=0),
                version.major_num,
                version.build_num,
                version.patch_num,
                version.version,
                location,
                folder,
            ]

            # Release & save
            self._release_driver_metadata(max_cache_size)
            self._save_driver_metadata()

            # Return
            return {"location": location, "version": version}

        finally:
            del driver

    # Cache utils  ------------------------------------------------------------------------
    def _generate_match_query(
        self,
        version: GeckoVersion,
        match_method: Literal["major", "build", "patch"] = "patch",
    ) -> str:
        """(Internal) Generate the query to match webdriver/binary from cache `<str>`."""
        # Construct query
        length = len(version)
        if length == 3 and match_method == "patch":
            return "major == %d and build == %d and patch == %d" % (
                version.major_num,
                version.build_num,
                version.patch_num,
            )
        elif length >= 2 and match_method != "major":
            return "major == %d and build == %d" % (
                version.major_num,
                version.build_num,
            )
        else:
            return "major == %d" % version.major_num


# File ---------------------------------------------------------------------------------------------
class LinuxZipFileWithPermissions(ZipFile):
    """Extract files in linux with correct permissions."""

    def extract(self, member, path=None, pwd=None):
        if not isinstance(member, ZipInfo):
            member = self.getinfo(member)

        if path is None:
            path = getcwd()

        ret_val = self._extract_member(member, path, pwd)  # noqa
        attr = member.external_attr >> 16
        chmod(ret_val, attr)
        return ret_val


class File:
    """Represents a downloaded file."""

    _MAC_EXECUTABLE_NAME: str = None
    _WIN_EXECUTABLE_NAME: str = None
    _LINUX_EXECUTABLE_NAME: str = None

    def __init__(self, name: str, os_name: str, url: str, content: bytes) -> None:
        """The downloaded file.

        :param os_name: `<str>` The name of the operating system.
        :param url: `<str>` The url that downloaded the file.
        :param content: `<bytes>` The downloaded file content.
        """
        # file name
        self._name: str = name
        self._filetype: str = None
        # Platform
        self._os_name: str = os_name
        # file data
        self._url: str = url
        self._content: bytes = content

    # Name --------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Access the name of the downloaded file `<str>`."""
        return self._name

    @property
    def filetype(self) -> Literal["zip", "tar.gz", "exe"]:
        """Access the type of the downloaded file `<str>`.

        Excepted values: `'zip'`, `'tar.gz'`, `'exe'`.
        """
        if self._filetype is None:
            if self._url.endswith(".zip"):
                self._filetype = "zip"
            elif self._url.endswith(".tar.gz"):
                self._filetype = "tar.gz"
            elif self._url.endswith(".exe"):
                self._filetype = "exe"
            else:
                raise errors.InvalidDownloadFileError(
                    "<{}>\nUnsupported file type from download url: "
                    "'{}'.".format(self.__class__.__name__, self._url)
                )
        return self._filetype

    # Unpack ------------------------------------------------------------------------------
    def unpack(self, directory: str) -> str:
        """Unpack the file.

        :param directory: `<str>` The directory to unpack the files.
        :return `<str>`: The path to the target executable of the unpacked files.
        """
        # Save content into local file
        download_file = self._save_file(directory)

        # Extract files
        folder = join_path(directory, "extracted")
        if self._filetype == "zip":
            files = self._extract_zip_file(download_file, folder)
        elif self._filetype == "tar.gz":
            files = self._extract_tar_file(download_file, folder)
        else:
            raise errors.InvalidDownloadFileError(
                "<{}>\nInvalid file: '{}'.".format(
                    self.__class__.__name__, download_file
                )
            )

        # Find executable
        executable = self._find_target_executable(folder, files)
        if executable is None:
            raise errors.InvalidDownloadFileError(
                "<{}>\nFailed to find executable from unpacked"
                "files: {}.".format(self.__class__.__name__, files)
            )
        # Return
        return executable

    def _save_file(self, directory: str) -> str:
        """(Internal) Save the downloaded content into a file.

        :param directory: `<str>` The directory to save the file.
        :return `<str>`: The absolute path to the saved file.
        """
        try:
            # Create directory
            makedirs(directory, exist_ok=True)
            # Save file
            file_path = join_path(directory, self._name + "." + self.filetype)
            while True:
                try:
                    with open(file_path, "wb") as file:
                        file.write(self._content)
                    return file_path
                except OSError:
                    makedirs(directory, exist_ok=True)
        finally:
            # Release memory
            self._content = None

    def _extract_zip_file(self, file_path: str, unzip_dir: str) -> list[str]:
        """(Internal) Extracts a zip file. Returns a list
        of the extracted file names `<list[str]>`.
        """
        try:
            if self._os_name == "linux":
                with LinuxZipFileWithPermissions(file_path) as archive:
                    archive.extractall(unzip_dir)
                    return archive.namelist()
            else:
                with ZipFile(file_path) as archive:
                    archive.extractall(unzip_dir)
                    return archive.namelist()
        except Exception as err:
            raise errors.InvalidDownloadFileError(
                "<{}>\nFailed to extract downloaded file: '{}'\n"
                "Error: {}".format(self.__class__.__name__, file_path, err)
            ) from err

    def _extract_tar_file(self, file_path: str, unzip_dir: str) -> list[str]:
        """(Internal) Extracts a tar file. Returns a list
        of the extracted file names `<list[str]>`.
        """
        try:
            try:
                with tarfile_open(file_path, mode="r:gz") as archive:
                    archive.extractall(unzip_dir)
                    return [x.name for x in archive.getmembers()]
            except ReadError:
                with tarfile_open(file_path, mode="r:bz2") as archive:
                    archive.extractall(unzip_dir)
                    return [x.name for x in archive.getmembers()]
        except Exception as err:
            raise errors.InvalidDownloadFileError(
                "<{}>\nFailed to extract downloaded file: '{}'\n"
                "Error: {}".format(self.__class__.__name__, file_path, err)
            ) from err

    def _find_target_executable(self, base_dir: str, files: list[str]) -> str | None:
        """(Internal) Find the target executable from the
        extracted files `<str>`. Return `None` if not found.
        """
        # Find windows executable
        if self._os_name == "win":
            match_name = self._WIN_EXECUTABLE_NAME
            for file in files:
                name = file.split("/")[-1]
                path = join_path(base_dir, file)
                if is_path_file(path) and name == match_name:
                    return path
            return None

        # Find unix executable
        if self._os_name == "mac":
            match_name = self._MAC_EXECUTABLE_NAME
        else:
            match_name = self._LINUX_EXECUTABLE_NAME

        # Find target executable
        executables = []
        for file in files:
            name = file.split("/")[-1]
            path = join_path(base_dir, file)
            if is_path_file(path):
                # . grant permission
                call(["chmod", "u+x", path])
                if name == match_name:
                    # . executable found
                    executables.append(path)

        # Return target executable
        try:
            return executables[0]
        except IndexError:
            return None

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (name='%s')>" % (self.__class__.__name__, self._name)


class EdgeDriverFile(File):
    """Represents a downloaded msedgedriver file."""

    _MAC_EXECUTABLE_NAME: str = "msedgedriver"
    _WIN_EXECUTABLE_NAME: str = "msedgedriver.exe"
    _LINUX_EXECUTABLE_NAME: str = "msedgedriver"

    def __init__(self, os_name: str, url: str, content: bytes) -> None:
        super().__init__("msedgedriver", os_name, url, content)


class ChromeDriverFile(File):
    """Represents a downloaded chromedriver file."""

    _MAC_EXECUTABLE_NAME: str = "chromedriver"
    _WIN_EXECUTABLE_NAME: str = "chromedriver.exe"
    _LINUX_EXECUTABLE_NAME: str = "chromedriver"

    def __init__(self, os_name: str, url: str, content: bytes) -> None:
        super().__init__("chromedriver", os_name, url, content)


class ChromeBinaryFile(File):
    """Represents a downloaded Chrome browser file."""

    _MAC_EXECUTABLE_NAME: str = "Google Chrome for Testing"
    _WIN_EXECUTABLE_NAME: str = "chrome.exe"
    _LINUX_EXECUTABLE_NAME: str = "chrome"

    def __init__(self, os_name: str, url: str, content: bytes) -> None:
        super().__init__("chrome", os_name, url, content)


class GeckoDriverFile(File):
    """Represents a downloaded geckodriver file."""

    _MAC_EXECUTABLE_NAME: str = "geckodriver"
    _WIN_EXECUTABLE_NAME: str = "geckodriver.exe"
    _LINUX_EXECUTABLE_NAME: str = "geckodriver"

    def __init__(self, os_name: str, url: str, content: bytes) -> None:
        super().__init__("geckodriver", os_name, url, content)
