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

# /usr/bin/python
# -*- coding: UTF-8 -*-
# fmt: off
# Common
from aselenium.actions import Actions
from aselenium.alert import Alert
from aselenium.connection import Connection
from aselenium.element import Element, ElementRect
from aselenium.options import BaseOptions, ChromiumBaseOptions, Timeouts, Proxy
from aselenium.service import BaseService, ChromiumBaseService
from aselenium.session import (
    Cookie, DevToolsCMD, JavaScript, Network, Permission, Viewport, Window, 
    WindowRect, Session, SessionContext, ChromiumBaseSession, ChromiumBaseSessionContext)
from aselenium.settings import DefaultTimeouts, DefaultNetworkConditions
from aselenium.shadow import Shadow
from aselenium.utils import KeyboardKeys, MouseButtons
from aselenium.webdriver import WebDriver, ChromiumBaseWebDriver

# Browser
from aselenium.edge import Edge, EdgeOptions, EdgeService, EdgeSession
from aselenium.chrome import Chrome, ChromeOptions, ChromeService, ChromeSession
from aselenium.chromium import Chromium, ChromiumOptions, ChromiumService, ChromiumSession

# Errors
from aselenium.errors import (
    # . base
    AseleniumError,
    # . timeout
    AseleniumTimeout, WebDriverTimeoutError,
    # . options
    OptionsError, InvalidOptionsError, InvalidCapabilitiesError, 
    InvalidOptionsProxyError, InvalidOptionsArgumentError, InvalidOptionsExtensionError,
    # . service
    ServiceError, ServiceExecutableNotFoundError, ServiceStartError, ServiceStopError, 
    ServiceSocketError, ServiceSocketOSError, ServiceProcessError, ServiceProcessOSError, 
    ServiceProcessTimeoutError,
    # . webdriver
    WebDriverError, NotFoundError, InternetDisconnectedError, InvalidValueError, 
    InvalidArgumentError, InvalidMethodError, InvalidRectValueError, InvalidResponseError, 
    UnknownMethodError, SessionError, SessionShutdownError, SessionClientError, 
    InvalidSessionError, InvalidSessionIdError, SessionDataError, SessionTimeoutError, 
    WindowError, WindowNotFountError, InvalidCookieError, InvalidCookieDomainError, 
    UnableToSetInvalidCookieError, CookieNotFoundError, InvalidScriptError, ScriptNotFoundError, 
    ScriptTimeoutError, InvalidFrameError, FrameNotFoundError, InvalidElementError, 
    InvalidElementStateError, ElementNotVisibleError, ElementNotInteractableError, 
    ElementNotSelectableError, ElementClickInterceptedError, ElementNotFoundError, 
    ElementStaleReferenceError, ElementCoordinatesError, InvalidShadowRootError, 
    ShadowRootNotFoundError, InvalidSelectorError, InvalidXPathSelectorError, 
    InvalidNetworkConditionsError, NetworkConditionsNotFoundError, InvalidFileError, 
    FileNotExistsError, InvalidPermissionError, InvalidPermissionNameError, 
    InvalidPermissionStateError, AlertError, UnexpectedAlertFoundError, AlertNotFoundError, 
    ImeError, ImeNotAvailableError, ImeActivationFailedError, CastingError, CastSinkNotFoundError, 
    DevToolsCMDError, DevToolsCMDNotFoundError, ScreenshotError, MoveTargetOutOfBoundsError, 
    InsecureCertificateError, InvalidCoordinatesError, UnknownError, UnknownCommandError,
)

__all__ = [
    # Common
    "Actions", "Alert", "Connection", "Element", "ElementRect", "BaseOptions", 
    "ChromiumBaseOptions", "Timeouts", "Proxy", "BaseService", "ChromiumBaseService", 
    "Cookie", "DevToolsCMD", "JavaScript", "Network", "Permission", "Viewport", 
    "Window", "WindowRect", "Session", "SessionContext", "ChromiumBaseSession", 
    "ChromiumBaseSessionContext", "DefaultTimeouts", "DefaultNetworkConditions", 
    "Shadow", "KeyboardKeys", "MouseButtons", "WebDriver", "ChromiumBaseWebDriver",
    # Browser
    "Edge", "EdgeOptions", "EdgeService", "EdgeSession", "Chrome", "ChromeOptions", 
    "ChromeService", "ChromeSession", "Chromium", "ChromiumOptions", "ChromiumService", 
    "ChromiumSession",
    # Errors
    "AseleniumError", "AseleniumTimeout", "WebDriverTimeoutError", "OptionsError", 
    "InvalidOptionsError", "InvalidCapabilitiesError", "InvalidOptionsProxyError", 
    "InvalidOptionsArgumentError", "InvalidOptionsExtensionError", "ServiceError", 
    "ServiceExecutableNotFoundError", "ServiceStartError", "ServiceStopError", 
    "ServiceSocketError", "ServiceSocketOSError", "ServiceProcessError", 
    "ServiceProcessOSError", "ServiceProcessTimeoutError", "WebDriverError", 
    "NotFoundError", "InternetDisconnectedError", "InvalidValueError", 
    "InvalidArgumentError", "InvalidMethodError", "InvalidRectValueError", 
    "InvalidResponseError", "UnknownMethodError", "SessionError", 
    "SessionShutdownError", "SessionClientError", "InvalidSessionError", 
    "InvalidSessionIdError", "SessionDataError", "SessionTimeoutError", "WindowError", 
    "WindowNotFountError", "InvalidCookieError", "InvalidCookieDomainError", 
    "UnableToSetInvalidCookieError", "CookieNotFoundError", "InvalidScriptError", 
    "ScriptNotFoundError", "ScriptTimeoutError", "InvalidFrameError", "FrameNotFoundError", 
    "InvalidElementError", "InvalidElementStateError", "ElementNotVisibleError", 
    "ElementNotInteractableError", "ElementNotSelectableError", "ElementClickInterceptedError", 
    "ElementNotFoundError", "ElementStaleReferenceError", "ElementCoordinatesError", 
    "InvalidShadowRootError", "ShadowRootNotFoundError", "InvalidSelectorError", 
    "InvalidXPathSelectorError", "InvalidNetworkConditionsError", "NetworkConditionsNotFoundError", 
    "InvalidFileError", "FileNotExistsError", "InvalidPermissionError", "InvalidPermissionNameError", 
    "InvalidPermissionStateError", "AlertError", "UnexpectedAlertFoundError", "AlertNotFoundError", 
    "ImeError", "ImeNotAvailableError", "ImeActivationFailedError", "CastingError", 
    "CastSinkNotFoundError", "DevToolsCMDError", "DevToolsCMDNotFoundError", "ScreenshotError", 
    "MoveTargetOutOfBoundsError", "InsecureCertificateError", "InvalidCoordinatesError", 
    "UnknownError", "UnknownCommandError",
]

(
    # Common
    Actions, Alert, Connection, Element, ElementRect, BaseOptions, 
    ChromiumBaseOptions, Timeouts, Proxy, BaseService, ChromiumBaseService, 
    Cookie, DevToolsCMD, JavaScript, Network, Permission, Viewport, Window, 
    WindowRect, Session, SessionContext, ChromiumBaseSession, 
    ChromiumBaseSessionContext, DefaultTimeouts, DefaultNetworkConditions, 
    Shadow, KeyboardKeys, MouseButtons, WebDriver, ChromiumBaseWebDriver,
    # Browser
    Edge, EdgeOptions, EdgeService, EdgeSession, 
    Chrome, ChromeOptions, ChromeService, ChromeSession, 
    Chromium, ChromiumOptions, ChromiumService, ChromiumSession,
)  # pyflakes
# fmt: on
