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
from aselenium.javascript.is_viewable import SCRIPT as ELEMENT_IS_VIEWABLE
from aselenium.javascript.get_attribute import SCRIPT as GET_ELEMENT_ATTRIBUTE

__all__ = [
    "GET_PAGE_VIEWPORT",
    "GET_PAGE_HEIGHT",
    "GET_PAGE_WIDTH",
    "GET_PERMISSION",
    "PAGE_SCROLL_BY",
    "PAGE_SCROLL_TO",
    "ELEMENT_EXISTS_IN_PAGE",
    "ELEMENT_EXISTS_IN_NODE",
    "FIND_ELEMENT_IN_PAGE",
    "FIND_ELEMENT_IN_NODE",
    "GET_ELEMENT_PROPERTIES",
    "GET_ELEMENT_CSS_PROPERTIES",
    "GET_ELEMENT_ATTRIBUTES",
    "GET_ELEMENT_ATTRIBUTE",
    "ELEMENT_IS_VALID",
    "ELEMENT_IS_VIEWABLE",
    "ELEMENT_IS_VISIBLE",
    "ELEMENT_SCROLL_INTO_VIEW",
    "ELEMENT_SUBMIT_FORM",
]

GET_PAGE_VIEWPORT: str = """
var width = window.innerWidth, height = window.innerHeight,
    x = window.pageXOffset || document.documentElement.scrollLeft,
    y = window.pageYOffset || document.documentElement.scrollTop;
return {width: width, height: height, x: x, y: y};"""
GET_PAGE_HEIGHT: str = """
var body = document.body, html = document.documentElement;
return Math.max(
    body.scrollHeight,
    body.offsetHeight,
    html.clientHeight,
    html.scrollHeight,
    html.offsetHeight
);"""
GET_PAGE_WIDTH: str = """
var body = document.body, html = document.documentElement;
return Math.max(
    body.scrollWidth,
    body.offsetWidth,
    html.clientWidth,
    html.scrollWidth,
    html.offsetWidth
);"""
GET_PERMISSION: str = "return navigator.permissions.query({name: arguments[0]});"
PAGE_SCROLL_BY: str = "window.scrollBy(arguments[0], arguments[1]);"
PAGE_SCROLL_TO: str = "window.scrollTo(arguments[0], arguments[1]);"
ELEMENT_EXISTS_IN_PAGE: dict[str, str] = {
    "css selector": "return !!document.querySelector(arguments[0]);",
    "xpath": "return !!document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;",
}
ELEMENT_EXISTS_IN_NODE: dict[str, str] = {
    "css selector": "return !!arguments[1].querySelector(arguments[0]);",
    "xpath": "return !!document.evaluate(arguments[0], arguments[1], null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;",
}
FIND_ELEMENT_IN_PAGE: dict[str, str] = {
    strategy: script.replace("return !!", "return ")
    for strategy, script in ELEMENT_EXISTS_IN_PAGE.items()
}
FIND_ELEMENT_IN_NODE: dict[str, str] = {
    strategy: script.replace("return !!", "return ")
    for strategy, script in ELEMENT_EXISTS_IN_NODE.items()
}
GET_ELEMENT_PROPERTIES: str = """
var elemt = arguments[0], props = [];
for (var i in elemt) { props.push(i); }
return props;"""
GET_ELEMENT_CSS_PROPERTIES: str = """
var style = window.getComputedStyle(arguments[0]), props = {};
for (var i in style) { if (style.hasOwnProperty(i)) { props[i] = style[i]; } }
return props;"""
GET_ELEMENT_ATTRIBUTES: str = """
var elemt = arguments[0], attrs = {};
for (var i = 0; i < elemt.attributes.length; ++i) {
    attrs[elemt.attributes[i].name] = elemt.attributes[i].value;
}
return attrs;"""
ELEMENT_IS_VALID: str = "return !!arguments[0];"
ELEMENT_IS_VISIBLE: str = """
var rect = arguments[0].getBoundingClientRect();
var isVisible = (rect.top >= 0) && (rect.top <= window.innerHeight);
return isVisible;"""
ELEMENT_SCROLL_INTO_VIEW: str = "arguments[0].scrollIntoView(true);"
ELEMENT_SUBMIT_FORM: str = """
var form = arguments[0];
while (form.nodeName != "FORM" && form.parentNode) { form = form.parentNode; }
if (!form) { throw Error('Unable to find containing form element'); }
if (!form.ownerDocument) { throw Error('Unable to find owning document'); }
var e = form.ownerDocument.createEvent('Event');
e.initEvent('submit', true, true);
if (form.dispatchEvent(e)) { HTMLFormElement.prototype.submit.call(form) }"""
