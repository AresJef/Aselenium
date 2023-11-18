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
from typing import Any, TYPE_CHECKING
from aselenium import errors
from aselenium.service import BaseService
from aselenium.connection import Connection

if TYPE_CHECKING:
    from aselenium.element import Element
    from aselenium.session import Session

__all__ = ["Shadow", "SHADOWROOT_KEY"]

# Constants ---------------------------------------------------------------------------------------
SHADOWROOT_KEY: str = "shadow-6066-11e4-a52e-4f735466cecf"


# Shadow ------------------------------------------------------------------------------------------
class Shadow:
    """Represents a shadow root inside an element."""

    def __init__(self, shadow_id: str, element: Element) -> None:
        """The shadow root inside an element.

        :param shadow_id: `<str>` The shadow root ID.
        :param element: `<Element>` The element that contains the shadow root.
        """
        # Validate
        if not shadow_id or not isinstance(shadow_id, str):
            raise errors.InvalidResponseError(
                "<{}>\nInvalid shadow root ID: {} {}".format(
                    self.__class__.__name__, repr(shadow_id), type(shadow_id)
                )
            )
        # Element
        self._element: Element = element
        # Session
        self._session: Session = element._session
        self._service: BaseService = self._session.service
        # Connection
        self._conn: Connection = self._session._conn
        # Shadow
        self._id: str = shadow_id
        self._base_url: str = self._session._base_url + "/shadow/" + self._id
        self._body: dict[str, str] = self._session._body | {"shadowId": self._id}

    # Basic -------------------------------------------------------------------------------
    @property
    def session_id(self) -> str:
        """Access the session ID of the shadow root `<str>`.
        e.g. '62eb095e1d01b00a4dc3a497c7330aa5'
        """
        return self._session._id

    @property
    def element_id(self) -> str:
        """Access the element ID of the shadow root `<str>`.
        e.g. '61A5CAC057B025F22A116E47F7950D24_element_1'
        """
        return self._element._id

    @property
    def id(self) -> str:
        """The the ID of the shadow root `<str>`.
        e.g. '61A5CAC057B025F22A116E47F7950D24_element_1'
        """
        return self._id

    @property
    def base_url(self) -> str:
        """Access the base URL of the shadow root `<str>`."""
        return self._base_url

    # Execute -----------------------------------------------------------------------------
    async def execute_command(
        self,
        command: str,
        body: dict | None = None,
        keys: dict | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Executes a command from the shadow root.

        :param command: `<str>` The command to execute.
        :param body: `<dict/None>` The body of the command. Defaults to `None`.
        :param keys: `<dict/None>` The keys to substitute in the command. Defaults to `None`.
        :param timeout: `<int/float/None>` Force timeout of the command. Defaults to `None`.
            For some webdriver versions, the browser will be frozen when
            executing certain commands. This parameter sets an extra
            timeout to throw the `SessionTimeoutError` exception if
            timeout is reached.
        :return `<dict>`: The response from the command.
        """
        return await self._conn.execute(
            self._base_url,
            command,
            body=body | self._body if body else self._body,
            keys=keys,
            timeout=timeout,
        )

    # Element -----------------------------------------------------------------------------
    async def exists_element(self, value: str) -> bool:
        """Check if an element exists (inside the shadow) by the given
        locator and strategy. This method ignores the implicit and
        explicit wait timeouts, and returns element existence immediately.

        :param value: `<str>` The locator for the element `(css only)`.
        :return `<bool>`: True if the element exists, False otherwise.

        ### Example:
        >>> await shadow.exists_element("#input_box")  # True / False
        """
        return await self._session._exists_element(value, "css", self)

    async def exist_elements(self, *values: str, all_: bool = True) -> bool:
        """Check if multiple elements exist (inside the shadow) by the
        given locators and strategy. This method ignores the implicit
        and explicit wait timeouts, and returns elements existence
        immediately.

        :param values: `<str>` The locators for multiple elements `(css only)`.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :param all_: `<bool>` How to determine elements existance. Defaults to `True (all elements)`.
            - `True`: All elements must exist to return True.
            - `False`: Any one of the elements exists returns True.

        :return `<bool>`: True if the elements exist, False otherwise.

        ### Example:
        >>> await shadow.exist_elements(
                "#input_box", "#input_box2", all_=True
            )  # True / False
        """
        return await self._session._exist_elements(values, "css", all_, self)

    async def find_element(self, value: str) -> Element | None:
        """Find the element (inside the shadow) by the given locator and strategy.

        :param value: `<str>` The locator for the element `(css only)`.
        :return `<Element/None>`: The located element, or `None` if not found.

        ### Example:
        >>> await shadow.find_element("#input_box")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_2', session='1e78...', service='http://...')>
        """
        return await self._session._find_element(self.execute_command, value, "css")

    async def find_elements(self, value: str) -> list[Element]:
        """Find elements (inside the shadow) by the given locator and strategy.

        :param value: `<str>` The locator for the elements `(css only)`.
        :return `<list[Element]>`: A list of located elements (empty if not found).

        ### Example:
        >>> await shadow.find_elements("#input_box")
            # [<Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>]
        """
        return await self._session._find_elements(self.execute_command, value, "css")

    async def find_1st_element(self, *values: str) -> Element | None:
        """Find the first located element (inside the shadow) among multiple locators.

        :param values: `<str>` The locators for multiple elements `(css only)`.
        :return `<Element/None>`: The first located element among all locators, or `None` if not found.

        ### Example:
        >>> await shadow.find_1st_element("#input_box", "#input_box2")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
        """
        return await self._session._find_1st_element(values, "css", self)

    async def wait_element_gone(
        self,
        value: str,
        timeout: int | float = 5,
    ) -> bool:
        """Wait for an element (inside the shadow) to disappear by the
        given locator and strategy.

        :param value: `<str>` The locator for the element `(css only)`.
        :param timeout: `<int/float>` Total seconds to wait for the element to disappear. Defaults to `5`.
        :return `<bool>`: True if the element is gone, False if timeout.
        ### Example:
        >>> await shadow.wait_element_gone("#input_box", timeout=5)  # True / False
        """
        return await self._session._wait_element_gone(value, "css", timeout, self)

    async def wait_elements_gone(
        self,
        *values: str,
        timeout: int | float = 5,
        all_: bool = True,
    ) -> bool:
        """Wait for multiple elements (inside the shadow) to disappear by
        the given locators and strategy

        :param values: `<str>` The locators for multiple elements `(css only)`.
        :param timeout: `<int/float>` Total seconds to wait for the element(s) disappear. Defaults to `5`.
        :param all_: How to determine element(s) are gone. Defaults to `True (all elements)`.
            - `True`: All elements must be gone to return True.
            - `False`: Any one of the elements is gone returns True.

        :return `<bool>`: True if the elements are gone, False if timeout.

        ### Example:
        >>> await shadow.wait_elements_gone(
                "#input_box", "#input_box2", timeout=5, all_=True
            )  # True / False
        """
        return await self._session._wait_elements_gone(
            values, "css", timeout, all_, self
        )

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (id='%s', element='%s', session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            self._element._id,
            self._session._id,
            self._service.url,
        )

    def __hash__(self) -> int:
        return hash(self.__class__.__name__, (hash(self._session), self._id))

    def __eq__(self, __o: Any) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, Shadow) else False

    def __del__(self):
        # Element
        self._element = None
        # Session
        self._session = None
        self._service = None
        # Connection
        self._conn = None
        # Shadow
        self._id = None
        self._base_url = None
        self._body = None
