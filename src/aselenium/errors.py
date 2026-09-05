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

"""Public exception hierarchy and W3C WebDriver error-response mapping."""

from __future__ import annotations

from asyncio import TimeoutError
from re import IGNORECASE, Pattern, compile
from typing import (
    Any,
)

from aiohttp import ClientError


# Base --------------------------------------------------------------------------------------------------
class AseleniumError(Exception):
    """Base class for all package-defined exceptions."""


class AseleniumTimeout(AseleniumError, TimeoutError):
    """Base class for package operations that exceed a time budget."""


class AseleniumInvalidPathError(AseleniumError, ValueError):
    """A filesystem input cannot be parsed or used safely."""


class AseleniumFileNotFoundError(AseleniumInvalidPathError, FileNotFoundError):
    """A required filesystem path does not identify a regular file."""


class AseleniumDirectoryNotFoundError(AseleniumInvalidPathError, FileNotFoundError):
    """A required filesystem path does not identify a directory."""


class AseleniumInvalidValueError(AseleniumError, ValueError):
    """Base class for invalid values rejected by package APIs."""


class AseleniumOSError(AseleniumError, OSError):
    """Base class for classified operating-system failures."""


# Platform ----------------------------------------------------------------------------------------------
class PlatformError(AseleniumError):
    """Base class for unsupported host or target platform configurations."""


class UnsupportedPlatformError(PlatformError):
    """The current host or requested target platform is unsupported."""


# Driver Manager ----------------------------------------------------------------------------------------
class DriverManagerError(AseleniumError):
    """Base class for browser discovery, provisioning, and cache failures."""


class DriverManagerTimeoutError(DriverManagerError, AseleniumTimeout):
    """A driver-management operation exhausted its total time budget."""


class DriverInstallationError(DriverManagerError, AseleniumInvalidValueError):
    """A requested browser or driver installation could not be completed."""


class DriverExecutableNotDetectedError(DriverManagerError, AseleniumFileNotFoundError):
    """No usable WebDriver executable was found after discovery or installation."""


class DriverRequestFailedError(DriverManagerError):
    """A vendor metadata request failed or returned an unusable response."""


class DriverRequestTimeoutError(DriverRequestFailedError, DriverManagerTimeoutError):
    """A vendor metadata request exhausted its total time budget."""


class DriverRequestRateLimitError(DriverRequestFailedError):
    """A driver-vendor endpoint rejected a request because of rate limiting."""


class DriverDownloadFailedError(DriverRequestFailedError):
    """A WebDriver archive could not be downloaded successfully."""


class InvalidVersionError(DriverManagerError, AseleniumInvalidValueError):
    """A version value or selector is malformed or unsupported."""


class InvalidDriverVersionError(InvalidVersionError):
    """A WebDriver version value is malformed or unavailable."""


class InvalidBrowserVersionError(InvalidVersionError):
    """A browser version value is malformed or unavailable."""


class BrowserBinaryNotDetectedError(DriverManagerError, AseleniumFileNotFoundError):
    """No usable browser executable was found at an override or known location."""


class BrowserDownloadFailedError(DriverDownloadFailedError):
    """A downloadable browser archive could not be obtained successfully."""


class FileDownloadTimeoutError(DriverDownloadFailedError, DriverManagerTimeoutError):
    """An artifact download exhausted its total time budget."""


class InvalidDownloadFileError(DriverRequestFailedError, OSError):
    """A downloaded archive or its extracted contents failed validation."""


# Options -----------------------------------------------------------------------------------------------
class OptionsError(AseleniumInvalidValueError):
    """Base class for invalid browser option configurations."""


class InvalidOptionsError(OptionsError):
    """A browser option value or capability combination is invalid."""


class InvalidProxyError(InvalidOptionsError):
    """A proxy mode, endpoint, credential, or bypass value is invalid."""


class InvalidProfileError(InvalidOptionsError):
    """A browser profile is invalid, unavailable, or cannot be cloned safely."""


class OptionsNotSetError(InvalidOptionsError, KeyError):
    """A requested option, capability, or preference has not been configured."""


# Services ----------------------------------------------------------------------------------------------
class ServiceError(AseleniumError):
    """Base class for local WebDriver service lifecycle failures."""


class ServiceExecutableNotFoundError(ServiceError, AseleniumFileNotFoundError):
    """The configured WebDriver service executable does not exist."""


class ServiceStartError(ServiceError):
    """A WebDriver service did not become ready after process startup."""


class ServiceStopError(ServiceError):
    """An owned WebDriver service or descendant process could not be stopped."""


class ServiceSocketError(ServiceError, AseleniumOSError):
    """A local TCP port could not be allocated or probed for a service."""


class ServiceProcessError(ServiceError, AseleniumOSError):
    """A WebDriver subprocess could not be launched, inspected, or controlled."""


class ServiceTimeoutError(ServiceError, AseleniumTimeout):
    """A WebDriver service did not start or stop within its time budget."""


# WebDriver ---------------------------------------------------------------------------------------------
class WebDriverError(AseleniumError):
    """Base class for errors returned by or encountered through WebDriver."""

    def __init__(
        self,
        msg: str | None = None,
        screen: str | None = None,
        stacktrace: list[str] | None = None,
    ) -> None:
        """Capture a WebDriver error and its optional diagnostic payload.

        Args:
            msg: Human-readable driver error message.
            screen: Optional screenshot data supplied by the driver.
            stacktrace: Optional remote stack-trace lines.
        """
        Exception.__init__(self, msg)
        self.msg: str | None = msg
        self.screen: str | None = screen
        self.stacktrace: list[str] | None = stacktrace

    def __str__(self) -> str:
        """Return the human-readable string representation.

        Returns:
            The human-readable string representation.
        """
        msg = self.msg or ""
        if self.screen:
            msg += "\nScreenshot: available via screen"
        if self.stacktrace:
            msg += "\nStacktrace:\n%s" % "\n".join(self.stacktrace)
        return msg


class WebDriverTimeoutError(WebDriverError, AseleniumTimeout):
    """WebDriver reported that a browser operation exceeded its native timeout."""


class WebDriverNotFoundError(WebDriverError):
    """Base class for missing WebDriver-managed resources."""


class ConnectionClosedError(WebDriverError):
    """The browser or driver closed a connection during an operation."""


class InternetDisconnectedError(WebDriverError):
    """Navigation failed because the browser reported no internet connection."""


# . Invalid value error
class InvalidValueError(WebDriverError, AseleniumInvalidValueError):
    """Base class for invalid W3C command parameters and response values."""


class InvalidArgumentError(InvalidValueError):
    """The arguments passed to a command are either invalid or malformed."""


class InvalidMethodError(InvalidValueError):
    """The requested operation is unsupported by the active driver endpoint."""


class InvalidRectValueError(InvalidValueError):
    """A browser rectangle contains a nonnumeric or non-finite coordinate."""


class InvalidResponseError(InvalidValueError):
    """A local helper or remote endpoint returned an invalid response shape."""


class InvalidExtensionError(InvalidArgumentError, InvalidOptionsError):
    """A browser extension archive, manifest, or encoded payload is invalid."""


class UnknownMethodError(InvalidMethodError):
    """A command URL exists, but it does not support the requested HTTP method."""


# . Session error
class SessionError(WebDriverError):
    """Base class for browser-session lifecycle and transport failures."""


class SessionClientError(SessionError, ClientError):
    """The HTTP client failed while communicating with a WebDriver service."""


class InvalidSessionError(SessionError, WebDriverNotFoundError):
    """A browser session is missing, closed, or no longer usable."""


class IncompatibleWebDriverError(InvalidSessionError):
    """The selected WebDriver cannot create a session for the browser version."""


class SessionDataError(SessionError):
    """A WebDriver HTTP response is malformed or violates transport policy."""


class SessionTimeoutError(SessionError, AseleniumTimeout):
    """A command exceeded the client's total response deadline."""


class SessionShutdownError(SessionError):
    """An owned browser session could not be shut down completely."""


class SessionQuitError(SessionShutdownError, ServiceStopError):
    """Remote-session deletion or owned-service teardown failed during quit."""


# . Window error
class WindowError(WebDriverError):
    """Base class for top-level browser-window failures."""


class ChangeWindowStateError(WindowError):
    """WebDriver could not maximize, minimize, or resize a browser window."""


class WindowNotFoundError(WindowError, WebDriverNotFoundError):
    """The requested top-level browsing context does not exist."""


# . Cookie error
class CookieError(WebDriverError):
    """Base class for cookie retrieval and mutation failures."""


class UnableToSetCookieError(CookieError, InvalidArgumentError):
    """WebDriver could not store the requested cookie."""


class InvalidCookieDomainError(CookieError, InvalidArgumentError):
    """A cookie domain does not match the active document's domain."""


class CookieNotFoundError(CookieError, WebDriverNotFoundError):
    """No cookie with the requested name exists in the active browsing context."""


# . JavaScript error
class JavaScriptError(WebDriverError):
    """Base class for JavaScript execution and script-cache failures."""


class InvalidJavaScriptError(JavaScriptError, InvalidArgumentError):
    """A JavaScript source, argument, or execution result is invalid."""


class JavaScriptNotFoundError(InvalidJavaScriptError, WebDriverNotFoundError):
    """No cached JavaScript snippet matches the requested name."""


class JavaScriptTimeoutError(InvalidJavaScriptError, WebDriverTimeoutError):
    """An asynchronous browser script exceeded the configured script timeout."""


# . Element error
class ElementError(WebDriverError):
    """Base class for DOM element lookup and interaction failures."""


class InvalidElementStateError(ElementError):
    """An element is not in a state that permits the requested command."""


class ElementNotInteractableError(InvalidElementStateError):
    """An element exists but cannot currently receive the requested interaction."""


class ElementClickInterceptedError(InvalidElementStateError):
    """Another painted element intercepted a click intended for the target."""


class ElementNotFoundError(ElementError, WebDriverNotFoundError):
    """No element matches the selector in the active search context.

    Verify the CSS selector and current frame. For content that appears
    asynchronously, use ``wait_until_element()`` instead of repeatedly calling
    ``find_element()``.
    """


class ElementStaleReferenceError(ElementNotFoundError):
    """A remote element reference no longer identifies a node in the current DOM.

    Navigation, frame changes, page refreshes, or client-side DOM replacement
    can invalidate a previously located element. Locate the element again before
    retrying the interaction.
    """


# . Frame error
class FrameError(WebDriverError):
    """Base class for browsing-context frame selection failures."""


class FrameNotFoundError(FrameError, WebDriverNotFoundError):
    """The requested frame does not exist in the active browsing context."""


# . Shadowroot error
class ShadowRootError(WebDriverError):
    """Base class for shadow-root lookup and descendant-command failures."""


class ShadowRootNotFoundError(ShadowRootError, WebDriverNotFoundError):
    """The requested element has no accessible shadow root."""


class DetachedShadowRootError(ShadowRootError, WebDriverNotFoundError):
    """A previously located shadow root is no longer attached to the DOM."""


# . Selector error
class SelectorError(WebDriverError):
    """Base class for unsupported or malformed element selectors."""


class InvalidSelectorError(SelectorError, InvalidArgumentError):
    """A selector is malformed or does not select DOM elements."""


class InvalidXPathSelectorError(InvalidSelectorError):
    """An XPath expression is malformed or produces a non-element result."""


# . Network conditions error
class NetworkConditionsError(WebDriverError):
    """Base class for Chromium network-emulation failures."""


class NetworkConditionsNotFoundError(NetworkConditionsError, WebDriverNotFoundError):
    """The active Chromium session has no emulated network conditions."""


# . Permission error
class BrowserPermissionError(InvalidArgumentError):
    """Base class for invalid browser permission descriptors and states."""


class InvalidPermissionNameError(BrowserPermissionError):
    """A permission descriptor name is empty or unsupported."""


class InvalidPermissionStateError(BrowserPermissionError):
    """A permission state is not granted, denied, prompt, or a required bool."""


# . Alert error
class AlertError(WebDriverError):
    """Base class for JavaScript alert, confirm, and prompt failures."""


class UnexpectedAlertFoundError(AlertError):
    """An unexpected modal dialog is blocking the requested browser command."""

    def __init__(
        self,
        msg: str | None = None,
        screen: str | None = None,
        stacktrace: list[str] | None = None,
        alert_text: str | None = None,
    ) -> None:
        """Capture an unexpected-alert error and the alert's text.

        Args:
            msg: Human-readable driver error message.
            screen: Optional screenshot data supplied by the driver.
            stacktrace: Optional remote stack-trace lines.
            alert_text: Text displayed by the blocking alert, when available.
        """
        super().__init__(msg, screen, stacktrace)
        self.alert_text: str | None = alert_text

    def __str__(self) -> str:
        """Return the human-readable string representation.

        Returns:
            The human-readable string representation.
        """
        message = super().__str__()
        if self.alert_text is None:
            return message
        alert = "Alert Text: %s" % self.alert_text
        return "%s\n%s" % (alert, message) if message else alert


class AlertNotFoundError(AlertError, WebDriverNotFoundError):
    """No JavaScript alert, confirm dialog, or prompt is currently open."""


# . Cast error
class CastingError(WebDriverError):
    """Base class for Chromium media-router casting failures."""


class CastSinkNotFoundError(CastingError, WebDriverNotFoundError):
    """No Chromium cast sink matches the requested receiver name."""


# . DevTools command error
class DevToolsCMDError(WebDriverError):
    """Base class for Chromium DevTools Protocol command failures."""


class DevToolsCMDNotFoundError(DevToolsCMDError, WebDriverNotFoundError):
    """No cached DevTools Protocol command matches the requested name."""


# . Other error
class ScreenshotError(WebDriverError):
    """WebDriver could not capture the requested viewport or element image."""


class MoveTargetOutOfBoundsError(WebDriverError):
    """A pointer-move target lies outside the document's valid coordinate space."""


class InsecureCertificateError(WebDriverError):
    """Navigation stopped at a TLS certificate warning that was not accepted."""


class InvalidCoordinatesError(WebDriverError):
    """An interaction contains coordinates WebDriver cannot apply."""


# . Unknown error
class UnknownError(WebDriverError):
    """WebDriver returned an error that has no more specific W3C classification."""


class UnknownCommandError(UnknownError):
    """WebDriver does not recognize the requested session command."""


# Error handling ----------------------------------------------------------------------------------------
class ErrorCode:
    """Browser-specific message markers accompanying W3C protocol errors."""

    FAILED_TO_CHANGE_WINDOW_STATE = "failed to change window state"
    NETWORK_CONDITIONS_NOT_SET = "network conditions must be set before"
    INVALID_PERMISSION_STATE = "unrecognized permission state"
    INVALID_PERMISSION_NAME = "Invalid PermissionDescriptor name"
    INTERNET_DISCONNECTED = "ERR_INTERNET_DISCONNECTED"
    CONNECTION_CLOSED = "ERR_CONNECTION_CLOSED"
    SINK_NOT_FOUND = "Sink not found"


WEBDRIVER_ERROR_MAP: dict[str, type[WebDriverError]] = {
    "no such element": ElementNotFoundError,
    "no such frame": FrameNotFoundError,
    "unknown command": UnknownCommandError,
    "stale element reference": ElementStaleReferenceError,
    "invalid element state": InvalidElementStateError,
    "unknown error": UnknownError,
    "javascript error": InvalidJavaScriptError,
    "timeout": WebDriverTimeoutError,
    "no such window": WindowNotFoundError,
    "invalid cookie domain": InvalidCookieDomainError,
    "unable to set cookie": UnableToSetCookieError,
    "unexpected alert open": UnexpectedAlertFoundError,
    "no such alert": AlertNotFoundError,
    "script timeout": JavaScriptTimeoutError,
    "invalid selector": InvalidSelectorError,
    "session not created": InvalidSessionError,
    "invalid session id": InvalidSessionError,
    "move target out of bounds": MoveTargetOutOfBoundsError,
    "element not interactable": ElementNotInteractableError,
    "invalid argument": InvalidArgumentError,
    "no such cookie": CookieNotFoundError,
    "unable to capture screen": ScreenshotError,
    "element click intercepted": ElementClickInterceptedError,
    "unsupported operation": InvalidMethodError,
    "no such shadow root": ShadowRootNotFoundError,
    "detached shadow root": DetachedShadowRootError,
    "insecure certificate": InsecureCertificateError,
    "invalid coordinates": InvalidCoordinatesError,
    "unknown method": UnknownMethodError,
    # Retain the legacy Chromium spelling for vendor compatibility.
    "unknown method exception": UnknownMethodError,
}

INCOMPATIBLE_DRIVER_PATTERN: Pattern[str] = compile(
    "session not created: this version .+ only supports .+ version .+", IGNORECASE
)


def webdriver_error_handler(res: dict[str, Any], *, http_status: int = 200) -> None:
    """Use HTTP status and W3C error strings, never JavaScript payload contents.

    Args:
        res: Parsed W3C response envelope returned by the driver.
        http_status: HTTP response status associated with ``res``.

    Raises:
        InvalidResponseError: The response is not a valid W3C success or error
            envelope.
        WebDriverError: The driver returned an error; a more specific subclass is
            selected when the W3C error code or browser message is recognized.
    """
    if not isinstance(res, dict):
        raise InvalidResponseError("WebDriver response must be an object")
    if "status" in res:
        raise InvalidResponseError(
            "JSON Wire Protocol status envelopes are unsupported; use a W3C WebDriver"
        )
    if "value" not in res:
        raise InvalidResponseError("WebDriver response has no value")
    if 200 <= http_status < 300:
        return
    value = res["value"]
    if not isinstance(value, dict) or not isinstance(value.get("error"), str):
        raise InvalidResponseError("Malformed W3C WebDriver error response")
    error = WEBDRIVER_ERROR_MAP.get(value["error"], WebDriverError)
    message = value.get("message", "Unknown WebDriver error")
    if not isinstance(message, str):
        raise InvalidResponseError("Malformed WebDriver error message")
    if error is UnknownError:
        if ErrorCode.FAILED_TO_CHANGE_WINDOW_STATE in message:
            error = ChangeWindowStateError
        elif ErrorCode.CONNECTION_CLOSED in message:
            error = ConnectionClosedError
        elif ErrorCode.INTERNET_DISCONNECTED in message:
            error = InternetDisconnectedError
    elif error is InvalidSessionError and INCOMPATIBLE_DRIVER_PATTERN.search(message):
        error = IncompatibleWebDriverError
    stack = value.get("stacktrace")
    stacktrace = stack.splitlines() if isinstance(stack, str) else None
    if error is UnexpectedAlertFoundError:
        alert = value.get("data", {})
        alert_text = alert.get("text") if isinstance(alert, dict) else None
        if alert_text is not None and not isinstance(alert_text, str):
            raise InvalidResponseError("Malformed unexpected-alert text")
        raise error(
            message,
            None,
            stacktrace,
            alert_text,
        )
    raise error(message, None, stacktrace)
