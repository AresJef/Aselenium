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

"""Remote DOM-element handles and element-scoped WebDriver operations."""

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
from aselenium._response import response_value, string_list, string_mapping, typed_value
from aselenium._wait import first_match, poll, validate_delay
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
        self._service: BaseService = session.service
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
        """Return the remote WebDriver element ID.

        Returns:
            The element's W3C remote ID.
        """
        return self._id

    @property
    def base_url(self) -> str:
        """Return the command URL for this remote element.

        Returns:
            The percent-encoded element command URL.
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
            value = await self._session._execute_script(
                javascript.ELEMENT_IS_VALID, self
            )
            return typed_value(value, bool, "Element existence state")
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check element existence: {}".format(
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
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before the click is sent.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid, including a boolean.
        """
        validate_delay(pause)
        await self.execute_command(Command.CLICK_ELEMENT)
        await self.pause(pause)

    async def send(
        self,
        *keys: str,
        pause: int | float | None = None,
    ) -> None:
        """Type text or special keyboard keys into the element.

        Use ``upload()`` to send local files instead of keyboard input.

        Args:
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before keyboard input is sent.
            *keys: Strings to type or ``KeyboardKeys`` constants to press.

        Raises:
            errors.InvalidArgumentError: ``pause`` or a keyboard input is invalid.

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
        validate_delay(pause)
        processed_keys = process_keys(*keys)
        await self.execute_command(
            Command.SEND_KEYS_TO_ELEMENT,
            body={"text": "".join(processed_keys)},
        )
        await self.pause(pause)

    async def upload(self, *files: PathInput, pause: int | float | None = None) -> None:
        """Upload local files to the element.

        Args:
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before file paths are sent.
            *files: Existing files supplied as strings, `pathlib.Path` objects,
                or compatible `os.PathLike[str]` values. Relative paths are
                resolved from the current working directory and `~` is expanded.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid or a file path does
                not identify an existing regular file.

        Example:
            >>> await element.upload("~/path/to/image.png")
        """
        # Validate
        validate_delay(pause)
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
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before form submission.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid, including a boolean.
            errors.InvalidResponseError: The form-submission script fails.
        """
        validate_delay(pause)
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
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before clearing the element.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid, including a boolean.
        """
        validate_delay(pause)
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
        return response_value(res, str, "Element tag name")

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
        return response_value(res, str, "Element text")

    @property
    async def dom_text(self) -> str:
        """Raw textContent, including hidden descendants (unlike rendered text).

        Returns:
            The element's current textContent, including hidden descendants.
        """
        value = await self._session._execute_script(
            "return arguments[0].textContent;", self
        )
        return typed_value(value, str, "Element DOM text")

    @property
    async def in_viewport(self) -> bool:
        """Whether a nonempty element rectangle intersects the viewport.

        Returns:
            True when the checked condition is satisfied; otherwise False.

        Example:
            >>> intersects_viewport = await element.in_viewport
        """
        value = await self._session._execute_script(
            "const r=arguments[0].getBoundingClientRect(); return r.width>0 && r.height>0 && r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth;",
            self,
        )
        return typed_value(value, bool, "Element viewport-intersection state")

    @property
    async def unobscured(self) -> bool:
        """Center-point hit test inside the visible rectangle; not a click guarantee.

        Returns:
            True when the checked condition is satisfied; otherwise False.

        Example:
            >>> reachable_at_center = await element.unobscured
        """
        value = await self._session._execute_script(
            "const e=arguments[0],r=e.getBoundingClientRect();"
            "const l=Math.max(0,r.left),t=Math.max(0,r.top),b=Math.min(innerHeight,r.bottom),q=Math.min(innerWidth,r.right);"
            "if(q<=l||b<=t)return false; const x=(l+q)/2,y=(t+b)/2;let n=document.elementFromPoint(x,y);"
            "const roots=[];for(let root=e.getRootNode();root&&root.host;root=root.host.getRootNode())roots.unshift(root);"
            "for(const root of roots){if(!n||(n!==root.host&&!root.host.contains(n)))return false;"
            "if(typeof root.elementFromPoint!=='function')return false;n=root.elementFromPoint(x,y);}"
            "while(n){if(n===e)return true;n=n.parentNode||(n.getRootNode&&n.getRootNode().host);}return false;",
            self,
        )
        return typed_value(value, bool, "Element center-point hit-test state")

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
        """Return the element's computed accessibility role when supported.

        Returns:
            The computed role, including an empty string when reported by the
            driver, or ``None`` when the command is unsupported.

        Raises:
            errors.InvalidResponseError: The driver returns a non-string value.
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_ARIA_ROLE)
        except errors.InvalidMethodError:
            return None
        return response_value(res, str, "Element ARIA role")

    @property
    async def aria_label(self) -> str | None:
        """Return the element's computed accessibility label when supported.

        Returns:
            The computed label, including an empty string when reported by the
            driver, or ``None`` when the command is unsupported.

        Raises:
            errors.InvalidResponseError: The driver returns a non-string value.
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_ARIA_LABEL)
        except errors.InvalidMethodError:
            return None
        return response_value(res, str, "Element ARIA label")

    @property
    async def properties(self) -> list[str]:
        """Return the property names of the element.

        Returns:
            The property names of the element.

        Example:
            >>> names = await element.properties
        """
        try:
            value = await self._session._execute_script(
                javascript.GET_ELEMENT_PROPERTIES, self
            )
            return string_list(value, "Element property names")
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
        """Return all computed CSS property names and values for the element.

        Returns:
            A mapping of computed CSS property names to serialized values.

        Raises:
            errors.InvalidResponseError: The script does not return a
                string-to-string mapping.

        Example:
            >>> css_props = await element.properties_css
        """
        try:
            value = await self._session._execute_script(
                javascript.GET_ELEMENT_CSS_PROPERTIES, self
            )
            return string_mapping(value, "Element CSS properties")
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
        return response_value(res, str, "Element CSS property")

    @property
    async def attributes(self) -> dict[str, str]:
        """Return the attributes of the element.

        Returns:
            The attributes of the element.

        Example:
            >>> attrs = await element.attributes
        """
        try:
            value = await self._session._execute_script(
                javascript.GET_ELEMENT_ATTRIBUTES, self
            )
            return string_mapping(value, "Element attributes")
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
        if "value" not in res:
            raise errors.InvalidResponseError(
                "Element DOM attribute response must contain a value"
            )
        value = res["value"]
        if value is not None and not isinstance(value, str):
            raise errors.InvalidResponseError(
                "Element DOM attribute response value must be str or None, "
                f"not {type(value).__name__}"
            )
        return value

    async def take_screenshot(self) -> bytes | None:
        """Capture the element as PNG data when the driver supports it.

        Returns:
            Decoded PNG bytes, or `None` when the command is unsupported.
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
        """Capture the element and save it as PNG.

        Args:
            path: Destination supplied as a string, `pathlib.Path`, or compatible
                `os.PathLike[str]`. Relative paths are resolved from the current
                working directory, `~` is expanded, and `.png` is appended unless
                the filename already ends with that exact suffix.

        Returns:
            `True` if nonempty screenshot data was written; otherwise `False`.

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
            value: Descendant element or a selector that identifies one.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                This argument is ignored when `value` is an `Element`.

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
                This argument is ignored for values that are `Element` objects.
            all_: Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
                - `True`: All elements must exist to return True.
                - `False`: Any one of the elements exists returns True.
            *values: Descendant elements or selectors that identify them.

        Returns:
            True if the elements exist, False otherwise.

        Example:
            >>> await element.elements_exist(
            ...     "#input_box", "#input_box2", by="css", all_=True
            ... )  # True / False
        """

        async def check_existence(value: str | Element) -> bool:
            """Perform one element-existence observation for the enclosing wait.

            Args:
                value: Descendant element or selector to check once.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        # Validate strategy
        strat = self._session._validate_selector_strategy(by)
        # Check existence
        if all_:
            for value in values:
                if not await check_existence(value):
                    return False
            return True
        else:
            for value in values:
                if await check_existence(value):
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
            value: Descendant element or a selector that identifies one.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                This argument is ignored when `value` is an `Element`.
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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                This argument is ignored for values that are `Element` objects.
            all_: Determine how to satisfy the condition. Defaults to `True (all elements)`.
                - `True`: All elements must satisfy the condition to return True.
                - `False`: Any one of the elements satisfies the condition returns True.
            timeout: Total seconds to wait until timeout. Defaults to `5`.
            *values: Descendant elements or selectors that identify them.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                value: Descendant element or selector evaluated during this poll.

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
                condition_checker: Async predicate applied to each candidate.

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

        Returns `False` immediately when no matching descendant exists.

        Args:
            value: Descendant-element selector.
            strat: Validated WebDriver selector strategy.

        Returns:
            True if an element exists (inside the element) without implicit wait; otherwise False.
        """
        try:
            result = await self._session._execute_script(
                javascript.ELEMENT_EXISTS_IN_NODE[strat], value, self
            )
            return typed_value(result, bool, "Descendant-element existence state")
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
        """Find one descendant without applying implicit wait.

        Args:
            value: Descendant-element selector.
            strat: Validated WebDriver selector strategy.

        Returns:
            The matching descendant element, or `None` when no match exists.
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
        """Create a shadow-root handle bound to this host element.

        Args:
            shadow_id: Nonempty W3C shadow-root ID.

        Returns:
            The shadow root.
        """
        return Shadow(shadow_id, self)

    # Utils -------------------------------------------------------------------------------
    async def pause(self, duration: int | float | None) -> None:
        """Pause element command sequencing for a duration in seconds.

        Args:
            duration: Finite, nonnegative delay in seconds, or ``None`` for no
                delay.

        Raises:
            errors.InvalidArgumentError: ``duration`` is not a finite,
                nonnegative number or ``None``.
        """
        validate_delay(duration)
        if duration is not None:
            await sleep(duration)

    def _validate_wait_str_value(self, value: Any) -> str:
        """Validate a nonempty string used by a wait condition.

        Args:
            value: Candidate string value.

        Returns:
            The validated string.

        Raises:
            errors.InvalidArgumentError: If `value` is not a nonempty string.
        """
        if not isinstance(value, str) or not value:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid wait until value: {} {}. "
                "Must be a nonempty string.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        return value

    def _raise_invalid_wait_condition(self, condition: Any) -> NoReturn:
        """Reject an unsupported descendant-element wait condition.

        Args:
            condition: Unsupported condition value.

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
        """Describe the handle without allocating a service endpoint.

        Returns:
            Element/session IDs and the already allocated service URL, if any.
        """
        return "<%s (id='%s', session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            self._session._id,
            getattr(self._service, "_url", None),
        )

    def __hash__(self) -> int:
        """Hash the remote element identity within its owning session.

        Returns:
            A hash derived from the owning session and remote element ID.
        """
        return hash((self._session, self._id))

    def __eq__(self, __o: Any) -> bool:
        """Return whether another handle identifies the same remote element.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` when both handles have the same remote ID and owning session.
        """
        return (
            isinstance(__o, Element)
            and self._session is __o._session
            and self._id == __o._id
        )
