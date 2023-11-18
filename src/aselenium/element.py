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
from typing import Any, Literal, TYPE_CHECKING
from aselenium import errors
from aselenium import javascript
from aselenium.command import Command
from aselenium.service import BaseService
from aselenium.connection import Connection
from aselenium.shadow import Shadow, SHADOWROOT_KEY
from aselenium.utils import Rectangle, KeyboardKeys
from aselenium.utils import is_file, is_file_dir_exists, process_keys

if TYPE_CHECKING:
    from aselenium.session import Session

__all__ = ["Element", "ElementRect", "ELEMENT_KEY"]

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
        """Access the base URL of the element `<str>`."""
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
        :param timeout: `<int/float/None>` Force timeout of the command. Defaults to `None`.
            For some webdriver versions, the browser will be frozen when
            executing certain commands. This parameter sets an extra
            timeout to throw the `SessionTimeoutError` exception if
            timeout is reached.
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
        except errors.InvalidScriptError as err:
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
        except errors.InvalidScriptError as err:
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
        except errors.InvalidScriptError as err:
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
        for file in files:
            if not is_file(file):
                raise errors.FileNotExistsError(
                    "<{}>\nInvalid file to upload: {}".format(
                        self.__class__.__name__, repr(file)
                    )
                )
        files = list(files)
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
        except errors.InvalidScriptError as err:
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

    async def scroll_into_view(self, timeout: int | float = 5) -> bool:
        """Scroll the viewport to the element location.

        :param timeout: `<int/float>` The timeout in seconds to wait for the element to scroll into view. Defaults to `5`.
        :return `<bool>`: True if the element has been scrolled into view, False if element was not found.

        ### Example:
        >>> viewable = await element.scroll_into_view()  # True / False
        """
        # Scroll
        try:
            await self._session._execute_script(
                javascript.ELEMENT_SCROLL_INTO_VIEW, self
            )
        except errors.InvalidScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to scroll into view: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

        # Check viewable
        if await self.viewable:
            return True

        # Wait for scroll
        try:
            timeout = self._session._validate_timeout(timeout)
        except errors.InvalidArgumentError as err:
            raise errors.InvalidArgumentError(f"<{self.__class__.__name__}>{err}")
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            if await self.viewable:
                return True
            await sleep(0.2)
        return False

    async def wait_for_gone(self, timeout: int | float = 5) -> bool:
        """Wait for the element to be gone from the DOM tree.

        :param timeout: `<int/float>` Total seconds to wait for the element be gone. Defaults to `5`.
        :return `<bool>`: True if the element was gone, False if timeout.
        """

        # Check existance
        if not await self.exists:
            return True

        # Wait for gone
        try:
            timeout = self._session._validate_timeout(timeout)
        except errors.InvalidArgumentError as err:
            raise errors.InvalidArgumentError(f"<{self.__class__.__name__}>{err}")
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            if not await self.exists:
                return True
            await sleep(0.2)
        return False

    # Information -------------------------------------------------------------------------
    @property
    async def tag(self) -> str:
        """Access the tag name of the element `<str>`."""
        res = await self.execute_command(Command.GET_ELEMENT_TAG_NAME)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element tag name from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def text(self) -> str:
        """Access the text of the element `<str>`."""
        res = await self.execute_command(Command.GET_ELEMENT_TEXT)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element text from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def rect(self) -> ElementRect:
        """Access the size and relative position of the element `<ElementRect>`.

        ### Example:
        >>> rect = await element.rect
            # <ElementRect (width=100, height=100, x=22, y=60)>
        """
        res = await self.execute_command(Command.GET_ELEMENT_RECT)
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
    async def aria_role(self) -> str:
        """Acess the aria role of the element `<str>`."""
        res = await self.execute_command(Command.GET_ELEMENT_ARIA_ROLE)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element aria role from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def aria_label(self) -> str:
        """Access the aria label of the element `<str>`."""
        res = await self.execute_command(Command.GET_ELEMENT_ARIA_LABEL)
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
        except errors.InvalidScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element properties: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_property(
        self,
        name: str,
    ) -> str | int | float | bool | list | dict | Element:
        """Get the property of the element by name.

        :param name: `<str>` Name of the property from the element.
        :return `<Any>`: The property value. If the property is an element, returns <class 'Element'>.
        """
        # Get property
        res = await self.execute_command(
            Command.GET_ELEMENT_PROPERTY, keys={"name": name}
        )
        try:
            val = res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element property from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

        # Element property
        if isinstance(val, dict) and ELEMENT_KEY in val:
            return self._create_element(val)
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
        except errors.InvalidScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element css properties: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_property_css(self, name: str) -> str:
        """Get the css (style) property of the element by name.

        :param name: `<str>` Name of the css property from the element.
        :return `<str>`: The css property value.

        ### Example:
        >>> css_prop = await element.get_css_property("align-content")  # "normal"
        """
        res = await self.execute_command(
            Command.GET_ELEMENT_VALUE_OF_CSS_PROPERTY, keys={"propertyName": name}
        )
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
        except errors.InvalidScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element attributes: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_attribute(self, name: str) -> str:
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
                javascript.GET_ELEMENT_ATTRIBUTES, self, name
            )
        except errors.InvalidScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element attribute: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def get_attribute_dom(self, name: str) -> str:
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
        res = await self.execute_command(
            Command.GET_ELEMENT_ATTRIBUTE, keys={"name": name}
        )
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get element attribute from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def take_screenshot(self) -> bytes:
        """Take a screenshot of the element `<bytes>`."""
        res = await self.execute_command(Command.ELEMENT_SCREENSHOT)
        try:
            return self._session._decode_base64(res["value"])
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
        if not is_file_dir_exists(path):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid `save_screenshot()` path: {}. "
                "File directory does not exist.".format(
                    self.__class__.__name__, repr(path)
                )
            )
        if not path.endswith(".png"):
            path += ".png"

        data = None
        try:
            # Take screenshot
            data = await self.take_screenshot()
            if not data:
                return False
            # Save screenshot
            try:
                with open(path, "wb") as f:
                    f.write(data)
                return True
            except OSError:
                return False
        finally:
            del data

    # Element -----------------------------------------------------------------------------
    async def exists_element(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
    ) -> bool:
        """Check if an element exists (inside the element) by the given
        locator and strategy. This method ignores the implicit wait
        timeouts, and returns element existence immediately.

        :param value: `<str>` The locator for the element.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<bool>`: True if the element exists, False otherwise.

        ### Example:
        >>> await element.exists_element("#input_box", by="css")  # True / False
        """
        return await self._session._exists_element(value, by, self)

    async def exist_elements(
        self,
        *values: str,
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
    ) -> bool:
        """Check if multiple elements exist (inside the element) by the
        given locators and strategy. This method ignores the implicit
        wait timeouts, and returns elements existence immediately.

        :param values: `<str>` The locators for multiple elements.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :param all_: `<bool>` How to determine elements existance. Defaults to `True (all elements)`.
            - `True`: All elements must exist to return True.
            - `False`: Any one of the elements exists returns True.

        :return `<bool>`: True if the elements exist, False otherwise.

        ### Example:
        >>> await element.exist_elements(
                "#input_box", "#input_box2", by="css", all_=True
            )  # True / False
        """
        return await self._session._exist_elements(values, by, all_, self)

    async def find_element(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
    ) -> Element | None:
        """Find the element (inside the element) by the given locator and strategy.

        :param value: `<str>` The locator for the element.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<Element/None>`: The located element, or `None` if not found.

        ### Example:
        >>> await element.find_element("#input_box", by="css")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_2', session='1e78...', service='http://...')>
        """
        return await self._session._find_element(self.execute_command, value, by)

    async def find_elements(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
    ) -> list[Element]:
        """Find elements (inside the element) by the given locator and strategy.

        :param value: `<str>` The locator for the elements.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<list[Element]>`: A list of located elements (empty if not found).

        ### Example:
        >>> await element.find_elements("#input_box", by="css")
            # [<Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>]
        """
        return await self._session._find_elements(self.execute_command, value, by)

    async def find_1st_element(
        self,
        *values: str,
        by: Literal["css", "xpath"] = "css",
    ) -> Element | None:
        """Find the first located element (inside the element) among multiple locators.

        :param values: `<str>` The locators for multiple elements.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<Element/None>`: The first located element among all locators, or `None` if not found.

        ### Example:
        >>> await element.find_1st_element("#input_box", "#input_box2", by="css")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
        """
        return await self._session._find_1st_element(values, by, self)

    async def wait_element_gone(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float = 5,
    ) -> bool:
        """Wait for an element (inside the element) to disappear by the
        given locator and strategy.

        :param value: `<str>` The locator for the element.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :param timeout: `<int/float>` Total seconds to wait for the element to disappear. Defaults to `5`.
        :return `<bool>`: True if the element is gone, False if timeout.

        ### Example:
        >>> await element.wait_element_gone("#input_box", by="css", timeout=5)  # True / False
        """
        return await self._session._wait_element_gone(value, by, timeout, self)

    async def wait_elements_gone(
        self,
        *values: str,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float = 5,
        all_: bool = True,
    ) -> bool:
        """Wait for multiple elements (inside the element) to disappear by
        the given locators and strategy.

        :param values: `<str>` The locators for multiple elements.
        :param by: `<str>` The locator strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :param timeout: `<int/float>` Total seconds to wait for the element(s) disappear. Defaults to `5`.
        :param all_: How to determine element(s) are gone. Defaults to `True (all elements)`.
            - `True`: All elements must be gone to return True.
            - `False`: Any one of the elements is gone returns True.

        :return `<bool>`: True if the elements are gone, False if timeout.

        ### Example:
        >>> await element.wait_elements_gone(
                "#input_box", "#input_box2", by="css", timeout=5, all_=True
            )  # True / False
        """
        return await self._session._wait_elements_gone(values, by, timeout, all_, self)

    def _create_element(self, element: dict[str, Any]) -> Element:
        """(Internal) Create the element `<Element>`."""
        try:
            return Element(element[ELEMENT_KEY], self)
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse element from response: {}".format(
                    self.__class__.__name__, element
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid element response: {}".format(
                    self.__class__.__name__, element[ELEMENT_KEY]
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
