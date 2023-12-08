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
from typing import Any
from re import Pattern, compile
from aselenium import errors

__all__ = ["ChromiumVersion", "FirefoxVersion", "GeckoVersion", "SafariVersion"]


# Version ------------------------------------------------------------------------------------------
class Version:
    """Represents a version (numeric only)."""

    _VERSION_PATTERN: Pattern = compile(r"\d+\.?\d*\.?\d*")
    _VERSION_SEGMENTS: int = 3

    def __init__(self, version: str | Version) -> None:
        """The version

        :param version: `<str>` The version. e.g. '120.0.1'
        """
        self._parse_version(version)
        # Version
        self._major: str = None
        self._build: str = None
        self._patch: str = None

    # Parsing -----------------------------------------------------------------------------
    def _parse_version(self, version: str | Version) -> None:
        """(Internal) Parse the version."""
        # Parse version
        try:
            matches = self._VERSION_PATTERN.search(version)
        except AttributeError as err:
            raise NotImplementedError(
                "<Version> Class attribute '_VERSION_PATTERN' "
                "must be implemented in subclass: <{}>.".format(self.__class__.__name__)
            ) from err
        except Exception as err:
            # . already a version instance
            if isinstance(version, self.__class__):
                self._version = version._version
                self._versions_str = version._versions_str
                self._versions_int = version._versions_int
                self._length = version._length
                return None  # exit
            # . failed to parse version
            raise errors.InvalidVersionError(
                "Invalid version: {} {}".format(repr(version), type(version))
            ) from err
        try:
            self._version = matches.group(0).rstrip(".")
            self._versions_str: list[str] = self._version.split(".")
            versions_int = [int(part) for part in self._versions_str]
        except Exception as err:
            raise errors.InvalidVersionError(
                "Invalid version: {} {}".format(repr(version), type(version))
            ) from err

        # Check version segments
        self._length: int = len(self._versions_str)

        # Compensate for missing segments (integer only)
        if self._length < self._VERSION_SEGMENTS:
            for _ in range(self._VERSION_SEGMENTS - self._length):
                versions_int.append(0)
        self._versions_int: tuple[int] = tuple(versions_int)

    # Version -----------------------------------------------------------------------------
    @property
    def version(self) -> str:
        """Access the version `<str>`."""
        return self._version

    @property
    def major(self) -> str:
        """Access the major version `<str>`.
        e.g. '120' for '120.0.1'
        """

        if self._major is None:
            self._major = self._versions_str[0]
        return self._major

    @property
    def major_num(self) -> int:
        """Access the major version `<int>`.
        e.g. 120 for '120.0.1'
        """
        return self._versions_int[0]

    @property
    def build(self) -> str:
        """Access the build version `<str>`.
        e.g. '120.0' for '120.0.1'
        """
        if self._build is None:
            if self._length < 2:
                return self.major
            self._build = ".".join(self._versions_str[:2])
        return self._build

    @property
    def build_num(self) -> int:
        """Access the build version `<int>`.
        e.g. 0 for '120.0.1'
        """
        return self._versions_int[1]

    @property
    def patch(self) -> str:
        """Access the patch version `<str>`.
        e.g. '120.0.1' for '120.0.1'
        """
        if self._patch is None:
            if self._length < 3:
                return self.build
            self._patch = ".".join(self._versions_str)
        return self._patch

    @property
    def patch_num(self) -> int:
        """Access the patch version `<int>`.
        e.g. 1 for '120.0.1'
        """
        return self._versions_int[2]

    # Special Methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return self._version.__repr__()

    def __str__(self) -> str:
        return self._version

    def __hash__(self) -> int:
        return hash(self._versions_int)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, self.__class__):
            return self._versions_int == other._versions_int
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, self.__class__):
            return self._versions_int > other._versions_int
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, self.__class__):
            return self._versions_int < other._versions_int
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, self.__class__):
            return self._versions_int >= other._versions_int
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, self.__class__):
            return self._versions_int <= other._versions_int
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        if isinstance(other, self.__class__):
            return self._versions_int != other._versions_int
        return NotImplemented

    def __len__(self) -> int:
        return self._length

    def __bool__(self) -> bool:
        return True


# Chromium Version ---------------------------------------------------------------------------------
class ChromiumVersion(Version):
    """Represents a Chromium based browser/webdriver version."""

    _VERSION_PATTERN: Pattern = compile(r"\d+\.?\d*\.?\d*\.?\d*")
    _VERSION_SEGMENTS: int = 4

    def __init__(self, version: Any) -> None:
        """The Chromium based browser/webdriver version.

        :param version: `<str>` The version. e.g. '113.0.5672.123'
        """
        super().__init__(version)
        # Version
        self._major: str = None
        self._minor: str = None
        self._build: str = None
        self._patch: str = None

    # Version -----------------------------------------------------------------------------
    @property
    def major(self) -> str:
        """Access the major version `<str>`.
        e.g. '113' for '113.0.5672.123'
        """

        if self._major is None:
            self._major = self._versions_str[0]
        return self._major

    @property
    def major_num(self) -> int:
        """Access the major version `<int>`.
        e.g. 113 for '113.0.5672.123'
        """
        return self._versions_int[0]

    @property
    def minor(self) -> str:
        """Access the minor version `<str>`.
        e.g. '113.0' for '113.0.5672.123'
        """
        if self._minor is None:
            if self._length < 2:
                return self.major
            self._minor = ".".join(self._versions_str[:2])
        return self._minor

    @property
    def minor_num(self) -> int:
        """Access the minor version `<int>`.
        e.g. 0 for '113.0.5672.123'
        """
        return self._versions_int[1]

    @property
    def build(self) -> str:
        """Access the build version `<str>`.
        e.g. '113.0.5672' for '113.0.5672.123'
        """
        if self._build is None:
            if self._length < 3:
                return self.major
            self._build = ".".join(self._versions_str[:3])
        return self._build

    @property
    def build_num(self) -> int:
        """Access the build version `<int>`.
        e.g. 5672 for '113.0.5672.123'
        """
        return self._versions_int[2]

    @property
    def patch(self) -> str:
        """Access the patch version `<str>`.
        e.g. '113.0.5672.123' for '113.0.5672.123'
        """
        if self._patch is None:
            if self._length < 4:
                return self.build
            self._patch = ".".join(self._versions_str)
        return self._patch

    @property
    def patch_num(self) -> int:
        """Access the patch version `<int>`.
        e.g. 123 for '113.0.5672.123'
        """
        return self._versions_int[3]


# Firefox Version ----------------------------------------------------------------------------------
class FirefoxVersion(Version):
    """Represents a Firefox browser version."""


# Gecko Version ------------------------------------------------------------------------------------
class GeckoVersion(Version):
    """Represents a Gecko driver version."""


# Safari Version -----------------------------------------------------------------------------------
class SafariVersion(Version):
    """Represents a Safari browser version."""
