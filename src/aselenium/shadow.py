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
from asyncio import sleep
from time import time as unix_time
from typing import Any, Literal, Awaitable, TYPE_CHECKING
from aselenium.command import Command
from aselenium import errors, javascript
from aselenium.service import BaseService
from aselenium.connection import Connection

if TYPE_CHECKING:
    from aselenium.element import Element
    from aselenium.session import Session

__all__ = ["Shadow"]

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
        :param timeout: `<int/float/None>` Session timeout for command execution. Defaults to `None`.
            This arguments overwrites the default `options.session_timeout`,
            which is designed to cope with a frozen session due to unknown
            errors. For more information about session timeout, please refer
            to the documentation of `options.session_timeout` attribute.

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
    async def element_exists(self, value: str | Element) -> bool:
        """Check if an element exists (inside the shadow). This method ignores
        the implicit wait timeout, and returns element existence immediately.

        :param value: `<str/Element>` The selector for the element (css only) *OR* an `<Element>` instance.
        :return `<bool>`: True if the element exists, False otherwise.

        ### Example:
        >>> await shadow.element_exists("#input_box")  # True / False
        """
        if self._session._is_element(value):
            return await value.exists
        else:
            return await self._element_exists_no_wait(value)

    async def elements_exist(self, *values: str | Element, all_: bool = True) -> bool:
        """Check if multiple elements exist (inside the shadow). This method
        ignores the implicit wait timeout, and returns elements existence
        immediately.

        :param values: `<str/Element>` The locators for multiple elements (css only) *OR* `<Element>` instances.
        :param all_: `<bool>` Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
            - `True`: All elements must exist to return True.
            - `False`: Any one of the elements exists returns True.

        :return `<bool>`: True if the elements exist, False otherwise.

        ### Example:
        >>> await shadow.elements_exist(
                "#input_box", "#input_box2", all_=True
            )  # True / False
        """

        async def check_existance(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value)

        # Check existance
        if all_:
            for value in values:
                if not await check_existance(value):
                    return False
            return True
        else:
            for value in values:
                if await check_existance(value):
                    return True
            return False

    async def find_element(self, value: str) -> Element | None:
        """Find the element (inside the shadow) by the given selector
        and strategy. The timeout for finding an element is determined
        by the implicit wait of the session.

        :param value: `<str>` The selector for the element `(css only)`.
        :return `<Element/None>`: The located element, or `None` if not found.

        ### Example:
        >>> await shadow.find_element("#input_box")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_2', session='1e78...', service='http://...')>
        """
        try:
            res = await self.execute_command(
                Command.FIND_ELEMENT, body={"using": "css selector", "value": value}
            )
        except errors.ElementNotFoundError:
            return None
        except errors.InvalidArgumentError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        # Create element
        try:
            return self._session._create_element(res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse element from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def find_elements(self, value: str) -> list[Element]:
        """Find elements (inside the shadow) by the given selector and
        strategy. The timeout for finding the elements is determined by
        the implicit wait of the session.

        :param value: `<str>` The selector for the elements `(css only)`.
        :return `<list[Element]>`: A list of located elements (empty if not found).

        ### Example:
        >>> await shadow.find_elements("#input_box")
            # [<Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>]
        """
        try:
            res = await self.execute_command(
                Command.FIND_ELEMENTS, body={"using": "css selector", "value": value}
            )
        except errors.ElementNotFoundError:
            return []
        except errors.InvalidArgumentError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        # Create elements
        try:
            return [self._session._create_element(value) for value in res["value"]]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse elements from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def find_1st_element(self, *values: str) -> Element | None:
        """Find the first located element (inside the shadow) among
        multiple locators. The timeout for finding the first element
        is determined by the implicit wait of the session.

        :param values: `<str>` The locators for multiple elements `(css only)`.
        :return `<Element/None>`: The first located element among all locators, or `None` if not found.

        ### Example:
        >>> await shadow.find_1st_element("#input_box", "#input_box2")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
        """
        # Locate 1st element
        timeout = (await self._session._get_timeouts()).implicit
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            for value in values:
                element = await self._find_element_no_wait(value)
                if element is not None:
                    return element
                await sleep(0.2)
        return None

    async def wait_until_element(
        self,
        condition: Literal[
            "gone",
            "exist",
            "visible",
            "viewable",
            "enabled",
            "selected",
        ],
        value: str | Element,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until an element (inside the shadow) satisfies the given condition.

        :param condition: `<str>` The condition to satisfy. Available options:
            - `'gone'`: Wait until an element disappears from the shadow.
            - `'exist'`: Wait until an element appears in the shadow.
            - `'visible'`: Wait until an element not only is displayed but also not
                blocked by any other elements (e.g. an overlay or modal).
            - `'viewable'`: Wait until an element is displayed regardless whether it
                is blocked by other elements (e.g. an overlay or modal).
            - `'enabled'`: Wait until an element is enabled.
            - `'selected'`: Wait until an element is selected.

        :param value: `<str/Element>` The selector for the element (css only) *OR* an `<Element>` instance.
        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return `<bool>`: True if the element satisfies the condition, False otherwise.

        ### Example:
        >>> await shadow.wait_until_element(
                "visible", "#input_box", by="css", timeout=5
            )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            if self._session._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value)

        async def is_exist(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value)

        async def is_visible(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.visible
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.visible

        async def is_viewable(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.viewable
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.viewable

        async def is_enabled(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.selected

        # Determine condition
        if condition == "gone":
            condition_checker = is_gone
        elif condition == "exist":
            condition_checker = is_exist
        elif condition == "visible":
            condition_checker = is_visible
        elif condition == "viewable":
            condition_checker = is_viewable
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        # Check condition
        if await condition_checker(value):
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await condition_checker(value):
                return True
        return False

    async def wait_until_elements(
        self,
        condition: Literal[
            "gone",
            "exist",
            "visible",
            "viewable",
            "enabled",
            "selected",
        ],
        *values: str | Element,
        all_: bool = True,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until multiple elements (inside the shadow) satisfy the given condition.

        :param condition: `<str>` The condition to satisfy. Available options:
            - `'gone'`: Wait until the elements disappear from the shadow.
            - `'exist'`: Wait until the elements appear in the shadow.
            - `'visible'`: Wait until the elements not only are displayed but also not
                blocked by any other elements (e.g. an overlay or modal).
            - `'viewable'`: Wait until the elements are displayed regardless whether
                blocked by other elements (e.g. an overlay or modal).
            - `'enabled'`: Wait until the elements are enabled.
            - `'selected'`: Wait until the elements are selected.

        :param values: `<str/Element>` The locators for multiple elements (css only) *OR* `<Element>` instances.
        :param all_: `<bool>` Determine how to satisfy the condition. Defaults to `True (all elements)`.
            - `True`: All elements must satisfy the condition to return True.
            - `False`: Any one of the elements satisfies the condition returns True.

        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return `<bool>`: True if the elements satisfy the condition, False otherwise.

        ### Example:
        >>> await shadow.wait_until_elements(
                "visible", "#input_box1", "#search_button",
                by="css", all_=True, timeout=5
            )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            if self._session._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value)

        async def is_exist(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value)

        async def is_visible(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.visible
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.visible

        async def is_viewable(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.viewable
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.viewable

        async def is_enabled(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.selected

        async def check_condition(values: tuple, condition_checker: Awaitable) -> bool:
            if all_:
                for value in values:
                    if not await condition_checker(value):
                        return False
                return True
            else:
                for value in values:
                    if await condition_checker(value):
                        return True
                return False

        # Determine condition
        if condition == "gone":
            condition_checker = is_gone
        elif condition == "exist":
            condition_checker = is_exist
        elif condition == "visible":
            condition_checker = is_visible
        elif condition == "viewable":
            condition_checker = is_viewable
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        # Check condition
        if await check_condition(values, condition_checker):
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await check_condition(values, condition_checker):
                return True
        return False

    async def _element_exists_no_wait(self, value: str) -> bool:
        """(Internal) Check if an element exists (inside the element)
        without implicit wait `<bool>`. Returns `False` immediately if
        element not exists.
        """
        try:
            return await self._session._execute_script(
                javascript.ELEMENT_EXISTS_IN_NODE["css selector"], value, self
            )
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidElementStateError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err

    async def _find_element_no_wait(self, value: str) -> Element | None:
        """(Internal) Find element (inside the element) without implicit
        wait `<Element>`. Returns `None` immediately if element not exists.
        """
        try:
            res = await self._session._execute_script(
                javascript.FIND_ELEMENT_IN_NODE["css selector"], value, self
            )
        except errors.ElementNotFoundError:
            return None
        except errors.InvalidElementStateError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        try:
            return self._session._create_element(res)
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse element from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    # Utils -------------------------------------------------------------------------------
    def _validate_timeout(self, value: Any) -> int | float:
        """(Internal) Validate if timeout value `> 0` `<int/float>`."""
        if not isinstance(value, (int, float)):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'timeout'. Must be an integer or float, "
                "instead got: {}.".format(self.__class__.__name__, type(value))
            )
        if value <= 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'timeout'. Must be greater than 0, "
                "instead got: {}.".format(self.__class__.__name__, value)
            )
        return value

    def _raise_invalid_wait_condition(self, condition: Any) -> None:
        """(Internal) Raise invalid wait until 'condition' error."""
        raise errors.InvalidArgumentError(
            "<{}>\nInvalid wait until condition: {} {}.".format(
                self.__class__.__name__, repr(condition), type(condition)
            )
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
