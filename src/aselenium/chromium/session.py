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
from aselenium.chromium.options import ChromiumOptions
from aselenium.chromium.service import ChromiumService
from aselenium.session import ChromiumBaseSession, ChromiumBaseSessionContext

__all__ = ["ChromiumSession", "ChromiumSessionContext"]


# Chromium Session --------------------------------------------------------------------------------
class ChromiumSession(ChromiumBaseSession):
    """Represents a session of the Chromium browser."""

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> ChromiumOptions:
        """Access the Chromium options `<ChromiumOptions>`."""
        return self._options

    @property
    def service(self) -> ChromiumService:
        """Access the Chromium service `<ChromiumService>`."""
        return self._service


class ChromiumSessionContext(ChromiumBaseSessionContext):
    """The context manager for a Chromium session."""

    def __init__(self, options: ChromiumOptions, service: ChromiumService) -> None:
        """The context manager for a Chromium session.

        :param options: `<ChromiumOptions>` The browser options.
        :param service: `<ChromiumService>` The browser service.
        """
        self._session = ChromiumSession(options, service)

    async def __aenter__(self) -> ChromiumSession:
        return await self.start()
