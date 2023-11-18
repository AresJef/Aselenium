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
from typing import Any, Type, Callable
from aselenium.element import Element, ELEMENT_KEY
from aselenium.shadow import Shadow, SHADOWROOT_KEY

__all__ = [
    "wrap_value",
    "warp_list",
    "warp_tuple",
    "warp_dict",
    "warp_element",
    "warp_shadow",
    "through",
]


def wrap_value(value: Any) -> list[Any] | dict[str, Any] | Any:
    """Wrap value `<Any>` to webdriver protocol `<list/dict>`."""
    return WARP_MAPPER.get(type(value), through)(value)


def warp_list(value: list[Any]) -> list[Any]:
    """Wrap value `<list>` to webdriver protocol `<list>`."""
    return [wrap_value(v) for v in value]


def warp_tuple(value: tuple[Any]) -> tuple[Any]:
    """Wrap value `<tuple>` to webdriver protocol `<list>`."""
    return [wrap_value(v) for v in value]


def warp_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Wrap value `<dict>` to webdriver protocol `<dict>`."""
    return {k: wrap_value(v) for k, v in value.items()}


def warp_element(value: Element) -> dict[str, str]:
    """Wrap value `<Element>` to webdriver protocol `<dict>`."""
    return {ELEMENT_KEY: value.id}


def warp_shadow(value: Shadow) -> dict[str, str]:
    """Wrap value `<Shadow>` to webdriver protocol `<dict>`."""
    return {SHADOWROOT_KEY: value.id}


def through(value: Any) -> Any:
    """Pass through value `<Any>`."""
    return value


WARP_MAPPER: dict[Type, Callable] = {
    list: warp_list,
    tuple: warp_tuple,
    dict: warp_dict,
    Element: warp_element,
    Shadow: warp_shadow,
}
