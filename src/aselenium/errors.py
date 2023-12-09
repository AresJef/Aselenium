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
from typing import Any
from asyncio import TimeoutError
from re import Pattern, compile, IGNORECASE
from orjson import loads
from aiohttp import ClientError


# Base --------------------------------------------------------------------------------------------------
class AseleniumError(Exception):
    """Base class for exceptions in this module."""


class AseleniumTimeout(AseleniumError, TimeoutError):
    """Exception raised for timeout."""


class AseleniumInvalidPathError(AseleniumError, ValueError):
    """Exception raised for invalid path."""


class AseleniumFileNotFoundError(AseleniumInvalidPathError, FileNotFoundError):
    """The file could not be found at the given path."""


class AseleniumDirectoryNotFoundError(AseleniumInvalidPathError, FileNotFoundError):
    """The directory could not be found at the given path."""


class AseleniumInvalidValueError(AseleniumError, ValueError):
    """Base exception class for all invalid value errors."""


class AseleniumOSError(AseleniumError, OSError):
    """Base exception class for all OS errors."""


# Platform ----------------------------------------------------------------------------------------------
class PlatformError(AseleniumError):
    """Base exception class for all platform errors."""


class UnsupportedPlatformError(PlatformError):
    """Exception raised for unsupported platform."""


# Driver Manager ----------------------------------------------------------------------------------------
class DriverManagerError(AseleniumError):
    """Base exception class for all driver manager errors."""


class DriverManagerTimeoutError(DriverManagerError, AseleniumTimeout):
    """Exception raised for driver manager timeout error."""


class DriverInstallationError(DriverManagerError, AseleniumInvalidValueError):
    """Exception raised for driver installation error."""


class DriverExecutableNotDetectedError(DriverManagerError, AseleniumFileNotFoundError):
    """Exception raised for driver executable not found error."""


class DriverRequestFailedError(DriverManagerError):
    """Exception raised for proxy error."""


class DriverRequestTimeoutError(DriverRequestFailedError, DriverManagerTimeoutError):
    """Exception raised for proxy error."""


class DriverRequestRateLimitError(DriverRequestFailedError):
    """Exception raised for rate limit error."""


class DriverDownloadFailedError(DriverRequestFailedError):
    """Exception raised for driver download failed error."""


class InvalidVersionError(DriverManagerError, AseleniumInvalidValueError):
    """Exception raised for invalid driver version."""


class InvalidDriverVersionError(InvalidVersionError):
    """Exception raised for invalid driver version."""


class InvalidBrowserVersionError(InvalidVersionError):
    """Exception raised for invalid browser version."""


class BrowserBinaryNotDetectedError(DriverManagerError, AseleniumFileNotFoundError):
    """Exception raised for browser binary not found error."""


class BrowserDownloadFailedError(DriverDownloadFailedError):
    """Exception raised for browser download failed error."""


class FileDownloadTimeoutError(DriverDownloadFailedError, DriverManagerTimeoutError):
    """Exception raised for driver download timeout error."""


class InvalidDownloadFileError(DriverRequestFailedError, OSError):
    """Exception raised for invalid driver file."""


# Options -----------------------------------------------------------------------------------------------
class OptionsError(AseleniumInvalidValueError):
    """Exception raised for errors in the options module."""


class InvalidOptionsError(OptionsError):
    """Exception raised for invalid options."""


class InvalidProxyError(InvalidOptionsError):
    """Exception raised for invalid proxy."""


class InvalidProfileError(InvalidOptionsError):
    """Exception raised for invalid profile."""


class OptionsNotSetError(InvalidOptionsError, KeyError):
    """Exception raised for options not set."""


# Services ----------------------------------------------------------------------------------------------
class ServiceError(AseleniumError):
    """Exception raised for errors for service."""


class ServiceExecutableNotFoundError(ServiceError, AseleniumFileNotFoundError):
    """Exception raised for service executable not found error."""


class ServiceStartError(ServiceError):
    """Exception raised for errors for starting service."""


class ServiceStopError(ServiceError):
    """Exception raised for errors for stopping service."""


class ServiceSocketError(ServiceError, AseleniumOSError):
    """Exception raised for service socket error."""


class ServiceProcessError(ServiceError, AseleniumOSError):
    """Exception raised for service process error."""


class ServiceTimeoutError(ServiceError, AseleniumTimeout):
    """Exception raised for service timeout error."""


# WebDriver ---------------------------------------------------------------------------------------------
class WebDriverError(AseleniumError):
    """Base webdriver exception."""

    def __init__(
        self,
        msg: str = None,
        screen: str = None,
        stacktrace: list[str] = None,
    ) -> None:
        super().__init__()
        self.msg: str | None = msg
        self.screen: str | None = screen
        self.stacktrace: list[str] | None = stacktrace

    def __str__(self) -> str:
        msg = self.msg
        if self.screen:
            msg += "\nScreenshot: available via screen"
        if self.stacktrace:
            msg += "\nStacktrace:\n%s" % "\n".join(self.stacktrace)
        return msg


class WebDriverTimeoutError(WebDriverError, AseleniumTimeout):
    """Thrown when a webdriver does not complete in enough time."""


class WebdriverNotFoundError(WebDriverError):
    """Exception raised when target not found."""


class InternetDisconnectedError(WebDriverError):
    """Exception raised when internet disconnected."""


# . Inavlid value error
class InvalidValueError(WebDriverError, AseleniumInvalidValueError):
    """Base exception class for all invalid value errors."""


class InvalidArgumentError(InvalidValueError):
    """The arguments passed to a command are either invalid or malformed."""


class InvalidMethodError(InvalidValueError):
    """The requested command matched a known URL but did not match any methods
    for that URL."""


class InvalidRectValueError(InvalidValueError):
    """The arguments passed to a command are either invalid or malformed."""


class InvalidResponseError(InvalidValueError):
    """Exception raised when response is invalid."""


class InvalidExtensionError(InvalidArgumentError, InvalidOptionsError):
    """Exception raised for invalid extensions."""


class UnknownMethodError(InvalidValueError):
    """The requested command matched a known URL but did not match any methods
    for that URL."""


# . Session error
class SessionError(WebDriverError):
    """Base exception class for all session errors."""


class SessionClientError(SessionError, ClientError):
    """Exception raised for session client error."""


class InvalidSessionError(SessionError, WebdriverNotFoundError):
    """Exception raised for invalid session error."""


class IncompatibleWebdriverError(InvalidSessionError):
    """Occurs if the given webdriver is not compatible with the current browser version."""


class SessionDataError(SessionError, UnicodeDecodeError):
    """Exception raised for session data error"""


class SessionTimeoutError(SessionError, AseleniumTimeout):
    """Exception raised for session timeout."""


class SessionShutdownError(SessionError):
    """Exception raised for session stop error."""


class SessionQuitError(SessionShutdownError, ServiceStopError):
    """Exception raised for session quit error."""


# . Window error
class WindowError(WebDriverError):
    """Base exception class for all window errors."""


class ChangeWindowStateError(WindowError):
    """Exception raised when failed to change window state."""


class WindowNotFountError(WindowError, WebdriverNotFoundError):
    """Thrown when window target to be switched doesn't exist."""


# . Cookie error
class CookieError(WebDriverError):
    """Base exception class for all errors relating to cookies."""


class UnableToSetCookieError(CookieError, InvalidArgumentError):
    """Thrown when a driver fails to set a cookie."""


class InvalidCookieDomainError(CookieError, InvalidArgumentError):
    """Thrown when attempting to add a cookie under a different domain than the
    current URL."""


class CookieNotFoundError(CookieError, WebdriverNotFoundError):
    """No cookie matching the given path name was found amongst the associated
    cookies of the current browsing context's active document."""


# . JavaScript error
class JavaScriptError(WebDriverError):
    """Base exception class for all errors relating to JavaScript."""


class InvalidJavaScriptError(JavaScriptError, InvalidArgumentError):
    """Thrown when a javascript error occurs."""


class JavaScriptNotFoundError(InvalidJavaScriptError, WebdriverNotFoundError):
    """Thrown when a javascript file is not found."""


class JavaScriptTimeoutError(InvalidJavaScriptError, WebDriverTimeoutError):
    """Thrown when a script does not complete in enough time."""


# . Element error
class ElementError(WebDriverError):
    """Base exception class for all errors relating to elements."""


class InvalidElementStateError(ElementError):
    """Thrown when a command could not be completed because the element is in
    an invalid state.

    This can be caused by attempting to clear an element that isn't both
    editable and resettable.
    """


class ElementNotVisibleError(InvalidElementStateError):
    """Thrown when an element is present on the DOM, but it is not visible, and
    so is not able to be interacted with.

    Most commonly encountered when trying to click or read text of an
    element that is hidden from view.
    """


class ElementNotInteractableError(InvalidElementStateError):
    """Thrown when an element is present in the DOM but interactions with that
    element will hit another element due to paint order."""


class ElementNotSelectableError(InvalidElementStateError):
    """Thrown when trying to select an unselectable element.

    For example, selecting a 'script' element.
    """


class ElementClickInterceptedError(InvalidElementStateError):
    """The Element Click command could not be completed because the element
    receiving the events is obscuring the element that was requested to be
    clicked."""


class ElementNotFoundError(ElementError, WebdriverNotFoundError):
    """Thrown when element could not be found.

    If you encounter this exception, you may want to check the following:
        * Check your selector used in your find_by...
        * Element may not yet be on the screen at the time of the find operation,
          (webpage is still loading) see selenium.webdriver.support.wait.WebDriverWait()
          for how to write a wait wrapper to wait for an element to appear.
    """


class ElementStaleReferenceError(ElementNotFoundError):
    """Thrown when a reference to an element is now "stale".

    Stale means the element no longer appears on the DOM of the page.

    Possible causes of StaleElementReferenceException include, but not limited to:
        * You are no longer on the same page, or the page may have refreshed since the element
          was located.
        * The element may have been removed and re-added to the screen, since it was located.
          Such as an element being relocated.
          This can happen typically with a javascript framework when values are updated and the
          node is rebuilt.
        * Element may have been inside an iframe or another context which was refreshed.
    """


class ElementCoordinatesError(ElementError, InvalidArgumentError):
    """The element coordinates provided to an interaction's operation are invalid."""


# . Frame error
class FrameError(WebDriverError):
    """Base exception class for all errors relating to invalid frames."""


class FrameNotFoundError(FrameError, WebdriverNotFoundError):
    """Thrown when frame target to be switched doesn't exist."""


# . Shadowroot error
class ShadowRootError(WebDriverError):
    """Base exception class for all errors relating to invalid shadowroot."""


class ShadowRootNotFoundError(ShadowRootError, WebdriverNotFoundError):
    """Thrown when trying to access the shadow root of an element when it does
    not have a shadow root attached."""


# . Selector error
class SelectorError(WebDriverError):
    """Base exception class for all errors relating to invalid selector."""


class InvalidSelectorError(SelectorError, InvalidArgumentError):
    """Thrown when the selector which is used to find an element does not
    return a WebElement.

    Currently this only happens when the selector is an xpath expression
    and it is either syntactically invalid (i.e. it is not a xpath
    expression) or the expression does not select WebElements (e.g.
    "count(//input)").
    """


class InvalidXPathSelectorError(InvalidSelectorError):
    """Thrown when the selector which is used to find an element does not
    return a WebElement.

    Currently this only happens when the selector is an xpath expression
    and it is either syntactically invalid (i.e. it is not a xpath
    expression) or the expression does not select WebElements (e.g.
    "count(//input)").
    """


# . Network conditions error
class NetworkConditionsError(WebDriverError):
    """Base exception class for all errors relating to invalid network conditions."""


class NetworkConditionsNotFoundError(NetworkConditionsError, WebdriverNotFoundError):
    """Thrown when trying to access the network conditions of a session when it does
    not have network conditions attached.
    """


# . Permission error
class BrowserPermissionError(InvalidArgumentError):
    """Base exception class for all errors relating to invalid permission."""


class InvalidPermissionNameError(BrowserPermissionError, InvalidArgumentError):
    """Exception raised when permission name is invalid."""


class InvalidPermissionStateError(BrowserPermissionError, InvalidArgumentError):
    """Exception raised when permission state is invalid."""


# . Alert error
class AlertError(WebDriverError):
    """Base exception class for all alert errors."""


class UnexpectedAlertFoundError(AlertError):
    """Thrown when an unexpected alert has appeared.

    Usually raised when an unexpected modal is blocking the webdriver
    from executing commands.
    """

    def __init__(
        self,
        msg: str = None,
        screen: str = None,
        stacktrace: list[str] = None,
        alert_text: str = None,
    ) -> None:
        super().__init__(msg, screen, stacktrace)
        self.alert_text: str = alert_text

    def __str__(self) -> str:
        return "\nAlert Text: %s%s" % (self.alert_text, super().__str__())


class AlertNotFoundError(AlertError, WebdriverNotFoundError):
    """Thrown when switching to alert that is not present.

    This can be caused by calling an operation on the Alert() class when
    an alert is not yet on the screen.
    """


# . IME error
class ImeError(WebDriverError):
    """Base exception class for all IME errors."""


class ImeNotAvailableError(ImeError):
    """Thrown when IME support is not available.

    This exception is thrown for every IME-related method call if IME
    support is not available on the machine.
    """


class ImeActivationFailedError(ImeError):
    """Thrown when activating an IME engine has failed."""


# . Cast error
class CastingError(WebDriverError):
    """Base exception class for all casting errors."""


class CastSinkNotFoundError(CastingError, WebdriverNotFoundError):
    """Thrown when cast sink is not found."""


# . DevTools command error
class DevToolsCMDError(WebDriverError):
    """Base exception class for all DevTools Protocol errors."""


class DevToolsCMDNotFoundError(DevToolsCMDError, WebdriverNotFoundError):
    """Exception raised for DevTools Protocol not found error."""


# . Other error
class ScreenshotError(WebDriverError):
    """A screen capture was made impossible."""


class MoveTargetOutOfBoundsError(WebDriverError):
    """Thrown when the target provided to the `ActionsChains` move() method is
    invalid, i.e. out of document."""


class InsecureCertificateError(WebDriverError):
    """Navigation caused the user agent to hit a certificate warning, which is
    usually the result of an expired or invalid TLS certificate."""


class InvalidCoordinatesError(WebDriverError):
    """The coordinates provided to an interaction's operation are invalid."""


# . Unknown error
class UnknownError(WebDriverError):
    """Thrown when an unknown error occurs."""


class UnknownCommandError(UnknownError):
    """Thrown when a command does not belong to the current session."""


# Error handling ----------------------------------------------------------------------------------------
class ErrorCode:
    """Error codes defined in the WebDriver wire protocol."""

    SUCCESS = 0
    # "no such element"
    NO_SUCH_ELEMENT = 7
    # "no such frame"
    NO_SUCH_FRAME = 8
    # "no such shadow root"
    NO_SUCH_SHADOW_ROOT = "no such shadow root"
    # "unknown command"
    UNKNOWN_COMMAND = 9
    # "stale element reference"
    STALE_ELEMENT_REFERENCE = 10
    # "element not visible"
    ELEMENT_NOT_VISIBLE = 11
    # "invalid element state"
    INVALID_ELEMENT_STATE = 12
    # "unknown error"
    UNKNOWN_ERROR = 13
    # "element not selectable"
    ELEMENT_IS_NOT_SELECTABLE = 15
    # "javascript error"
    JAVASCRIPT_ERROR = 17
    # "invalid selector"
    XPATH_LOOKUP_ERROR = 19
    # "timeout"
    TIMEOUT = 21
    # "no such window"
    NO_SUCH_WINDOW = 23
    # "invalid cookie domain"
    INVALID_COOKIE_DOMAIN = 24
    # "unable to set cookie"
    UNABLE_TO_SET_COOKIE = 25
    # "unexpected alert open"
    UNEXPECTED_ALERT_OPEN = 26
    # "no such alert"
    NO_ALERT_OPEN = 27
    # "script timeout"
    SCRIPT_TIMEOUT = 28
    # "invalid element coordinates"
    INVALID_ELEMENT_COORDINATES = 29
    # "ime not available"
    IME_NOT_AVAILABLE = 30
    # "ime engine activation failed"
    IME_ENGINE_ACTIVATION_FAILED = 31
    # "invalid selector"
    INVALID_SELECTOR = 32
    # "session not created"
    SESSION_NOT_CREATED = 33
    # "move target out of bounds"
    MOVE_TARGET_OUT_OF_BOUNDS = 34
    # "invalid selector"
    INVALID_XPATH_SELECTOR = 51
    # "invalid selector"
    INVALID_XPATH_SELECTOR_RETURN_TYPER = 52
    # "element not interactable"
    ELEMENT_NOT_INTERACTABLE = 60
    " insecure certificate"
    INSECURE_CERTIFICATE = "insecure certificate"
    # "invalid argument"
    INVALID_ARGUMENT = 61
    # "invalid coordinates"
    INVALID_COORDINATES = "invalid coordinates"
    # "invalid session id"
    INVALID_SESSION_ID = "invalid session id"
    # "no such cookie"
    NO_SUCH_COOKIE = 62
    # "unable to capture screen"
    UNABLE_TO_CAPTURE_SCREEN = 63
    # element click intercepted"
    ELEMENT_CLICK_INTERCEPTED = 64
    # "unknown method exception"
    UNKNOWN_METHOD = "unknown method exception"
    # "unsupported operation"]
    METHOD_NOT_ALLOWED = 405
    # "failed to change window state"
    FAILED_TO_CHANGE_WINDOW_STATE = "failed to change window state"
    # "network conditions must be set before"
    NETWORK_CONDITIONS_NOT_SET = "network conditions must be set before"
    # "unrecognized permission state"
    INVALID_PERMISSION_STATE = "unrecognized permission state"
    # "Invalid PermissionDescriptor name"
    INVALID_PERMISSION_NAME = "Invalid PermissionDescriptor name"
    # "ERR_INTERNET_DISCONNECTED"
    INTERNET_DISCONNECTED = "ERR_INTERNET_DISCONNECTED"
    # "Sink not found"
    SINK_NOT_FOUND = "Sink not found"


WEBDRIVER_ERROR_MAP: dict[int | str, Exception] = {
    7: ElementNotFoundError,
    "no such element": ElementNotFoundError,
    8: FrameNotFoundError,
    "no such frame": FrameNotFoundError,
    9: UnknownCommandError,
    "unknown command": UnknownCommandError,
    10: ElementStaleReferenceError,
    "stale element reference": ElementStaleReferenceError,
    11: ElementNotVisibleError,
    "element not visible": ElementNotVisibleError,
    12: InvalidElementStateError,
    "invalid element state": InvalidElementStateError,
    13: UnknownError,
    "unknown error": UnknownError,
    15: ElementNotSelectableError,
    "element not selectable": ElementNotSelectableError,
    17: InvalidJavaScriptError,
    "javascript error": InvalidJavaScriptError,
    19: InvalidXPathSelectorError,
    "invalid selector": InvalidXPathSelectorError,
    21: WebDriverTimeoutError,
    "timeout": WebDriverTimeoutError,
    23: WindowNotFountError,
    "no such window": WindowNotFountError,
    24: InvalidCookieDomainError,
    "invalid cookie domain": InvalidCookieDomainError,
    25: UnableToSetCookieError,
    "unable to set cookie": UnableToSetCookieError,
    26: UnexpectedAlertFoundError,
    "unexpected alert open": UnexpectedAlertFoundError,
    27: AlertNotFoundError,
    "no such alert": AlertNotFoundError,
    28: JavaScriptTimeoutError,
    "script timeout": JavaScriptTimeoutError,
    29: ElementCoordinatesError,
    "invalid element coordinates": ElementCoordinatesError,
    30: ImeNotAvailableError,
    "ime not available": ImeNotAvailableError,
    31: ImeActivationFailedError,
    "ime engine activation failed": ImeActivationFailedError,
    32: InvalidSelectorError,
    "invalid selector": InvalidSelectorError,
    33: InvalidSessionError,
    "session not created": InvalidSessionError,
    "invalid session id": InvalidSessionError,
    34: MoveTargetOutOfBoundsError,
    "move target out of bounds": MoveTargetOutOfBoundsError,
    51: InvalidXPathSelectorError,
    52: InvalidXPathSelectorError,
    60: ElementNotInteractableError,
    "element not interactable": ElementNotInteractableError,
    61: InvalidArgumentError,
    "invalid argument": InvalidArgumentError,
    62: CookieNotFoundError,
    "no such cookie": CookieNotFoundError,
    63: ScreenshotError,
    "unable to capture screen": ScreenshotError,
    64: ElementClickInterceptedError,
    "element click intercepted": ElementClickInterceptedError,
    405: InvalidMethodError,
    "unsupported operation": InvalidMethodError,
    "no such shadow root": ShadowRootNotFoundError,
    "insecure certificate": InsecureCertificateError,
    "invalid coordinates": InvalidCoordinatesError,
    "unknown method exception": UnknownMethodError,
}

INCOMPATIBLE_DRIVER_PATTERN: Pattern = compile(
    "session not created: this version .+ only supports .+ version .+", IGNORECASE
)
"""
Edge error message:
This version of Microsoft Edge WebDriver only supports Microsoft Edge version 110
Current browser version is 119.0.2151.97 with binary path ~

Chromium error message:
aselenium.errors.IncompatibleWebdriverError: session not created: This version of ChromeDriver only supports Chrome version 116
Current browser version is 119.0.6045.199 with binary path ~
"""


def webdriver_error_handler(res: dict[str, Any]) -> None:
    """Check response from the WebDriver for error.

    :params res: The response from the WebDriver server as a dictionary object.
    :raises: Subclass of `WebDriverError` if any error occurs.
    """

    # Success - no error
    status = res.get("status")
    if status == ErrorCode.SUCCESS or not status:
        return None  # exit

    # Error - message
    value = res.get("value")
    if isinstance(value, str) and isinstance(status, int):
        try:
            value: dict = loads(value)
            if len(value) == 1:
                value = value["value"]
            if not (status := value.get("error")):
                status = value.get("status", ErrorCode.UNKNOWN_ERROR)
                message = value.get("value") or value.get("message")
                if isinstance(message, dict):
                    value = message
                    message = message.get("message", "Unknown error")
            else:
                message = value.get("message", "Unknown error")
        except ValueError:
            try:
                message = res.get("message", value.get("message", "Unknown error"))
            except AttributeError:
                message = str(value)
    else:
        message = res.get("message", value.get("message", "Unknown error"))

    # Map webdriver error
    error = WEBDRIVER_ERROR_MAP.get(status, WebDriverError)
    if error is UnknownError:
        if ErrorCode.INTERNET_DISCONNECTED in message:
            error = InternetDisconnectedError
        elif ErrorCode.FAILED_TO_CHANGE_WINDOW_STATE in message:
            error = ChangeWindowStateError
    elif error is InvalidSessionError:
        if INCOMPATIBLE_DRIVER_PATTERN.search(message) is not None:
            error = IncompatibleWebdriverError

    # Raise direct error
    if isinstance(value, str):
        raise error(value)

    # Error - screen
    screen = value.get("screen")

    # Error - stacktrace
    stacktrace = None
    # strace = value.get("stackTrace") or value.get("stacktrace")
    # if strace:
    #     if isinstance(strace, str):
    #         stacktrace = strace.split("\n")
    #     else:
    #         stacktrace = []
    #         try:
    #             frame: dict
    #             for frame in strace:
    #                 line = frame.get("lineNumber", "")
    #                 file = frame.get("fileName", "<anonymous>")
    #                 if line:
    #                     file = "%s:%s" % (file, line)
    #                 meth = frame.get("methodName", "<anonymous>")
    #                 if "className" in frame:
    #                     meth = f"{frame['className']}.{meth}"
    #                 msg = "    at %s (%s)"
    #                 stacktrace.append(msg % (meth, file))
    #         except TypeError:
    #             pass
    # else:
    #     stacktrace = None

    # Raise unexpected alert error
    if error is UnexpectedAlertFoundError:
        if "data" in value:
            alert_text = value["data"].get("text")
        elif "alert" in value:
            alert_text = value["alert"].get("text")
        else:
            alert_text = None
        raise error(message, screen, stacktrace, alert_text)

    # Raise webdriver error
    raise error(message, screen, stacktrace)
