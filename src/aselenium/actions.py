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
"""Aselenium actions implementation and supporting types."""

from __future__ import annotations

from asyncio import sleep
from math import isfinite
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypedDict,
)

from aselenium import errors
from aselenium.command import Command
from aselenium.element import ELEMENT_KEY, Element
from aselenium.settings import Constraint
from aselenium.utils import MouseButtons, process_keys

if TYPE_CHECKING:
    from aselenium.session import Session

__all__ = ["Actions"]


# Types -------------------------------------------------------------------------------------------
class PointerActions(TypedDict, total=False):
    """The pointer (mouse) actions to perform.

    Example:
        >>> payload = {"type": "pointer", "parameters": {"pointerType": "mouse"},
        ...            "id": "mouse", "actions": [{"type": "pointerDown", "button": 0}]}
    """

    type: str
    parameters: dict[str, str]
    id: str
    actions: list[dict[str, Any]]


class KeyActions(TypedDict, total=False):
    """The keyboard actions to perform.

    Example:
        >>> payload = {"type": "key", "id": "key",
        ...            "actions": [{"type": "keyDown", "value": "a"}]}
    """

    type: str
    id: str
    actions: list[dict[str, Any]]


class WheelActions(TypedDict, total=False):
    """The wheel actions to perform.

    Example:
        >>> payload = {"type": "wheel", "id": "wheel", "actions": [
        ...     {"type": "scroll", "x": 0, "y": 0, "deltaX": 0, "deltaY": 100,
        ...      "duration": 0, "origin": "viewport"}]}
    """

    type: str
    id: str
    actions: list[dict[str, Any]]


class ActionsChain(TypedDict):
    """The complete actions chain to perform.

    Example:
        >>> chain = session.actions().click()
        >>> payload = chain.actions
    """

    pointer: PointerActions
    key: KeyActions
    wheel: WheelActions


# Actions -----------------------------------------------------------------------------------------
class Actions:
    """Represent an actions chain that performs (automate) low level interactions such as mouse movements, key presses, and wheel scrolls."""

    def __init__(
        self,
        session: Session,
        pointer: Literal["mouse", "pen", "touch"] = "mouse",
        duration: int | float = 0.2,
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            session: The session to perform the action chain.
            pointer: The pointer type to use. Defaults to `'mouse'`.
                Available options: `"mouse"`, `"pen"`, `"touch"`.
            duration: The duration in seconds to perform a pointer move or wheel scroll action. Defaults to `0.2`.
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
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not isfinite(duration)
            or duration < 0
            or not isfinite(duration * 1000)
        ):
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
        """Return all the actions to be performed.

        Example:
            >>> chain = session.actions().click()
            >>> payload = chain.actions

        Returns:
            All the actions to be performed.
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

        Args:
            element: The Element to move to. Defaults to `None`.
                - If specified, moves the pointer to the center of the element,
                where 'x/y' are the offsets relative to the center.
                - If not specified (`None`), moves the pointer to the given 'x/y'
                coordinates of the viewport.
            x: The x-coordinate of the viewport, `*OR*` the x-offset to the center of an 'element'. Defaults to `0`.
            y: The y-coordinate of the viewport, `*OR*` the y-offset to the center of an 'element'. Defaults to `0`.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.

        Example:
            >>> # . move the pointer to x/y coordinates of the viewport
            >>> await session.actions().move_to(x=100, y=100).perform()

            >>> # . move the pointer to the center of an element
            >>> element = await session.find_element("#element")
            >>> await session.actions().move_to(element=element).perform()
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

        Args:
            x: The x-coordinate offset relative to the pointer. Defaults to `0`.
            y: The y-coordinate offset relative to the pointer. Defaults to `0`.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.

        Example:
            >>> # . move the pointer by x/y offset relative to its origin
            >>> await session.actions().move_by(x=100, y=100).perform()
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

        Args:
            button: The button to click. Defaults to `MouseButtons.LEFT`.
            hold: Whether to hold the button down after clicked. Defaults to `False`.
            double: Whether to perform a double click (ignored when `hold=True`). Defaults to `False`.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.

        Example:
            >>> # . click (press & release) the left button of the pointer
            >>> await session.actions().click().perform()

            >>> # . press & hold the right button of the pointer
            >>> from aselenium import MouseButtons
            >>> await session.actions().click(MouseButtons.RIGHT, hold=True).perform()

            >>> # . double click the left button of the pointer
            >>> await session.actions().click(double=True).perform()
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
        """Release a previously press & hold button of the pointer (mouse). Use after the action `click(hold=True)`.

        Args:
            button: The button to release. Defaults to `MouseButtons.LEFT`.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.

        Example:
            >>> await session.actions().click(hold=True).release().perform()
        """
        self._pointer_up(button)
        return self.pause(pause)

    def drag_and_drop(
        self,
        drag: Element | None = None,
        drag_x: int = 0,
        drag_y: int = 0,
        drop: Element | None = None,
        drop_x: int = 0,
        drop_y: int = 0,
        pause: int | float | None = None,
    ) -> Actions:
        """Drag and drop an element (coordinates) to another element (coordinates).

        Notice:
        The `drag_and_drop` method eqvivalent to the following actions:
            - move_to(drag, drag_x, drag_y)
            - click(MouseButtons.LEFT, hold=True)
            - move_to(drop, drop_x, drop_y)
            - release(MouseButtons.LEFT)

        Based on testing, drag and drop only works properly for Chromium based browsers.

        Args:
            drag: The source element to drag. Defaults to `None`.
            drag_x: The x-coordinate of the viewport, `*OR*` the x-offset to the center of a 'drag' element. Defaults to `0`.
            drag_y: The y-coordinate of the viewport, `*OR*` the y-offset to the center of a 'drag' element. Defaults to `0`.
            drop: The destination element to drop. Defaults to `None`.
            drop_x: The x-coordinate of the viewport, `*OR*` the x-offset to the center of an 'drop' element. Defaults to `0`.
            drop_y: The y-coordinate of the viewport, `*OR*` the y-offset to the center of an 'drop' element. Defaults to `0`.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.

        Example:
            >>> left = await session.find_element("#left_element")
            >>> right = await session.find_element("#right_element")
            >>> if left is None or right is None:
            ...     raise LookupError("Both drag targets must exist")
            >>> await session.actions().drag_and_drop(drag=left, drop=right).perform()
        """
        self.move_to(element=drag, x=drag_x, y=drag_y)
        self._pointer_down(MouseButtons.LEFT)
        self.move_to(element=drop, x=drop_x, y=drop_y)
        self._pointer_up(MouseButtons.LEFT)
        return self.pause(pause)

    def _pointer_move(
        self,
        x: float = 0,
        y: float = 0,
        origin: str | Element | None = None,
        duration: int | float | None = None,
        **kwargs: Any,
    ) -> None:
        """Move the pointer (mouse) to a location.

        Args:
            x: X used by this operation.
            y: Y used by this operation.
            origin: Origin used by this operation.
            duration: Duration used by this operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.
        """
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

    def _pointer_down(self, button: int, **kwargs: Any) -> None:
        """Press down a button of the pointer (mouse).

        Args:
            button: Button used by this operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.
        """
        self._add_pointer_action(
            {
                "type": "pointerDown",
                "duration": 0,
                "button": button,
                **self._adjust_kwargs(kwargs),
            },
        )

    def _pointer_up(self, button: int) -> None:
        """Release a button of the pointer (mouse).

        Args:
            button: Button used by this operation.
        """
        self._add_pointer_action({"type": "pointerUp", "duration": 0, "button": button})

    def _pointer_cancel(self) -> None:
        """Cancel a pointer (mouse) action."""
        self._add_pointer_action({"type": "pointerCancel"})

    def _add_pointer_action(self, action: dict[str, Any]) -> None:
        """Add a pointer (mouse) action to the chain.

        Args:
            action: Action used by this operation.
        """
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
        """Add a pause for the pointer (mouse) actions.

        Args:
            duration: Duration used by this operation.
        """
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
        key: str,
        pause: int | float | None = None,
    ) -> Actions:
        """Press down a keyboard KEY.

        Args:
            key: The KEY to press down.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.

        Example:
            >>> from aselenium import KeyboardKeys

            >>> await (
            ...     session.actions()
            ...     .key_down(KeyboardKeys.CONTROL)
            ...     .key_down("a")
            ...     .key_up("a")
            ...     .key_up(KeyboardKeys.CONTROL)
            ...     .perform()
            ... )
        """
        self._key_down(key)
        return self.pause(pause)

    def key_up(self, key: str, pause: int | float | None = None) -> Actions:
        """Release a keyboard KEY.

        Args:
            key: The KEY to release.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.

        Example:
            >>> from aselenium import KeyboardKeys

            >>> await (
            ...     session.actions()
            ...     .key_down(KeyboardKeys.CONTROL)
            ...     .key_down("a")
            ...     .key_up("a")
            ...     .key_up(KeyboardKeys.CONTROL)
            ...     .perform()
            ... )
        """
        self._key_up(key)
        return self.pause(pause)

    def send_keys(
        self,
        *keys: str,
        pause: int | float | None = None,
    ) -> Actions:
        """Simulate the action of typing keyboard keys.

        Notice:
        Different from the `send_key_combo()`, the `send_keys()` method simulates
        the actions of typing a series of keyboard keys, such as `Hello world!`.
        Each key is first pressed down and then released in the specified order.

        Example:
            >>> from aselenium import KeyboardKeys
            >>> inputbox = await session.find_element("#inputbox")
            >>> if inputbox is None:
            ...     raise LookupError("The input field is missing")
            >>> await (
            ...     session.actions()
            ...     .move_to(inputbox)
            ...     .click()
            ...     .send_keys("Hello world!")
            ...     .send_keys(KeyboardKeys.ENTER)
            ...     .perform()
            ... )

        Args:
            pause: Total seconds to pause after the action. Defaults to `None`.
            *keys: The keys to send.

        Returns:
            The actions chain.
        """
        for key in process_keys(*keys):
            self._key_down(key)
            self._key_up(key)
        return self.pause(pause)

    def send_key_combo(
        self,
        *keys: str,
        pause: int | float | None = None,
    ) -> Actions:
        """Simulates the action of pressing a combination of keys.

        Notice:
        Different from the `send_keys()`, the `send_key_combo()` method simulates
        the action of pressing a combination of keys, such as `ctrl + a` (select all),
        `ctrl + c` (copy), `ctrl + v` (paste), etc. Each key is first pressed down in
        the specified order, and then released in the reverse order.

        Args:
            pause: Total seconds to pause after the action. Defaults to `None`.
            *keys: The keys combinations to send.

        Returns:
            The actions chain.

        Example:
            >>> from aselenium import KeyboardKeys

            >>> field = await session.find_element("#inputbox")
            >>> if field is None:
            ...     raise LookupError("The input field is missing")
            >>> await (
            ...     session.actions()
            ...     .move_to(field)
            ...     .click()
            ...     .send_keys("Hello world!")
            ...     .send_key_combo(KeyboardKeys.CONTROL, "a")
            ...     .send_key_combo(KeyboardKeys.CONTROL, "x")
            ...     .send_key_combo(KeyboardKeys.CONTROL, "v")
            ...     .perform()
            ... )
        """
        processed_keys = process_keys(*keys)
        for key in processed_keys:
            self._key_down(key)
        for key in reversed(processed_keys):
            self._key_up(key)
        return self.pause(pause)

    def _key_down(self, key: str, **kwargs: Any) -> None:
        """Press down a keyboard KEY.

        Args:
            key: Lookup key used by the current operation.
            **kwargs: Keyword arguments forwarded to the wrapped operation.
        """
        self._add_key_action(
            {"type": "keyDown", "value": key, **self._adjust_kwargs(kwargs)}
        )

    def _key_up(self, key: str) -> None:
        """Release a keyboard KEY.

        Args:
            key: Lookup key used by the current operation.
        """
        self._add_key_action({"type": "keyUp", "value": key})

    def _add_key_action(self, action: dict[str, Any]) -> None:
        """Add a keyboard action to the chain.

        Args:
            action: Action used by this operation.
        """
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
        """Add a pause for the keyboard actions.

        Args:
            duration: Duration used by this operation.
        """
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

        Args:
            element: The Element to scroll to.
            x: The x-offset to the center of an 'element'. Defaults to `0`.
            y: The y-offset to the center of an 'element'. Defaults to `0`.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.
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

        Args:
            x: The x-coordinate offset relative to current viewport position. Defaults to `0`.
            y: The y-coordinate offset relative to current viewport position. Defaults to `0`.
            pause: Total seconds to pause after the action. Defaults to `None`.

        Returns:
            The actions chain.
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
        """Scroll the viewport to a location.

        Args:
            x: X used by this operation.
            y: Y used by this operation.
            x_delta: X delta used by this operation.
            y_delta: Y delta used by this operation.
            origin: Origin used by this operation.
            duration: Duration used by this operation.
        """
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

    def _add_wheel_action(self, action: dict[str, Any]) -> None:
        """Add a wheel action to the chain.

        Args:
            action: Action used by this operation.
        """
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
        """Add a pause for the wheel actions.

        Args:
            duration: Duration used by this operation.
        """
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

        Args:
            duration: The duration to pause in seconds.

        Returns:
            The actions chain.
        """
        if duration is None:
            return self
        duration = self._adjust_duration(duration)
        self._add_pointer_pause(duration)
        self._add_key_pause(duration)
        self._add_wheel_pause(duration)
        return self

    # Perform -----------------------------------------------------------------------------
    async def perform(self, explicit_wait: int | float | None = None) -> None:
        """Perform (execute) the actions chain.

        The dispatched queue is cleared even if the request fails, so an ambiguous
        failure cannot cause queued input to be replayed automatically. Await this
        call before reusing the chain to build a new sequence. Cancellation
        propagates to the caller.

        Args:
            explicit_wait: Optional finite, nonnegative delay in seconds after the driver
                responds. None adds no delay. This does not wait for a specific DOM state;
                use a condition-based wait when a page updates after the input sequence.
        """
        if explicit_wait is not None and (
            isinstance(explicit_wait, bool)
            or not isinstance(explicit_wait, (int, float))
            or not isfinite(explicit_wait)
            or explicit_wait < 0
        ):
            raise errors.InvalidArgumentError(
                "explicit_wait must be a finite nonnegative number"
            )
        # Perform the actions
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
            # Clear dispatched input without losing the owning session. An
            # ambiguous failure is not automatically replayed on another call.
            self._pointer_actions = {}
            self._key_actions = {}
            self._wheel_actions = {}

        # Explicit wait
        if explicit_wait is None:
            return None
        try:
            await sleep(explicit_wait)
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nArgument 'explicit_wait' must "
                "be a positive `<'int/float'>`, instead of: {} {}.".format(
                    self.__class__.__name__, repr(explicit_wait), type(explicit_wait)
                )
            ) from err

    async def reset(self) -> Actions:
        """Reset the action chain.

        Returns:
            The Actions value produced by this operation.
        """
        await self._session.execute_command(Command.W3C_CLEAR_ACTIONS)
        self._pointer_actions = {}
        self._key_actions = {}
        self._wheel_actions = {}
        return self

    # Utils -------------------------------------------------------------------------------
    def _adjust_duration(self, duration: int | float | None) -> int:
        """Adjust the duration to milliseconds.

        Args:
            duration: Duration used by this operation.

        Returns:
            Adjust the duration to milliseconds.
        """
        if duration is None:
            return self._duration
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not isfinite(duration)
            or duration < 0
            or not isfinite(duration * 1000)
        ):
            raise errors.InvalidArgumentError(
                "<{}>\nArgument 'duration' an integer or float "
                "with value `> 0`. Instead of: {} {}.".format(
                    self.__class__.__name__, repr(duration), type(duration)
                )
            )
        return int(duration * 1000)

    def _adjust_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Adjust the keyword arguments.

        Args:
            kwargs: Keyword arguments forwarded to the wrapped operation.

        Returns:
            A mapping containing the adjust kwargs data.
        """

        def adjust_key(key: str) -> str:
            """Validate and normalize the key before adding it to the action sequence.

            Args:
                key: Lookup key used by the current operation.

            Returns:
                And normalize the key before adding it to the action sequence.
            """
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
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        count = sum(
            len(device.get("actions", []))
            for device in (
                self._pointer_actions,
                self._key_actions,
                self._wheel_actions,
            )
        )
        return "<Actions (queued=%d, payload=<redacted>)>" % count
