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
"""Aselenium version implementation and supporting types."""

from __future__ import annotations

from re import Pattern, compile
from typing import (
    Any,
)

from aselenium import errors

__all__ = ["ChromiumVersion", "FirefoxVersion", "GeckoVersion", "SafariVersion"]


# Version ------------------------------------------------------------------------------------------
class Version:
    """Represent a version (numeric only)."""

    _VERSION_PATTERN: Pattern[str] = compile(r"\d+\.?\d*\.?\d*")
    _VERSION_SEGMENTS: int = 3
    _version: str
    _versions_str: list[str]
    _versions_int: tuple[int, ...]
    _length: int

    def __init__(self, version: str | Version) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            version: The version. e.g. '120.0.1'

        Raises:
            errors.InvalidVersionError: No supported numeric version can be parsed.

        Example:
            >>> from aselenium import ChromiumVersion
            >>> version = ChromiumVersion("120.0.6099.71")
            >>> version.build
            '120.0.6099'
            >>> version < ChromiumVersion("121.0.0.0")
            True
        """
        self._parse_version(version)
        # Version
        self._major: str | None = None
        self._build: str | None = None
        self._patch: str | None = None

    # Parsing -----------------------------------------------------------------------------
    def _parse_version(self, version: str | Version) -> None:
        """Parse the version.

        Args:
            version: Version object or version selector for this operation.
        """
        # Parse version
        try:
            if not isinstance(version, str):
                raise TypeError("Version input is not text")
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
            if matches is None:
                raise ValueError("No numeric version found")
            self._version = matches.group(0).rstrip(".")
            self._versions_str = self._version.split(".")
            versions_int = [int(part) for part in self._versions_str]
        except Exception as err:
            raise errors.InvalidVersionError(
                "Invalid version: {} {}".format(repr(version), type(version))
            ) from err

        # Check version segments
        self._length = len(self._versions_str)

        # Compensate for missing segments (integer only)
        if self._length < self._VERSION_SEGMENTS:
            for _ in range(self._VERSION_SEGMENTS - self._length):
                versions_int.append(0)
        self._versions_int = tuple(versions_int)

    # Version -----------------------------------------------------------------------------
    @property
    def version(self) -> str:
        """Return the version.

        Returns:
            The version.
        """
        return self._version

    @property
    def major(self) -> str:
        """Return the major version. e.g. '120' for '120.0.1'.

        Returns:
            The major version. e.g. '120' for '120.0.1'.
        """
        if self._major is None:
            self._major = self._versions_str[0]
        return self._major

    @property
    def major_num(self) -> int:
        """Return the major version. e.g. 120 for '120.0.1'.

        Returns:
            The major version. e.g. 120 for '120.0.1'.
        """
        return self._versions_int[0]

    @property
    def build(self) -> str:
        """Return the build version. e.g. '120.0' for '120.0.1'.

        Returns:
            The build version. e.g. '120.0' for '120.0.1'.
        """
        if self._build is None:
            if self._length < 2:
                return self.major
            self._build = ".".join(self._versions_str[:2])
        return self._build

    @property
    def build_num(self) -> int:
        """Return the build version. e.g. 0 for '120.0.1'.

        Returns:
            The build version. e.g. 0 for '120.0.1'.
        """
        return self._versions_int[1]

    @property
    def patch(self) -> str:
        """Return the patch version. e.g. '120.0.1' for '120.0.1'.

        Returns:
            The patch version. e.g. '120.0.1' for '120.0.1'.
        """
        if self._patch is None:
            if self._length < 3:
                return self.build
            self._patch = ".".join(self._versions_str)
        return self._patch

    @property
    def patch_num(self) -> int:
        """Return the patch version. e.g. 1 for '120.0.1'.

        Returns:
            The patch version. e.g. 1 for '120.0.1'.
        """
        return self._versions_int[2]

    # Special Methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return self._version.__repr__()

    def __str__(self) -> str:
        """Return the human-readable string representation.

        Returns:
            The human-readable string representation.
        """
        return self._version

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return hash(self._versions_int)

    def __eq__(self, other: Any) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            other: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        if isinstance(other, self.__class__):
            return self._versions_int == other._versions_int
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        """Return whether this instance sorts after another object.

        Args:
            other: Object to compare with this instance.

        Returns:
            True if this instance sorts after another object; otherwise False.
        """
        if isinstance(other, self.__class__):
            return self._versions_int > other._versions_int
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        """Return whether this instance sorts before another object.

        Args:
            other: Object to compare with this instance.

        Returns:
            True if this instance sorts before another object; otherwise False.
        """
        if isinstance(other, self.__class__):
            return self._versions_int < other._versions_int
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        """Return whether this instance sorts after or equal to another object.

        Args:
            other: Object to compare with this instance.

        Returns:
            True if this instance sorts after or equal to another object; otherwise False.
        """
        if isinstance(other, self.__class__):
            return self._versions_int >= other._versions_int
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        """Return whether this instance sorts before or equal to another object.

        Args:
            other: Object to compare with this instance.

        Returns:
            True if this instance sorts before or equal to another object; otherwise False.
        """
        if isinstance(other, self.__class__):
            return self._versions_int <= other._versions_int
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        """Return whether this instance differs from another object.

        Args:
            other: Object to compare with this instance.

        Returns:
            True if this instance differs from another object; otherwise False.
        """
        if isinstance(other, self.__class__):
            return self._versions_int != other._versions_int
        return NotImplemented

    def __len__(self) -> int:
        """Return the number of stored items.

        Returns:
            The number of stored items.
        """
        return self._length

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True


# Chromium Version ---------------------------------------------------------------------------------
class ChromiumVersion(Version):
    """Represent a Chromium based browser/webdriver version."""

    _VERSION_PATTERN: Pattern[str] = compile(r"\d+\.?\d*\.?\d*\.?\d*")
    _VERSION_SEGMENTS: int = 4

    def __init__(self, version: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            version: The version. e.g. '113.0.5672.123'
        """
        super().__init__(version)
        # Version
        self._major: str | None = None
        self._minor: str | None = None
        self._build: str | None = None
        self._patch: str | None = None

    # Version -----------------------------------------------------------------------------
    @property
    def major(self) -> str:
        """Return the major version. e.g. '113' for '113.0.5672.123'.

        Returns:
            The major version. e.g. '113' for '113.0.5672.123'.
        """
        if self._major is None:
            self._major = self._versions_str[0]
        return self._major

    @property
    def major_num(self) -> int:
        """Return the major version. e.g. 113 for '113.0.5672.123'.

        Returns:
            The major version. e.g. 113 for '113.0.5672.123'.
        """
        return self._versions_int[0]

    @property
    def minor(self) -> str:
        """Return the minor version. e.g. '113.0' for '113.0.5672.123'.

        Returns:
            The minor version. e.g. '113.0' for '113.0.5672.123'.
        """
        if self._minor is None:
            if self._length < 2:
                return self.major
            self._minor = ".".join(self._versions_str[:2])
        return self._minor

    @property
    def minor_num(self) -> int:
        """Return the minor version. e.g. 0 for '113.0.5672.123'.

        Returns:
            The minor version. e.g. 0 for '113.0.5672.123'.
        """
        return self._versions_int[1]

    @property
    def build(self) -> str:
        """Return the build version. e.g. '113.0.5672' for '113.0.5672.123'.

        Returns:
            The build version. e.g. '113.0.5672' for '113.0.5672.123'.
        """
        if self._build is None:
            if self._length < 3:
                return self.major
            self._build = ".".join(self._versions_str[:3])
        return self._build

    @property
    def build_num(self) -> int:
        """Return the build version. e.g. 5672 for '113.0.5672.123'.

        Returns:
            The build version. e.g. 5672 for '113.0.5672.123'.
        """
        return self._versions_int[2]

    @property
    def patch(self) -> str:
        """Return the patch version. e.g. '113.0.5672.123' for '113.0.5672.123'.

        Returns:
            The patch version. e.g. '113.0.5672.123' for '113.0.5672.123'.
        """
        if self._patch is None:
            if self._length < 4:
                return self.build
            self._patch = ".".join(self._versions_str)
        return self._patch

    @property
    def patch_num(self) -> int:
        """Return the patch version. e.g. 123 for '113.0.5672.123'.

        Returns:
            The patch version. e.g. 123 for '113.0.5672.123'.
        """
        return self._versions_int[3]


# Firefox Version ----------------------------------------------------------------------------------
class FirefoxVersion(Version):
    """Represent a Firefox browser version."""


# Gecko Version ------------------------------------------------------------------------------------
class GeckoVersion(Version):
    """Represent a Gecko driver version."""


# Safari Version -----------------------------------------------------------------------------------
class SafariVersion(Version):
    """Represent a Safari browser version."""
