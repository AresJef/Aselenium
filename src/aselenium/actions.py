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
from typing import Any, Literal, TypedDict, TYPE_CHECKING
from aselenium import errors
from aselenium.command import Command
from aselenium.settings import Constraint
from aselenium.element import Element, ELEMENT_KEY
from aselenium.utils import KeyboardKeys, MouseButtons
from aselenium.utils import process_keys, prettify_dict

if TYPE_CHECKING:
    from aselenium.session import Session

__all__ = ["Actions"]


# Types -------------------------------------------------------------------------------------------
class PointerActions(TypedDict):
    """The pointer (mouse) actions to perform `<dict>`.

    Expected format:
    >>> {
            "type": "pointer",
            "parameters": {"pointerType": "mouse"},
            "id": "mouse",
            "actions": [
                {'type': 'pointerDown', 'duration': 0, 'button': 0},
                ...
            ],
        }
    """

    type: str
    parameters: dict[str, str]
    id: str
    actions: list[dict[str, Any]]


class KeyActions(TypedDict):
    """The keyboard actions to perform `<dict>`.

    Expected format:
    >>> {
            "type": "key",
            "id": "key",
            "actions": [
                {'type': 'keyDown', 'value': 'a'},
                ...
            ],
        }
    """

    type: str
    id: str
    actions: list[dict[str, Any]]


class WheelActions(TypedDict):
    """The wheel actions to perform `<dict>`.

    Expected format:
    >>> {
            "type": "wheel",
            "id": "wheel",
            "actions": [
                {'type': 'scroll', 'x': 0, 'y': 0, 'duration': 0, 'origin': 'viewport'},
                ...
            ],
        }
    """

    type: str
    id: str
    actions: list[dict[str, Any]]


class ActionsChain(TypedDict):
    """The complete actions chain to perform `<dict>`.

    Expected format:
    >>> {
            "pointer": {...},
            "key": {...},
            "wheel": {...},
        }
    """

    pointer: PointerActions
    key: KeyActions
    wheel: WheelActions


# Actions -----------------------------------------------------------------------------------------
class Actions:
    """Represent an actions chain that peforms (automate) low
    level interactions such as mouse movements, key press, and
    wheel scroll.
    """

    def __init__(
        self,
        session: Session,
        pointer: Literal["mouse", "pen", "touch"] = "mouse",
        duration: int | float = 0.2,
    ) -> None:
        """The actions chain that peforms (automate) low level
        interactions such as mouse movements, key presses, and
        wheel scrolls.

        :param session: `<Session>` The session to perform the action chain.
        :param pointer: `<str>` The pointer type to use. Defaults to `'mouse'`.
            Available options: `"mouse"`, `"pen"`, `"touch"`.
        :param duration: `<int/float>` The duration in seconds to perform a pointer move or wheel scroll action. Defaults to `0.2`.
        """
        # Validate pointer
        if pointer not in Constraint.POINTER_TYPES:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid pointer {}, accepts: {}".format(
                    self.__class__.__name__,
                    repr(pointer),
                    sorted(Constraint.POINTER_TYPES),
                )
            )
        self._pointer_type: str = pointer
        # Validate duration
        if not isinstance(duration, (int, float)) or duration < 0:
            raise errors.InvalidArgumentError(
                "<{}>\nArgument 'duration' must be an integer or "
                "float with value `> 0`. Instead of: {} {}.".format(
                    self.__class__.__name__, repr(duration), type(duration)
                )
            )
        self._duration: int = int(duration * 1000)
        # Session
        self._session: Session = session
        # Device
        self._pointer_id = self._pointer_type
        self._key_id = "key"
        self._wheel_id = "wheel"
        # Chain
        self._pointer_actions: PointerActions = {}
        self._key_actions: KeyActions = {}
        self._wheel_actions: WheelActions = {}

    # Properties --------------------------------------------------------------------------
    @property
    def actions(self) -> ActionsChain:
        """Access all the actions to be performed `<ActionsDict>`.

        Expected format:
        >>> {
                "pointer": {...},
                "key": {...},
                "wheel": {...},
            }
        """
        return {
            "pointer": self._pointer_actions,
            "key": self._key_actions,
            "wheel": self._wheel_actions,
        }

    # Pointer Actions ---------------------------------------------------------------------
    def move_to(
        self,
        element: Element | None = None,
        x: int = 0,
        y: int = 0,
        pause: int | float | None = None,
    ) -> Actions:
        """Move the pointer (mouse) to an element (or a location).

        :param element: `<Element/None>` The Element to move to. Defaults to `None`.
            - If specified, moves the pointer to the center of the element,
              where 'x/y' are the offsets relative to the center.
            - If not specified (`None`), moves the pointer to the given 'x/y'
              coordinates of the viewport.

        :param x: `<int>` The x-coordinate of the viewport, `*OR*` the x-offset to the center of an 'element'. Defaults to `0`.
        :param y: `<int>` The y-coordinate of the viewport, `*OR*` the y-offset to the center of an 'element'. Defaults to `0`.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.

        ### Example:
        >>> # . move the pointer to x/y coordinates of the viewport
            await session.actions().move_to(x=100, y=100).perform()

        >>> # . move the pointer to the center of an element
            element = await session.find_element("#element")
            await session.actions().move_to(element=element).perform()
        """
        if isinstance(element, Element):
            self._pointer_move(x=x, y=y, origin=element)
        else:
            self._pointer_move(x=x, y=y, origin="viewport")
        return self.pause(pause)

    def move_by(
        self,
        x: int = 0,
        y: int = 0,
        pause: int | float | None = None,
    ) -> Actions:
        """Move the pointer (mouse) by the given offsets.

        :param x: `<int>` The x-coordinate offset relative to the pointer. Defaults to `0`.
        :param y: `<int>` The y-coordinate offset relative to the pointer. Defaults to `0`.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.

        ### Example:
        >>> # . move the pointer by x/y offset relative to its origin
            await session.actions().move_by(x=100, y=100).perform()
        """
        self._pointer_move(x=x, y=y, origin="pointer")
        return self.pause(pause)

    def click(
        self,
        button: int = MouseButtons.LEFT,
        hold: bool = False,
        double: bool = False,
        pause: int | float | None = None,
    ) -> Actions:
        """Click a button of the pointer (mouse).

        :param button: `<int>` The button to click. Defaults to `MouseButtons.LEFT`.
        :param hold: `<bool>` Whether to hold the button down after clicked. Defaults to `False`.
        :param double: `<bool>` Whether to perform a double click (ignored when `hold=True`). Defaults to `False`.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The Actions chian.

        ### Example:
        >>> # . click (press & release) the left button of the pointer
            await session.actions().click().perform()

        >>> # . press & hold the right button of the pointer
            from aselenium import MouseButtons
            await session.actions().click(MouseButtons.RIGHT, hold=True).perform()

        >>> # . double click the left button of the pointer
            await session.actions().click(double=True).perform()
        """
        self._pointer_down(button)
        if hold:
            return self.pause(pause)
        if double:
            self._pointer_up(button)
            self._pointer_down(button)
        self._pointer_up(button)
        return self.pause(pause)

    def release(
        self,
        button: int = MouseButtons.LEFT,
        pause: int | float | None = None,
    ) -> Actions:
        """Release a previously press & hold button of the pointer (mouse).
        Use after the action `click(hold=True)`.

        :param button: `<int>` The button to release. Defaults to `MouseButtons.LEFT`.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.

        ### Example:
        >>> # . press & hold & release the left button of the pointer
            (
                await session.actions().click(hold=True)
                ...  # some actions
                .release()
                .perform()
            )
        """
        self._pointer_up(button)
        return self.pause(pause)

    def drop_and_drop(
        self,
        src_element: Element,
        dst_element: Element,
        pause: int | float | None = None,
    ) -> Actions:
        """Drag and drop an element to another element.

        :param src_element: `<Element>` The source element to drag.
        :param dst_element: `<Element>` The destination element to drop.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.

        ### Notice:
        The `drag_and_drop` method is a custom chain of the following actions:
            - move_to(element=src_element)
            - click(hold=True)
            - move_to(element=dst_element)
            - release()

        ### Example:
        >>> left_element = await session.find_element("#left_element")
            right_element = await session.find_element("#right_element")
            (
                await session.actions()
                .drag_and_drop(left_element, right_element)
                .perform())
            )
        """
        self.move_to(element=src_element)
        self.click(hold=True)
        self.move_to(element=dst_element)
        self.release()
        return self.pause(pause)

    def _pointer_move(
        self,
        x: float = 0,
        y: float = 0,
        origin: str | Element | None = None,
        duration: int | float | None = None,
        **kwargs,
    ) -> None:
        "(Internal) Move the pointer (mouse) to a location."
        action = {
            "type": "pointerMove",
            "duration": self._adjust_duration(duration),
            "x": int(x),
            "y": int(y),
            **self._adjust_kwargs(kwargs),
        }
        if isinstance(origin, Element):
            action["origin"] = {ELEMENT_KEY: origin.id}
        elif origin is not None:
            action["origin"] = origin
        self._add_pointer_action(action)

    def _pointer_down(self, button: int, **kwargs) -> None:
        "(Internal) Press down a button of the pointer (mouse)."
        self._add_pointer_action(
            {
                "type": "pointerDown",
                "duration": 0,
                "button": button,
                **self._adjust_kwargs(kwargs),
            },
        )

    def _pointer_up(self, button: int) -> None:
        "(Internal) Release a button of the pointer (mouse)."
        self._add_pointer_action({"type": "pointerUp", "duration": 0, "button": button})

    def _pointer_cancel(self) -> None:
        "(Internal) Cancel a pointer (mouse) action."
        self._add_pointer_action({"type": "pointerCancel"})

    def _add_pointer_action(self, action: dict) -> None:
        "(Internal) Add a pointer (mouse) action to the chain."
        if not self._pointer_actions:
            self._pointer_actions = {
                "type": "pointer",
                "parameters": {"pointerType": self._pointer_type},
                "id": self._pointer_id,
                "actions": [action],
            }
        else:
            self._pointer_actions["actions"].append(action)
        self._add_key_pause(0)
        self._add_wheel_pause(0)

    def _add_pointer_pause(self, duration: int | float) -> None:
        "(Internal) Add a pause for the pointer (mouse) actions."
        if not self._pointer_actions:
            self._pointer_actions = {
                "type": "pointer",
                "parameters": {"pointerType": self._pointer_type},
                "id": self._pointer_id,
                "actions": [{"type": "pause", "duration": duration}],
            }
        else:
            self._pointer_actions["actions"].append(
                {"type": "pause", "duration": duration}
            )

    # Keyboard Actions --------------------------------------------------------------------
    def key_down(
        self,
        key: str | KeyboardKeys,
        pause: int | float | None = None,
    ) -> Actions:
        """Press down a keyboard KEY.

        :param key: `<str/KeyboardKeys>` The KEY to press down.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.

        ### Example:
        >>> # . control + a (select all)
            From aselenium import KeyboardKeys
            (
                await session.actions()
                .key_down(KeyboardKeys.CONTROL)
                .key_down("a")
                .key_up("a")
                .key_up(KeyboardKeys.CONTROL)
                .perform()
            )
        """
        self._key_down(key)
        return self.pause(pause)

    def key_up(self, key: str, pause: int | float | None = None) -> Actions:
        """Release a keyboard KEY.

        :param key: `<str>` The KEY to release.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.

        ### Example:
        >>> # . control + a (select all)
            From aselenium import KeyboardKeys
            (
                await session.actions()
                .key_down(KeyboardKeys.CONTROL)
                .key_down("a")
                .key_up("a")
                .key_up(KeyboardKeys.CONTROL)
                .perform()
            )
        """
        self._key_up(key)
        return self.pause(pause)

    def send_keys(
        self,
        *keys: str | KeyboardKeys,
        pause: int | float | None = None,
    ) -> Actions:
        """Send keyboard KEYs.

        :param keys: `<str/KeyboardKeys>` The keys to send.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.

        Example:
        >>> From aselenium import KeyboardKeys
            inputbox = await session.find_element("#inputbox")
            (
                await session.actions()
                .move_to(inputbox)
                .click()
                .send_keys("Hello world!")
                .send_keys(KeyboardKeys.ENTER)
                .perform()
            )
        """
        for key in process_keys(*keys):
            self._key_down(key)
            self._key_up(key)
        return self.pause(pause)

    def _key_down(self, key: str, **kwargs) -> None:
        "(Internal) Press down a keyboard KEY."
        self._add_key_action(
            {"type": "keyDown", "value": key, **self._adjust_kwargs(kwargs)}
        )

    def _key_up(self, key: str) -> None:
        "(Internal) Release a keyboard KEY."
        self._add_key_action({"type": "keyUp", "value": key})

    def _add_key_action(self, action: dict) -> None:
        "(Internal) Add a keyboard action to the chain."
        if not self._key_actions:
            self._key_actions = {
                "type": "key",
                "id": self._key_id,
                "actions": [action],
            }
        else:
            self._key_actions["actions"].append(action)
        self._add_pointer_pause(0)
        self._add_wheel_pause(0)

    def _add_key_pause(self, duration: int | float) -> None:
        "(Internal) Add a pause for the keyboard actions."
        if not self._key_actions:
            self._key_actions = {
                "type": "key",
                "id": self._key_id,
                "actions": [{"type": "pause", "duration": duration}],
            }
        else:
            self._key_actions["actions"].append({"type": "pause", "duration": duration})

    # Wheel Actions -----------------------------------------------------------------------
    def scroll_to(
        self,
        element: Element,
        x: int = 0,
        y: int = 0,
        pause: int | float | None = None,
    ) -> Actions:
        """Scroll the viewport to an element.

        :param element: `<Element/None>` The Element to scroll to.
        :param x: `<int>` The x-offset to the center of an 'element'. Defaults to `0`.
        :param y: `<int>` The y-offset to the center of an 'element'. Defaults to `0`.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.
        """
        if not isinstance(element, Element):
            raise errors.InvalidArgumentError(
                "<{}>\nArgument 'element' must be an `<Element>` "
                "instance. Instead of: {} {}.".format(
                    self.__class__.__name__, repr(element), type(element)
                )
            )
        self._wheel_scroll(x_delta=x, y_delta=y, origin=element)
        return self.pause(pause)

    def scroll_by(
        self,
        x: int = 0,
        y: int = 0,
        pause: int | float | None = None,
    ) -> Actions:
        """Scroll the viewport by the given offsets.

        :param x: `<int>` The x-coordinate offset relative to current viewport position. Defaults to `0`.
        :param y: `<int>` The y-coordinate offset relative to current viewport position. Defaults to `0`.
        :param pause: `<int/float/None>` Total seconds to pause after the action. Defaults to `None`.
        :return `<Actions>`: The actions chain.
        """
        self._wheel_scroll(x_delta=x, y_delta=y, origin="viewport")
        return self.pause(pause)

    def _wheel_scroll(
        self,
        x: int = 0,
        y: int = 0,
        x_delta: int = 0,
        y_delta: int = 0,
        origin: str | Element | None = None,
        duration: int | float | None = 0,
    ) -> None:
        "(Internal) Scroll the viewport to a location."
        action = {
            "type": "scroll",
            "x": int(x),
            "y": int(y),
            "deltaX": int(x_delta),
            "deltaY": int(y_delta),
            "duration": self._adjust_duration(duration),
        }
        if isinstance(origin, Element):
            action["origin"] = {ELEMENT_KEY: origin.id}
        elif origin is not None:
            action["origin"] = origin
        self._add_wheel_action(action)

    def _add_wheel_action(self, action: dict) -> None:
        "(Internal) Add a wheel action to the chain."
        if not self._wheel_actions:
            self._wheel_actions = {
                "type": "wheel",
                "id": self._wheel_id,
                "actions": [action],
            }
        else:
            self._wheel_actions["actions"].append(action)
        self._add_pointer_pause(0)
        self._add_key_pause(0)

    def _add_wheel_pause(self, duration: int | float) -> None:
        "(Internal) Add a pause for the wheel actions."
        if not self._wheel_actions:
            self._wheel_actions = {
                "type": "wheel",
                "id": self._wheel_id,
                "actions": [{"type": "pause", "duration": duration}],
            }
        else:
            self._wheel_actions["actions"].append(
                {"type": "pause", "duration": duration}
            )

    # Pause Actions -----------------------------------------------------------------------
    def pause(self, duration: int | float | None) -> Actions:
        """Pause the chain for a given duration.

        :param duration: `<int/float/None>` The duration to pause in seconds.
        :return `<Actions>`: The actions chain.
        """
        if duration is None:
            return self
        try:
            duration = int(duration * 1000)
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nArgument 'duration' must be a positive `<int/float>`, "
                "instead of: {}.".format(self.__class__.__name__, repr(duration))
            ) from err
        self._add_pointer_pause(duration)
        self._add_key_pause(duration)
        self._add_wheel_pause(duration)
        return self

    # Perform -----------------------------------------------------------------------------
    async def perform(self) -> None:
        """Perform (execute) the actions chain."""
        try:
            await self._session.execute_command(
                Command.W3C_ACTIONS,
                {
                    "actions": [
                        action
                        for action in [
                            self._pointer_actions,
                            self._key_actions,
                            self._wheel_actions,
                        ]
                        if action
                    ]
                },
            )
        except errors.MoveTargetOutOfBoundsError as err:
            raise errors.MoveTargetOutOfBoundsError(
                f"<{self.__class__.__name__}> {err}\n"
                "-> This might be caused by trying to perform an action to move "
                "the pointer (mouse) or scoll the viewport out of the document."
            )

        finally:
            self._collect_garbage()

    async def reset(self) -> Actions:
        """Reset the action chain."""
        await self._session.execute_command(Command.W3C_CLEAR_ACTIONS)
        self._pointer_actions = {}
        self._key_actions = {}
        self._wheel_actions = {}
        return self

    # Utils -------------------------------------------------------------------------------
    def _adjust_duration(self, duration: int | float | None) -> int:
        "(Internal) Adjust the duration to milliseconds."
        if duration is None:
            return self._duration
        elif isinstance(duration, int) and duration >= 0:
            return duration * 1000
        elif isinstance(duration, float) and duration >= 0:
            return int(duration * 1000)
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nArgument 'duration' an integer or float "
                "with value `> 0`. Instead of: {} {}.".format(
                    self.__class__.__name__, repr(duration), type(duration)
                )
            )

    def _adjust_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        "(Internal) Adjust the keyword arguments."

        def adjust_key(key: str) -> str:
            if "_" in key:
                key, *keys = key.split("_")
                key += "".join([i.title() for i in keys])
            return key

        if kwargs:
            return {adjust_key(k): v for k, v in kwargs.items() if v is not None}
        else:
            return {}

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<Actions:\n%s\n>" % (
            "\n".join(
                "%s Actions: %s" % (key.title(), prettify_dict(val))
                for key, val in self.actions.items()
                if val
            ),
        )

    def __del__(self):
        self._collect_garbage()

    def _collect_garbage(self) -> None:
        """(Internal) Release most of the memory occupied by the query variables."""
        self._session = None
        self._duration = None
        # Device
        self._pointer_type = None
        self._pointer_id = None
        self._key_id = None
        self._wheel_id = None
        # Chain
        self._pointer_actions = None
        self._key_actions = None
        self._wheel_actions = None
