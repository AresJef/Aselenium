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
# Common ----------------------------------------------------------------------------------------------------
"""Public exports for the aselenium package."""

from aselenium.actions import Actions
from aselenium.alert import Alert
from aselenium.chrome import Chrome, ChromeOptions, ChromeService, ChromeSession
from aselenium.chromium import (
    Chromium,
    ChromiumOptions,
    ChromiumService,
    ChromiumSession,
)
from aselenium.connection import Connection
from aselenium.edge import Edge, EdgeOptions, EdgeService, EdgeSession
from aselenium.element import Element, ElementRect
from aselenium.errors import (
    AlertError,
    AlertNotFoundError,
    AseleniumError,
    AseleniumFileNotFoundError,
    AseleniumInvalidValueError,
    AseleniumOSError,
    AseleniumTimeout,
    BrowserBinaryNotDetectedError,
    BrowserDownloadFailedError,
    BrowserPermissionError,
    CastingError,
    CastSinkNotFoundError,
    ChangeWindowStateError,
    ConnectionClosedError,
    CookieError,
    CookieNotFoundError,
    DevToolsCMDError,
    DevToolsCMDNotFoundError,
    DriverDownloadFailedError,
    DriverExecutableNotDetectedError,
    DriverInstallationError,
    DriverManagerError,
    DriverManagerTimeoutError,
    DriverRequestFailedError,
    DriverRequestRateLimitError,
    DriverRequestTimeoutError,
    ElementClickInterceptedError,
    ElementError,
    ElementNotFoundError,
    ElementNotInteractableError,
    ElementStaleReferenceError,
    FileDownloadTimeoutError,
    FrameError,
    FrameNotFoundError,
    IncompatibleWebdriverError,
    InsecureCertificateError,
    InternetDisconnectedError,
    InvalidArgumentError,
    InvalidBrowserVersionError,
    InvalidCookieDomainError,
    InvalidCoordinatesError,
    InvalidDownloadFileError,
    InvalidDriverVersionError,
    InvalidElementStateError,
    InvalidExtensionError,
    InvalidJavaScriptError,
    InvalidMethodError,
    InvalidOptionsError,
    InvalidPermissionNameError,
    InvalidPermissionStateError,
    InvalidProfileError,
    InvalidProxyError,
    InvalidRectValueError,
    InvalidResponseError,
    InvalidSelectorError,
    InvalidSessionError,
    InvalidValueError,
    InvalidVersionError,
    InvalidXPathSelectorError,
    JavaScriptError,
    JavaScriptNotFoundError,
    JavaScriptTimeoutError,
    MoveTargetOutOfBoundsError,
    NetworkConditionsError,
    NetworkConditionsNotFoundError,
    OptionsError,
    OptionsNotSetError,
    PlatformError,
    ScreenshotError,
    SelectorError,
    ServiceError,
    ServiceExecutableNotFoundError,
    ServiceProcessError,
    ServiceSocketError,
    ServiceStartError,
    ServiceStopError,
    ServiceTimeoutError,
    SessionClientError,
    SessionDataError,
    SessionError,
    SessionQuitError,
    SessionShutdownError,
    SessionTimeoutError,
    ShadowRootError,
    ShadowRootNotFoundError,
    UnableToSetCookieError,
    UnexpectedAlertFoundError,
    UnknownCommandError,
    UnknownError,
    UnknownMethodError,
    UnsupportedPlatformError,
    WebDriverError,
    WebdriverNotFoundError,
    WebDriverTimeoutError,
    WindowError,
    WindowNotFountError,
)
from aselenium.firefox import (
    Firefox,
    FirefoxOptions,
    FirefoxProfile,
    FirefoxService,
    FirefoxSession,
)
from aselenium.manager import (
    ChromeDriverManager,
    ChromiumDriverManager,
    ChromiumVersion,
    EdgeDriverManager,
    FirefoxDriverManager,
    FirefoxVersion,
    GeckoVersion,
    SafariDriverManager,
    SafariVersion,
)
from aselenium.options import ChromiumProfile, Proxy, Timeouts
from aselenium.safari import Safari, SafariOptions, SafariService, SafariSession
from aselenium.session import (
    Cookie,
    DevToolsCMD,
    JavaScript,
    Network,
    Permission,
    Session,
    Viewport,
    Window,
    WindowRect,
)
from aselenium.shadow import Shadow
from aselenium.utils import KeyboardKeys, MouseButtons
from aselenium.webdriver import WebDriver

# Exceptions ------------------------------------------------------------------------------------------------
# fmt: on
# . base
# . platform
# . driver manager
# . options
# . service
# . webdriver

# Gecko Based -----------------------------------------------------------------------------------------------
# . Firefox

# . Chrome
# . Chromium
# . Edge
# Safari ----------------------------------------------------------------------------------------------------

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
    "WebDriverError", "WebDriverTimeoutError", "WebdriverNotFoundError", "ConnectionClosedError", "InternetDisconnectedError",
    "InvalidValueError", "InvalidArgumentError", "InvalidMethodError", "InvalidRectValueError",
    "InvalidResponseError", "InvalidExtensionError", "UnknownMethodError", "SessionError",
    "SessionClientError", "InvalidSessionError", "IncompatibleWebdriverError", "SessionDataError",
    "SessionTimeoutError", "SessionShutdownError", "SessionQuitError", "WindowError", "ChangeWindowStateError",
    "WindowNotFountError", "CookieError", "UnableToSetCookieError", "InvalidCookieDomainError",
    "CookieNotFoundError", "JavaScriptError", "InvalidJavaScriptError", "JavaScriptNotFoundError",
    "JavaScriptTimeoutError", "ElementError", "InvalidElementStateError",
    "ElementNotInteractableError", "ElementClickInterceptedError",
    "ElementNotFoundError", "ElementStaleReferenceError", "FrameError",
    "FrameNotFoundError", "ShadowRootError", "ShadowRootNotFoundError", "SelectorError",
    "InvalidSelectorError", "InvalidXPathSelectorError", "NetworkConditionsError",
    "NetworkConditionsNotFoundError", "BrowserPermissionError", "InvalidPermissionNameError",
    "InvalidPermissionStateError", "AlertError", "UnexpectedAlertFoundError", "AlertNotFoundError",
    "CastingError",
    "CastSinkNotFoundError", "DevToolsCMDError", "DevToolsCMDNotFoundError", "ScreenshotError",
    "MoveTargetOutOfBoundsError", "InsecureCertificateError", "InvalidCoordinatesError",
    "UnknownError", "UnknownCommandError",
]
# fmt: on
