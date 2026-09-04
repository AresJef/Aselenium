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
"""Aselenium utils implementation and supporting types."""

from __future__ import annotations

from collections.abc import ItemsView, Iterator, KeysView, ValuesView
from math import ceil, floor
from os import PathLike, fspath
from os.path import dirname, expanduser, isdir, isfile
from pathlib import Path
from platform import system
from plistlib import load
from typing import (
    Any,
    TypeVar,
)

from orjson import loads

from aselenium import errors

__all__ = ["KeyboardKeys", "MouseButtons"]
R = TypeVar("R", bound="Rectangle")


# Class: rectangle --------------------------------------------------------------------------------
class Rectangle:
    """Represent the size and relative position of a rectangle object."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            width: The width of the rectangle object.
            height: The height of the rectangle object.
            x: The x-coordinate of the rectangle object.
            y: The y-coordinate of the rectangle object.
        """
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
        """Return as dictionary.

        e.g. `{'width': 100, 'height': 100, 'x': 0, 'y': 0}`

        Returns:
            As dictionary.
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
    def width(self, value: int | None) -> None:
        # Ignore None
        """Set the width.

        Args:
            value: New width value. None is handled according to the property's reset/ignore semantics.
        """
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
        """Return the height.

        Returns:
            The height.
        """
        return self._height

    @height.setter
    def height(self, value: int | None) -> None:
        # Ignore None
        """Set the height.

        Args:
            value: New height value. None is handled according to the property's reset/ignore semantics.
        """
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
        """Return the x-coordinate.

        Returns:
            The x-coordinate.
        """
        return self._x

    @x.setter
    def x(self, value: int | None) -> None:
        # Ignore None
        """Set the x.

        Args:
            value: New x value. None is handled according to the property's reset/ignore semantics.
        """
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
        """Return the y-coordinate.

        Returns:
            The y-coordinate.
        """
        return self._y

    @y.setter
    def y(self, value: int | None) -> None:
        # Ignore None
        """Set the y.

        Args:
            value: New y value. None is handled according to the property's reset/ignore semantics.
        """
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
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

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
    """A custom dictionary."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the instance with the supplied configuration.

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
            default: Default used by this operation.

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
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

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
            key: Lookup key used by the current operation.
            value: Value to inspect, normalize, or assign as described above.
        """
        self._dict[key] = value

    def __getitem__(self, key: str) -> Any:
        """Return the item associated with the supplied index or key.

        Args:
            key: Lookup key used by the current operation.

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


# Utils: file -------------------------------------------------------------------------------------
def is_path_dir(path: str | Any) -> bool:
    """Check if a path exists and is a directory.

    Args:
        path: Filesystem path to inspect or operate on.

    Returns:
        True if a path exists and is a directory; otherwise False.
    """
    try:
        return isdir(path)
    except Exception:
        return False


def is_path_file(path: str | Any) -> bool:
    """Check if a path exists and is a file.

    Args:
        path: Filesystem path to inspect or operate on.

    Returns:
        True if a path exists and is a file; otherwise False.
    """
    try:
        return isfile(path)
    except Exception:
        return False


def is_file_dir_exists(file: str | Any) -> bool:
    """Check if the file's directory exists.

    Args:
        file: File used by this operation.

    Returns:
        True if the file's directory exists; otherwise False.
    """
    try:
        return isdir(dirname(file))
    except Exception:
        return False


def _absolute_path(path: str | PathLike[str]) -> str:
    """Expand a nonempty text path without changing symlink-sensitive traversal.

    Args:
        path: Nonempty path string or string-valued filesystem-path object.

    Returns:
        An absolute string with user-home expansion applied. Symbolic links are
        not resolved and parent components are preserved.

    Raises:
        errors.AseleniumInvalidPathError: The path is empty, contains a null
            character, is not string-valued, or cannot be made absolute.
    """
    try:
        value = fspath(path)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("Expected a nonempty text path without null characters")
        return str(Path(expanduser(value)).absolute())
    except Exception as err:
        raise errors.AseleniumInvalidPathError(
            "Filesystem path {} {} is not valid.".format(repr(path), type(path))
        ) from err


def validate_dir(path: str | PathLike[str]) -> str:
    """Validate an existing directory and return its absolute path.

    Args:
        path: Nonempty directory path string or string-valued pathlike object.
            Relative paths are anchored to the current working directory and
            leading user-home markers are expanded.

    Returns:
        Absolute directory path, preserving symbolic-link names and parent
        components rather than resolving or normalizing their traversal.

    Raises:
        errors.AseleniumInvalidPathError: The input is not a nonempty text path.
        errors.AseleniumDirectoryNotFoundError: The path does not identify an
            existing directory. Symbolic links to existing directories are valid.

    Example:
        >>> from pathlib import Path
        >>> Path(validate_dir(".")).is_absolute()
        True
    """
    path = _absolute_path(path)
    if not is_path_dir(path):
        raise errors.AseleniumDirectoryNotFoundError(
            "Directory '{}' does not exist.".format(path)
        )
    return path


def validate_file(path: str | PathLike[str]) -> str:
    """Validate an existing regular file and return its absolute path.

    Args:
        path: Nonempty file path string or string-valued pathlike object.
            Relative paths are anchored to the current working directory and
            leading user-home markers are expanded.

    Returns:
        Absolute file path, preserving symbolic-link names and parent components
        rather than resolving or normalizing their traversal.

    Raises:
        errors.AseleniumInvalidPathError: The input is not a nonempty text path.
        errors.AseleniumFileNotFoundError: The path does not identify an existing
            regular file. Symbolic links to existing regular files are valid.
    """
    path = _absolute_path(path)
    if not is_path_file(path):
        raise errors.AseleniumFileNotFoundError(
            "File '{}' does not exist.".format(path)
        )
    return path


def validate_save_file_path(path: str | PathLike[str], file_ext: str) -> str:
    """Validate a file destination and append its required suffix when absent.

    Args:
        path: Nonempty file path string or string-valued pathlike object. Relative
            paths are made absolute and leading user-home markers are expanded.
            Whitespace in a filename is preserved rather than stripped.
        file_ext: Required case-sensitive suffix, such as ".png" or ".pdf".

    Returns:
        Absolute destination with the suffix appended if necessary. The parent
        directory must already exist; this function creates no files or folders.
        Symbolic-link names and parent traversal components are preserved.

    Raises:
        errors.AseleniumInvalidPathError: The input is not a nonempty text path,
            or the supplied or suffixed destination names an existing directory.
        errors.AseleniumDirectoryNotFoundError: The destination's parent directory
            does not exist.

    Example:
        >>> from pathlib import Path
        >>> destination = validate_save_file_path("capture", ".png")
        >>> Path(destination).is_absolute() and destination.endswith("capture.png")
        True
    """
    path = _absolute_path(path)
    if is_path_dir(path):
        raise errors.AseleniumInvalidPathError(
            "Output path '{}' identifies a directory, not a file.".format(path)
        )
    if not is_file_dir_exists(path):
        raise errors.AseleniumDirectoryNotFoundError(
            "File directory '{}' does not exist.".format(path)
        )
    if not path.endswith(file_ext):
        path += file_ext
    if is_path_dir(path):
        raise errors.AseleniumInvalidPathError(
            "Output path '{}' identifies a directory, not a file.".format(path)
        )
    return path


# Utils: dict -------------------------------------------------------------------------------------
def prettify_dict(dic: dict[str, Any], lead: str = "  ") -> str:
    """Stringify a dictionary in a pretty format.

    Args:
        dic: The dictionary to be stringified.
        lead: The leading spaces for each line. Defaults to `'  '` (double space).

    Returns:
        The prettified dictionary as a string.
    """

    def prettify(dic: dict[str, Any], indent: int) -> list[Any]:
        """Format the supplied diagnostic text for display.

        Args:
            dic: Dic used by this operation.
            indent: Indent used by this operation.

        Returns:
            The diagnostic value formatted as indented JSON where possible.
        """
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
def load_plist_file(plist_file: str) -> dict[str, Any]:
    """Load a local plist file.

    Args:
        plist_file: Plist file used by this operation.

    Returns:
        A local plist file.
    """
    with open(plist_file, "rb") as file:
        return load(file)


# Utils: json -------------------------------------------------------------------------------------
def load_json_file(json_file: str) -> dict[str, Any]:
    """Load a local json file.

    Args:
        json_file: Json file used by this operation.

    Returns:
        A local json file.
    """
    with open(json_file, "r", encoding="utf-8") as file:
        return loads(file.read())
