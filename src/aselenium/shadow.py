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
"""Aselenium shadow implementation and supporting types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NoReturn,
)
from urllib.parse import quote

from aselenium import errors, javascript
from aselenium._wait import first_match, poll
from aselenium.command import Command

if TYPE_CHECKING:
    from aselenium.connection import Connection
    from aselenium.element import Element
    from aselenium.service import BaseService
    from aselenium.session import Session

__all__ = ["Shadow"]

# Constants ---------------------------------------------------------------------------------------
SHADOWROOT_KEY: str = "shadow-6066-11e4-a52e-4f735466cecf"


# Shadow ------------------------------------------------------------------------------------------
class Shadow:
    """Represent a shadow root inside an element."""

    def __init__(self, shadow_id: str, element: Element) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            shadow_id: The shadow root ID.
            element: The element that contains the shadow root.
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
        self._base_url: str = (
            self._session._base_url + "/shadow/" + quote(self._id, safe="")
        )

    # Basic -------------------------------------------------------------------------------
    @property
    def session_id(self) -> str | None:
        """Return the parent session's current ID.

        Returns:
            The session ID, or None after the parent session has been closed.
        """
        return self._session._id

    @property
    def element_id(self) -> str:
        """Return the element ID of the shadow root. e.g. '61A5CAC057B025F22A116E47F7950D24_element_1'.

        Returns:
            The element id of the shadow root. e.g. '61a5cac057b025f22a116e47f7950d24_element_1'.
        """
        return self._element._id

    @property
    def id(self) -> str:
        """The the ID of the shadow root. e.g. '61A5CAC057B025F22A116E47F7950D24_element_1'.

        Returns:
            The stored id.
        """
        return self._id

    @property
    def base_url(self) -> str:
        """Return the base URL of the shadow root.

        Returns:
            The base url of the shadow root.
        """
        return self._base_url

    # Execute -----------------------------------------------------------------------------
    async def execute_command(
        self,
        command: str,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Executes a command from the shadow root.

        Args:
            command: The command to execute.
            body: The body of the command. Defaults to `None`.
            keys: The keys to substitute in the command. Defaults to `None`.
            timeout: Session timeout for command execution. Defaults to `None`.
                This argument overrides the default `options.session_timeout`,
                which is designed to cope with a frozen session due to unknown
                errors. For more information about session timeout, please refer
                to the documentation of `options.session_timeout` attribute.

        Returns:
            The response from the command.
        """
        return await self._conn.execute(
            self._base_url,
            command,
            body=body,
            keys=keys,
            timeout=timeout,
        )

    # Element -----------------------------------------------------------------------------
    async def element_exists(self, value: str | Element) -> bool:
        """Check if an element exists (inside the shadow). This method ignores the implicit wait timeout, and returns element existence immediately.

        Args:
            value: The selector for the element (css only) *OR* an  instance.

        Returns:
            True if the element exists, False otherwise.

        Example:
            >>> await shadow.element_exists("#input_box")  # True / False
        """
        if self._session._is_element(value):
            return await value.exists
        else:
            return await self._element_exists_no_wait(value)

    async def elements_exist(self, *values: str | Element, all_: bool = True) -> bool:
        """Check if multiple elements exist (inside the shadow). This method ignores the implicit wait timeout, and returns elements existence immediately.

        Args:
            all_: Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
                - `True`: All elements must exist to return True.
                - `False`: Any one of the elements exists returns True.
            *values: The locators for multiple elements (css only) *OR*  instances.

        Returns:
            True if the elements exist, False otherwise.

        Example:
            >>> await shadow.elements_exist(
            ...     "#input_box", "#input_box2", all_=True
            ... )  # True / False
        """

        async def check_existance(value: str | Element) -> bool:
            """Perform one element-existence observation for the enclosing wait.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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
        """Find the element (inside the shadow) by the given selector and strategy. The timeout for finding an element is determined by the implicit wait of the session.

        Args:
            value: The selector for the element `(css only)`.

        Returns:
            The located element, or `None` if not found.

        Example:
            >>> await shadow.find_element("#input_box")
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
        """Find elements (inside the shadow) by the given selector and strategy. The timeout for finding the elements is determined by the implicit wait of the session.

        Args:
            value: The selector for the elements `(css only)`.

        Returns:
            A list of located elements (empty if not found).

        Example:
            >>> await shadow.find_elements("#input_box")
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
            return self._session._create_elements(res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse elements from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def find_1st_element(self, *values: str) -> Element | None:
        """Find the first located element (inside the shadow) among multiple locators. The timeout for finding the first element is determined by the implicit wait of the session.

        Args:
            *values: The locators for multiple elements `(css only)`.

        Returns:
            The first located element among all locators, or `None` if not found.

        Example:
            >>> await shadow.find_1st_element("#input_box", "#input_box2")
        """
        # Locate 1st element
        timeout = (await self._session._get_timeouts()).implicit
        return await first_match(
            values, lambda value: self._find_element_no_wait(value), timeout
        )

    async def wait_until_element(
        self,
        condition: Literal[
            "gone", "exist", "unobscured", "in_viewport", "enabled", "selected"
        ],
        value: str | Element,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until an element (inside the shadow) satisfies the given condition.

        Args:
            condition: The condition to satisfy. Available options:
                - `'gone'`: Wait until an element disappears from the shadow.
                - `'exist'`: Wait until an element appears in the shadow.
                - `'unobscured'`: Wait for center-point hit testing to reach the element.
                - `'in_viewport'`: Wait for a nonempty rectangle intersecting the viewport.
                - `'enabled'`: Wait until an element is enabled.
                - `'selected'`: Wait until an element is selected.
            value: The selector for the element (css only) *OR* an  instance.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the element satisfies the condition, False otherwise.

        Example:
            >>> await shadow.wait_until_element(
            ...     "unobscured", "#input_box", timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value)

        async def is_exist(value: str | Element) -> bool:
            """Check whether a matching element currently exists.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value)

        async def is_unobscured(value: str | Element) -> bool:
            """Check the matched element using a center-point hit test.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.unobscured
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.unobscured

        async def is_in_viewport(value: str | Element) -> bool:
            """Check whether the matched element intersects the viewport.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.in_viewport
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.in_viewport

        async def is_enabled(value: str | Element) -> bool:
            """Check whether the matched element is enabled.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            """Check whether the matched element is selected.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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
        elif condition == "unobscured":
            condition_checker = is_unobscured
        elif condition == "in_viewport":
            condition_checker = is_in_viewport
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        return bool(await poll(lambda: condition_checker(value), timeout))

    async def wait_until_elements(
        self,
        condition: Literal[
            "gone", "exist", "unobscured", "in_viewport", "enabled", "selected"
        ],
        *values: str | Element,
        all_: bool = True,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until multiple elements (inside the shadow) satisfy the given condition.

        Args:
            condition: The condition to satisfy. Available options:
                - `'gone'`: Wait until the elements disappear from the shadow.
                - `'exist'`: Wait until the elements appear in the shadow.
                - `'unobscured'`: Wait for center-point hit testing to reach the element.
                - `'in_viewport'`: Wait for nonempty rectangles intersecting the viewport.
                - `'enabled'`: Wait until the elements are enabled.
                - `'selected'`: Wait until the elements are selected.
            all_: Determine how to satisfy the condition. Defaults to `True (all elements)`.
                - `True`: All elements must satisfy the condition to return True.
                - `False`: Any one of the elements satisfies the condition returns True.
            timeout: Total seconds to wait until timeout. Defaults to `5`.
            *values: The locators for multiple elements (css only) *OR*  instances.

        Returns:
            True if the elements satisfy the condition, False otherwise.

        Example:
            >>> await shadow.wait_until_elements(
            ...     "unobscured", "#input_box1", "#search_button",
            ...     all_=True, timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value)

        async def is_exist(value: str | Element) -> bool:
            """Check whether a matching element currently exists.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value)

        async def is_unobscured(value: str | Element) -> bool:
            """Check the matched element using a center-point hit test.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.unobscured
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.unobscured

        async def is_in_viewport(value: str | Element) -> bool:
            """Check whether the matched element intersects the viewport.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.in_viewport
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.in_viewport

        async def is_enabled(value: str | Element) -> bool:
            """Check whether the matched element is enabled.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            """Check whether the matched element is selected.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if self._session._is_element(value):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value)
                return False if element is None else await element.selected

        async def check_condition(
            values: tuple[Any, ...],
            condition_checker: Callable[[str | Element], Awaitable[bool]],
        ) -> bool:
            """Evaluate the condition for each requested selector in the current poll.

            Args:
                values: Input values evaluated in order by this operation.
                condition_checker: Condition checker used by this operation.

            Returns:
                True when the requested condition holds for all candidates if all_ is True, or for any candidate otherwise; False if the requirement is not met.
            """
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
        elif condition == "unobscured":
            condition_checker = is_unobscured
        elif condition == "in_viewport":
            condition_checker = is_in_viewport
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        return bool(
            await poll(lambda: check_condition(values, condition_checker), timeout)
        )

    async def _element_exists_no_wait(self, value: str) -> bool:
        """Check if an element exists (inside the element) without implicit wait. Returns `False` immediately if element not exists.

        Args:
            value: Value to inspect, normalize, or assign as described above.

        Returns:
            True if an element exists (inside the element) without implicit wait; otherwise False.
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
        """Find element (inside the element) without implicit wait. Returns `None` immediately if element not exists.

        Args:
            value: Value to inspect, normalize, or assign as described above.

        Returns:
            The Element value produced by this operation. None indicates that no value is available.
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
        """Validate if timeout value `> 0`.

        Args:
            value: If timeout value `> 0` supplied for validation.

        Returns:
            If timeout value `> 0`.
        """
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

    def _raise_invalid_wait_condition(self, condition: Any) -> NoReturn:
        """Raise invalid wait until 'condition' error.

        Args:
            condition: Asynchronous no-argument predicate whose truthy result completes the wait.

        Raises:
            errors.InvalidArgumentError: Always raised with the supplied diagnostic context.
        """
        raise errors.InvalidArgumentError(
            "<{}>\nInvalid wait until condition: {} {}.".format(
                self.__class__.__name__, repr(condition), type(condition)
            )
        )

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (id='%s', element='%s', session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            self._element._id,
            self._session._id,
            self._service.url,
        )

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return hash((self._session, self._id))

    def __eq__(self, __o: Any) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return (
            self._session == __o._session and self._id == __o._id
            if isinstance(__o, Shadow)
            else False
        )
