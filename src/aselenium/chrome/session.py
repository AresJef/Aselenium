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
from aselenium.session import ChromiumBaseSession
from aselenium.chrome.options import ChromeOptions
from aselenium.chrome.service import ChromeService

__all__ = ["ChromeSession"]


# Chrome Session ----------------------------------------------------------------------------------
class ChromeSession(ChromiumBaseSession):
    """Represents a session of the Chrome browser."""

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> ChromeOptions:
        """Access the Chrome options `<ChromeOptions>`."""
        return self._options

    @property
    def service(self) -> ChromeService:
        """Access the Chrome service `<ChromeService>`."""
        return self._service
