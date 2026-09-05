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

# Driver Commands ---------------------------------------------------------------------------------
"""WebDriver command identifiers and their HTTP endpoint templates."""

__all__ = ["COMMANDS", "Command"]


class Command:
    """Name the protocol operations accepted by :data:`COMMANDS`."""

    # Session - Start
    NEW_SESSION: str = "newSession"
    # Session - Quit
    QUIT: str = "quit"
    # Session - Navigate
    GET: str = "get"
    GO_FORWARD: str = "goForward"
    GO_BACK: str = "goBack"
    REFRESH: str = "refresh"
    # Session - Info
    GET_TITLE: str = "getTitle"
    GET_CURRENT_URL: str = "getCurrentUrl"
    GET_PAGE_SOURCE: str = "getPageSource"
    SCREENSHOT: str = "screenshot"
    PRINT_PAGE: str = "printPage"
    # Session - Timeout
    GET_TIMEOUTS: str = "getTimeouts"
    SET_TIMEOUTS: str = "setTimeouts"
    # Session - Cookie
    GET_ALL_COOKIES: str = "getCookies"
    ADD_COOKIE: str = "addCookie"
    GET_COOKIE: str = "getCookie"
    DELETE_COOKIE: str = "deleteCookie"
    DELETE_ALL_COOKIES: str = "deleteAllCookies"
    # Session - Network
    SET_NETWORK_CONDITIONS: str = "setNetworkConditions"
    GET_NETWORK_CONDITIONS: str = "getNetworkConditions"
    # Session - Permission
    SET_PERMISSION: str = "setPermissions"
    # Session - Action
    W3C_ACTIONS: str = "actions"
    W3C_CLEAR_ACTIONS: str = "clearActionState"
    # Session - Logs
    GET_AVAILABLE_LOG_TYPES: str = "getAvailableLogTypes"
    GET_LOG: str = "getLog"
    # Session - Window
    NEW_WINDOW: str = "newWindow"
    W3C_GET_CURRENT_WINDOW_HANDLE: str = "w3cGetCurrentWindowHandle"
    W3C_GET_WINDOW_HANDLES: str = "w3cGetWindowHandles"
    SWITCH_TO_WINDOW: str = "switchToWindow"
    CLOSE: str = "close"
    GET_WINDOW_RECT: str = "getWindowRect"
    SET_WINDOW_RECT: str = "setWindowRect"
    W3C_MAXIMIZE_WINDOW: str = "w3cMaximizeWindow"
    MINIMIZE_WINDOW: str = "minimizeWindow"
    FULLSCREEN_WINDOW: str = "fullscreenWindow"
    # Session - Script
    W3C_EXECUTE_SCRIPT: str = "w3cExecuteScript"
    W3C_EXECUTE_SCRIPT_ASYNC: str = "w3cExecuteScriptAsync"
    # Session - Alert
    W3C_DISMISS_ALERT: str = "w3cDismissAlert"
    W3C_ACCEPT_ALERT: str = "w3cAcceptAlert"
    W3C_SET_ALERT_VALUE: str = "w3cSetAlertValue"
    W3C_GET_ALERT_TEXT: str = "w3cGetAlertText"
    # Session - Frame
    SWITCH_TO_FRAME: str = "switchToFrame"
    SWITCH_TO_PARENT_FRAME: str = "switchToParentFrame"
    # Session - Element
    FIND_ELEMENT: str = "findElement"
    FIND_ELEMENTS: str = "findElements"
    W3C_GET_ACTIVE_ELEMENT: str = "w3cGetActiveElement"
    # Element - Control
    CLICK_ELEMENT: str = "clickElement"
    CLEAR_ELEMENT: str = "clearElement"
    SEND_KEYS_TO_ELEMENT: str = "sendKeysToElement"
    IS_ELEMENT_SELECTED: str = "isElementSelected"
    IS_ELEMENT_ENABLED: str = "isElementEnabled"
    # Element - Info
    GET_ELEMENT_TAG_NAME: str = "getElementTagName"
    GET_ELEMENT_TEXT: str = "getElementText"
    GET_ELEMENT_RECT: str = "getElementRect"
    GET_ELEMENT_ARIA_ROLE: str = "getElementAriaRole"
    GET_ELEMENT_ARIA_LABEL: str = "getElementAriaLabel"
    GET_ELEMENT_PROPERTY: str = "getElementProperty"
    GET_ELEMENT_VALUE_OF_CSS_PROPERTY: str = "getElementValueOfCssProperty"
    GET_ELEMENT_ATTRIBUTE: str = "getElementAttribute"
    ELEMENT_SCREENSHOT: str = "elementScreenshot"
    # Element - Shadow
    GET_SHADOW_ROOT: str = "getShadowRoot"
    # Chromium - Casting
    GET_SINKS: str = "getSinks"
    GET_ISSUE_MESSAGE: str = "getIssueMessage"
    SET_SINK_TO_USE: str = "setSinkToUse"
    START_DESKTOP_MIRRORING: str = "startDesktopMirroring"
    START_TAB_MIRRORING: str = "startTabMirroring"
    STOP_CASTING: str = "stopCasting"
    # Chromium - DevTools Protocol
    EXECUTE_CDP_COMMAND: str = "executeCdpCommand"

    ### Safari Specific ###
    SAFARI_GET_PERMISSIONS: str = "safariGetPermissions"
    SAFARI_SET_PERMISSIONS: str = "safariSetPermissions"

    ### Firefox Specific ###
    FIREFOX_GET_CONTEXT: str = "firefoxGetContext"
    FIREFOX_SET_CONTEXT: str = "firefoxSetContext"
    FIREFOX_INSTALL_ADDON: str = "firefoxInstallAddon"
    FIREFOX_UNINSTALL_ADDON: str = "firefoxUninstallAddon"
    FIREFOX_FULL_PAGE_SCREENSHOT: str = "firefoxFullPageScreenshot"


COMMANDS: dict[str, tuple[str, str]] = {
    # Session - Start | format: "{CMD}"
    Command.NEW_SESSION: ("POST", "/session"),
    # Session - Quit | format: "/session/$sessionId{CMD}"
    Command.QUIT: ("DELETE", ""),
    # Session - Navigate | format: "/session/$sessionId{CMD}"
    Command.GET: ("POST", "/url"),
    Command.GO_FORWARD: ("POST", "/forward"),
    Command.GO_BACK: ("POST", "/back"),
    Command.REFRESH: ("POST", "/refresh"),
    # Session - Info | format: "/session/$sessionId{CMD}"
    Command.GET_TITLE: ("GET", "/title"),
    Command.GET_CURRENT_URL: ("GET", "/url"),
    Command.GET_PAGE_SOURCE: ("GET", "/source"),
    Command.SCREENSHOT: ("GET", "/screenshot"),
    Command.PRINT_PAGE: ("POST", "/print"),
    # Session - Timeout | format: "/session/$sessionId{CMD}"
    Command.GET_TIMEOUTS: ("GET", "/timeouts"),
    Command.SET_TIMEOUTS: ("POST", "/timeouts"),
    # Session - Cookie | format: "/session/$sessionId{CMD}"
    Command.GET_ALL_COOKIES: ("GET", "/cookie"),
    Command.ADD_COOKIE: ("POST", "/cookie"),
    Command.GET_COOKIE: ("GET", "/cookie/$name"),
    Command.DELETE_COOKIE: ("DELETE", "/cookie/$name"),
    Command.DELETE_ALL_COOKIES: ("DELETE", "/cookie"),
    # Session - Network | format: "/session/$sessionId{CMD}"
    Command.SET_NETWORK_CONDITIONS: ("POST", "/chromium/network_conditions"),
    Command.GET_NETWORK_CONDITIONS: ("GET", "/chromium/network_conditions"),
    # Session - Permission | format: "/session/$sessionId{CMD}"
    Command.SET_PERMISSION: ("POST", "/permissions"),
    # Session - Action | format: "/session/$sessionId{CMD}"
    Command.W3C_ACTIONS: ("POST", "/actions"),
    Command.W3C_CLEAR_ACTIONS: ("DELETE", "/actions"),
    # Session - Logs | format: "/session/$sessionId{CMD}"
    Command.GET_AVAILABLE_LOG_TYPES: ("GET", "/se/log/types"),
    Command.GET_LOG: ("POST", "/se/log"),
    # Session - Window | format: "/session/$sessionId{CMD}"
    Command.NEW_WINDOW: ("POST", "/window/new"),
    Command.W3C_GET_CURRENT_WINDOW_HANDLE: ("GET", "/window"),
    Command.W3C_GET_WINDOW_HANDLES: ("GET", "/window/handles"),
    Command.SWITCH_TO_WINDOW: ("POST", "/window"),
    Command.CLOSE: ("DELETE", "/window"),
    Command.GET_WINDOW_RECT: ("GET", "/window/rect"),
    Command.SET_WINDOW_RECT: ("POST", "/window/rect"),
    Command.W3C_MAXIMIZE_WINDOW: ("POST", "/window/maximize"),
    Command.MINIMIZE_WINDOW: ("POST", "/window/minimize"),
    Command.FULLSCREEN_WINDOW: ("POST", "/window/fullscreen"),
    # Session - Script | format: "/session/$sessionId{CMD}"
    Command.W3C_EXECUTE_SCRIPT: ("POST", "/execute/sync"),
    Command.W3C_EXECUTE_SCRIPT_ASYNC: ("POST", "/execute/async"),
    # Session - Alert | format: "/session/$sessionId{CMD}"
    Command.W3C_DISMISS_ALERT: ("POST", "/alert/dismiss"),
    Command.W3C_ACCEPT_ALERT: ("POST", "/alert/accept"),
    Command.W3C_SET_ALERT_VALUE: ("POST", "/alert/text"),
    Command.W3C_GET_ALERT_TEXT: ("GET", "/alert/text"),
    # Session - Frame | format: "/session/$sessionId{CMD}"
    Command.SWITCH_TO_FRAME: ("POST", "/frame"),
    Command.SWITCH_TO_PARENT_FRAME: ("POST", "/frame/parent"),
    # Session - Element | format: "/session/$sessionId{CMD}"
    Command.FIND_ELEMENT: ("POST", "/element"),
    Command.FIND_ELEMENTS: ("POST", "/elements"),
    Command.W3C_GET_ACTIVE_ELEMENT: ("GET", "/element/active"),
    # Element - Control | format: "/session/$sessionId/element/$id{CMD}"
    Command.CLICK_ELEMENT: ("POST", "/click"),
    Command.CLEAR_ELEMENT: ("POST", "/clear"),
    Command.SEND_KEYS_TO_ELEMENT: ("POST", "/value"),
    Command.IS_ELEMENT_SELECTED: ("GET", "/selected"),
    Command.IS_ELEMENT_ENABLED: ("GET", "/enabled"),
    # Element - Info | format: "/session/$sessionId/element/$id{CMD}"
    Command.GET_ELEMENT_TAG_NAME: ("GET", "/name"),
    Command.GET_ELEMENT_TEXT: ("GET", "/text"),
    Command.GET_ELEMENT_RECT: ("GET", "/rect"),
    Command.GET_ELEMENT_ARIA_ROLE: ("GET", "/computedrole"),
    Command.GET_ELEMENT_ARIA_LABEL: ("GET", "/computedlabel"),
    Command.GET_ELEMENT_PROPERTY: ("GET", "/property/$name"),
    Command.GET_ELEMENT_VALUE_OF_CSS_PROPERTY: ("GET", "/css/$propertyName"),
    Command.GET_ELEMENT_ATTRIBUTE: ("GET", "/attribute/$name"),
    Command.ELEMENT_SCREENSHOT: ("GET", "/screenshot"),
    # Element - Shadow | format: "/session/$sessionId/element/$id{CMD}"
    Command.GET_SHADOW_ROOT: ("GET", "/shadow"),
    # fmt: off
    # Chromium - Casting | format: "/session/$sessionId{CMD}"
    Command.GET_SINKS: ("GET", "/$vendorPrefix/cast/get_sinks"),
    Command.GET_ISSUE_MESSAGE: ("GET", "/$vendorPrefix/cast/get_issue_message"),
    Command.SET_SINK_TO_USE: ("POST", "/$vendorPrefix/cast/set_sink_to_use"),
    Command.START_DESKTOP_MIRRORING: (
        "POST",
        "/$vendorPrefix/cast/start_desktop_mirroring",
    ),
    Command.START_TAB_MIRRORING: ("POST", "/$vendorPrefix/cast/start_tab_mirroring"),
    Command.STOP_CASTING: ("POST", "/$vendorPrefix/cast/stop_casting"),
    # Chromium - DevTools Protocol | format: "/session/$sessionId{CMD}"
    Command.EXECUTE_CDP_COMMAND: ("POST", "/$vendorPrefix/cdp/execute"),
    # fmt : on
    ### Firefox Specific ###
    # Session | format: "/session/$sessionId{CMD}"
    Command.FIREFOX_GET_CONTEXT: ("GET", "/moz/context"),
    Command.FIREFOX_SET_CONTEXT: ("POST", "/moz/context"),
    Command.FIREFOX_INSTALL_ADDON: ("POST", "/moz/addon/install"),
    Command.FIREFOX_UNINSTALL_ADDON: ("POST", "/moz/addon/uninstall"),
    Command.FIREFOX_FULL_PAGE_SCREENSHOT: ("GET", "/moz/screenshot/full"),
    ### Safari Specific ###
    # Session | format: "/session/$sessionId{CMD}"
    Command.SAFARI_GET_PERMISSIONS: ("GET", "/apple/permissions"),
    Command.SAFARI_SET_PERMISSIONS: ("POST", "/apple/permissions"),
}
