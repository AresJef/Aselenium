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

"""Convert nested Python values and browser handles to W3C command parameters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aselenium.element import ELEMENT_KEY, Element
from aselenium.shadow import SHADOWROOT_KEY, Shadow


def wrap_value(value: Any) -> Any:
    """Recursively encode containers and browser handles as WebDriver values.

    Args:
        value: A list, tuple, dictionary, Element, Shadow, or scalar value.
            Subclasses of these containers and handles are also supported.

    Returns:
        Lists and dictionaries with nested handles encoded by their W3C IDs.
        Tuples become lists. Other values pass through unchanged; serialization
        of unsupported objects may subsequently fail in the transport layer.

    Example:
        >>> payload = wrap_value({"target": element, "arguments": (1, 2)})
    """
    wrapper = WARP_MAPPER.get(type(value))
    if wrapper is not None:
        return wrapper(value)
    for value_type, wrapper in WARP_MAPPER.items():
        if isinstance(value, value_type):
            return wrapper(value)
    return value


def warp_list(value: list[Any]) -> list[Any]:
    """Encode each item in a list without mutating the input.

    Args:
        value: List containing command arguments or nested containers.

    Returns:
        A new list of recursively encoded values.
    """
    return [wrap_value(v) for v in value]


def warp_tuple(value: tuple[Any, ...]) -> list[Any]:
    """Convert a tuple of command arguments to an encoded JSON-compatible list.

    Args:
        value: Positional command arguments to encode in their original order.

    Returns:
        A new list of recursively encoded values.
    """
    return [wrap_value(v) for v in value]


def warp_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Encode dictionary values while preserving their keys.

    Args:
        value: String-keyed command data containing scalars or nested values.

    Returns:
        A new dictionary with the same keys and recursively encoded values.
    """
    return {k: wrap_value(v) for k, v in value.items()}


def warp_element(value: Element) -> dict[str, str]:
    """Encode an element handle as a W3C element reference.

    Args:
        value: Element handle belonging to the target browser session.

    Returns:
        A single-entry mapping from the W3C element key to the element ID.
    """
    return {ELEMENT_KEY: value.id}


def warp_shadow(value: Shadow) -> dict[str, str]:
    """Encode a shadow-root handle as a W3C shadow reference.

    Args:
        value: Shadow-root handle belonging to the target browser session.

    Returns:
        A single-entry mapping from the W3C shadow key to the shadow-root ID.
    """
    return {SHADOWROOT_KEY: value.id}


WARP_MAPPER: dict[type[Any], Callable[[Any], Any]] = {
    list: warp_list,
    tuple: warp_tuple,
    dict: warp_dict,
    Element: warp_element,
    Shadow: warp_shadow,
}
