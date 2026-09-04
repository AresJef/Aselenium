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
"""Aselenium element implementation and supporting types."""

from __future__ import annotations

from asyncio import sleep
from collections.abc import Awaitable, Callable
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NoReturn,
)
from urllib.parse import quote

from aselenium import errors, javascript
from aselenium._output import save_bytes
from aselenium._paths import PathInput, file_path, save_file_path
from aselenium._wait import first_match, poll
from aselenium.command import Command
from aselenium.shadow import SHADOWROOT_KEY, Shadow
from aselenium.utils import (
    Rectangle,
    process_keys,
)

if TYPE_CHECKING:
    from aselenium.connection import Connection
    from aselenium.service import BaseService
    from aselenium.session import Session

__all__ = ["Element", "ElementRect"]

# Constants ---------------------------------------------------------------------------------------
ELEMENT_KEY: str = "element-6066-11e4-a52e-4f735466cecf"


# Element Objects ---------------------------------------------------------------------------------
class ElementRect(Rectangle):
    """Represent the size and relative position of an element."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """Initialize an element's rectangle in CSS pixels.

        Args:
            width: The width of the element.
            height: The height of the element.
            x: The x-coordinate of the element.
            y: The y-coordinate of the element.
        """
        super().__init__(width, height, x, y)

    # Special methods ---------------------------------------------------------------------
    def copy(self) -> ElementRect:
        """Copy the element rectangle.

        Returns:
            An independent copy of this value object.
        """
        return super().copy()


# Element -----------------------------------------------------------------------------------------
class Element:
    """Represent a DOM tree element."""

    def __init__(self, element_id: str, session: Session) -> None:
        """Bind a validated remote element ID to a started session.

        Args:
            element_id: The element ID.
            session: The session of the element.

        Raises:
            errors.InvalidResponseError: The element ID is not a nonempty string.
            errors.InvalidSessionError: The session has no connection or command URL.
        """
        # Validate
        if not element_id or not isinstance(element_id, str):
            raise errors.InvalidResponseError(
                "<{}>\nInvalid element ID: {} {}".format(
                    self.__class__.__name__, repr(element_id), type(element_id)
                )
            )
        # Session
        self._session: Session = session
        self._service: BaseService = session._service
        # Connection
        connection, base_url = session._conn, session._base_url
        if connection is None or base_url is None:
            raise errors.InvalidSessionError("Element requires a started session")
        self._conn: Connection = connection
        # Element
        self._id: str = element_id
        self._base_url: str = base_url + "/element/" + quote(self._id, safe="")

    # Basic -------------------------------------------------------------------------------
    @property
    def session_id(self) -> str | None:
        """Return the parent session's current ID.

        Returns:
            The session ID, or None after the parent session has been closed.
        """
        return self._session._id

    @property
    def id(self) -> str:
        """Return the ID of the element. e.g. '61A5CAC057B025F22A116E47F7950D24_element_1'.

        Returns:
            The id of the element. e.g. '61a5cac057b025f22a116e47f7950d24_element_1'.
        """
        return self._id

    @property
    def base_url(self) -> str:
        """Return the base service URL of the element.

        Returns:
            The base service url of the element.
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
        """Executes a command from the element.

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

    # Control -----------------------------------------------------------------------------
    @property
    async def exists(self) -> bool:
        """Return whether the element still exists in the DOM tree when this attribute is called.

        Returns:
            True if the element still exists in the DOM tree when this attribute is called; otherwise False.
        """
        try:
            return await self._session._execute_script(
                javascript.ELEMENT_IS_VALID, self
            )
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check element existance: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    @property
    async def enabled(self) -> bool:
        """Return whether the element is enabled.

        Returns:
            True if the element is enabled; otherwise False.

        Raises:
            errors.InvalidResponseError: The driver returns a non-boolean state.
        """
        try:
            res = await self.execute_command(Command.IS_ELEMENT_ENABLED)
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        try:
            value = res["value"]
            if not isinstance(value, bool):
                raise errors.InvalidResponseError(
                    "Element enabled state must be a boolean"
                )
            return value
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check if element is enabled from response: {}".format(
                    self.__class__.__name__, repr(res)
                )
            ) from err

    @property
    async def selected(self) -> bool:
        """Return whether the element is selected.

        Primarily used for checking if a checkbox or radio button is selected.

        Returns:
            True if the element is selected; otherwise False.

        Raises:
            errors.InvalidResponseError: The driver returns a non-boolean state.
        """
        try:
            res = await self.execute_command(Command.IS_ELEMENT_SELECTED)
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        try:
            value = res["value"]
            if not isinstance(value, bool):
                raise errors.InvalidResponseError(
                    "Element selected state must be a boolean"
                )
            return value
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check if element is selected from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def click(self, pause: int | float | None = None) -> None:
        """Click the element.

        Args:
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.
        """
        await self.execute_command(Command.CLICK_ELEMENT)
        await self.pause(pause)

    async def send(
        self,
        *keys: str,
        pause: int | float | None = None,
    ) -> None:
        """Simulate typing or keyboard keys pressing into the element. (To send local files, use the `upload()` method.).

        Args:
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.
            *keys: strings to be typed or keyboard keys to be pressed.

        Example:
            >>> from aselenium import KeyboardKeys
            >>> inputbox = await session.find_element("#input_box")
            >>> assert inputbox is not None
            >>> # Sent text - "Hello world!"
            >>> await inputbox.send("Hello world!")
            >>> # Select all - Ctrl + A
            >>> await inputbox.send(KeyboardKeys.CONTROL, "a")
            >>> # Copy text - Ctrl + C
            >>> await inputbox.send(KeyboardKeys.CONTROL, "c")
            >>> # Delete text - Delete
            >>> await inputbox.send(KeyboardKeys.DELETE)
            >>> # Paste text - Ctrl + V
            >>> await inputbox.send(KeyboardKeys.CONTROL, "v")
            >>> # Press Enter
            >>> await inputbox.send(KeyboardKeys.ENTER)
        """
        processed_keys = process_keys(*keys)
        await self.execute_command(
            Command.SEND_KEYS_TO_ELEMENT,
            body={"text": "".join(processed_keys)},
        )
        await self.pause(pause)

    async def upload(self, *files: PathInput, pause: int | float | None = None) -> None:
        """Upload local files to the element.

        Args:
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.
            *files: The absolute path of the files to upload.

        Example:
            >>> await element.upload("~/path/to/image.png")
        """
        # Validate
        try:
            validated_files = [file_path(file) for file in files]
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nUpload 'file' error: {}".format(self.__class__.__name__, err)
            )
        # Upload
        await self.execute_command(
            Command.SEND_KEYS_TO_ELEMENT,
            # WebDriver uploads are newline-delimited path strings.
            body={"text": "\n".join(map(str, validated_files))},
        )
        # Pause
        await self.pause(pause)

    async def submit(self, pause: int | float | None = None) -> None:
        """Submit a form (must be an element nested inside a form).

        Args:
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.
        """
        try:
            await self._session._execute_script(javascript.ELEMENT_SUBMIT_FORM, self)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nElement might not nested inside a form. Error: {}".format(
                    self.__class__.__name__, err
                )
            ) from err
        await self.pause(pause)

    async def clear(self, pause: int | float | None = None) -> None:
        """Clear the text for the text entry element.

        Args:
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.
        """
        await self.execute_command(Command.CLEAR_ELEMENT)
        await self.pause(pause)

    async def switch_frame(self) -> bool:
        """Switch focus to the frame of the element.

        Returns:
            True if the focus has been switched, False if frame was not found.

        Example:
            >>> switch = await element.switch_frame()  # True / False
        """
        try:
            await self._session.execute_command(
                Command.SWITCH_TO_FRAME, body={"id": {ELEMENT_KEY: self.id}}
            )
            return True
        except errors.FrameNotFoundError:
            return False
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False

    async def scroll_into_view(self) -> bool:
        """Scroll the viewport to the element location.

        Returns:
            True if the element is scrolled into view, False if the element is outside the viewport.

        Example:
            >>> in_viewport = await element.scroll_into_view()  # True / False
        """
        # Scroll
        try:
            await self._session._execute_script(
                javascript.ELEMENT_SCROLL_INTO_VIEW, self
            )
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to scroll into view: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

        # Check viewport intersection
        return await self.in_viewport

    async def wait_until(
        self,
        condition: Literal["gone", "unobscured", "in_viewport", "enabled", "selected"],
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the element satisfies a condition.

        Args:
            condition: The condition to satisfy. Available options:
                - `'gone'`: Wait until the element disappears from the DOM tree.
                - `'unobscured'`: Wait for center-point hit testing to reach the element.
                - `'in_viewport'`: Wait for a nonempty rectangle intersecting the viewport.
                - `'enabled'`: Wait until the element is enabled.
                - `'selected'`: Wait until the element is selected.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the element satisfies the condition, False otherwise.

        Example:
            >>> await element.wait_until("unobscured", timeout=5)  # True / False
        """

        async def is_gone() -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return not await self.exists

        async def is_unobscured() -> bool:
            """Check the matched element using a center-point hit test.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.unobscured

        async def is_in_viewport() -> bool:
            """Check whether the matched element intersects the viewport.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.in_viewport

        async def is_enabled() -> bool:
            """Check whether the matched element is enabled.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.enabled

        async def is_selected() -> bool:
            """Check whether the matched element is selected.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.selected

        # Determine condition
        if condition == "gone":
            condition_checker = is_gone
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

        return bool(await poll(lambda: condition_checker(), timeout))

    # Information -------------------------------------------------------------------------
    @property
    async def tag(self) -> str | None:
        """Return the tag name of the element.

        Returns:
            The tag name of the element.
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_TAG_NAME)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element tag name from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def wait_until_tag(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the tag of the element satisfies the given condition.

        Args:
            condition: The condition the tag needs to satisfy.
                Expected values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
            value: The value of the condition.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the tag satisfies the condition, False if timeout.

        Example:
            >>> await element.wait_until_tag("equals", "div", 5)  # True / False
        """

        async def equals() -> bool:
            """Check whether the current text exactly matches the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.tag == value

        async def contains() -> bool:
            """Check whether the current text contains the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            tag = await self.tag
            return tag is not None and value in tag

        async def startswith() -> bool:
            """Check whether the current text begins with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            tag = await self.tag
            return tag is not None and tag.startswith(value)

        async def endswith() -> bool:
            """Check whether the current text ends with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            tag = await self.tag
            return tag is not None and tag.endswith(value)

        # Validate value & condition
        value = self._validate_wait_str_value(value)
        if condition == "equals":
            condition_checker = equals
        elif condition == "contains":
            condition_checker = contains
        elif condition == "startswith":
            condition_checker = startswith
        elif condition == "endswith":
            condition_checker = endswith
        else:
            self._raise_invalid_wait_condition(condition)

        return bool(await poll(lambda: condition_checker(), timeout))

    @property
    async def text(self) -> str | None:
        """Return the text of the element.

        Returns:
            The text of the element.
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_TEXT)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element text from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    @property
    async def dom_text(self) -> str:
        """Raw textContent, including hidden descendants (unlike rendered text).

        Returns:
            The element's current textContent, including hidden descendants.
        """
        return await self._session._execute_script(
            "return arguments[0].textContent;", self
        )

    @property
    async def in_viewport(self) -> bool:
        """Whether a nonempty element rectangle intersects the viewport.

        Returns:
            True when the checked condition is satisfied; otherwise False.

        Example:
            >>> intersects_viewport = await element.in_viewport
        """
        return bool(
            await self._session._execute_script(
                "const r=arguments[0].getBoundingClientRect(); return r.width>0 && r.height>0 && r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth;",
                self,
            )
        )

    @property
    async def unobscured(self) -> bool:
        """Center-point hit test inside the visible rectangle; not a click guarantee.

        Returns:
            True when the checked condition is satisfied; otherwise False.

        Example:
            >>> reachable_at_center = await element.unobscured
        """
        return bool(
            await self._session._execute_script(
                "const e=arguments[0],r=e.getBoundingClientRect();"
                "const l=Math.max(0,r.left),t=Math.max(0,r.top),b=Math.min(innerHeight,r.bottom),q=Math.min(innerWidth,r.right);"
                "if(q<=l||b<=t)return false; const x=(l+q)/2,y=(t+b)/2;let n=document.elementFromPoint(x,y);"
                "const roots=[];for(let root=e.getRootNode();root&&root.host;root=root.host.getRootNode())roots.unshift(root);"
                "for(const root of roots){if(!n||(n!==root.host&&!root.host.contains(n)))return false;"
                "if(typeof root.elementFromPoint!=='function')return false;n=root.elementFromPoint(x,y);}"
                "while(n){if(n===e)return true;n=n.parentNode||(n.getRootNode&&n.getRootNode().host);}return false;",
                self,
            )
        )

    async def wait_until_text(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the text of the element satisfies the given condition.

        Args:
            condition: The condition the text needs to satisfy.
                Expected values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
            value: The value of the condition.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the text satisfies the condition, False if timeout.

        Example:
            >>> await element.wait_until_text("startswith", "google", 5)  # True / False
        """

        async def equals() -> bool:
            """Check whether the current text exactly matches the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.text == value

        async def contains() -> bool:
            """Check whether the current text contains the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            text = await self.text
            return text is not None and value in text

        async def startswith() -> bool:
            """Check whether the current text begins with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            text = await self.text
            return text is not None and text.startswith(value)

        async def endswith() -> bool:
            """Check whether the current text ends with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            text = await self.text
            return text is not None and text.endswith(value)

        # Validate value & condition
        value = self._validate_wait_str_value(value)
        if condition == "equals":
            condition_checker = equals
        elif condition == "contains":
            condition_checker = contains
        elif condition == "startswith":
            condition_checker = startswith
        elif condition == "endswith":
            condition_checker = endswith
        else:
            self._raise_invalid_wait_condition(condition)

        return bool(await poll(lambda: condition_checker(), timeout))

    @property
    async def rect(self) -> ElementRect | None:
        """Return the size and relative position of the element.

        Returns:
            The size and relative position of the element.

        Example:
            >>> rect = await element.rect
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_RECT)
        except errors.InvalidMethodError:
            return None
        try:
            return ElementRect(**res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element rect from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid element rect response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    @property
    async def aria_role(self) -> str | None:
        """Acess the aria role of the element.

        Returns:
            Acess the aria role of the element. None indicates that no value is available.
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_ARIA_ROLE)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element aria role from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    @property
    async def aria_label(self) -> str | None:
        """Return the aria label of the element.

        Returns:
            The aria label of the element.
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_ARIA_LABEL)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element aria label from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    @property
    async def properties(self) -> list[str]:
        """Return the property names of the element.

        Returns:
            The property names of the element.

        Example:
            >>> names = await element.properties
        """
        try:
            return await self._session._execute_script(
                javascript.GET_ELEMENT_PROPERTIES, self
            )
        except errors.InvalidMethodError:
            return []
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element properties: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_property(
        self,
        name: str,
    ) -> str | int | float | bool | list[Any] | dict[str, Any] | Element | None:
        """Get the property of the element by name.

        Args:
            name: Name of the property from the element.

        Returns:
            The property value. If the property is an element, returns <class 'Element'>.

        Example:
            >>> current_value = await element.get_property("value")
        """
        # Get property
        try:
            res = await self.execute_command(
                Command.GET_ELEMENT_PROPERTY, keys={"name": name}
            )
        except errors.InvalidMethodError:
            return None
        try:
            val = res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element property from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

        # Element property
        if isinstance(val, dict) and ELEMENT_KEY in val:
            return self._session._create_element(val)
        # Regular property
        else:
            return val

    @property
    async def properties_css(self) -> dict[str, str]:
        """Acess all the css (style) properties of the element.

        Returns:
            A mapping containing the properties css data.

        Example:
            >>> css_props = await element.css_properties
        """
        try:
            return await self._session._execute_script(
                javascript.GET_ELEMENT_CSS_PROPERTIES, self
            )
        except errors.InvalidMethodError:
            return {}
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element css properties: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_property_css(self, name: str) -> str | None:
        """Get the css (style) property of the element by name.

        Args:
            name: Name of the css property from the element.

        Returns:
            The css property value.

        Example:
            >>> css_prop = await element.get_property_css("align-content")
        """
        try:
            res = await self.execute_command(
                Command.GET_ELEMENT_VALUE_OF_CSS_PROPERTY, keys={"propertyName": name}
            )
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element css property from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    @property
    async def attributes(self) -> dict[str, str]:
        """Return the attributes of the element.

        Returns:
            The attributes of the element.

        Example:
            >>> attrs = await element.attributes
        """
        try:
            return await self._session._execute_script(
                javascript.GET_ELEMENT_ATTRIBUTES, self
            )
        except errors.InvalidMethodError:
            return {}
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element attributes: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_attribute_dom(self, name: str) -> str | None:
        """Read the current DOM attribute through the W3C attribute command.

        Attribute mutations are reflected. Use get_property() for a JavaScript
        property, such as an input's current value, instead of mixing the two.

        Args:
            name: Name of the attribute from the element.

        Returns:
            The current DOM attribute value.

        Example:
            >>> attr = await element.get_attribute_dom("placeholder")
        """
        try:
            res = await self.execute_command(
                Command.GET_ELEMENT_ATTRIBUTE, keys={"name": name}
            )
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element attribute from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def take_screenshot(self) -> bytes | None:
        """Take a screenshot of the element.

        Returns:
            Take a screenshot of the element. None indicates that no value is available.
        """
        try:
            res = await self.execute_command(Command.ELEMENT_SCREENSHOT)
        except errors.InvalidMethodError:
            return None
        try:
            return self._session._decode_base64(res["value"], "ascii")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element screenshot from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid element screenshot response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    async def save_screenshot(self, path: PathInput) -> bool:
        """Take & save the screenshot of the element into local PNG file.

        Args:
            path: The absolute path to save the screenshot.

        Returns:
            True if the screenshot has been saved, False if failed.

        Example:
            >>> await element.save_screenshot("~/path/to/screenshot.png")  # True / False
        """
        # Validate save path
        try:
            destination = save_file_path(path, ".png")
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nSave screenshot 'path' error: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

        data = None
        try:
            # Take screenshot
            data = await self.take_screenshot()
            if not data:
                return False
            # Save screenshot
            return await save_bytes(destination, data)
        finally:
            del data

    # Element -----------------------------------------------------------------------------
    async def element_exists(
        self,
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
    ) -> bool:
        """Check if an element exists (inside the element). This method ignores the implicit wait timeout, and returns element existence immediately.

        Args:
            value: The selector for the element *OR* an  instance.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                If the given 'value' is an, this argument will be ignored.

        Returns:
            True if the element exists, False otherwise.

        Example:
            >>> await element.element_exists("#input_box", by="css")  # True / False
        """
        if isinstance(value, Element):
            return await value.exists
        else:
            strat = self._session._validate_selector_strategy(by)
            return await self._element_exists_no_wait(value, strat)

    async def elements_exist(
        self,
        *values: str | Element,
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
    ) -> bool:
        """Check if multiple elements exist (inside the element). This method ignores the implicit wait timeout, and returns elements existence immediately.

        Args:
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                For values that are  instances, this argument will be ignored.
            all_: Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
                - `True`: All elements must exist to return True.
                - `False`: Any one of the elements exists returns True.
            *values: The locators for multiple elements *OR*  instances.

        Returns:
            True if the elements exist, False otherwise.

        Example:
            >>> await element.elements_exist(
            ...     "#input_box", "#input_box2", by="css", all_=True
            ... )  # True / False
        """

        async def check_existance(value: str | Element) -> bool:
            """Perform one element-existence observation for the enclosing wait.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        # Validate strategy
        strat = self._session._validate_selector_strategy(by)
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

    async def find_element(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
    ) -> Element | None:
        """Find the element (inside the element) by the given selector and strategy. The timeout for finding an element is determined by the implicit wait of the session.

        Args:
            value: The selector for the element.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.

        Returns:
            The located element, or `None` if not found.

        Example:
            >>> await element.find_element("#input_box", by="css")
        """
        # Locate element
        strat = self._session._validate_selector_strategy(by)
        try:
            res = await self.execute_command(
                Command.FIND_ELEMENT, body={"using": strat, "value": value}
            )
        except errors.ElementNotFoundError:
            return None
        except errors.InvalidArgumentError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid '{}' selector: {}".format(
                    self.__class__.__name__, by, repr(value)
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

    async def find_elements(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
    ) -> list[Element]:
        """Find elements (inside the element) by the given selector and strategy. The timeout for finding the elements is determined by the implicit wait of the session.

        Args:
            value: The selector for the elements.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.

        Returns:
            A list of located elements (empty if not found).

        Example:
            >>> await element.find_elements("#input_box", by="css")
        """
        # Locate elements
        strat = self._session._validate_selector_strategy(by)
        try:
            res = await self.execute_command(
                Command.FIND_ELEMENTS, body={"using": strat, "value": value}
            )
        except errors.ElementNotFoundError:
            return []
        except errors.InvalidArgumentError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid '{}' selector: {}".format(
                    self.__class__.__name__, by, repr(value)
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

    async def find_1st_element(
        self,
        *values: str,
        by: Literal["css", "xpath"] = "css",
    ) -> Element | None:
        """Find the first located element (inside the element) among multiple locators. The timeout for finding the first element is determined by the implicit wait of the session.

        Args:
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            *values: The locators for multiple elements.

        Returns:
            The first located element among all locators, or `None` if not found.

        Example:
            >>> await element.find_1st_element("#input_box", "#input_box2", by="css")
        """
        # Validate strategy
        strat = self._session._validate_selector_strategy(by)

        # Locate 1st element
        timeout = (await self._session._get_timeouts()).implicit
        return await first_match(
            values, lambda value: self._find_element_no_wait(value, strat), timeout
        )

    async def wait_until_element(
        self,
        condition: Literal[
            "gone", "exist", "unobscured", "in_viewport", "enabled", "selected"
        ],
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until an element (inside the element) satisfies the given condition.

        Args:
            condition: The condition to satisfy. Available options:
                - `'gone'`: Wait until an element disappears from the element.
                - `'exist'`: Wait until an element appears in the element.
                - `'unobscured'`: Wait for center-point hit testing to reach the element.
                - `'in_viewport'`: Wait for a nonempty rectangle intersecting the viewport.
                - `'enabled'`: Wait until an element is enabled.
                - `'selected'`: Wait until an element is selected.
            value: The selector for the element *OR* an  instance.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                If the given 'value' is an, this argument will be ignored.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the element satisfies the condition, False otherwise.

        Example:
            >>> await element.wait_until_element(
            ...     "unobscured", "#input_box", by="css", timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            """Check whether a matching element currently exists.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_unobscured(value: str | Element) -> bool:
            """Check the matched element using a center-point hit test.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.unobscured
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.unobscured

        async def is_in_viewport(value: str | Element) -> bool:
            """Check whether the matched element intersects the viewport.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.in_viewport
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.in_viewport

        async def is_enabled(value: str | Element) -> bool:
            """Check whether the matched element is enabled.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            """Check whether the matched element is selected.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.selected

        # Validate strategy
        strat = self._session._validate_selector_strategy(by)

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
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until multiple elements (inside the element) satisfy the given condition.

        Args:
            condition: The condition to satisfy. Available options:
                - `'gone'`: Wait until the elements disappear from the element.
                - `'exist'`: Wait until the elements appear in the element.
                - `'unobscured'`: Wait for center-point hit testing to reach the element.
                - `'in_viewport'`: Wait for nonempty rectangles intersecting the viewport.
                - `'enabled'`: Wait until the elements are enabled.
                - `'selected'`: Wait until the elements are selected.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                For values that are  instances, this argument will be ignored.
            all_: Determine how to satisfy the condition. Defaults to `True (all elements)`.
                - `True`: All elements must satisfy the condition to return True.
                - `False`: Any one of the elements satisfies the condition returns True.
            timeout: Total seconds to wait until timeout. Defaults to `5`.
            *values: The locators for multiple elements *OR*  instances.

        Returns:
            True if the elements satisfy the condition, False otherwise.

        Example:
            >>> await element.wait_until_elements(
            ...     "unobscured", "#input_box1", "#search_button",
            ...     by="css", all_=True, timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            """Check whether a matching element currently exists.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_unobscured(value: str | Element) -> bool:
            """Check the matched element using a center-point hit test.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.unobscured
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.unobscured

        async def is_in_viewport(value: str | Element) -> bool:
            """Check whether the matched element intersects the viewport.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.in_viewport
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.in_viewport

        async def is_enabled(value: str | Element) -> bool:
            """Check whether the matched element is enabled.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            """Check whether the matched element is selected.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value, strat)
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

        # Validate strategy
        strat = self._session._validate_selector_strategy(by)

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

    async def _element_exists_no_wait(self, value: str, strat: str) -> bool:
        """Check if an element exists (inside the element) without implicit wait.

        Returns `False` immediately if element not exists.

        Args:
            value: Value to inspect, normalize, or assign as described above.
            strat: Strat used by this operation.

        Returns:
            True if an element exists (inside the element) without implicit wait; otherwise False.
        """
        try:
            return await self._session._execute_script(
                javascript.ELEMENT_EXISTS_IN_NODE[strat], value, self
            )
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidElementStateError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidXPathSelectorError(
                "<{}>\nInvalid 'xpath' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err

    async def _find_element_no_wait(self, value: str, strat: str) -> Element | None:
        """Find element (inside the element) without implicit wait. Returns `None` immediately if element not exists.

        Args:
            value: Value to inspect, normalize, or assign as described above.
            strat: Strat used by this operation.

        Returns:
            The Element value produced by this operation. None indicates that no value is available.
        """
        try:
            res = await self._session._execute_script(
                javascript.FIND_ELEMENT_IN_NODE[strat], value, self
            )
        except errors.ElementNotFoundError:
            return None
        except errors.InvalidElementStateError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidXPathSelectorError(
                "<{}>\nInvalid 'xpath' selector: {}".format(
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

    # Shadow ------------------------------------------------------------------------------
    @property
    async def shadow(self) -> Shadow | None:
        """Return the shadow root of the element.

        Returns:
            The shadow root, or `None` if not found.

        Example:
            >>> shadow = await element.shadow
        """
        # Locate shadow root
        try:
            res = await self.execute_command(Command.GET_SHADOW_ROOT)
        except errors.ShadowRootNotFoundError:
            return None
        except errors.InvalidMethodError:
            return None
        # Create shadow root
        try:
            return self._create_shadow(res["value"][SHADOWROOT_KEY])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to create shadow root from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid shadow root response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    def _create_shadow(self, shadow_id: str) -> Shadow:
        """Create the shadow root.

        Args:
            shadow_id: The id of the element.
                e.g. "289DEC2B8885F15A2BDD2E92AC0404F3_element_1"

        Returns:
            The shadow root.
        """
        return Shadow(shadow_id, self)

    # Utils -------------------------------------------------------------------------------
    async def pause(self, duration: int | float | None) -> None:
        """Pause the for a given duration.

        Args:
            duration: The duration to pause in seconds.
        """
        if duration is None:
            return None  # exit
        try:
            await sleep(duration)
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'duration' to pause: {}.".format(
                    self.__class__.__name__, repr(duration)
                )
            ) from err

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

    def _validate_wait_str_value(self, value: Any) -> str:
        """Validate if wait until 'value' is a non-empty string.

        Args:
            value: If wait until 'value' is a non-empty string supplied for validation.

        Returns:
            If wait until 'value' is a non-empty string.
        """
        if not isinstance(value, str) or not value:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid wait until value: {} {}. "
                "Must an non-empty string.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
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
        return "<%s (id='%s', session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            self._session._id,
            self._service.url,
        )

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return hash((self.__class__.__name__, hash(self._session), self._id))

    def __eq__(self, __o: Any) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return hash(self) == hash(__o) if isinstance(__o, Element) else False
