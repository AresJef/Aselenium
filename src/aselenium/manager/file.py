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

"""One-shot downloaded artifacts and safe executable archive extraction."""

from __future__ import annotations

import json
import logging
import os
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from shutil import copyfileobj, rmtree
from tarfile import ReadError
from tarfile import open as tarfile_open
from tempfile import mkdtemp
from typing import (
    Literal,
)
from zipfile import ZipFile

import psutil

from aselenium import errors
from aselenium._paths import PathInput, is_link, parse_path
from aselenium.manager._cache import (
    ChromeFileManager as ChromeFileManager,
)
from aselenium.manager._cache import (
    ChromiumBaseFileManager as ChromiumBaseFileManager,
)
from aselenium.manager._cache import (
    EdgeFileManager as EdgeFileManager,
)
from aselenium.manager._cache import (
    FileManager as FileManager,
)
from aselenium.manager._cache import (
    FirefoxFileManager as FirefoxFileManager,
)
from aselenium.manager._filesystem import (
    ArchiveWriter,
    checked_path,
    filesystem_operation,
    member_path,
)
from aselenium.manager._http import Download

_LOGGER = logging.getLogger(__name__)


# File ---------------------------------------------------------------------------------------------
class File:
    """Own one downloaded driver or browser artifact until it is unpacked."""

    _MAC_EXECUTABLE_NAME: str | None = None
    _WIN_EXECUTABLE_NAME: str | None = None
    _LINUX_EXECUTABLE_NAME: str | None = None

    def __init__(
        self, name: str, os_name: str, url: str, content: bytes | Download
    ) -> None:
        """Create a one-shot downloaded artifact for a target platform.

        Args:
            name: Portable executable product basename, without an extension.
            os_name: Normalized target operating-system identifier.
            url: Vendor download URL used to determine the archive type.
            content: Archive bytes or an owned temporary download. Saving or unpacking
                consumes this content and closes a supplied Download stream.
        """
        # file name
        self._name: str = name
        self._filetype: Literal["zip", "tar.gz"] | None = None
        # Platform
        self._os_name: str = os_name
        # file data
        self._url: str = url
        self._content: bytes | Download | None = content

    # Name --------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Return the name of the downloaded file.

        Returns:
            The name of the downloaded file.
        """
        return self._name

    @property
    def filetype(self) -> Literal["zip", "tar.gz"]:
        """Return the supported archive type inferred from the download URL.

        Returns:
            ``"zip"`` or ``"tar.gz"``.

        Raises:
            errors.InvalidDownloadFileError: The URL does not identify a
                supported archive.
        """
        if self._filetype is None:
            if self._url.endswith(".zip"):
                self._filetype = "zip"
            elif self._url.endswith(".tar.gz"):
                self._filetype = "tar.gz"
            else:
                raise errors.InvalidDownloadFileError(
                    "<{}>\nUnsupported file type from download url: '{}'.".format(
                        self.__class__.__name__, self._url
                    )
                )
        return self._filetype

    # Unpack ------------------------------------------------------------------------------
    def unpack(
        self,
        directory: PathInput,
    ) -> Path:
        """Validate and atomically publish a downloaded executable archive.

        Args:
            directory: Destination supplied as text or a string-valued path-like
                object. It is parsed once at this public filesystem boundary.

        Returns:
            Absolute path to the executable in the published artifact directory.

        Raises:
            errors.InvalidDownloadFileError: The destination is unsafe, the archive is
                invalid, extraction fails, or atomic publication cannot complete.
        """
        destination = parse_path(directory)
        return self._unpack_to(destination)

    def _unpack_to(
        self,
        destination: Path,
        *,
        _before_publish: Callable[[Path, Path], None] | None = None,
        _owner_key: str | None = None,
    ) -> Path:
        """Publish an archive to an already-parsed destination path.

        This is the Path-only core used by cache workflows that already own a
        validated ``Path``. It deliberately performs no filesystem-protocol
        conversion or public-input parsing.

        Args:
            destination: Absolute destination path retained by the calling workflow.
            _before_publish: Optional hook called with the staging directory and
                executable before publication.
            _owner_key: Artifact ownership key recorded for safe abandoned-staging recovery.

        Returns:
            Absolute path to the executable in the published artifact directory.

        Raises:
            errors.InvalidDownloadFileError: The destination is not an absolute
                ``Path``, the archive is invalid, extraction fails, or atomic
                publication cannot complete.
        """
        staging: Path | None = None
        try:
            if not isinstance(destination, Path) or not destination.is_absolute():
                raise ValueError("Archive destination must be an absolute pathlib.Path")
            # The caller selects the parent; never follow a link at the entry
            # itself and never overwrite an existing entry, even if incomplete.
            parent = destination.parent.resolve(strict=True)
            destination = checked_path(parent, parent / destination.name)
            if destination.exists():
                raise FileExistsError(
                    "Refusing to overwrite cache entry: %s" % destination
                )
            staging = Path(
                filesystem_operation(
                    lambda: mkdtemp(prefix=".aselenium-stage-", dir=parent),
                    "Create private extraction staging directory",
                )
            )
            if _owner_key is not None:
                with (staging / "ownership.json").open("x") as marker:
                    json.dump(
                        {
                            "key": _owner_key,
                            "pid": os.getpid(),
                            "started": psutil.Process().create_time(),
                        },
                        marker,
                    )
            download_file = self._save_file(staging)
            folder = staging / "extracted"
            if self._filetype == "zip":
                members = self._extract_zip_file(download_file, folder)
            elif self._filetype == "tar.gz":
                members = self._extract_tar_file(download_file, folder)
            else:
                raise ValueError("Unsupported executable archive format")
            executable = self._find_target_executable(folder, members)
            if executable is None:
                raise ValueError(
                    "Downloaded archive does not contain the expected executable"
                )
            relative = executable.relative_to(staging)
            publication = staging
            # The extracted tree is authoritative; do not retain a second
            # compressed copy of every driver/browser in the cache.
            filesystem_operation(
                lambda: checked_path(publication, download_file).unlink(),
                "Remove consumed archive",
            )
            if _before_publish is not None:
                _before_publish(staging, executable)

            def publish() -> None:
                """Rename the validated staging directory without overwriting an existing cache entry."""
                checked_path(parent, destination)
                if destination.exists():
                    raise FileExistsError(
                        "Refusing to overwrite cache entry: %s" % destination
                    )
                publication.rename(destination)

            filesystem_operation(
                publish, "Publish validated cache entry %s" % destination
            )
            staging = None
            return destination / relative
        except Exception as cause:
            raise errors.InvalidDownloadFileError(
                "<%s> Failed to unpack download into %r: %s"
                % (self.__class__.__name__, destination, cause)
            ) from cause
        finally:
            if isinstance(self._content, Download):
                self._content.close()
            self._content = None
            if staging is not None:
                try:

                    def cleanup() -> None:
                        """Remove only the failed extraction staging directory owned by this call."""
                        checked_path(staging.parent, staging)
                        rmtree(staging)

                    filesystem_operation(
                        cleanup, "Remove failed extraction staging %s" % staging
                    )
                except (errors.DriverManagerError, OSError, ValueError) as cause:
                    _LOGGER.warning("Extraction staging retained: %s", cause)

    def _save_file(self, directory: Path) -> Path:
        """Save the downloaded content into a file.

        Args:
            directory: Absolute private directory owned by this extraction workflow.

        Returns:
            Absolute path to the saved file.
        """
        content = self._content
        if content is None:
            raise errors.InvalidDownloadFileError(
                "Downloaded content has already been consumed"
            )
        try:
            root = directory
            if not root.is_absolute() or ".." in root.parts:
                raise ValueError("Download directory must be an absolute owned path")
            name = member_path(self._name + "." + self.filetype)
            if len(name.parts) != 1:
                raise ValueError("Downloaded filename must be a basename")

            def save() -> Path:
                """Write the downloaded archive to an exclusively created staging file.

                Returns:
                    Absolute path to the saved archive.
                """
                if is_link(root):
                    raise ValueError("Download directory cannot be a link")
                root.mkdir(mode=0o700, parents=True, exist_ok=True)
                file_path = checked_path(root, root.joinpath(*name.parts))
                created = False
                try:
                    with file_path.open("xb") as file:
                        created = True
                        if isinstance(content, Download):
                            content.stream.seek(0)
                            copyfileobj(content.stream, file, 1024 * 1024)
                        else:
                            file.write(content)
                    return file_path
                except OSError as cause:
                    # Only remove a file created by this attempt. Never remove
                    # a pre-existing destination after an exclusive-open error.
                    if created and file_path.exists():
                        try:
                            filesystem_operation(
                                lambda: checked_path(root, file_path).unlink(),
                                "Remove partial downloaded archive %s" % file_path,
                            )
                        except errors.DriverManagerError as cleanup_error:
                            _LOGGER.warning(
                                "Partial downloaded archive retained: %s", cleanup_error
                            )
                            raise errors.DriverManagerError(
                                "Archive write failed and its partial file could not be removed: %s"
                                % file_path
                            ) from cause
                    raise

            return filesystem_operation(
                save, "Save downloaded archive in %s" % directory
            )
        finally:
            # Release memory
            if isinstance(self._content, Download):
                self._content.close()
            self._content = None

    def _extract_zip_file(
        self, file_path: Path, unzip_dir: Path
    ) -> list[PurePosixPath]:
        """Extract a ZIP archive through the bounded, link-safe writer.

        Args:
            file_path: Retained path to the downloaded ZIP archive.
            unzip_dir: New private directory that receives validated members.

        Returns:
            Validated ZIP member paths in archive order.

        Raises:
            errors.InvalidDownloadFileError: The archive is invalid, encrypted,
                unsafe, or exceeds an extraction limit.
        """
        try:
            writer = ArchiveWriter(unzip_dir)
            with ZipFile(file_path) as archive:
                for member in archive.infolist():
                    mode = member.external_attr >> 16
                    file_type = stat.S_IFMT(mode)
                    if member.flag_bits & 1:
                        raise ValueError("Encrypted archives are not supported")
                    if member.is_dir():
                        if file_type not in (0, stat.S_IFDIR):
                            raise ValueError("Conflicting ZIP member type")
                        writer.add(member.filename, "dir", member.file_size, mode)
                    elif file_type in (0, stat.S_IFREG, stat.S_IFLNK):
                        kind = "symlink" if file_type == stat.S_IFLNK else "file"
                        with archive.open(member) as source:
                            writer.add(
                                member.filename,
                                kind,
                                member.file_size,
                                mode,
                                source=source,
                            )
                    else:
                        raise ValueError("ZIP special files are not permitted")
            return writer.finish()
        except Exception as err:
            raise errors.InvalidDownloadFileError(
                "<{}>\nFailed to extract downloaded file: '{}'\nError: {}".format(
                    self.__class__.__name__, file_path, err
                )
            ) from err

    def _extract_tar_file(
        self, file_path: Path, unzip_dir: Path
    ) -> list[PurePosixPath]:
        """Extract a compressed TAR archive through the bounded, link-safe writer.

        Args:
            file_path: Retained path to the downloaded TAR archive.
            unzip_dir: New private directory that receives validated members.

        Returns:
            Validated TAR member paths in archive order.

        Raises:
            errors.InvalidDownloadFileError: The archive is invalid, unsafe, or
                exceeds an extraction limit.
        """
        try:
            writer = ArchiveWriter(unzip_dir)
            try:
                archive = tarfile_open(file_path, mode="r:gz")
            except ReadError:
                archive = tarfile_open(file_path, mode="r:bz2")
            with archive:
                for member in archive:
                    if member.issparse():
                        raise ValueError("Sparse archive members are not permitted")
                    if member.isdir():
                        writer.add(member.name, "dir", member.size, member.mode)
                    elif member.isfile():
                        stream = archive.extractfile(member)
                        if stream is None:
                            raise ValueError("Missing regular TAR member data")
                        with stream as source:
                            writer.add(
                                member.name,
                                "file",
                                member.size,
                                member.mode,
                                source=source,
                            )
                    elif member.issym() or member.islnk():
                        writer.add(
                            member.name,
                            "symlink" if member.issym() else "hardlink",
                            member.size,
                            member.mode,
                            link=member.linkname,
                        )
                    else:
                        raise ValueError("TAR special files are not permitted")
            return writer.finish()
        except Exception as err:
            raise errors.InvalidDownloadFileError(
                "<{}>\nFailed to extract downloaded file: '{}'\nError: {}".format(
                    self.__class__.__name__, file_path, err
                )
            ) from err

    def _find_target_executable(
        self, base_dir: Path, files: list[PurePosixPath]
    ) -> Path | None:
        """Find the target executable from the extracted files. Return `None` if not found.

        Args:
            base_dir: Absolute private archive-extraction directory.
            files: Validated archive member names produced by the extraction writer.

        Returns:
            Absolute path to the target executable, or None when it is absent.
        """
        if self._os_name == "win":
            match_name = self._WIN_EXECUTABLE_NAME
        elif self._os_name == "mac":
            match_name = self._MAC_EXECUTABLE_NAME
        else:
            match_name = self._LINUX_EXECUTABLE_NAME
        root = checked_path(base_dir.parent, base_dir)
        if not root.is_dir():
            raise errors.InvalidDownloadFileError(
                "Archive extraction directory does not exist"
            )
        matches = []
        for relative in files:
            if relative.name != match_name:
                continue
            path = root.joinpath(*relative.parts).resolve(strict=False)
            path.relative_to(root)
            if path.is_file():
                matches.append(path)
        matches = list(dict.fromkeys(matches))
        if not matches:
            return None
        if len(matches) != 1:
            raise errors.InvalidDownloadFileError(
                "Archive contains ambiguous target executables"
            )
        target = checked_path(root, matches[0])
        if self._os_name != "win":
            filesystem_operation(
                lambda: target.chmod(target.stat().st_mode | stat.S_IXUSR),
                "Make validated driver executable %s" % target,
            )
        return target

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (name='%s')>" % (self.__class__.__name__, self._name)


class EdgeDriverFile(File):
    """Represent a downloaded msedgedriver file."""

    _MAC_EXECUTABLE_NAME: str = "msedgedriver"
    _WIN_EXECUTABLE_NAME: str = "msedgedriver.exe"
    _LINUX_EXECUTABLE_NAME: str = "msedgedriver"

    def __init__(self, os_name: str, url: str, content: bytes | Download) -> None:
        """Create a one-shot Microsoft Edge WebDriver archive.

        Args:
            os_name: Operating-system identifier used by the driver vendor.
            url: URL used for the request or browser navigation.
            content: Archive bytes or an owned Download consumed and closed by unpacking.
        """
        super().__init__("msedgedriver", os_name, url, content)


class ChromeDriverFile(File):
    """Represent a downloaded chromedriver file."""

    _MAC_EXECUTABLE_NAME: str = "chromedriver"
    _WIN_EXECUTABLE_NAME: str = "chromedriver.exe"
    _LINUX_EXECUTABLE_NAME: str = "chromedriver"

    def __init__(self, os_name: str, url: str, content: bytes | Download) -> None:
        """Create a one-shot ChromeDriver archive.

        Args:
            os_name: Operating-system identifier used by the driver vendor.
            url: URL used for the request or browser navigation.
            content: Archive bytes or an owned Download consumed and closed by unpacking.
        """
        super().__init__("chromedriver", os_name, url, content)


class ChromeBinaryFile(File):
    """Represent a downloaded Chrome browser file."""

    _MAC_EXECUTABLE_NAME: str = "Google Chrome for Testing"
    _WIN_EXECUTABLE_NAME: str = "chrome.exe"
    _LINUX_EXECUTABLE_NAME: str = "chrome"

    def __init__(self, os_name: str, url: str, content: bytes | Download) -> None:
        """Create a one-shot Chrome for Testing archive.

        Args:
            os_name: Operating-system identifier used by the driver vendor.
            url: URL used for the request or browser navigation.
            content: Archive bytes or an owned Download consumed and closed by unpacking.
        """
        super().__init__("chrome", os_name, url, content)


class GeckoDriverFile(File):
    """Represent a downloaded geckodriver file."""

    _MAC_EXECUTABLE_NAME: str = "geckodriver"
    _WIN_EXECUTABLE_NAME: str = "geckodriver.exe"
    _LINUX_EXECUTABLE_NAME: str = "geckodriver"

    def __init__(self, os_name: str, url: str, content: bytes | Download) -> None:
        """Create a one-shot GeckoDriver archive.

        Args:
            os_name: Operating-system identifier used by the driver vendor.
            url: URL used for the request or browser navigation.
            content: Archive bytes or an owned Download consumed and closed by unpacking.
        """
        super().__init__("geckodriver", os_name, url, content)
