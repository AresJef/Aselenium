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
"""Aselenium options implementation and supporting types."""

from __future__ import annotations

from copy import deepcopy
from typing import (
    Any,
)

from aselenium.logs import logger
from aselenium.options import BaseOptions

__all__ = ["SafariOptions"]


# Safari Options ----------------------------------------------------------------------------------
class SafariOptions(BaseOptions):
    """Safari options."""

    DEFAULT_CAPABILITIES: dict[str, Any] = {
        "browserName": "safari",
        "platformName": "mac",
    }
    "the default capabilities of the safari browser `dict[str, Any]`"

    def __init__(self) -> None:
        """Initialize the instance."""
        super().__init__()

    # Caps: basic -------------------------------------------------------------------------
    def construct(self) -> dict[str, Any]:
        """Construct the final capabilities for the browser.

        Returns:
            A mapping containing the construct data.
        """
        return deepcopy(self._capabilities)

    # Caps: automatic inspection ----------------------------------------------------------
    @property
    def automatic_inspection(self) -> bool:
        """Return whether to enable automatic inspection of web views.

        Returns:
            True if to enable automatic inspection of web views; otherwise False.
        """
        return self._capabilities.get("safari:automaticInspection", False)

    @automatic_inspection.setter
    def automatic_inspection(self, value: bool) -> None:
        """Set the automatic inspection.

        Args:
            value: New automatic inspection value.

        Raises:
            InvalidOptionsError: If value is not a bool.
        """
        value = self._validate_bool(value, "automatic_inspection")
        if not value:
            self._capabilities.pop("safari:automaticInspection", None)
        else:
            self._capabilities["safari:automaticInspection"] = True
        self._caps_changed()

    # Caps: automatic profiling ----------------------------------------------------------
    @property
    def automatic_profiling(self) -> bool:
        """Return whether to enable automatic profiling of web views.

        Returns:
            True if to enable automatic profiling of web views; otherwise False.
        """
        return self._capabilities.get("safari:automaticProfiling", False)

    @automatic_profiling.setter
    def automatic_profiling(self, value: bool) -> None:
        """Set the automatic profiling.

        Args:
            value: New automatic profiling value.

        Raises:
            InvalidOptionsError: If value is not a bool.
        """
        value = self._validate_bool(value, "automatic_profiling")
        if not value:
            self._capabilities.pop("safari:automaticProfiling", None)
        else:
            self._capabilities["safari:automaticProfiling"] = True
        self._caps_changed()

    # Caps: technology preview -----------------------------------------------------------
    @property
    def technology_preview(self) -> bool:
        """Return whether to use Safari Technology Preview.

        Returns:
            True if to use Safari Technology Preview; otherwise False.
        """
        return self._capabilities["browserName"] == "Safari Technology Preview"

    @technology_preview.setter
    def technology_preview(self, value: bool) -> None:
        """Set the technology preview.

        Args:
            value: New technology preview value.

        Raises:
            InvalidOptionsError: If value is not a bool.
        """
        value = self._validate_bool(value, "technology_preview")
        if value:
            self._capabilities["browserName"] = "Safari Technology Preview"
        else:
            self._capabilities["browserName"] = "safari"
        self._caps_changed()

    # Caps: proxy ------------------------------------------------------------------------
    @property
    def proxy(self) -> None:
        """Return browser proxy configurations."""
        return None

    @proxy.setter
    def proxy(self, value: str | None) -> None:
        """Set the proxy.

        Args:
            value: New proxy value. None is handled according to the property's reset/ignore semantics.
        """
        logger.warning(
            "<{}>\nSafari does not support custom proxy configurations.".format(
                self.__class__.__name__
            )
        )
