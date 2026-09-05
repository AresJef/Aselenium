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

"""Chrome-specific typed accessors for Chromium session behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aselenium.session import ChromiumBaseSession

if TYPE_CHECKING:
    from aselenium.chrome.options import ChromeOptions
    from aselenium.chrome.service import ChromeService

__all__ = ["ChromeSession"]


# Chrome Session ----------------------------------------------------------------------------------
class ChromeSession(ChromiumBaseSession):
    """Represent a session of the Chrome browser."""

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> ChromeOptions:
        """Return the Chrome options.

        Returns:
            The browser options owned by this facade or session.
        """
        return cast("ChromeOptions", super().options)

    @property
    def service(self) -> ChromeService:
        """Return the Chrome service.

        Returns:
            The driver service owned by the session.
        """
        return cast("ChromeService", super().service)
