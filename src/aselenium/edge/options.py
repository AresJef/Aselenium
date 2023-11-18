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
from aselenium import errors
from aselenium.options import ChromiumBaseOptions

__all__ = ["EdgeOptions"]


# Edge Options ------------------------------------------------------------------------------------
class EdgeOptions(ChromiumBaseOptions):
    """Edge options."""

    DEFAULT_CAPABILITIES: dict[str, Any] = {"browserName": "MicrosoftEdge"}
    VENDOR_PREFIX: str = "ms"
    KEY: str = "ms:edgeOptions"

    def __init__(self) -> None:
        super().__init__()
        self._use_webview: bool = False

    # Caps: basic -------------------------------------------------------------------------
    def construct(self) -> dict[str, Any]:
        """Construct the final capabilities for the browser."""
        caps = super().construct()
        if self._use_webview:
            caps["browserName"] = "webview2"
        return caps

    # Caps: web view ----------------------------------------------------------------------
    @property
    def use_webview(self) -> bool:
        """Access whether to use the WebView2 browser instead
        of the default Edge browser `<bool>`.
        """
        return self._use_webview

    @use_webview.setter
    def use_webview(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise errors.InvalidOptionsError(
                f"<{self.__class__.__name__}>\n`use_webview` must be type of `<bool>`."
            )
        self._use_webview = value
