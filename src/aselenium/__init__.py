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

# Chromium Based --------------------------------------------------------------------------------------------
# fmt: off
from aselenium.manager import ChromiumVersion
from aselenium.options import ChromiumProfile
# . Chrome
from aselenium.manager import ChromeDriverManager
from aselenium.chrome import Chrome, ChromeOptions, ChromeService, ChromeSession
# . Chromium
from aselenium.manager import ChromiumDriverManager
from aselenium.chromium import Chromium, ChromiumOptions, ChromiumService, ChromiumSession
# . Edge
from aselenium.manager import EdgeDriverManager
from aselenium.edge import Edge, EdgeOptions, EdgeService, EdgeSession

# Gecko Based -----------------------------------------------------------------------------------------------
from aselenium.firefox import FirefoxProfile
from aselenium.manager import FirefoxDriverManager, GeckoVersion, FirefoxVersion
# . Firefox
from aselenium.firefox import Firefox, FirefoxOptions, FirefoxService, FirefoxSession

# Safari ----------------------------------------------------------------------------------------------------
from aselenium.manager import SafariDriverManager, SafariVersion
from aselenium.safari import Safari, SafariOptions, SafariService, SafariSession

# Common ----------------------------------------------------------------------------------------------------
from aselenium.actions import Actions
from aselenium.alert import Alert
from aselenium.connection import Connection
from aselenium.element import Element, ElementRect
from aselenium.options import Proxy, Timeouts
from aselenium.session import Session, Cookie, DevToolsCMD, JavaScript, Network, Permission, Viewport, Window, WindowRect
from aselenium.shadow import Shadow
from aselenium.utils import KeyboardKeys, MouseButtons
from aselenium.webdriver import WebDriver

# Exceptions ------------------------------------------------------------------------------------------------
# fmt: on
# . base
from aselenium.errors import (
    AseleniumError,
    AseleniumTimeout,
    AseleniumFileNotFoundError,
    AseleniumInvalidValueError,
    AseleniumOSError,
)

# . platform
from aselenium.errors import PlatformError, UnsupportedPlatformError

# . driver manager
from aselenium.errors import (
    DriverManagerError,
    DriverManagerTimeoutError,
    DriverInstallationError,
    DriverExecutableNotDetectedError,
    DriverRequestFailedError,
    DriverRequestTimeoutError,
    DriverRequestRateLimitError,
    DriverDownloadFailedError,
    InvalidVersionError,
    InvalidDriverVersionError,
    InvalidBrowserVersionError,
    BrowserBinaryNotDetectedError,
    BrowserDownloadFailedError,
    FileDownloadTimeoutError,
    InvalidDownloadFileError,
)

# . options
from aselenium.errors import (
    OptionsError,
    InvalidOptionsError,
    InvalidProxyError,
    InvalidProfileError,
    OptionsNotSetError,
)

# . service
from aselenium.errors import (
    ServiceError,
    ServiceExecutableNotFoundError,
    ServiceStartError,
    ServiceStopError,
    ServiceSocketError,
    ServiceProcessError,
    ServiceTimeoutError,
)

# . webdriver
from aselenium.errors import (
    WebDriverError,
    WebDriverTimeoutError,
    WebdriverNotFoundError,
    InternetDisconnectedError,
    InvalidValueError,
    InvalidArgumentError,
    InvalidMethodError,
    InvalidRectValueError,
    InvalidResponseError,
    InvalidExtensionError,
    UnknownMethodError,
    SessionError,
    SessionClientError,
    InvalidSessionError,
    IncompatibleWebdriverError,
    SessionDataError,
    SessionTimeoutError,
    SessionShutdownError,
    SessionQuitError,
    WindowError,
    ChangeWindowStateError,
    WindowNotFountError,
    CookieError,
    UnableToSetCookieError,
    InvalidCookieDomainError,
    CookieNotFoundError,
    JavaScriptError,
    InvalidJavaScriptError,
    JavaScriptNotFoundError,
    JavaScriptTimeoutError,
    ElementError,
    InvalidElementStateError,
    ElementNotVisibleError,
    ElementNotInteractableError,
    ElementNotSelectableError,
    ElementClickInterceptedError,
    ElementNotFoundError,
    ElementStaleReferenceError,
    ElementCoordinatesError,
    FrameError,
    FrameNotFoundError,
    ShadowRootError,
    ShadowRootNotFoundError,
    SelectorError,
    InvalidSelectorError,
    InvalidXPathSelectorError,
    NetworkConditionsError,
    NetworkConditionsNotFoundError,
    BrowserPermissionError,
    InvalidPermissionNameError,
    InvalidPermissionStateError,
    AlertError,
    UnexpectedAlertFoundError,
    AlertNotFoundError,
    ImeError,
    ImeNotAvailableError,
    ImeActivationFailedError,
    CastingError,
    CastSinkNotFoundError,
    DevToolsCMDError,
    DevToolsCMDNotFoundError,
    ScreenshotError,
    MoveTargetOutOfBoundsError,
    InsecureCertificateError,
    InvalidCoordinatesError,
    UnknownError,
    UnknownCommandError,
)

# All -------------------------------------------------------------------------------------------------------
# fmt: off
__all__ = [
    # Chromium Based
    "ChromiumVersion", "ChromiumProfile",
    "ChromeDriverManager", "Chrome", "ChromeOptions", "ChromeService", "ChromeSession",
    "ChromiumDriverManager", "Chromium", "ChromiumOptions", "ChromiumService", "ChromiumSession",
    "EdgeDriverManager", "Edge", "EdgeOptions", "EdgeService", "EdgeSession",
    # Gecko Based
    "FirefoxProfile", "FirefoxDriverManager", "GeckoVersion", "FirefoxVersion",
    "Firefox", "FirefoxOptions", "FirefoxService", "FirefoxSession",
    # Safari
    "SafariDriverManager", "SafariVersion", "Safari", "SafariOptions", "SafariService", "SafariSession",
    # Common
    "Actions", "Alert", "Connection", "Element", "ElementRect", "Proxy", "Timeouts", "Session", "Cookie", "DevToolsCMD", 
    "JavaScript", "Network", "Permission", "Viewport", "Window", "WindowRect", "Shadow", "KeyboardKeys", "MouseButtons", "WebDriver",
    # Exceptions
    # . base
    "AseleniumError", "AseleniumTimeout", "AseleniumFileNotFoundError", "AseleniumInvalidValueError", "AseleniumOSError",
    # . platform
    "PlatformError", "UnsupportedPlatformError",
    # . driver manager
    "DriverManagerError", "DriverManagerTimeoutError", "DriverInstallationError", "DriverExecutableNotDetectedError",
    "DriverRequestFailedError", "DriverRequestTimeoutError", "DriverRequestRateLimitError", "DriverDownloadFailedError",
    "InvalidVersionError", "InvalidDriverVersionError", "InvalidBrowserVersionError", "BrowserBinaryNotDetectedError", 
    "BrowserDownloadFailedError", "FileDownloadTimeoutError", "InvalidDownloadFileError", 
    # . options
    "OptionsError", "InvalidOptionsError", "InvalidProxyError", "InvalidProfileError", "OptionsNotSetError",
    # . service
    "ServiceError", "ServiceExecutableNotFoundError", "ServiceStartError", "ServiceStopError",
    "ServiceSocketError", "ServiceProcessError", "ServiceTimeoutError",
    # . webdriver
    "WebDriverError", "WebDriverTimeoutError", "WebdriverNotFoundError", "InternetDisconnectedError",
    "InvalidValueError", "InvalidArgumentError", "InvalidMethodError", "InvalidRectValueError",
    "InvalidResponseError", "InvalidExtensionError", "UnknownMethodError", "SessionError",
    "SessionClientError", "InvalidSessionError", "IncompatibleWebdriverError", "SessionDataError",
    "SessionTimeoutError", "SessionShutdownError", "SessionQuitError", "WindowError", "ChangeWindowStateError",
    "WindowNotFountError", "CookieError", "UnableToSetCookieError", "InvalidCookieDomainError",
    "CookieNotFoundError", "JavaScriptError", "InvalidJavaScriptError", "JavaScriptNotFoundError",
    "JavaScriptTimeoutError", "ElementError", "InvalidElementStateError", "ElementNotVisibleError",
    "ElementNotInteractableError", "ElementNotSelectableError", "ElementClickInterceptedError",
    "ElementNotFoundError", "ElementStaleReferenceError", "ElementCoordinatesError", "FrameError",
    "FrameNotFoundError", "ShadowRootError", "ShadowRootNotFoundError", "SelectorError",
    "InvalidSelectorError", "InvalidXPathSelectorError", "NetworkConditionsError",
    "NetworkConditionsNotFoundError", "BrowserPermissionError", "InvalidPermissionNameError",
    "InvalidPermissionStateError", "AlertError", "UnexpectedAlertFoundError", "AlertNotFoundError",
    "ImeError", "ImeNotAvailableError", "ImeActivationFailedError", "CastingError",
    "CastSinkNotFoundError", "DevToolsCMDError", "DevToolsCMDNotFoundError", "ScreenshotError",
    "MoveTargetOutOfBoundsError", "InsecureCertificateError", "InvalidCoordinatesError",
    "UnknownError", "UnknownCommandError",
]
(
    # Chromium Based
    ChromiumVersion, ChromiumProfile,
    ChromeDriverManager, Chrome, ChromeOptions, ChromeService, ChromeSession,
    ChromiumDriverManager, Chromium, ChromiumOptions, ChromiumService, ChromiumSession,
    EdgeDriverManager, Edge, EdgeOptions, EdgeService, EdgeSession,
    # Gecko Based
    FirefoxProfile, FirefoxDriverManager, GeckoVersion, FirefoxVersion,
    Firefox, FirefoxOptions, FirefoxService, FirefoxSession,
    # Safari
    SafariDriverManager, SafariVersion, Safari, SafariOptions, SafariService, SafariSession,
    # Common
    Actions, Alert, Connection, Element, ElementRect, Proxy, Timeouts, Session, Cookie, DevToolsCMD, 
    JavaScript, Network, Permission, Viewport, Window, WindowRect, Shadow, KeyboardKeys, MouseButtons, WebDriver,
)   # pyflakes
# fmt: on
