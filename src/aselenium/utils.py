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
from orjson import loads
from plistlib import load
from platform import system
from math import ceil, floor
from os.path import isfile, isdir, dirname, expanduser
from typing import Any, Iterator, KeysView, ValuesView, ItemsView
from aselenium import errors

__all__ = ["KeyboardKeys", "MouseButtons"]


# Class: rectangle --------------------------------------------------------------------------------
class Rectangle:
    """Represents the size and relative position of an rectangle object."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """The size and relative position of an retangle object.

        :param width: `<int>` The width of the rectangle object.
        :param height: `<int>` The height of the rectangle object.
        :param x: `<int>` The x-coordinate of the rectangle object.
        :param y: `<int>` The y-coordinate of the rectangle object.
        """
        try:
            self._width: int = ceil(width)
            self._height: int = ceil(height)
            self._x: int = floor(x)
            self._y: int = floor(y)
        except Exception as err:
            raise errors.InvalidRectValueError(
                "<{}>\nInvalid rectangle values: "
                "{'width': {}, 'height': {}, 'x': {}, 'y': {}}.".format(
                    self.__class__.__name__, repr(width), repr(height), repr(x), repr(y)
                )
            ) from err

    # Properties ---------------------------------------------------------------
    @property
    def dict(self) -> dict[str, int]:
        """Access as dictionary `dict[str, int]>`.

        e.g. `{'width': 100, 'height': 100, 'x': 0, 'y': 0}`
        """
        return {
            "width": self._width,
            "height": self._height,
            "x": self._x,
            "y": self._y,
        }

    @property
    def width(self) -> int:
        """Access the width `<int>`."""
        return self._width

    @width.setter
    def width(self, value: int | None) -> None:
        # Ignore None
        if value is None:
            return None  # exit
        # Set value
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
        """Access the height `<int>`."""
        return self._height

    @height.setter
    def height(self, value: int | None) -> None:
        # Ignore None
        if value is None:
            return None  # exit
        # Set value
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
        """Access the x-coordinate `<int>`."""
        return self._x

    @x.setter
    def x(self, value: int | None) -> None:
        # Ignore None
        if value is None:
            return None  # exit
        # Set value
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
        """Access the y-coordinate `<int>`."""
        return self._y

    @y.setter
    def y(self, value: int | None) -> None:
        # Ignore None
        if value is None:
            return None  # exit
        # Set value
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
        """Access the coordinate of top `<int>`.
        Equivalent to property `y`.
        """
        return self._y

    @property
    def bottom(self) -> int:
        """Access the coordinate of bottom `<int>`.
        Equivalent to property `y + height`.
        """
        return self._y + self._height

    @property
    def left(self) -> int:
        """Access the coordinate of left `<int>`.
        Equivalent to property `x`.
        """
        return self._x

    @property
    def right(self) -> int:
        """Access the coordinate of right `<int>`.
        Equivalent to property `x + width`.
        """
        return self._x + self._width

    @property
    def center_x(self) -> int:
        """Access the x-coordinate of the center `<int>`."""
        return self._x + self._width // 2

    @property
    def center_y(self) -> int:
        """Access the y-coordinate of the center `<int>`."""
        return self._y + self._height // 2

    # Special methods ----------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (width=%s, height=%s, x=%s, y=%s)>" % (
            self.__class__.__name__,
            self._width,
            self._height,
            self._x,
            self._y,
        )

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __bool__(self) -> bool:
        return True

    def copy(self) -> Rectangle:
        """Copy the ractangle object."""
        return Rectangle(self._width, self._height, self._x, self._y)


# Utils: custom dictionary ------------------------------------------------------------------------
class CustomDict:
    """A custom dictionary."""

    def __init__(self, **kwargs: Any) -> None:
        """A custom dictionary.

        :param kwargs: `<dict>` The dictionary to be initialized.
        """
        self._dict: dict[str, Any] = kwargs

    # Properties ---------------------------------------------------------------
    @property
    def dict(self) -> dict[str, Any]:
        """Access the dictionary `dict[str, Any]>`."""
        return self._dict.copy()

    # Access -------------------------------------------------------------------
    def keys(self) -> KeysView[str]:
        return self._dict.keys()

    def values(self) -> ValuesView[Any]:
        return self._dict.values()

    def items(self) -> ItemsView[str, Any]:
        return self._dict.items()

    def get(self, key: str, default: Any = None) -> Any:
        return self._dict.get(key, default)

    # Special methods ----------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (dict=%s)>" % (self.__class__.__name__, self._dict)

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __len__(self) -> int:
        return self._dict.__len__()

    def __iter__(self) -> Iterator[str]:
        return self._dict.__iter__()

    def __setitem__(self, key: str, value: Any) -> None:
        self._dict[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._dict[key]

    def __contains__(self, key: str) -> bool:
        return self._dict.__contains__(key)

    def __del__(self):
        self._dict = None


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
    "Mouse buttons."

    LEFT = 0
    MIDDLE = 1
    RIGHT = 2
    BACK = 3
    FORWARD = 4


def process_keys(*keys: str | KeyboardKeys | Any) -> list[str]:
    """Process the input keys to comply with the W3C spec `<list[str]>`."""
    lst = []
    for key in keys:
        if isinstance(key, KeyboardKeys):
            lst.append(key)
        else:
            if not isinstance(key, str):
                key = str(key)
            for i in key:
                lst.append(i)
    return lst


# Utils: file -------------------------------------------------------------------------------------
def is_path_dir(path: str | Any) -> bool:
    """Check if a path exists and is a directory `<bool>`."""
    try:
        return isdir(path)
    except Exception:
        return False


def is_path_file(path: str | Any) -> bool:
    """Check if a path exists and is a file `<bool>`."""
    try:
        return isfile(path)
    except Exception:
        return False


def is_file_dir_exists(file: str | Any) -> bool:
    """Check if the file's directory exists `<bool>`."""
    try:
        return isdir(dirname(file))
    except Exception:
        return False


def validate_dir(path: str | Any) -> str:
    """Validate a directory and return the absolute path `<str>`."""
    try:
        path = expanduser(path)
    except Exception as err:
        raise errors.AseleniumInvalidPathError(
            "Directory {} {} is not valid.".format(repr(path), type(path))
        ) from err
    if not is_path_dir(path):
        raise errors.AseleniumDirectoryNotFoundError(
            "Directory '{}' not exists.".format(path)
        )
    return path


def validate_file(path: str | Any) -> str:
    """Validate a file and return the absolute path `<str>`."""
    try:
        path = expanduser(path)
    except Exception as err:
        raise errors.AseleniumInvalidPathError(
            "File path {} {} is not valid.".format(repr(path), type(path))
        ) from err
    if not is_path_file(path):
        raise errors.AseleniumFileNotFoundError("File '{}' not exists.".format(path))
    return path


def validate_save_file_path(path: str | Any, file_ext: str) -> str:
    """Validates a file path and ensures that the directory exists."""
    try:
        path = expanduser(path)
    except Exception as err:
        raise errors.AseleniumInvalidPathError(
            "File path {} {} is not valid.".format(repr(path), type(path))
        ) from err
    if not is_file_dir_exists(path):
        raise errors.AseleniumDirectoryNotFoundError(
            "File directory '{}' does not exist.".format(path)
        )
    if not path.endswith(file_ext):
        path += file_ext
    return path


# Utils: dict -------------------------------------------------------------------------------------
def prettify_dict(dic: dict, lead: str = "  ") -> str:
    """Stringify a dictionary in a pretty format.

    :param dic: `<dict>` The dictionary to be stringified.
    :param lead: `<str>` The leading spaces for each line. Defaults to `'  '` (double space).
    :returns `<str>`: The prettified dictionary as a string.
    """

    def prettify(dic: dict, indent: int) -> list:
        reps = []
        for key, val in dic.items():
            if isinstance(val, dict):
                if val:
                    reps.append(lead * indent + "%s: {" % repr(key))
                    reps += prettify(val, indent + 1)
                    reps.append(lead * indent + "}")
                else:
                    reps.append(lead * indent + "%s: {}" % repr(key))
            else:
                reps.append(lead * indent + "%s: %s" % (repr(key), repr(val)))
        return reps

    return "{\n%s\n}" % "\n".join(prettify(dic, 1))


# Utils: plist ------------------------------------------------------------------------------------
def load_plist_file(plist_file: str) -> dict:
    """Load a local plist file `<dict>`."""
    with open(plist_file, "rb") as file:
        return load(file)


# Utils: json -------------------------------------------------------------------------------------
def load_json_file(json_file: str) -> dict:
    """Load a local json file `<dict>`."""
    with open(json_file, "r") as file:
        return loads(file.read())
