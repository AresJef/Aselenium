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

"""Geometry, key constants, value containers, and property-list decoding."""

from __future__ import annotations

from collections.abc import ItemsView, Iterator, KeysView, ValuesView
from math import ceil, floor, isfinite
from pathlib import Path
from platform import system
from plistlib import load
from typing import (
    Any,
    TypeVar,
    cast,
)

from aselenium import errors
from aselenium._paths import PathInput, parse_path

__all__ = ["KeyboardKeys", "MouseButtons"]
R = TypeVar("R", bound="Rectangle")


# Class: rectangle --------------------------------------------------------------------------------
class Rectangle:
    """Represent integral browser geometry derived from finite real numbers."""

    def __init__(
        self,
        width: int | float,
        height: int | float,
        x: int | float,
        y: int | float,
    ) -> None:
        """Round dimensions upward and coordinates downward to browser integers.

        Args:
            width: Finite rectangle width, rounded toward positive infinity.
            height: Finite rectangle height, rounded toward positive infinity.
            x: Finite horizontal coordinate, rounded toward negative infinity.
            y: Finite vertical coordinate, rounded toward negative infinity.

        Raises:
            errors.InvalidRectValueError: A value is boolean, nonnumeric, or not
                finite.
        """
        values = (width, height, x, y)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            for value in values
        ):
            raise errors.InvalidRectValueError(
                "<{}>\nInvalid rectangle values: "
                "{{'width': {}, 'height': {}, 'x': {}, 'y': {}}}.".format(
                    self.__class__.__name__, repr(width), repr(height), repr(x), repr(y)
                )
            )
        try:
            self._width: int = ceil(width)
            self._height: int = ceil(height)
            self._x: int = floor(x)
            self._y: int = floor(y)
        except Exception as err:
            raise errors.InvalidRectValueError(
                "<{}>\nInvalid rectangle values: "
                "{{'width': {}, 'height': {}, 'x': {}, 'y': {}}}.".format(
                    self.__class__.__name__, repr(width), repr(height), repr(x), repr(y)
                )
            ) from err

    # Properties ---------------------------------------------------------------
    @property
    def dict(self) -> dict[str, int]:
        """Return the rectangle as a WebDriver-compatible mapping.

        Returns:
            Integer ``width``, ``height``, ``x``, and ``y`` values.

        Example:
            >>> Rectangle(100, 80, 10, 20).dict
            {'width': 100, 'height': 80, 'x': 10, 'y': 20}
        """
        return {
            "width": self._width,
            "height": self._height,
            "x": self._x,
            "y": self._y,
        }

    @property
    def width(self) -> int:
        """Return the width.

        Returns:
            The width.
        """
        return self._width

    @width.setter
    def width(self, value: int | float | None) -> None:
        # Ignore None
        """Set the width.

        Args:
            value: Finite width rounded upward. ``None`` leaves the value unchanged.
        """
        if value is None:
            return None  # exit
        # Set value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise errors.InvalidRectValueError(
                f"<{self.__class__.__name__}>\nInvalid rectangle width: {value!r}."
            )
        try:
            self._width = ceil(value)
        except Exception as err:
            raise errors.InvalidRectValueError(
                "<{}>\nInvalid rectangle width: {}.".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err

    @property
    def height(self) -> int:
        """Return the height.

        Returns:
            The height.
        """
        return self._height

    @height.setter
    def height(self, value: int | float | None) -> None:
        # Ignore None
        """Set the height.

        Args:
            value: Finite height rounded upward. ``None`` leaves the value unchanged.
        """
        if value is None:
            return None  # exit
        # Set value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise errors.InvalidRectValueError(
                f"<{self.__class__.__name__}>\nInvalid rectangle height: {value!r}."
            )
        try:
            self._height = ceil(value)
        except Exception as err:
            raise errors.InvalidRectValueError(
                "<{}>\nInvalid rectangle height: {}.".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err

    @property
    def x(self) -> int:
        """Return the x-coordinate.

        Returns:
            The x-coordinate.
        """
        return self._x

    @x.setter
    def x(self, value: int | float | None) -> None:
        # Ignore None
        """Set the x.

        Args:
            value: Finite coordinate rounded downward. ``None`` leaves it unchanged.
        """
        if value is None:
            return None  # exit
        # Set value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise errors.InvalidRectValueError(
                f"<{self.__class__.__name__}>\nInvalid rectangle x-coordinate: {value!r}."
            )
        try:
            self._x = floor(value)
        except Exception as err:
            raise errors.InvalidRectValueError(
                "<{}>\nInvalid rectangle x-coordinate: {}.".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err

    @property
    def y(self) -> int:
        """Return the y-coordinate.

        Returns:
            The y-coordinate.
        """
        return self._y

    @y.setter
    def y(self, value: int | float | None) -> None:
        # Ignore None
        """Set the y.

        Args:
            value: Finite coordinate rounded downward. ``None`` leaves it unchanged.
        """
        if value is None:
            return None  # exit
        # Set value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise errors.InvalidRectValueError(
                f"<{self.__class__.__name__}>\nInvalid rectangle y-coordinate: {value!r}."
            )
        try:
            self._y = floor(value)
        except Exception as err:
            raise errors.InvalidRectValueError(
                "<{}>\nInvalid rectangle y-coordinate: {}.".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err

    @property
    def top(self) -> int:
        """Return the coordinate of top. Equivalent to property `y`.

        Returns:
            The coordinate of top. equivalent to property `y`.
        """
        return self._y

    @property
    def bottom(self) -> int:
        """Return the coordinate of bottom. Equivalent to property `y + height`.

        Returns:
            The coordinate of bottom. equivalent to property `y + height`.
        """
        return self._y + self._height

    @property
    def left(self) -> int:
        """Return the coordinate of left. Equivalent to property `x`.

        Returns:
            The coordinate of left. equivalent to property `x`.
        """
        return self._x

    @property
    def right(self) -> int:
        """Return the coordinate of right. Equivalent to property `x + width`.

        Returns:
            The coordinate of right. equivalent to property `x + width`.
        """
        return self._x + self._width

    @property
    def center_x(self) -> int:
        """Return the x-coordinate of the center.

        Returns:
            The x-coordinate of the center.
        """
        return self._x + self._width // 2

    @property
    def center_y(self) -> int:
        """Return the y-coordinate of the center.

        Returns:
            The y-coordinate of the center.
        """
        return self._y + self._height // 2

    # Special methods ----------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (width=%s, height=%s, x=%s, y=%s)>" % (
            self.__class__.__name__,
            self._width,
            self._height,
            self._x,
            self._y,
        )

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return self is __o

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self: R) -> R:
        """Copy the rectangle object.

        Returns:
            An independent copy of this value object.
        """
        return type(self)(self._width, self._height, self._x, self._y)


# Utils: custom dictionary ------------------------------------------------------------------------
class CustomDict:
    """Provide an identity-based mutable mapping with defensive snapshots."""

    def __init__(self, **kwargs: Any) -> None:
        """Store the supplied keyword entries in insertion order.

        Args:
            **kwargs: The dictionary to be initialized.
        """
        self._dict: dict[str, Any] = kwargs

    # Properties ---------------------------------------------------------------
    @property
    def dict(self) -> dict[str, Any]:
        """Return the dictionary.

        Returns:
            The dictionary.
        """
        return self._dict.copy()

    # Access -------------------------------------------------------------------
    def keys(self) -> KeysView[str]:
        """Return a view of the stored mapping keys.

        Returns:
            A view of the stored mapping keys.
        """
        return self._dict.keys()

    def values(self) -> ValuesView[Any]:
        """Return a view of the stored mapping values.

        Returns:
            A view of the stored mapping values.
        """
        return self._dict.values()

    def items(self) -> ItemsView[str, Any]:
        """Return a view of the stored key-value pairs.

        Returns:
            A view of the stored key-value pairs.
        """
        return self._dict.items()

    def get(self, key: str, default: Any = None) -> Any:
        """Return a stored value or the supplied default when the key is absent.

        Args:
            key: Lookup key used by the current operation.
            default: Value returned when ``key`` is absent.

        Returns:
            A stored value or the supplied default when the key is absent.
        """
        return self._dict.get(key, default)

    # Special methods ----------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (dict=%s)>" % (self.__class__.__name__, self._dict)

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return self is __o

    def __len__(self) -> int:
        """Return the number of stored items.

        Returns:
            The number of stored items.
        """
        return self._dict.__len__()

    def __iter__(self) -> Iterator[str]:
        """Iterate over the stored keys in insertion order.

        Yields:
            Mapping keys, not the values associated with them.
        """
        return self._dict.__iter__()

    def __setitem__(self, key: str, value: Any) -> None:
        """Assign the value associated with the supplied key.

        Args:
            key: Mapping key to create or replace.
            value: Value stored under ``key`` without transformation.
        """
        self._dict[key] = value

    def __getitem__(self, key: str) -> Any:
        """Return the item associated with the supplied index or key.

        Args:
            key: Mapping key to retrieve.

        Returns:
            The item associated with the supplied index or key.
        """
        return self._dict[key]

    def __contains__(self, key: str) -> bool:
        """Return whether the supplied item is present.

        Args:
            key: Lookup key used by the current operation.

        Returns:
            True if the supplied item is present; otherwise False.
        """
        return self._dict.__contains__(key)


# Utils: keyboard & mouse -------------------------------------------------------------------------
class KeyboardKeys:
    """Special keyboard keys."""

    # Basic keys
    NULL: str = "\ue000"
    CANCEL: str = "\ue001"  # ^break
    HELP: str = "\ue002"
    BACKSPACE: str = "\ue003"
    BACK_SPACE: str = BACKSPACE
    TAB: str = "\ue004"
    CLEAR: str = "\ue005"
    RETURN: str = "\ue006"
    ENTER: str = "\ue007"
    SHIFT: str = "\ue008"
    LEFT_SHIFT: str = SHIFT
    CONTROL: str = "\ue009"
    LEFT_CONTROL: str = CONTROL
    ALT: str = "\ue00a"
    LEFT_ALT: str = ALT
    PAUSE: str = "\ue00b"
    ESCAPE: str = "\ue00c"
    SPACE: str = "\ue00d"
    PAGE_UP: str = "\ue00e"
    PAGE_DOWN: str = "\ue00f"
    END: str = "\ue010"
    HOME: str = "\ue011"
    LEFT: str = "\ue012"
    ARROW_LEFT: str = LEFT
    UP: str = "\ue013"
    ARROW_UP: str = UP
    RIGHT: str = "\ue014"
    ARROW_RIGHT: str = RIGHT
    DOWN: str = "\ue015"
    ARROW_DOWN: str = DOWN
    INSERT: str = "\ue016"
    DELETE: str = "\ue017"
    SEMICOLON: str = "\ue018"
    EQUALS: str = "\ue019"

    # Number pad keys
    NUMPAD0: str = "\ue01a"
    NUMPAD1: str = "\ue01b"
    NUMPAD2: str = "\ue01c"
    NUMPAD3: str = "\ue01d"
    NUMPAD4: str = "\ue01e"
    NUMPAD5: str = "\ue01f"
    NUMPAD6: str = "\ue020"
    NUMPAD7: str = "\ue021"
    NUMPAD8: str = "\ue022"
    NUMPAD9: str = "\ue023"
    MULTIPLY: str = "\ue024"
    ADD: str = "\ue025"
    SEPARATOR: str = "\ue026"
    SUBTRACT: str = "\ue027"
    DECIMAL: str = "\ue028"
    DIVIDE: str = "\ue029"

    # Function keys
    F1: str = "\ue031"
    F2: str = "\ue032"
    F3: str = "\ue033"
    F4: str = "\ue034"
    F5: str = "\ue035"
    F6: str = "\ue036"
    F7: str = "\ue037"
    F8: str = "\ue038"
    F9: str = "\ue039"
    F10: str = "\ue03a"
    F11: str = "\ue03b"
    F12: str = "\ue03c"

    # Special keys
    META: str = "\ue03d"
    COMMAND: str = "\ue03d" if system() == "Darwin" else CONTROL
    ZENKAKU_HANKAKU: str = "\ue040"


class MouseButtons:
    """Mouse buttons."""

    LEFT = 0
    MIDDLE = 1
    RIGHT = 2
    BACK = 3
    FORWARD = 4


def process_keys(*keys: object) -> list[str]:
    """Split text and key constants into individual WebDriver key values.

    Args:
        *keys: Strings or values converted with str(). KeyboardKeys constants are
            strings; an instance of the KeyboardKeys namespace is not a key.

    Returns:
        Individual Unicode characters in input order, including special key codes.

    Raises:
        errors.InvalidArgumentError: A KeyboardKeys namespace instance is supplied.
    """
    lst: list[str] = []
    for key in keys:
        if isinstance(key, KeyboardKeys):
            raise errors.InvalidArgumentError(
                "Use a KeyboardKeys constant, not a KeyboardKeys instance"
            )
        else:
            lst.extend(str(key))
    return lst


# Utils: plist ------------------------------------------------------------------------------------
def load_plist_file(plist_file: PathInput) -> dict[str, Any]:
    """Decode a property-list file from an accepted filesystem path.

    Args:
        plist_file: Existing plist path supplied as text, ``Path``, or another
            string-valued ``os.PathLike`` object.

    Returns:
        The decoded top-level property-list mapping.

    Raises:
        errors.AseleniumInvalidPathError: The path value is empty, invalid, or
            not string-valued.
        OSError: The path cannot be opened or read.
        plistlib.InvalidFileException: The file is not a valid property list.
        ValueError: The plist root is not a dictionary, or a top-level key is
            not a string.
    """
    return _load_plist_file(parse_path(plist_file))


def _load_plist_file(plist_file: Path) -> dict[str, Any]:
    """Decode a plist from an already parsed host-native path.

    Args:
        plist_file: Absolute path retained by the calling filesystem workflow.

    Returns:
        The decoded top-level property-list mapping.

    Raises:
        OSError: The path cannot be opened or read.
        plistlib.InvalidFileException: The file is not a valid property list.
        ValueError: The path is not an absolute ``Path``, the plist root is not
            a dictionary, or a top-level key is not a string.
    """
    if not isinstance(plist_file, Path) or not plist_file.is_absolute():
        raise ValueError("Property-list path must be an absolute pathlib.Path")
    with plist_file.open("rb") as file:
        value = load(file)
    if not isinstance(value, dict):
        raise ValueError("Property-list root must be a dictionary")
    if not all(isinstance(key, str) for key in value):
        raise ValueError("Property-list root keys must all be strings")
    return cast(dict[str, Any], value)
