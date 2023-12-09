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
from aselenium.shadow import Shadow, SHADOWROOT_KEY
from aselenium.utils import Rectangle, KeyboardKeys
from aselenium.utils import process_keys, validate_file, validate_save_file_path

if TYPE_CHECKING:
    from aselenium.session import Session

__all__ = ["Element", "ElementRect"]

# Constants ---------------------------------------------------------------------------------------
ELEMENT_KEY: str = "element-6066-11e4-a52e-4f735466cecf"


# Element Objects ---------------------------------------------------------------------------------
class ElementRect(Rectangle):
    """Represents the size and relative position of an element."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """The size and relative position of the element.

        :param width: `<int>` The width of the element.
        :param height: `<int>` The height of the element.
        :param x: `<int>` The x-coordinate of the element.
        :param y: `<int>` The y-coordinate of the element.
        """
        super().__init__(width, height, x, y)

    # Special methods ---------------------------------------------------------------------
    def copy(self) -> ElementRect:
        """Copy the element rectangle `<ElementRect>`."""
        return super().copy()


# Element -----------------------------------------------------------------------------------------
class Element:
    """Represents a DOM tree element."""

    def __init__(self, element_id: str, session: Session) -> None:
        """The DOM tree element.

        :param element_id: `<str>` The element ID.
        :param session: `<Session>` The session of the element.
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
        self._conn: Connection = session._conn
        # Element
        self._id: str = element_id
        self._base_url: str = session._base_url + "/element/" + self._id
        self._body: dict[str, str] = session._body | {"id": self._id}

    # Basic -------------------------------------------------------------------------------
    @property
    def session_id(self) -> str:
        """Access the session ID of the element `<str>`.
        e.g. '62eb095e1d01b00a4dc3a497c7330aa5'
        """
        return self._session._id

    @property
    def id(self) -> str:
        """Access the ID of the element `<str>`.
        e.g. '61A5CAC057B025F22A116E47F7950D24_element_1'
        """
        return self._id

    @property
    def base_url(self) -> str:
        """Access the base service URL of the element `<str>`."""
        return self._base_url

    # Execute -----------------------------------------------------------------------------
    async def execute_command(
        self,
        command: str,
        body: dict | None = None,
        keys: dict | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Executes a command from the element.

        :param command: `<str>` The command to execute.
        :param body: `<dict/None>` The body of the command. Defaults to `None`.
        :param keys: `<dict/None>` The keys to substitute in the command. Defaults to `None`.
        :param timeout: `<int/float/None>` Session timeout for command execution. Defaults to `None`.
            This arguments overwrites the default `options.session_timeout`,
            which is designed to cope with a frozen session due to unknown
            errors. For more information about session timeout, please refer
            to the documentation of `options.session_timeout` attribute.

        :return: `<dict>` The response from the command.
        """
        return await self._conn.execute(
            self._base_url,
            command,
            body=body | self._body if body else self._body,
            keys=keys,
            timeout=timeout,
        )

    # Control -----------------------------------------------------------------------------
    @property
    async def exists(self) -> bool:
        """Access whether the element still exists in the
        DOM tree when this attribute is called `<bool>`.
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
    async def visible(self) -> bool:
        """Access whether the element is visible `<bool>`.

        Visible means that the element is not only displayed but also
        not blocked by any other elements (e.g. an overlay or modal).
        """
        try:
            return await self._session._execute_script(
                javascript.ELEMENT_IS_VISIBLE, self
            )
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check element visibility: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    @property
    async def viewable(self) -> bool:
        """Access whether the element is in the viewport `<bool>`.

        Viewable means that the element is displayed regardless whether
        it is blocked by other elements (e.g. an overlay or modal).
        """
        try:
            return await self._session._execute_script(
                javascript.ELEMENT_IS_VIEWABLE, self
            )
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check element viewability: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    @property
    async def enabled(self) -> bool:
        """Access whether the element is enabled `<bool>`."""
        try:
            res = await self.execute_command(Command.IS_ELEMENT_ENABLED)
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check if element is enabled from "
                "response: {}".format(self.__class__.__name__, repr(res))
            ) from err

    @property
    async def selected(self) -> bool:
        """Access whether the element is selected `<bool>`.

        Primarily used for checking if a checkbox or radio button is selected.
        """
        try:
            res = await self.execute_command(Command.IS_ELEMENT_SELECTED)
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidMethodError:
            return False
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to check if element is selected from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def click(self, pause: int | float | None = None) -> None:
        """Click the element.

        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.
        """
        await self.execute_command(Command.CLICK_ELEMENT)
        await self.pause(pause)

    async def send(
        self,
        *keys: str | KeyboardKeys,
        pause: int | float | None = None,
    ) -> None:
        """Simulate typing or keyboard keys pressing into the element.
        (To send local files, use the `upload()` method.)

        :param keys: `<str/KeyboardKeys>` strings to be typed or keyboard keys to be pressed.
        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.

        ### Example:
        >>> from aslenium import KeyboardKeys
            inputbox = await session.find_element("#input_box")
            # Sent text - "Hello world!"
            await inputbox.send("Hello world!")
            # Select all - Ctrl + A
            await inputbox.send(KeyboardKeys.CONTROL, "a")
            # Copy text - Ctrl + C
            await inputbox.send(KeyboardKeys.CONTROL, "c")
            # Delete text - Delete
            await inputbox.send(KeyboardKeys.DELETE)
            # Paste text - Ctrl + V
            await inputbox.send(KeyboardKeys.CONTROL, "v")
            # Press Enter
            await inputbox.send(KeyboardKeys.ENTER)
        """
        keys = process_keys(*keys)
        await self.execute_command(
            Command.SEND_KEYS_TO_ELEMENT,
            body={"text": "".join(keys), "value": keys},
        )
        await self.pause(pause)

    async def upload(self, *files: str, pause: int | float | None = None) -> None:
        """Upload local files to the element.

        :param files: `<str>` The absolute path of the files to upload.
        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.

        ### Example:
        >>> await element.upload("~/path/to/image.png")
        """
        # Validate
        try:
            files = [validate_file(file) for file in files]
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nUpload 'file' error: {}".format(self.__class__.__name__, err)
            )
        # Upload
        await self.execute_command(
            Command.SEND_KEYS_TO_ELEMENT,
            body={"text": "\n".join(files), "value": files},
        )
        # Pause
        await self.pause(pause)

    async def submit(self, pause: int | float | None = None) -> None:
        """Submit a form (must be an element nested inside a form).

        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.
        """
        try:
            self._session._execute_script(javascript.ELEMENT_SUBMIT_FORM, self)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nElement might not nested inside a form. "
                "Error: {}".format(self.__class__.__name__, err)
            ) from err
        await self.pause(pause)

    async def clear(self, pause: int | float | None = None) -> None:
        """Clear the text for the text entry element.

        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.
        """
        await self.execute_command(Command.CLEAR_ELEMENT)
        await self.pause(pause)

    async def switch_frame(self) -> bool:
        """Switch focus to the frame of the element.

        :return `<bool>`: True if the focus has been switched, False if frame was not found.

        ### Example:
        >>> switch = await element.switch_frame()  # True / Flase
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

    async def scroll_into_view(self, timeout: int | float | None = 5) -> bool:
        """Scroll the viewport to the element location.

        :param timeout: `<int/float/None>` Total seconds to wait for the element to scroll into view. Defaults to `5`.
        :return `<bool>`: True if the element has been scrolled into view, False if element was not found.

        ### Example:
        >>> viewable = await element.scroll_into_view()  # True / False
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

        # Check viewable
        if await self.viewable:
            return True
        elif timeout is None:
            return False

        # Wait for scroll
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await self.viewable:
                return True
        return False

    async def wait_until(
        self,
        condition: Literal["gone", "visible", "viewable", "enabled", "selected"],
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the element satisfies a condition.

        :param condition: `<str>` The condition to satisfy. Available options:
            - `'gone'`: Wait until the element disappears from the DOM tree.
            - `'visible'`: Wait until the element not only is displayed but also not
                blocked by any other elements (e.g. an overlay or modal).
            - `'viewable'`: Wait until the element is displayed regardless whether it
                is blocked by other elements (e.g. an overlay or modal).
            - `'enabled'`: Wait until the element is enabled.
            - `'selected'`: Wait until the element is selected.

        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return `<bool>`: True if the element satisfies the condition, False otherwise.

        ### Example:
        >>> await element.wait_until("visible", timeout=5)  # True / False
        """

        async def is_gone() -> bool:
            return not await self.exists

        async def is_visible() -> bool:
            return await self.visible

        async def is_viewable() -> bool:
            return await self.viewable

        async def is_enabled() -> bool:
            return await self.enabled

        async def is_selected() -> bool:
            return await self.selected

        # Determine condition
        if condition == "gone":
            condition_checker = is_gone
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
        if await condition_checker():
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await condition_checker():
                return True
        return False

    # Information -------------------------------------------------------------------------
    @property
    async def tag(self) -> str | None:
        """Access the tag name of the element `<str>`."""
        try:
            res = await self.execute_command(Command.GET_ELEMENT_TAG_NAME)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element tag name from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def wait_until_tag(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the tag of the element satisfies the given condition.

        :param condition: `<str>` The condition the tag needs to satisfy.
            Excepted values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
        :param value: `<str>` The value of the condition.
        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return: `<bool>` True if the tag satisfies the condition, False if timeout.

        ### Example:
        >>> await element.wait_until_tag("equals", "div", 5)  # True / False
        """

        async def equals() -> bool:
            return await self.tag == value

        async def contains() -> bool:
            tag = await self.tag
            return tag is not None and value in tag

        async def startswith() -> bool:
            tag = await self.tag
            return tag is not None and tag.startswith(value)

        async def endswith() -> bool:
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

        # Check condition
        if await condition_checker():
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await condition_checker():
                return True
        return False

    @property
    async def text(self) -> str | None:
        """Access the text of the element `<str>`."""
        try:
            res = await self.execute_command(Command.GET_ELEMENT_TEXT)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element text from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def wait_until_text(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the text of the element satisfies the given condition.

        :param condition: `<str>` The condition the text needs to satisfy.
            Excepted values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
        :param value: `<str>` The value of the condition.
        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return: `<bool>` True if the text satisfies the condition, False if timeout.

        ### Example:
        >>> await element.wait_until_text("startswith", "google", 5)  # True / False
        """

        async def equals() -> bool:
            return await self.text == value

        async def contains() -> bool:
            text = await self.text
            return text is not None and value in text

        async def startswith() -> bool:
            text = await self.text
            return text is not None and text.startswith(value)

        async def endswith() -> bool:
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

        # Check condition
        if await condition_checker():
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await condition_checker():
                return True
        return False

    @property
    async def rect(self) -> ElementRect | None:
        """Access the size and relative position of the element `<ElementRect>`.

        ### Example:
        >>> rect = await element.rect
            # <ElementRect (width=100, height=100, x=22, y=60)>
        """
        try:
            res = await self.execute_command(Command.GET_ELEMENT_RECT)
        except errors.InvalidMethodError:
            return None
        try:
            return ElementRect(**res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element rect from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid element rect response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    @property
    async def aria_role(self) -> str | None:
        """Acess the aria role of the element `<str>`."""
        try:
            res = await self.execute_command(Command.GET_ELEMENT_ARIA_ROLE)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element aria role from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def aria_label(self) -> str | None:
        """Access the aria label of the element `<str>`."""
        try:
            res = await self.execute_command(Command.GET_ELEMENT_ARIA_LABEL)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element aria label from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def properties(self) -> list[str]:
        """Access the property names of the element `<list[str]>`.

        ### Example:
        >>> names = await element.properties
            # ['align', 'title', 'lang', 'translate', 'dir', 'hidden', ...]
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
    ) -> str | int | float | bool | list | dict | Element | None:
        """Get the property of the element by name.

        :param name: `<str>` Name of the property from the element.
        :return `<Any>`: The property value. If the property is an element, returns <class 'Element'>.
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
                "<{}>\nFailed to get element property from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

        # Element property
        if isinstance(val, dict) and ELEMENT_KEY in val:
            return self._session._create_element(val)
        # Regular property
        else:
            return val

    @property
    async def properties_css(self) -> dict[str, str]:
        """Acess all the css (style) properties of the element `<dict[str, str]>`.

        ### Example:
        >>> css_props = await element.css_properties
            # {'align-content': 'normal', 'align-items': 'normal', 'align-self': 'auto', ...}
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

        :param name: `<str>` Name of the css property from the element.
        :return `<str>`: The css property value.

        ### Example:
        >>> css_prop = await element.get_css_property("align-content")  # "normal"
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
                "<{}>\nFailed to get element css property from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def attributes(self) -> dict[str, str]:
        """Access the attributes of the element `<dict[str, str]>`.

        ### Example:
        >>> attrs = await element.attributes
            # {'aria-label': 'Close', 'class': 'title-text c-font-medium c-color-t'}
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

    async def get_attribute(self, name: str) -> str | None:
        """Get the latest attribute value.

        If the attribute's value has been changed after the page loaded,
        this method will always return the latest updated value.

        :param name: `<str>` Name of the attribute from the element.
        :return `<str>`: The latest attribute value.

        ### Example:
        >>> attr = await element.get_attribute("#input")
            # "please enter password"
        """
        try:
            return await self._session._execute_script(
                javascript.GET_ELEMENT_ATTRIBUTE, self, name
            )
        except errors.InvalidMethodError:
            return None
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element attribute: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_attribute_dom(self, name: str) -> str | None:
        """Get the attribute's initial value from the DOM tree.

        This method ignores any changes made after the page loaded.
        To get the updated value (if changed) of the attribute, use
        the `get_attribute()` method instead.

        :param name: `<str>` Name of the attribute from the element.
        :return `<str>`: The initial attribute value.

        ### Example:
        >>> attr = await element.get_attribute_dom("#input")
            # "please enter password"
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
                "<{}>\nFailed to get element attribute from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def take_screenshot(self) -> bytes | None:
        """Take a screenshot of the element `<bytes>`."""
        try:
            res = await self.execute_command(Command.ELEMENT_SCREENSHOT)
        except errors.InvalidMethodError:
            return None
        try:
            return self._session._decode_base64(res["value"], "ascii")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element screenshot from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid element screenshot response: "
                "{}".format(self.__class__.__name__, res["value"])
            ) from err

    async def save_screenshot(self, path: str) -> bool:
        """Take & save the screenshot of the element into local PNG file.

        :param path: `<str>` The absolute path to save the screenshot.
        :return `<bool>`: True if the screenshot has been saved, False if failed.

        ### Example:
        >>> await element.save_screenshot("~/path/to/screenshot.png")  # True / False
        """
        # Validate save path
        try:
            path = validate_save_file_path(path, ".png")
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
            try:
                with open(path, "wb") as file:
                    file.write(data)
                return True
            except OSError:
                return False
        finally:
            del data

    # Element -----------------------------------------------------------------------------
    async def element_exists(
        self,
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
    ) -> bool:
        """Check if an element exists (inside the element). This method ignores
        the implicit wait timeout, and returns element existence immediately.

        :param value: `<str/Element>` The selector for the element *OR* an `<Element>` instance.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            If the given 'value' is an `<Element>`, this argument will be ignored.
        :return `<bool>`: True if the element exists, False otherwise.

        ### Example:
        >>> await element.element_exists("#input_box", by="css")  # True / False
        """
        if self._session._is_element(value):
            return await value.exists
        else:
            strat = self._session._validate_selector_strategy(by)
            return await self._element_exists_no_wait(value, strat)

    async def elements_exist(
        self,
        *values: str,
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
    ) -> bool:
        """Check if multiple elements exist (inside the element). This method
        ignores the implicit wait timeout, and returns elements existence
        immediately.

        :param values: `<str/Element>` The locators for multiple elements *OR* `<Element>` instances.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            For values that are `<Element>` instances, this argument will be ignored.
        :param all_: `<bool>` Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
            - `True`: All elements must exist to return True.
            - `False`: Any one of the elements exists returns True.

        :return `<bool>`: True if the elements exist, False otherwise.

        ### Example:
        >>> await element.elements_exist(
                "#input_box", "#input_box2", by="css", all_=True
            )  # True / False
        """

        async def check_existance(value: str | Element) -> bool:
            if self._session._is_element(value):
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
        """Find the element (inside the element) by the given selector
        and strategy. The timeout for finding an element is determined
        by the implicit wait of the session.

        :param value: `<str>` The selector for the element.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<Element/None>`: The located element, or `None` if not found.

        ### Example:
        >>> await element.find_element("#input_box", by="css")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_2', session='1e78...', service='http://...')>
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
        """Find elements (inside the element) by the given selector and
        strategy. The timeout for finding the elements is determined by
        the implicit wait of the session.

        :param value: `<str>` The selector for the elements.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<list[Element]>`: A list of located elements (empty if not found).

        ### Example:
        >>> await element.find_elements("#input_box", by="css")
            # [<Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>]
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
            return [self._session._create_element(value) for value in res["value"]]
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
        """Find the first located element (inside the element) among
        multiple locators. The timeout for finding the first element
        is determined by the implicit wait of the session.

        :param values: `<str>` The locators for multiple elements.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<Element/None>`: The first located element among all locators, or `None` if not found.

        ### Example:
        >>> await element.find_1st_element("#input_box", "#input_box2", by="css")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
        """
        # Validate strategy
        strat = self._session._validate_selector_strategy(by)

        # Locate 1st element
        timeout = (await self._session._get_timeouts()).implicit
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            for value in values:
                element = await self._find_element_no_wait(value, strat)
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
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until an element (inside the element) satisfies the given condition.

        :param condition: `<str>` The condition to satisfy. Available options:
            - `'gone'`: Wait until an element disappears from the element.
            - `'exist'`: Wait until an element appears in the element.
            - `'visible'`: Wait until an element not only is displayed but also not
                blocked by any other elements (e.g. an overlay or modal).
            - `'viewable'`: Wait until an element is displayed regardless whether it
                is blocked by other elements (e.g. an overlay or modal).
            - `'enabled'`: Wait until an element is enabled.
            - `'selected'`: Wait until an element is selected.

        :param value: `<str/Element>` The selector for the element *OR* an `<Element>` instance.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            If the given 'value' is an `<Element>`, this argument will be ignored.
        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return `<bool>`: True if the element satisfies the condition, False otherwise.

        ### Example:
        >>> await element.wait_until_element(
                "visible", "#input_box", by="css", timeout=5
            )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            if self._session._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_visible(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.visible
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.visible

        async def is_viewable(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.viewable
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.viewable

        async def is_enabled(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            if self._session._is_element(value):
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
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until multiple elements (inside the element) satisfy the given condition.

        :param condition: `<str>` The condition to satisfy. Available options:
            - `'gone'`: Wait until the elements disappear from the element.
            - `'exist'`: Wait until the elements appear in the element.
            - `'visible'`: Wait until the elements not only are displayed but also not
                blocked by any other elements (e.g. an overlay or modal).
            - `'viewable'`: Wait until the elements are displayed regardless whether
                blocked by other elements (e.g. an overlay or modal).
            - `'enabled'`: Wait until the elements are enabled.
            - `'selected'`: Wait until the elements are selected.

        :param values: `<str/Element>` The locators for multiple elements *OR* `<Element>` instances.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            For values that are `<Element>` instances, this argument will be ignored.
        :param all_: `<bool>` Determine how to satisfy the condition. Defaults to `True (all elements)`.
            - `True`: All elements must satisfy the condition to return True.
            - `False`: Any one of the elements satisfies the condition returns True.

        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return `<bool>`: True if the elements satisfy the condition, False otherwise.

        ### Example:
        >>> await element.wait_until_elements(
                "visible", "#input_box1", "#search_button",
                by="css", all_=True, timeout=5
            )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            if self._session._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_visible(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.visible
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.visible

        async def is_viewable(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.viewable
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.viewable

        async def is_enabled(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            if self._session._is_element(value):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value, strat)
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

        # Validate strategy
        strat = self._session._validate_selector_strategy(by)

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

    async def _element_exists_no_wait(self, value: str, strat: str) -> bool:
        """(Internal) Check if an element exists (inside the element)
        without implicit wait `<bool>`. Returns `False` immediately if
        element not exists.
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
        """(Internal) Find element (inside the element) without implicit
        wait `<Element>`. Returns `None` immediately if element not exists.
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
        """Access the shadow root of the element.

        :return `<Shadow/None>`: The shadow root, or `None` if not found.

        ### Example:
        >>> shadow = await element.shadow
            # <Shadow (id='72216A833579C94EF54047C00F423735_element_4', element='7221...', session='f8c2...', service='http://...)>
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
                "<{}>\nFailed to create shadow root from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid shadow root response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    def _create_shadow(self, shadow_id: str) -> Shadow:
        """(Internal) Create the shadow root.

        :param shadow_id: `<str>` The id of the element.
            e.g. "289DEC2B8885F15A2BDD2E92AC0404F3_element_1"
        :return `<Shadow>`: The shadow root.
        """
        return Shadow(shadow_id, self)

    # Utils -------------------------------------------------------------------------------
    async def pause(self, duration: int | float | None) -> None:
        """Pause the for a given duration.

        :param duration: `<int/float/None>` The duration to pause in seconds.
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

    def _validate_wait_str_value(self, value: Any) -> str:
        """(Internal) Validate if wait until 'value' is a non-empty string `<str>`."""
        if not isinstance(value, str) or not value:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid wait until value: {} {}. "
                "Must an non-empty string.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
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
        return "<%s (id='%s', session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            self._session._id,
            self._service.url,
        )

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, hash(self._session), self._id))

    def __eq__(self, __o: Any) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, Element) else False

    def __del__(self):
        # Session
        self._session = None
        self._service = None
        # Connection
        self._conn = None
        # Element
        self._id = None
        self._base_url = None
        self._body = None
