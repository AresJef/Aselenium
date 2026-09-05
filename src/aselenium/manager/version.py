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

"""Comparable browser and driver versions parsed from vendor output."""

from __future__ import annotations

from re import Pattern, compile
from typing import ClassVar

from aselenium import errors

__all__ = ["ChromiumVersion", "FirefoxVersion", "GeckoVersion", "SafariVersion"]


# Version ------------------------------------------------------------------------------------------
class Version:
    """Parse and compare the first supported numeric version in vendor text.

    Missing components compare as zero. Consequently, ``Version("120")`` and
    ``Version("120.0.0")`` compare equal, while ``version`` and ``str()`` retain
    the matched substring's original component count.
    """

    _VERSION_PATTERN: ClassVar[Pattern[str]] = compile(r"\d+(?:\.\d+){0,2}")
    _VERSION_SEGMENTS: ClassVar[int] = 3
    _version: str
    _versions_str: tuple[str, ...]
    _versions_int: tuple[int, ...]
    _length: int

    def __init__(self, version: str | Version) -> None:
        """Parse vendor text or copy a compatible version instance.

        Args:
            version: Dotted numeric version or vendor output containing one,
                such as ``"Firefox 120.0.1"``.

        Raises:
            errors.InvalidVersionError: The value is neither text nor a
                compatible version instance, or it contains no numeric version.

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
        """Populate display and zero-padded comparison components.

        Args:
            version: Vendor output, dotted version text, or an instance accepted
                by this parser class.

        Raises:
            errors.InvalidVersionError: No supported numeric version is present.
        """
        if isinstance(version, self.__class__):
            self._version = version._version
            self._versions_str = version._versions_str
            self._versions_int = version._versions_int
            self._length = version._length
            return
        if not isinstance(version, str):
            raise errors.InvalidVersionError(
                "Invalid version: {} {}".format(repr(version), type(version))
            )

        match = self._VERSION_PATTERN.search(version)
        if match is None:
            raise errors.InvalidVersionError(
                "Invalid version: {} {}".format(repr(version), type(version))
            )

        self._version = match.group(0)
        self._versions_str = tuple(self._version.split("."))
        versions_int = [int(part) for part in self._versions_str]

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
        """Return the matched numeric substring without zero-padding.

        Returns:
            One-to-three-component version text extracted from the input.
        """
        return self._version

    @property
    def major(self) -> str:
        """Return the first version component as text.

        Returns:
            Major component, such as ``"120"`` for ``"120.0.1"``.
        """
        if self._major is None:
            self._major = self._versions_str[0]
        return self._major

    @property
    def major_num(self) -> int:
        """Return the first version component as an integer.

        Returns:
            Major component, such as ``120`` for ``"120.0.1"``.
        """
        return self._versions_int[0]

    @property
    def build(self) -> str:
        """Return text through the second component when one was present.

        Returns:
            Two-component prefix such as ``"120.0"``, or the major text for a
            one-component input.
        """
        if self._build is None:
            if self._length < 2:
                return self.major
            self._build = ".".join(self._versions_str[:2])
        return self._build

    @property
    def build_num(self) -> int:
        """Return the second comparison component as an integer.

        Returns:
            Second component, or zero when it was absent from the input.
        """
        return self._versions_int[1]

    @property
    def patch(self) -> str:
        """Return text through the third component when one was present.

        Returns:
            Complete three-component text, or the longest shorter prefix parsed.
        """
        if self._patch is None:
            if self._length < 3:
                return self.build
            self._patch = ".".join(self._versions_str)
        return self._patch

    @property
    def patch_num(self) -> int:
        """Return the third comparison component as an integer.

        Returns:
            Third component, or zero when it was absent from the input.
        """
        return self._versions_int[2]

    # Special Methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return the Python representation of the matched version text.

        Returns:
            Quoted version text suitable for diagnostics.
        """
        return self._version.__repr__()

    def __str__(self) -> str:
        """Return the matched version text.

        Returns:
            Version substring without comparison padding.
        """
        return self._version

    def __hash__(self) -> int:
        """Hash the zero-padded numeric comparison components.

        Returns:
            Hash consistent with equality between abbreviated versions.
        """
        return hash(self._versions_int)

    def __eq__(self, other: object) -> bool:
        """Compare normalized components with a compatible version object.

        Args:
            other: Candidate version object.

        Returns:
            ``True`` when numeric components match, ``False`` when they differ,
            or ``NotImplemented`` for an incompatible type.
        """
        if isinstance(other, self.__class__):
            return self._versions_int == other._versions_int
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        """Compare whether this normalized version sorts after another.

        Args:
            other: Candidate version object.

        Returns:
            Comparison result, or ``NotImplemented`` for an incompatible type.
        """
        if isinstance(other, self.__class__):
            return self._versions_int > other._versions_int
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        """Compare whether this normalized version sorts before another.

        Args:
            other: Candidate version object.

        Returns:
            Comparison result, or ``NotImplemented`` for an incompatible type.
        """
        if isinstance(other, self.__class__):
            return self._versions_int < other._versions_int
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        """Compare whether this normalized version is at least another.

        Args:
            other: Candidate version object.

        Returns:
            Comparison result, or ``NotImplemented`` for an incompatible type.
        """
        if isinstance(other, self.__class__):
            return self._versions_int >= other._versions_int
        return NotImplemented

    def __le__(self, other: object) -> bool:
        """Compare whether this normalized version is at most another.

        Args:
            other: Candidate version object.

        Returns:
            Comparison result, or ``NotImplemented`` for an incompatible type.
        """
        if isinstance(other, self.__class__):
            return self._versions_int <= other._versions_int
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        """Compare normalized components for inequality.

        Args:
            other: Candidate version object.

        Returns:
            ``True`` when numeric components differ, ``False`` when they match,
            or ``NotImplemented`` for an incompatible type.
        """
        if isinstance(other, self.__class__):
            return self._versions_int != other._versions_int
        return NotImplemented

    def __len__(self) -> int:
        """Return the number of components present in the parsed source text.

        Returns:
            Component count before missing comparison components are zero-padded.
        """
        return self._length

    def __bool__(self) -> bool:
        """Keep every successfully parsed version truthy.

        Returns:
            Always ``True``.
        """
        return True


# Chromium Version ---------------------------------------------------------------------------------
class ChromiumVersion(Version):
    """Parse and compare up to four Chromium-family version components."""

    _VERSION_PATTERN: ClassVar[Pattern[str]] = compile(r"\d+(?:\.\d+){0,3}")
    _VERSION_SEGMENTS: ClassVar[int] = 4

    def __init__(self, version: str | ChromiumVersion) -> None:
        """Parse Chromium version text or copy another Chromium version.

        Args:
            version: Dotted version or vendor output containing one, such as
                ``"Google Chrome 113.0.5672.123"``.

        Raises:
            errors.InvalidVersionError: No Chromium-style numeric version can
                be parsed.
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
        """Return the Chromium major component as text.

        Returns:
            Major component, such as ``"113"`` for ``"113.0.5672.123"``.
        """
        if self._major is None:
            self._major = self._versions_str[0]
        return self._major

    @property
    def major_num(self) -> int:
        """Return the Chromium major component as an integer.

        Returns:
            Major component, such as ``113`` for ``"113.0.5672.123"``.
        """
        return self._versions_int[0]

    @property
    def minor(self) -> str:
        """Return text through the Chromium minor component when present.

        Returns:
            Two-component prefix such as ``"113.0"``, or the major text for a
            one-component input.
        """
        if self._minor is None:
            if self._length < 2:
                return self.major
            self._minor = ".".join(self._versions_str[:2])
        return self._minor

    @property
    def minor_num(self) -> int:
        """Return the Chromium minor comparison component as an integer.

        Returns:
            Second component, or zero when it was absent from the input.
        """
        return self._versions_int[1]

    @property
    def build(self) -> str:
        """Return text through the Chromium build component when present.

        Returns:
            Three-component prefix such as ``"113.0.5672"``. Inputs without a
            build component fall back to the major text.
        """
        if self._build is None:
            if self._length < 3:
                return self.major
            self._build = ".".join(self._versions_str[:3])
        return self._build

    @property
    def build_num(self) -> int:
        """Return the Chromium build comparison component as an integer.

        Returns:
            Third component, or zero when it was absent from the input.
        """
        return self._versions_int[2]

    @property
    def patch(self) -> str:
        """Return text through the Chromium patch component when present.

        Returns:
            Complete four-component text, or the longest supported shorter view.
        """
        if self._patch is None:
            if self._length < 4:
                return self.build
            self._patch = ".".join(self._versions_str)
        return self._patch

    @property
    def patch_num(self) -> int:
        """Return the Chromium patch comparison component as an integer.

        Returns:
            Fourth component, or zero when it was absent from the input.
        """
        return self._versions_int[3]


# Firefox Version ----------------------------------------------------------------------------------
class FirefoxVersion(Version):
    """Parse and compare up to three Firefox browser version components."""


# Gecko Version ------------------------------------------------------------------------------------
class GeckoVersion(Version):
    """Parse and compare up to three geckodriver version components."""


# Safari Version -----------------------------------------------------------------------------------
class SafariVersion(Version):
    """Parse and compare up to three Safari browser version components."""
