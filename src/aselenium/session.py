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
from __future__ import annotations
from math import ceil
from uuid import uuid4
from copy import deepcopy
from time import time as unix_time
from base64 import b64decode, b64encode
from asyncio import sleep, CancelledError
from typing import Any, Literal, Awaitable
from aselenium.logs import logger
from aselenium.alert import Alert
from aselenium.shadow import Shadow
from aselenium.actions import Actions
from aselenium.command import Command
from aselenium.errors import ErrorCode
from aselenium import errors, javascript
from aselenium.valuewrap import warp_tuple
from aselenium.connection import Connection
from aselenium.element import Element, ELEMENT_KEY
from aselenium.manager.version import Version, ChromiumVersion
from aselenium.service import BaseService, ChromiumBaseService
from aselenium.settings import Constraint, DefaultNetworkConditions
from aselenium.options import BaseOptions, ChromiumBaseOptions, Timeouts
from aselenium.utils import validate_save_file_path, Rectangle, CustomDict

__all__ = [
    "Cookie",
    "DevToolsCMD",
    "JavaScript",
    "Network",
    "Permission",
    "Viewport",
    "Window",
    "WindowRect",
]


# Session Objects ---------------------------------------------------------------------------------
class Cookie(CustomDict):
    """Represents a cookie of the webpage."""

    def __init__(self, **data: Any) -> None:
        """The cookie of the webpage.

        :param data [keywords]: `<Any>` The cookie data.
        """
        super().__init__(**data)
        # Validate name
        if "name" in self._dict:
            self.__nkey: str = "name"
        elif "Name" in self._dict:
            self.__nkey: str = "Name"
        else:
            raise errors.InvalidArgumentError(
                "<{}>\Lack of required attribute 'name': {}.".format(
                    self.__class__.__name__, repr(self._dict)
                )
            )

    # Name --------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Access the name of the cookie `<str>`."""
        return self._dict[self.__nkey]

    @name.setter
    def name(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid cookie name: {} {}.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        self._dict[self.__nkey] = value

    # Attributes --------------------------------------------------------------------------
    @property
    def data(self) -> dict[str, Any]:
        """Access the data of the cookie `<dict>`."""
        return self._dict

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<Cookie (name='%s', data=%s)" % (self.name, self._dict)

    def copy(self) -> Cookie:
        """Copy the cookie object `<Cookie>`."""
        return Cookie(**self._dict)


class DevToolsCMD:
    """Represents a cached Chrome DevTools Protocol command."""

    def __init__(
        self,
        name: str,
        cmd: str,
        **kwargs: Any,
    ) -> None:
        """The cached Chrome DevTools Protocol command.

        :param name: `<str>` The name of the command.
        :param cmd: `<str>` The command lines for the devtools protocal.
        :param kwargs: `<Any>` Additional keyword arguments for the command.
        """
        # Command name
        if isinstance(name, str) and name:
            self._name: str = name
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid name: {} {}.".format(
                    self.__class__.__name__, name, type(name)
                )
            )
        # Command lines
        if isinstance(cmd, str) and cmd:
            self._cmd: str = cmd
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid DevTools Protocol command: {} {}.".format(
                    self.__class__.__name__, cmd, type(cmd)
                )
            )
        # Arguments
        self._kwargs: dict[str, Any] = kwargs

    # Properties --------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Access the name of the command `<str>`."""
        return self._name

    @property
    def cmd(self) -> str:
        """Access the command line `<str>`"""
        return self._cmd

    @property
    def kwargs(self) -> dict[str, Any]:
        """Access the keyword arguments for the command `<dict>`"""
        return self._kwargs

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<DevToolsCMD (name='%s', cmd='%s', kwargs=%s)>" % (
            self._name,
            self._cmd[:27] + "..." if len(self._cmd) > 30 else self._cmd,
            self._kwargs,
        )

    def __hash__(self) -> int:
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, str):
            return self._name == __o
        elif isinstance(__o, DevToolsCMD):
            return self._name == __o._name and self._cmd == __o._cmd
        else:
            return False

    def __bool__(self) -> bool:
        return True

    def __del__(self):
        self._name = None
        self._cmd = None
        self._kwargs = None

    def copy(self) -> DevToolsCMD:
        """Copy the DevTools Command object `<DevToolsCMD>`."""
        cmd = DevToolsCMD(self._name, self._cmd)
        cmd._kwargs = deepcopy(self._kwargs)
        return cmd


class JavaScript:
    """Represents a cached javascript of the session."""

    def __init__(self, name: str, script: str, *args: Any) -> None:
        """The cached javascript of the session.

        :param name: `<str>` The name of the javascript.
        :param script: `<str>` The raw javascript code.
        :param args: `<Any>` The arguments for the javascript.
        """
        # JavaScript name
        if isinstance(name, str) and name:
            self._name: str = name
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid javascript name: {} {}.".format(
                    self.__class__.__name__, name, type(name)
                )
            )
        # JavaScript code
        if isinstance(script, str) and script:
            self._script: str = script
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid javascript code: {} {}.".format(
                    self.__class__.__name__, script, type(script)
                )
            )
        # Arguments
        self._args: list[Any] = list(args)

    # Properties --------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Access the name of the javascript `<str>`."""
        return self._name

    @property
    def script(self) -> str:
        """Access the javascript code `<str>`."""
        return self._script

    @property
    def args(self) -> list[Any]:
        """Access the arguments for the javascript `<list[Any]>`."""
        return self._args

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<JavaScript (name='%s', script='%s', args=%s)>" % (
            self._name,
            self._script[:27] + "..." if len(self._script) > 30 else self._script,
            self._args,
        )

    def __hash__(self) -> int:
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, str):
            return self._name == __o
        elif isinstance(__o, JavaScript):
            return self._name == __o._name and self._script == __o._script
        else:
            return False

    def __bool__(self) -> bool:
        return True

    def __del__(self):
        self._name = None
        self._script = None
        self._args = None

    def copy(self) -> JavaScript:
        """Copy the javascript object `<JavaScript>`."""
        js = JavaScript(self._name, self._script)
        js._args = deepcopy(self._args)
        return js


class Network:
    """Represents the network condition of the session."""

    def __init__(
        self,
        offline: bool | None = None,
        latency: int | None = None,
        upload_throughput: int | None = None,
        download_throughput: int | None = None,
    ) -> None:
        """The network condition of the session.

        :param offline: `<bool/None>` Whether to simulate an offline
        network condition. If `None`, set to default condition.

        :param latency: `<int/None>` The minimum latency overhead. If
        `None`, set to default condition.

        :param upload_throughput: `<int/None>` The maximum upload throughput
        in bytes per second. If `None`, set to default condition.

        :param download_throughput: `<int/None>` The maximum download
        throughput in bytes per second. If `None`, set to default condition.
        """
        self._offline: bool = None
        self._latency: int = None
        self._upload_throughput: int = None
        self._download_throughput: int = None
        # Set values
        self.offline = offline
        self.latency = latency
        self.upload_throughput = upload_throughput
        self.download_throughput = download_throughput

    # Dict --------------------------------------------------------------------------------
    @property
    def dict(self) -> dict[str, int]:
        """Access the network condition as a
        dictionary `<dict[str, int]>`.

        Excepted format:
        >>> {
                "offline": False,
                "latency": 0,
                "upload_throughput": -1,
                "download_throughput": -1,
            }
        """
        return {
            "offline": self._offline,
            "latency": self._latency,
            "upload_throughput": self._upload_throughput,
            "download_throughput": self._download_throughput,
        }

    # Offline -----------------------------------------------------------------------------
    @property
    def offline(self) -> bool:
        """Access the network offline condition `<bool>`."""
        return self._offline

    @offline.setter
    def offline(self, value: bool | None) -> None:
        # Value is None
        if value is None:
            if self._offline is None:
                self._offline = DefaultNetworkConditions.OFFLINE
        # Set value
        else:
            self._offline = bool(value)

    # Latency -----------------------------------------------------------------------------
    @property
    def latency(self) -> int:
        """Access the network latency condition `<int>`."""
        return self._latency

    @latency.setter
    def latency(self, value: int | None) -> None:
        # Value is None
        if value is None:
            if self._latency is None:
                self._latency = DefaultNetworkConditions.LATENCY
        # Set value
        else:
            if not isinstance(value, int) or value < 0:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid latency: {} {}.".format(
                        self.__class__.__name__, repr(value), type(value)
                    )
                )
            self._latency = value

    # Upload throughput -------------------------------------------------------------------
    @property
    def upload_throughput(self) -> int:
        """Access the network upload throughput condition `<int>`."""
        return self._upload_throughput

    @upload_throughput.setter
    def upload_throughput(self, value: int | None) -> None:
        # Value is None
        if value is None:
            if self._upload_throughput is None:
                self._upload_throughput = DefaultNetworkConditions.UPLOAD_THROUGHPUT
        # Set value
        else:
            if not isinstance(value, int) or value < -1:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid upload throughput: {} {}.".format(
                        self.__class__.__name__, repr(value), type(value)
                    )
                )
            self._upload_throughput = value

    # Download throughput -----------------------------------------------------------------
    @property
    def download_throughput(self) -> int:
        """Access the network download throughput condition `<int>`."""
        return self._download_throughput

    @download_throughput.setter
    def download_throughput(self, value: int | None) -> None:
        # Value is None
        if value is None:
            if self._download_throughput is None:
                self._download_throughput = DefaultNetworkConditions.DOWNLOAD_THROUGHPUT
        # Set value
        else:
            if not isinstance(value, int) or value < -1:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid download throughput: {} {}.".format(
                        self.__class__.__name__, repr(value), type(value)
                    )
                )
            self._download_throughput = value

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return (
            "<Network (offline=%s, latency=%s, upload_throughput=%s, download_throughput=%s)>"
            % (
                self._offline,
                self._latency,
                self._upload_throughput,
                self._download_throughput,
            )
        )

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, Network) else False

    def __bool__(self) -> bool:
        return True

    def copy(self) -> Network:
        """Copy the network condition object."""
        return Network(
            offline=self._offline,
            latency=self._latency,
            upload_throughput=self._upload_throughput,
            download_throughput=self._download_throughput,
        )


class Permission:
    """Represents a permission of the session."""

    def __init__(
        self,
        name: str,
        state: Literal["granted", "denied", "prompt"],
    ) -> None:
        self.name = name
        self.state = state

    # Dict  --------------------------------------------------------------------------------
    @property
    def dict(self) -> dict[str, int]:
        """Access the permission as a dictionary `<dict[str, int]>`.

        Excepted format:
        >>> {"name": "video_capture", "state": "prompt"}
        """
        return {"name": self._name, "state": self._state}

    # Name --------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Access the name of the permission `<str>`."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        if value not in Constraint.PERMISSION_NAMES:
            raise errors.InvalidPermissionNameError(
                "<{}>\nInvalid permission name: {} {}.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        self._name: str = value

    # State -------------------------------------------------------------------------------
    @property
    def state(self) -> str:
        """Access the permission state `<str>`.

        Excepted values: `"granted"`, `"denied"`, `"prompt"`
        """
        return self._state

    @state.setter
    def state(self, value: str) -> None:
        if value not in Constraint.PERMISSION_STATES:
            raise errors.InvalidPermissionStateError(
                "<{}>\nInvalid permission state: {} {}.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        self._state: str = value

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<Permission (name='%s', state='%s')>" % (self._name, self._state)

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, Permission) else False

    def __bool__(self) -> bool:
        return True

    def copy(self) -> Permission:
        """Copy the network condition object."""
        return Permission(name=self._name, state=self._state)


class Viewport(Rectangle):
    """Represents the size and relative position of a window viewport."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """The size and relative position of the window viewport.

        :param width: `<int>` The width of the viewport.
        :param height: `<int>` The height of the viewport.
        :param x: `<int>` The x-coordinate of the viewport.
        :param y: `<int>` The y-coordinate of the viewport.
        """
        super().__init__(width, height, x, y)

    # Special methods ---------------------------------------------------------------------
    def copy(self) -> Viewport:
        """Copy the viewport `<Viewport>`."""
        return super().copy()


class Window:
    """Represents a window of the session."""

    def __init__(self, handle: str, name: str | None = None) -> None:
        """The window of the session.

        :param handle: `<str>` The unique handle of the window.
        :param name: `<str/None>` The name of the window. Defaults to `uuid4()`.
        """
        # Window handle
        if isinstance(handle, str) and handle:
            self._handle: str = handle
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid window handle: {} {}.".format(
                    self.__class__.__name__, handle, type(handle)
                )
            )
        # Window name
        if isinstance(name, str) and name:
            self._name: str = name
        elif name is None:
            self._name: str = uuid4().hex
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid window name: {} {}.".format(
                    self.__class__.__name__, name, type(name)
                )
            )

    # Properties --------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Access the name of the window `<str>`."""
        return self._name

    @property
    def handle(self) -> str:
        """Access the unique handle of the window `<str>`."""
        return self._handle

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<Window (name='%s', handle='%s')>" % (self._name, self._handle)

    def __hash__(self) -> int:
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, str):
            return self._name == __o
        elif isinstance(__o, Window):
            return self._name == __o._name and self._handle == __o._handle
        else:
            return False

    def __bool__(self) -> bool:
        return True

    def __del__(self):
        self._name = None
        self._handle = None

    def copy(self) -> Window:
        """Copy the window object."""
        return Window(self._handle, name=self._name)


class WindowRect(Rectangle):
    """Represents the size and relative position of a window."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """The size and relative position of the window.

        :param width: `<int>` The width of the window.
        :param height: `<int>` The height of the window.
        :param x: `<int>` The x-coordinate of the window.
        :param y: `<int>` The y-coordinate of the window.
        """
        super().__init__(width, height, x, y)

    # Special methods ---------------------------------------------------------------------
    def copy(self) -> WindowRect:
        """Copy the window rectangle `<WindowRect>`."""
        return super().copy()


# Session -----------------------------------------------------------------------------------------
class Session:
    """Represents a session of the browser."""

    def __init__(self, options: BaseOptions, service: BaseService) -> None:
        """The session of the browser.

        :param options: `<BaseOptions>` The browser options.
        :param service: `<BaseService>` The webdriver service.
        """
        # Options
        self._options: BaseOptions = options
        self._browser_location: str = self._options.browser_location
        self._browser_version: str = self._options.browser_version
        # Service
        self._service: BaseService = service
        # Connection
        self._conn: Connection | None = None
        # Vender prefix
        self._vendor: dict[str, str] = {"vendorPrefix": self._options.VENDOR_PREFIX}
        # Session
        self._id: str | None = None
        self._base_url: str | None = None
        self._body: dict[str, str] | None = None
        self._timeouts: Timeouts | None = None
        self._session_timeout: int | float = options._session_timeout
        # Window
        self._window_by_name: dict[str, Window] = {}
        self._window_by_handle: dict[str, Window] = {}
        # Script
        self._script_by_name: dict[str, JavaScript] = {}
        # Status
        self.__closed: bool = False

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> BaseOptions:
        """Access the browser options `<BaseOptions>`."""
        return self._options

    @property
    def browser_version(self) -> Version:
        """Access the browser binary version of the session `<Version>`."""
        return self._browser_version

    @property
    def browser_location(self) -> str:
        """Access the browser binary location of the session `<str>`."""
        return self._browser_location

    @property
    def service(self) -> BaseService:
        """Access the webdriver service `<BaseService>`."""
        return self._service

    @property
    def driver_version(self) -> Version:
        """Access the webdriver binary version of the session `<Version>`."""
        return self._service._driver_version

    @property
    def driver_location(self) -> str:
        """Access the webdriver binary location of the session `<str>`."""
        return self._service._driver_location

    @property
    def connection(self) -> Connection:
        """Access the session connection `<Connection>`."""
        return self._conn

    @property
    def id(self) -> str:
        """Access the ID of the session `<str>`."""
        return self._id

    @property
    def base_url(self) -> str:
        """Access the base `service` URL of the session `<str>`."""
        return self._base_url

    # Execute -----------------------------------------------------------------------------
    async def execute_command(
        self,
        command: str,
        body: dict | None = None,
        keys: dict | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Executes a command from the session.

        :param command: `<str>` The command to execute.
        :param body: `<dict/None>` The body of the command. Defaults to `None`.
        :param keys: `<dict/None>` The keys to substitute in the command. Defaults to `None`.
        :param timeout: `<int/float/None>` Session timeout for command execution. Defaults to `None`.
            This arguments overwrites the default `options.session_timeout`,
            which is designed to cope with a frozen session due to unknown
            errors. For more information about session timeout, please refer
            to the documentation of `options.session_timeout` attribute.

        :return: `<dict>` The response from the command.
        """
        return await self._conn.execute(
            self._base_url,
            command,
            body=body | self._body if body else self._body,
            keys=keys,
            timeout=timeout,
        )

    # Start / Quit ------------------------------------------------------------------------
    async def start(self) -> Window:
        """Start the session, and return the default `<Window>`."""
        # Check status
        if self.__closed:
            raise errors.InvalidSessionError(
                "<{}>\nThe session has already been terminated. "
                "Use `acquire()` method to start a new session.".format(
                    self.__class__.__name__
                )
            )

        # Start the service
        await self._service.start()
        self._conn = Connection(self._service.session, self._session_timeout)

        # Start the session
        return await self._start_session("default")

    async def quit(self) -> None:
        """Quit (close) the session."""
        # Already closed
        if self.__closed:
            return None  # exit

        # Close session
        try:
            cancelled = False
            exceptions = []

            # . stop session
            while True:
                try:
                    await self.execute_command(Command.QUIT, timeout=1)
                    break
                except CancelledError:
                    cancelled = True
                except errors.SessionClientError:
                    if not self._service.running:
                        break
                except errors.SessionTimeoutError:
                    break
                except Exception as err:
                    exceptions.append(str(err))
                    break

            # . stop service
            try:
                await self._service.stop()
            except CancelledError:
                cancelled = True
            except Exception as err:
                exceptions.append(str(err))

            # . raise errors
            if cancelled:
                raise CancelledError
            if exceptions:
                raise errors.SessionQuitError(
                    "<{}>\nSession not quit gracefully: {}\n{}".format(
                        self.__class__.__name__, self._id, "\n".join(exceptions)
                    )
                )

        # Cleanup
        finally:
            self._collect_garbage()

    async def _start_session(self, name: str = "default") -> Window:
        """(Internal) Start the default window of session, and returns it `<Window>`.
        This method should only be called when session service is started or all
        the windows of the session are closed.

        :param name: `<str>` The name of the first window for the session. Defaults to `'default'`.
        """

        def parse_session_id(res: dict) -> str:
            # Get session id - level 1
            if session_id := res.get("sessionId"):
                return session_id  # exit

            # Get session id - level 2
            res = res.get("value", res)
            if session_id := res.get("sessionId"):
                return session_id  # exit

            # Raise error
            res = res.get("error", res)
            if isinstance(res, dict):
                raise errors.InvalidSessionError(
                    "<{}>\nFailed to create new session: {}\n"
                    "Message: {}".format(
                        self.__class__.__name__,
                        res.get("error", "Unknown"),
                        res.get("message", "Unknown"),
                    )
                )
            else:
                raise errors.InvalidSessionError(
                    "<{}>\nFailed to create new session: {}".format(
                        self.__class__.__name__, res
                    )
                )

        # Validate service
        if not self._service.running:
            raise errors.InvalidSessionError(
                "<{}>\nFailed to create new session. Please `start()` "
                "the service of the session first.".format(self.__class__.__name__)
            )

        # Start session
        res = await self._conn.execute(
            "",
            Command.NEW_SESSION,
            body={"capabilities": {"alwaysMatch": self._options.capabilities}},
            timeout=10,
        )
        self._id = parse_session_id(res)
        self._base_url = "/session/" + self._id
        self._body = {"sessionId": self._id}

        # Set default window of the session
        handle = await self._active_window_handle()
        if not handle:
            raise errors.InvalidSessionError(
                "<{}>\nFailed to create new session: {}".format(
                    self.__class__.__name__, self._id
                )
            )
        return self._cache_window(handle, name)

    # Navigate ----------------------------------------------------------------------------
    async def load(
        self,
        url: str,
        timeout: int | float | None = None,
        retry: bool = False,
    ) -> None:
        """Load a web page in the actice window.

        :param url: URL to be loaded.

        :param timeout: `<int/float/None>` Session timeout for page loading. Defaults to `None`.
            This arguments overwrites the default `options.session_timeout`,
            which is designed to cope with a frozen session due to unknown
            errors. For more information about session timeout, please refer
            to the documentation of `options.session_timeout` attribute. If
            the webdriver fails to response in time, a `SessionTimeoutError`
            will be raised.

        :param retry: `<bool>` Whether to retry if failed to load the webpage. Defaults to `False`.
            Retries are attempted only when the `WebDriverTimeoutError` is
            raised due to native `pageLoad` timeout. The function does not
            retry on `SessionTimeoutError` (as mentioned above). The maximum
            retry limit is 10, and exceeding this limit without successful
            loading will eventually raise the `WebDriverTimeoutError`.

        ### Example:
        >>> await session.load("https://www.google.com")
        """
        if not retry:
            await self.execute_command(Command.GET, body={"url": url}, timeout=timeout)
            return None  # exit

        exc = None
        for _ in range(10):
            try:
                await self.execute_command(
                    Command.GET, body={"url": url}, timeout=timeout
                )
                return None  # exit
            except errors.WebDriverTimeoutError as err:
                exc = err
        raise exc

    async def refresh(
        self,
        timeout: int | float | None = None,
        retry: bool = False,
    ) -> None:
        """Refresh the active page window.

        :param timeout: `<int/float/None>` Session timeout for page loading. Defaults to `None`.
            This arguments overwrites the default `options.session_timeout`,
            which is designed to cope with a frozen session due to unknown
            errors. For more information about session timeout, please refer
            to the documentation of `options.session_timeout` attribute. If
            the webdriver fails to response in time, a `SessionTimeoutError`
            will be raised.

        :param retry: `<bool>` Whether to retry if failed to load the webpage. Defaults to `False`.
            Retries are attempted only when the `WebDriverTimeoutError` is
            raised due to native `pageLoad` timeout. The function does not
            retry on `SessionTimeoutError` (as mentioned above). The maximum
            retry limit is 10, and exceeding this limit without successful
            loading will eventually raise the `WebDriverTimeoutError`.

        ### Example:
        >>> await session.refresh()
        """
        if not retry:
            await self.execute_command(Command.REFRESH, timeout=timeout)
            return None  # exit

        exc = None
        for _ in range(10):
            try:
                await self.execute_command(Command.REFRESH, timeout=timeout)
                return None  # exit
            except errors.WebDriverTimeoutError as err:
                exc = err
        raise exc

    async def forward(self, timeout: int | float | None = None) -> None:
        """Navigate forwards in the browser history (if possible).

        :param timeout: `<int/float/None>` Session timeout for page loading. Defaults to `None`.
            This arguments overwrites the default `options.session_timeout`,
            which is designed to cope with a frozen session due to unknown
            errors. For more information about session timeout, please refer
            to the documentation of `options.session_timeout` attribute. If
            the webdriver fails to response in time, a `SessionTimeoutError`
            will be raised.

        ### Example:
        >>> await session.forward()
        """
        await self.execute_command(Command.GO_FORWARD, timeout=timeout)

    async def backward(self, timeout: int | float | None = None) -> None:
        """Navigate backwards in the browser history (if possible).

        :param timeout: `<int/float/None>` Session timeout for page loading. Defaults to `None`.
            This arguments overwrites the default `options.session_timeout`,
            which is designed to cope with a frozen session due to unknown
            errors. For more information about session timeout, please refer
            to the documentation of `options.session_timeout` attribute. If
            the webdriver fails to response in time, a `SessionTimeoutError`
            will be raised.

        ### Example:
        >>> await session.backward()
        """
        await self.execute_command(Command.GO_BACK, timeout=timeout)

    # Information -------------------------------------------------------------------------
    @property
    async def url(self) -> str:
        """Access the URL of the active page window `<str>`.

        ### Example:
        >>> await session.url # "https://www.google.com/"
        """
        res = await self.execute_command(Command.GET_CURRENT_URL)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse page url from "
                "response: {}".format(self.__class__.__name__, err)
            ) from err

    async def wait_until_url(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the URL of the active page window satisfies the given condition.

        :param condition: `<str>` The condition the URL needs to satisfy.
            Excepted values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
        :param value: `<str>` The value of the condition.
        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return: `<bool>` True if the URL satisfies the condition, False if timeout.

        ### Example:
        >>> await session.load("https://www.google.com/")
            await session.wait_until_url("contains", "google", 5)  # True / False
        """

        async def equals() -> bool:
            return await self.url == value

        async def contains() -> bool:
            return value in await self.url

        async def startswith() -> bool:
            return (await self.url).startswith(value)

        async def endswith() -> bool:
            return (await self.url).endswith(value)

        # Validate value & condition
        value = self._validate_wait_str_value(value)
        if condition == "equals":
            condition_checker = equals
        elif condition == "contains":
            condition_checker = contains
        elif condition == "startswith":
            condition_checker = startswith
        elif condition == "endswith":
            condition_checker = endswith
        else:
            self._raise_invalid_wait_condition(condition)

        # Check condition
        if await condition_checker():
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await condition_checker():
                return True
        return False

    @property
    async def title(self) -> str:
        """Access the title of the active page window `<str>`.

        ### Example:
        >>> await session.title # "Google"
        """
        res = await self.execute_command(Command.GET_TITLE)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse page title from "
                "response: {}".format(self.__class__.__name__, err)
            ) from err

    async def wait_until_title(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the title of the active page window satisfies the given condition.

        :param condition: `<str>` The condition the title needs to satisfy.
            Excepted values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
        :param value: `<str>` The value of the condition.
        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return: `<bool>` True if the title satisfies the condition, False if timeout.

        >>> await session.load("https://www.google.com/")
            await session.wait_until_title("contains", "Google", 5)  # True / False
        """

        async def equals() -> bool:
            return await self.title == value

        async def contains() -> bool:
            return value in await self.title

        async def startswith() -> bool:
            return (await self.title).startswith(value)

        async def endswith() -> bool:
            return (await self.title).endswith(value)

        # Validate value & condition
        value = self._validate_wait_str_value(value)
        if condition == "equals":
            condition_checker = equals
        elif condition == "contains":
            condition_checker = contains
        elif condition == "startswith":
            condition_checker = startswith
        elif condition == "endswith":
            condition_checker = endswith
        else:
            self._raise_invalid_wait_condition(condition)

        # Check condition
        if await condition_checker():
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await condition_checker():
                return True
        return False

    @property
    async def viewport(self) -> Viewport:
        """Access the size and relative position of the
        viewport for active page window `<Viewport>`.

        ### Example:
        >>> viewport = await session.viewport
            # <Viewport (width=1200, height=776, x=0, y=2143)>
        """
        try:
            res = await self._execute_script(javascript.GET_PAGE_VIEWPORT)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to request page viewport: "
                "{}".format(self.__class__.__name__, err)
            ) from err
        try:
            return Viewport(**res)
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid page viewport response: "
                "{}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def page_width(self) -> int:
        """Access the width of the active page window `<int>`.

        ### Example:
        >>> await session.page_width # 1200
        """
        try:
            return await self._execute_script(javascript.GET_PAGE_WIDTH)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to request page width: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    @property
    async def page_height(self) -> int:
        """Access the height of the active page window `<int>`.

        ### Example:
        >>> await session.page_height # 800
        """
        try:
            return await self._execute_script(javascript.GET_PAGE_HEIGHT)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to request page height: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    @property
    async def page_source(self) -> str:
        """Access the source of the active page window `<str>`.

        ### Example:
        >>> source = await session.page_source
            # "<!DOCTYPE html><html ..."
        """
        res = await self.execute_command(Command.GET_PAGE_SOURCE)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse page source from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def take_screenshot(self) -> bytes:
        """Take a screenshot of the active page window `<bytes>`.

        ### Example:
        >>> screenshot = await session.take_screenshot()
            # b'iVBORw0KGgoAAAANSUhEUgAA...'
        """
        res = await self.execute_command(Command.SCREENSHOT)
        try:
            return self._decode_base64(res["value"], "ascii")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse screenshot data from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid screenshot response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    async def save_screenshot(self, path: str) -> bool:
        """Take & save the screenshot of the active page window
        into a local PNG file.

        :param path: `<str>` The path to save the screenshot. e.g. `~/path/to/screenshot.png`.
        :return `<bool>`: True if the screenshot has been saved, False if failed.

        ### Example:
        >>> await session.save_screenshot("~/path/to/screenshot.png")  # True / False
        """
        # Validate screenshot path
        try:
            path = validate_save_file_path(path, ".png")
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nSave screenshot 'path' error: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

        # Take & save screenshot
        data = None
        try:
            # . take screenshot
            data = await self.take_screenshot()
            if not data:
                return False
            # . save screenshot
            try:
                with open(path, "wb") as file:
                    file.write(data)
                return True
            except Exception as err:
                logger.error(
                    "<{}> Failed to save screenshot: "
                    "{}".format(self.__class__.__name__, err)
                )
                return False
        finally:
            del data

    async def print_page(
        self,
        orientation: Literal["portrait", "landscape"] | None = None,
        scale: int | float | None = None,
        background: bool | None = None,
        page_width: int | float | None = None,
        page_height: int | float | None = None,
        margin_top: int | float | None = None,
        margin_bottom: int | float | None = None,
        margin_left: int | float | None = None,
        margin_right: int | float | None = None,
        shrink_to_fit: bool | None = None,
        page_ranges: list[str] | None = None,
    ) -> bytes:
        """Print the active page window into PDF.

        :param orientation: `<str>` The print orientation. Accepts: "portrait", "landscape".
        :param scale: `<int/float>` The scale of the page rendering. Must between 0.1 - 2.
        :param background: `<bool>` Whether to print the CSS backgrounds.
        :param page_width: `<int/float>` Paper width.
        :param page_height: `<int/float>` Paper height.
        :param margin_top: `<int/float>` Top margin size.
        :param margin_bottom: `<int/float>` Bottom margin size.
        :param margin_left: `<int/float>` Left margin size.
        :param margin_right: `<int/float>` Right margin size.
        :param shrink_to_fit: `<int/float>` Whether to scale page to fit paper size.
        :param page_ranges: `<list[str]>` Paper ranges to print, e.g., ['1-5', '8', '11-13'].
        :return `<bytes>`: The page PDF data.

        ### Example:
        >>> await session.print_page()
            # b'iVBORw0KGgoAAAANSUhEUgAA...'
        """

        def orie_validator(param: str, value: str) -> bool:
            if value is None:
                return False
            if value not in Constraint.PAGE_ORIENTATIONS:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid print {}: {}. Available options: {}".format(
                        param, repr(value), sorted(Constraint.PAGE_ORIENTATIONS)
                    )
                )
            return True

        def scal_validator(param: str, value: float) -> bool:
            if not nums_validator(param, value):
                return False
            if not 0.1 <= value <= 2:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid print {}: {}. Must between 0.1 and 2.".format(
                        self.__class__.__name__, param, repr(value)
                    )
                )
            return True

        def bool_validator(param: str, value: bool) -> bool:
            if value is None:
                return False
            if not isinstance(value, bool):
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid {} argument: {} {}. Must be a boolean.".format(
                        self.__class__.__name__, param, repr(value), type(value)
                    )
                )
            return True

        def nums_validator(param: str, value: float) -> bool:
            if value is None:
                return False
            if not isinstance(value, (int, float)):
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid {} argument: {} {}. Must be an integer or float.".format(
                        self.__class__.__name__, param, repr(value), type(value)
                    )
                )
            if value < 0:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid {} argument: {}. Must be greater than 0.".format(
                        self.__class__.__name__, param, repr(value)
                    )
                )
            return True

        def list_validator(param: str, value: list[str]) -> bool:
            if value is None:
                return False
            if not isinstance(value, list):
                raise errors.InvalidArgumentError(
                    "{}\nInvalid {} argument: {} {}. Must be a list.".format(
                        self.__class__.__name__, param, repr(value), type(value)
                    )
                )
            return True

        # Print options
        options = {}
        if orie_validator("orientation", orientation):
            options["orientation"] = orientation
        if scal_validator("scale", scale):
            options["scale"] = scale
        if bool_validator("background", background):
            options["background"] = background
        if nums_validator("page_width", page_width):
            options["page"] = options.get("page", {}) | {"width": page_width}
        if nums_validator("page_height", page_height):
            options["page"] = options.get("page", {}) | {"height": page_height}
        if nums_validator("margin_top", margin_top):
            options["margin"] = options.get("margin", {}) | {"top": margin_top}
        if nums_validator("margin_bottom", margin_bottom):
            options["margin"] = options.get("margin", {}) | {"bottom": margin_bottom}
        if nums_validator("margin_left", margin_left):
            options["margin"] = options.get("margin", {}) | {"left": margin_left}
        if nums_validator("margin_right", margin_right):
            options["margin"] = options.get("margin", {}) | {"right": margin_right}
        if bool_validator("shrink_to_fit", shrink_to_fit):
            options["shrinkToFit"] = shrink_to_fit
        if list_validator("page_ranges", page_ranges):
            options["pageRanges"] = [str(i) for i in page_ranges]

        # Print request
        res = await self.execute_command(Command.PRINT_PAGE, body=options)
        try:
            return self._decode_base64(res["value"], "ascii")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse print data from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid print response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    async def save_page(
        self,
        path: str,
        orientation: Literal["portrait", "landscape"] | None = None,
        scale: int | float | None = None,
        background: bool | None = None,
        page_width: int | float | None = None,
        page_height: int | float | None = None,
        margin_top: int | float | None = None,
        margin_bottom: int | float | None = None,
        margin_left: int | float | None = None,
        margin_right: int | float | None = None,
        shrink_to_fit: bool | None = None,
        page_ranges: list[str] | None = None,
    ) -> bool:
        """Print & save the active page window into a local PDF file.

        :param path: `<str>` The path to save the PDF. e.g. `~/path/to/screenshot.png`.
        :param orientation: `<str>` The print orientation. Accepts: "portrait", "landscape".
        :param scale: `<int/float>` The scale of the page rendering. Must between 0.1 - 2.
        :param background: `<bool>` Whether to print the CSS backgrounds.
        :param page_width: `<int/float>` Paper width.
        :param page_height: `<int/float>` Paper height.
        :param margin_top: `<int/float>` Top margin size.
        :param margin_bottom: `<int/float>` Bottom margin size.
        :param margin_left: `<int/float>` Left margin size.
        :param margin_right: `<int/float>` Right margin size.
        :param shrink_to_fit: `<int/float>` Whether to scale page to fit paper size.
        :param page_ranges: `<list[str]>` Paper ranges to print, e.g., ['1-5', '8', '11-13'].
        :return `<bool>`: True if the PDF has been saved, False if failed.

        ### Example:
        >>> await session.save_page("~/path/to/screenshot.pdf")  # True / False
        """
        # Validate pdf path
        try:
            path = validate_save_file_path(path, ".pdf")
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nSave page 'path' error: {}".format(self.__class__.__name__, err)
            ) from err

        # Print & save pdf
        data = None
        try:
            # . print pdf
            data = await self.print_page(
                orientation=orientation,
                scale=scale,
                background=background,
                page_width=page_width,
                page_height=page_height,
                margin_top=margin_top,
                margin_bottom=margin_bottom,
                margin_left=margin_left,
                margin_right=margin_right,
                shrink_to_fit=shrink_to_fit,
                page_ranges=page_ranges,
            )
            if not data:
                return False
            # . save pdf
            try:
                with open(path, "wb") as file:
                    file.write(data)
                return True
            except Exception as err:
                logger.error(
                    "<{}> Failed to save PDF: {}".format(self.__class__.__name__, err)
                )
                return False
        finally:
            del data

    # Timeouts ----------------------------------------------------------------------------
    @property
    async def timeouts(self) -> Timeouts:
        """Access the timeouts of the current session `<Timeouts>`.

        ### Timeouts explain:

        - implicit: The amount of time the current sessions will wait when
        searching for an element if not immediately present.

        - pageLoad: The amount of time the current sessions will wait for
        a page load to complete before raising an error.

        - script: The amount of time the current sessions will wait for an
        asynchronous script to finish execution before raising an error.

        ### Example:
        >>> timeouts = await options.timeouts
            # <Timeouts (implicity=0, pageLoad=300000, script=30000, unit='ms')>
        """
        if self._timeouts is None:
            await self._refresh_timeouts()
        return self._timeouts.copy()

    async def set_timeouts(
        self,
        implicit: int | float | None = None,
        pageLoad: int | float | None = None,
        script: int | float | None = None,
    ) -> Timeouts:
        """Sets the timeouts of the current session.

        ### Notice
        All of the timeout values should be in `SECONDS` instead of milliseconds
        (as the webdriver protocol requires). The values will be converted to
        milliseconds automatically.

        :param implicit: `<int/float/None>` Total `seconds` the current session
        should wait when searching for an element if not immediately present.
        If `None (default)`, keep the current implicit timeout.

        :param pageLoad: `<int/float/None>` Total `seconds` the current session
        should wait for a page load to complete before returning an error. if
        `None (default)`, keep the current pageLoad timeout.

        :param script: `<int/float/None>` Total `seconds` the current session
        should wait for an asynchronous script to finish execution before
        returning an error. if `None (default)`, keep the current script timeout.

        :return `<Timeouts>`: The timeouts after update.

        ### Example:
        >>> timeouts = await session.set_timeouts(
                implicit=0.1, pageLoad=30, script=3
            )
            # <Timeouts (implicity=100, pageLoad=30000, script=3000, unit='ms')>
        """
        # Update timeouts
        timeouts = await self.timeouts
        if implicit is not None:
            timeouts.implicit = implicit
        if pageLoad is not None:
            timeouts.pageLoad = pageLoad
        if script is not None:
            timeouts.script = script
        await self._conn.execute(
            self._base_url, Command.SET_TIMEOUTS, body=timeouts.dict
        )
        # Refresh & return timeouts
        await self._refresh_timeouts()
        return self._timeouts.copy()

    async def reset_timeouts(self) -> Timeouts:
        """Resets the timeouts of the current session to the orginal
        options values, and returns the reset `<Timeouts>`.

        ### Example:
        >>> timeouts = await session.reset_timeouts()
            # <Timeouts (implicity=0, pageLoad=300000, script=30000, unit='ms')>
        """
        # Reset timeouts
        await self._conn.execute(
            self._base_url,
            Command.SET_TIMEOUTS,
            body=self._options.timeouts.dict,
        )
        # Refresh & return timeouts
        await self._refresh_timeouts()
        return self._timeouts.copy()

    async def _refresh_timeouts(self) -> None:
        """(Internal) Refresh the timeouts of the current session."""
        res = await self.execute_command(Command.GET_TIMEOUTS)
        try:
            self._timeouts = Timeouts(**res["value"], unit="ms")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse timeouts from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid timeouts response: "
                "{}".format(self.__class__.__name__, res["value"])
            ) from err

    async def _get_timeouts(self) -> Timeouts:
        """(Internal) Get the cached timeouts of the current session."""
        if self._timeouts is None:
            await self._refresh_timeouts()
        return self._timeouts

    # Cookies -----------------------------------------------------------------------------
    @property
    async def cookies(self) -> list[Cookie]:
        """Access all the cookies of the active page window `<list[Cookie]>`.

        ### Example:
        >>> cookies = await session.cookies
            # [
            #    <Cookie (name='ZFY', data={'domain': '.baidu.com', 'expiry': 1720493275, ...})>
            #    <Cookie (name='ZFK', data={'domain': '.baidu.com', 'expiry': 1720493275, ...})>
            #    ...
            # ]
        """
        # Request cookies
        res = await self.execute_command(Command.GET_ALL_COOKIES)
        try:
            cookies = res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse cookies data from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        # Create cookies
        return [self._create_cookie(cookie) for cookie in cookies]

    async def get_cookie(self, name: str | Cookie) -> Cookie | None:
        """Get a specific cookie from the active page window.

        :param name: `<str/Cookie>` The name of the cookie or a `<Cookie>` instance.
        :return `<Cookie/None>`: The specified cookie, or `None` if not found.

        ### Example:
        >>> cookie = await session.get_cookie("ZFY")
            # <Cookie (name='ZFY', data={'domain': '.baidu.com', 'expiry': 1720493275, ...})>
        """
        # Request cookie
        try:
            res = await self.execute_command(
                Command.GET_COOKIE,
                keys={"name": self._validate_cookie_name(name)},
            )
        except errors.CookieNotFoundError:
            return None
        # Create cookie
        try:
            return self._create_cookie(res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse cookie data from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def add_cookie(self, cookie: dict[str, Any] | Cookie) -> Cookie:
        """Add a cookie to the active page window.

        :param cookie: `<dict/Cookie>` Cookie as a dictionary or a `<Cookie>` instance.
        :return `<Cookie>`: The newly added cookie.

        ### Example:
        >>> cookie = await session.add_cookie({'name' : 'foo', 'value' : 'bar'})
            # <Cookie (name='foo', data={'name': 'foo', 'value': 'bar'}>
        """
        # Construct cookie
        if isinstance(cookie, Cookie):
            pass
        elif isinstance(cookie, dict):
            cookie = self._create_cookie(cookie)
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'cookie' arguement: {}. Must be "
                "a dictionary or `<Cookie>` instance".format(
                    self.__class__.__name__, cookie
                )
            )
        # Execute & return
        await self.execute_command(Command.ADD_COOKIE, {"cookie": cookie.dict})
        return await self.get_cookie(cookie)

    async def delete_cookie(self, name: str | Cookie) -> None:
        """Delete a cookie from the active page window.

        :param name: `<str/Cookie>` The name of the cookie or a `<Cookie>` instance.

        ### Example:
        >>> await session.delete_cookie("ZFY")
        """
        await self.execute_command(
            Command.DELETE_COOKIE,
            keys={"name": self._validate_cookie_name(name)},
        )

    async def delete_cookies(self) -> None:
        """Delete all cookies from the active page window.

        ### Example:
        >>> await session.delete_cookies()
        """
        await self.execute_command(Command.DELETE_ALL_COOKIES)

    def _validate_cookie_name(self, name: Any) -> str:
        """(Internal) Validate the name of a cookie `<str>`."""
        if isinstance(name, str):
            return name
        elif isinstance(name, Cookie):
            return name.name
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid cookie 'name': {} {}. Must be "
                "a string or `<Cookie>` instance.".format(
                    self.__class__.__name__, repr(name), type(name)
                )
            )

    def _create_cookie(self, cookie: dict[str, Any]) -> Cookie:
        """(Internal) Create the cookie `<Cookie>`."""
        try:
            return Cookie(**cookie)
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid cookie: {}".format(self.__class__.__name__, cookie)
            ) from err

    # Window ------------------------------------------------------------------------------
    @property
    async def windows(self) -> list[Window]:
        """Access all the open windows of the session `<list[Window]>`.

        ### Example:
        >>> windows = await session.windows
            # [
            #    <Window (name='default', handle='CCEF49C484842CFE1AB855ECCA164858')>
            #    <Window (name='window1', handle='CCEF49C484842CFE1AB855ECCA164858')>
            #    ...
            # ]
        """
        # Request all windows
        try:
            res = await self.execute_command(Command.W3C_GET_WINDOW_HANDLES)
        except errors.InvalidSessionError:
            # . all windows are closed
            self._window_by_name.clear()
            self._window_by_handle.clear()
            return []
        try:
            handles = res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse window handles from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

        # Remove closed windows
        for handle in list(self._window_by_handle):
            if handle not in handles:
                win = self._window_by_handle.pop(handle)
                self._window_by_name.pop(win.name, None)

        # Cache new windows
        for handle in handles:
            if handle not in self._window_by_handle:
                self._cache_window(handle)

        # Return windows
        return list(self._window_by_handle.values())

    @property
    async def active_window(self) -> Window | None:
        """Access the active (focused) window of the session `<Window>`.
        Returns `None` if no window is active.

        ### Example:
        >>> win = await session.active_window
            # <Window (name='default', handle='CCEF49C484842CFE1AB855ECCA164858')>
        """
        # Request active window handle
        handle = await self._active_window_handle()

        # No active window
        if not handle:
            return None
        # Match cached window
        elif handle in self._window_by_handle:
            return self._window_by_handle[handle]
        # Cache as new window
        else:
            return self._cache_window(handle)

    async def get_window(self, window: str | Window) -> Window | None:
        """Get a specific open window of the session.

        :param window: `<str/Window>` Accepts three kinds of input:
            - `<str>`: The name of the window.
            - `<str>`: The handle of the window.
            - `<Window>`: A window instance.

        :return `<Window>`: The matched open window of the session, or `None` if not found.

        ### Example:
        >>> win = await session.get_window("default")
            # <Window (name='default', handle='CCEF49C484842CFE1AB855ECCA164858')>
        """
        # Match cache by name
        if window in self._window_by_name:
            return self._window_by_name[window]
        # Match cache by handle
        elif window in self._window_by_handle:
            return self._window_by_handle[window]
        # Match from session
        else:
            return await self._match_session_window(window)

    async def new_window(
        self,
        name: str,
        win_type: Literal["window", "tab"] = "tab",
        switch: bool = True,
    ) -> Window:
        """Create (open) a new window for the session.

        :param name: `<str>` The name of the new window.
        :param win_type: `<str>` The type of the window to create, accepts: `'tab'` or `'window'`. Defaults to `'tab'`.
        :param switch: `<bool>` Whether to switch focus to the new window. Defaults to `True`.
        :return `<Window>`: The newly created window.

        ### Notice
        In the scenario when all windows are closed, this method will
        automatically start a new session with the same service. However,
        the session ID will be updated and the new window name will be
        reset to `'default'`.

        ### Example:
        >>> win = await session.new_window("new", "tab")
            # <Window (name='new', handle='B89293FA79B6389AF1657B972FBD6B26')>
        """
        # Validate window type & name
        if win_type not in Constraint.WINDOW_TYPES:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid window win_type: {}. "
                "Available options: {}".format(
                    self.__class__.__name__,
                    repr(win_type),
                    sorted(Constraint.WINDOW_TYPES),
                )
            )
        name = self._validate_window_name(name)

        # Create & cache new window
        try:
            res = await self.execute_command(
                Command.NEW_WINDOW, body={"type": win_type}
            )
        except errors.InvalidSessionError as err:
            # . All windows are closed: start a new session
            self._window_by_name = {}
            self._window_by_handle = {}
            return await self._start_session(name)
        try:
            win = self._cache_window(res["value"]["handle"], name=name)
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse new window handle from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid new window response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            )

        # Return (switch) window
        return await self.switch_window(win) if switch else win

    async def switch_window(self, window: str | Window) -> Window:
        """Switch to a specific open window of the session.

        :param window: `<str/Window>` Accepts three kinds of input:
            - `<str>`: The name of the window.
            - `<str>`: The handle of the window.
            - `<Window>`: A window instance.

        :return `<Window>`: The new focused window.

        ### Example:
        >>> win = await session.switch_window("new")
            # <Window (name='new', handle='B89293FA79B6389AF1657B972FBD6B26')>
        """
        # Get existing window
        win = await self.get_window(window)
        if not win:
            raise errors.WindowNotFountError(
                "<{}>\nCan't switch to window {}. "
                "Window not found.".format(self.__class__.__name__, repr(window))
            )

        # Switch window
        try:
            # . switch to specified window
            await self.execute_command(
                Command.SWITCH_TO_WINDOW, body={"handle": win.handle}
            )
            return win
        except errors.WindowNotFountError as err:
            win = await self._match_session_window(window)
            # . fallback to a session window rematch
            if win:
                await self.execute_command(
                    Command.SWITCH_TO_WINDOW, body={"handle": win.handle}
                )
                return win
            # . window not found
            raise err

    async def rename_window(self, window: str | Window, new_name: str) -> Window:
        """Rename a specific opened window.

        ### Notice
        This method does not affect or make changes to the webdriver,
        but simple changes the name of the window cached in the program.

        :param window: `<str/Window>` Accepts three kinds of input:
            - `<str>`: The name of the window.
            - `<str>`: The handle of the window.
            - `<Window>`: A window instance.

        :param new_name: `<str>` The new name for the window.
        :return `<Window>`: The window after name update.

        ### Example:
        >>> # Create a new window
            win = await session.new_window("new")
            # <Window (name='new', handle='9C03D8A1739E049EF6EE92ECE4032CD1')>

        >>> # Rename the window
            win = await session.rename_window("new", "new_renamed")
            # <Window (name='new_renamed', handle='9C03D8A1739E049EF6EE92ECE4032CD1')>
        """
        # Validate name
        name = self._validate_window_name(new_name)

        # Get existing window
        win = await self.get_window(window)
        if not win:
            raise errors.WindowNotFountError(
                "<{}>\nCannot rename window {}. Window not found".format(
                    self.__class__.__name__, repr(window)
                )
            )
        handle = win.handle

        # Remove old & cache new window
        self._remove_window(win)
        return self._cache_window(handle, name=name)

    async def close_window(
        self,
        switch_to: str | Window | None = None,
    ) -> Window | None:
        """Close the active (focus) window.

        :param switch_to: `<str/Window/None>` The window to switch to after closing the active window. Accepts four kinds of input:
            - `None (default)`: Switch to a random open window.
            - `<str>`: Switch to an open window by window name.
            - `<str>`: Switch to an open window by window handle.
            - `<Window>`: Switch to an open window by window instance.
            - `*Notice*` If the specified window does not exist, will automatically
              switch to a random open window.

        :return `<Window>`: The new active (focus) window, or `None` if all windows are closed.

        ### Example:
        >>> win = await session.close_window()
            # <Window (name='default', handle='CCEF49C484842CFE1AB855ECCA164858')>
        """
        # Get the active window
        if not (win := await self.active_window):
            return None  # exit: all windows are closed

        # Close & remove the window
        await self.execute_command(Command.CLOSE)
        self._remove_window(win)

        # Switch to specified window
        if switch_to is not None:
            try:
                return await self.switch_window(switch_to)
            except errors.InvalidSessionError:
                return None  # exit: all windows are closed
            except errors.WindowNotFountError:
                pass  # specified window not found -> switch to a random window

        # Switch to a random window
        try:
            if wins := await self.windows:
                await self.switch_window(wins[0])
                return wins[0]
            else:
                return None  # exit: all windows are closed
        except (errors.InvalidSessionError, errors.WindowNotFountError):
            return None  # exit: all windows are closed

    async def _active_window_handle(self) -> str | None:
        """(Internal) Request the handle of the active (focus) window `<str>`.
        Returns `None` if all windows are closed.
        """
        # Get window handle
        try:
            res = await self.execute_command(Command.W3C_GET_CURRENT_WINDOW_HANDLE)
        except (errors.InvalidSessionError, errors.WindowNotFountError):
            return None
        # Return window handle
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse window handle from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def _match_session_window(self, window: str | Window) -> Window | None:
        """(Internal) Match window from the current session `<Window>`."""
        for win in await self.windows:
            if window == win.handle or window == win.name:
                return win
        return None

    def _cache_window(self, handle: str, name: str = None) -> Window:
        """(Internal) Cache the new window `<Window>`."""
        win = Window(handle, name=name)
        self._window_by_name[win.name] = win
        self._window_by_handle[win.handle] = win
        return win

    def _remove_window(self, window: str | Window) -> bool:
        """(Internal) Remove cached window `<bool>`."""
        if window in self._window_by_name:
            win = self._window_by_name.pop(window)
            self._window_by_handle.pop(win.handle, None)
            return True
        elif window in self._window_by_handle:
            win = self._window_by_handle.pop(window)
            self._window_by_name.pop(win.name, None)
            return True
        else:
            return False

    def _validate_window_name(self, name: Any) -> str:
        """(Internal) Validate window name `<str>`."""
        if not isinstance(name, str) or not name:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid window name: {} {}.".format(
                    self.__class__.__name__, repr(name), type(name)
                )
            )
        if name in self._window_by_name:
            raise errors.InvalidArgumentError(
                "<{}>\nWindow name '{}' has been taken. "
                "Please choose another one.".format(self.__class__.__name__, name)
            )
        return name

    # Window Rect -------------------------------------------------------------------------
    @property
    async def window_rect(self) -> WindowRect:
        """Access the size and relative position of
        the active window `<WindowRect>`.

        ### Example:
        >>> rect = await session.window_rect
            # <WindowRect (width=1200, height=900, x=22, y=60)>
        """
        res = await self.execute_command(Command.GET_WINDOW_RECT)
        return self._create_window_rect(res)

    async def set_window_rect(
        self,
        width: int | None = None,
        height: int | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> WindowRect:
        """Set the size and relative position of the active window.

        :param width: `<int/None>` The new width of the window. If `None (default)`, keep the current width.
        :param height: `<int/None>` The new height of the window. If `None (default)`, keep the current height.
        :param x: `<int/None>` The new x coordinate of the window. If `None (default)`, keep the current x coordinate.
        :param y: `<int/None>` The new y coordinate of the window. If `None (default)`, keep the current y coordinate.

        ### Example:
        >>> rect = await session.set_window_rect(800, 500, 22, 60)
            # <WindowRect (width=800, height=500, x=22, y=60)>
        """
        # Update from current rect
        rect = await self.window_rect
        rect.width = width
        rect.height = height
        rect.x = x
        rect.y = y

        # Set new window rect
        res = await self._change_windows_state(Command.SET_WINDOW_RECT, rect.dict, 20)
        return self._create_window_rect(res)

    async def maximize_window(self) -> WindowRect:
        """Maximize the active window.

        :return: `<WindowRect>` The window ractangle after maximization.

        ### Example:
        >>> rect = await session.maximize_window()
            # <WindowRect (width=1512, height=944, x=0, y=38)>
        """
        res = await self._change_windows_state(Command.W3C_MAXIMIZE_WINDOW, None, 20)
        return self._create_window_rect(res)

    async def minimize_window(self) -> None:
        """Minimize the active window.

        ### Example:
        >>> await session.minimize_window()
        """
        await self._change_windows_state(Command.MINIMIZE_WINDOW, None, 20)

    async def fullscreen_window(self) -> None:
        """Set the active window to fullscreen.

        ### Example:
        >>> await session.fullscreen_window()
        """
        await self._change_windows_state(Command.FULLSCREEN_WINDOW, None, 20)

    async def _change_windows_state(
        self,
        command: str,
        body: dict | None,
        retry: int,
    ) -> Any:
        """(Internal) Change the state of the active window with retry."""
        window_state_retry = 0
        while True:
            try:
                return await self.execute_command(command, body=body)
            except errors.ChangeWindowStateError:
                if window_state_retry >= retry:
                    raise
                window_state_retry += 1
                await sleep(0.2)

    def _create_window_rect(self, res: dict) -> WindowRect:
        """(Internal) Parse & create window rect from response.

        :param res: `<dict>` The direct response for window rect related response.
        :return `<WindowRect>`: The size and relative position of the window.
        """
        try:
            return WindowRect(**res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse window rect from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid window rect response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            )

    # Scroll ------------------------------------------------------------------------------
    async def scroll_by(
        self,
        width: int = 0,
        height: int = 0,
        pause: int | float | None = None,
    ) -> None:
        """Scroll the viewport by the given height & width.

        :param width: `<int>` The width to scroll. Defaults to `0`.
        :param height: `<int>` The height to scroll. Defaults to `0`.
        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.

        ### Example:
        >>> await session.scroll_by(100, 100)
        """
        try:
            await self._execute_script(javascript.PAGE_SCROLL_BY, width, height)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to scroll the viewport by width ({}) & height ({}): {}".format(
                    self.__class__.__name__, repr(width), repr(height), err
                )
            ) from err
        await self.pause(pause)

    async def scroll_to(
        self,
        x: int = 0,
        y: int = 0,
        pause: int | float | None = None,
    ) -> None:
        """Scroll the viewport to the given x & y coordinates.

        :param x: `<int>` The x-coordinate to scroll to. Defaults to `0`.
        :param y: `<int>` The y-coordinate to scroll to. Defaults to `0`.
        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.

        ### Example:
        >>> await session.scroll_to(100, 100)
        """
        try:
            await self._execute_script(javascript.PAGE_SCROLL_TO, x, y)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to scroll the viewport to x ({}) & y ({}): {}".format(
                    self.__class__.__name__, repr(x), repr(y), err
                )
            ) from err
        await self.pause(pause)

    async def scroll_to_top(
        self,
        value: int = 1,
        by: Literal["steps", "pixels"] = "steps",
        pause: int | float = 0.2,
    ) -> None:
        """Scroll the viewport to the top of the page.
        (Does not affect the horizontal position of the viewport.)

        :param value: `<int>` The value for the sroll 'by' strategy.
        :param by: `<str>` The scrolling strategy. Defaults to `'steps'`.
            - `'steps'`: The 'value' sets the approximate steps it
               takes to scroll to the top of the page.
            - `'pixels'`: The 'value' sets the exact pixels to scroll
               for each step to the top of the page.

        :param pause: `<int/flaot>` Seconds to pause between each scroll. Defaults to `0.2`.

        ### Example:
        >>> await session.scroll_to_top(12, "count")
            # Try to scroll to the top of the page in 12 steps.
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        by = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixals
        if by == "steps":
            viewport = await self.viewport
            # . fast path - already at top
            if viewport.top <= 0:
                return None  # exit
            # . fast path - straight to top
            if value == 1:
                await self.scroll_to(x=viewport.x, y=0)
                return None  # exit
            # . calculate pixals
            pixel = ceil(viewport.top / value)
        else:
            pixel = value

        # Scroll to top
        await self.scroll_by(height=-pixel)
        await sleep(pause)
        while (await self.viewport).top > 0:
            await self.scroll_by(height=-pixel)
            await sleep(pause)

    async def scroll_to_bottom(
        self,
        value: int = 1,
        by: Literal["steps", "pixels"] = "steps",
        pause: int | float = 0.2,
    ) -> None:
        """Scroll the viewport to the bottom of the page.
        (Does not affect the horizontal position of the viewport.)

        :param value: `<int>` The value for the sroll 'by' strategy.
        :param by: `<str>` The scrolling strategy. Defaults to `'steps'`.
            - `'steps'`: The 'value' sets the approximate steps it
               takes to scroll to the bottom of the page.
            - `'pixels'`: The 'value' sets the exact pixels to scroll
               for each step to the bottom of the page.

        :param pause: `<int/flaot>` Seconds to pause between each scroll. Defaults to `0.2`.

        ### Example:
        >>> await session.scroll_to_bottom(100, "pixel")
            # Scroll to the bottom of the page by 100 pixels each time.
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        by = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixal
        if by == "steps":
            bottom = (await self.viewport).bottom
            height = await self.page_height
            # . fast path - already at bottom
            if height - bottom <= 1:
                return None
            # . calculate pixals
            pixel = ceil((height - bottom) / value)
        else:
            pixel = value

        # Scroll to bottom
        await self.scroll_by(height=pixel)
        await sleep(pause)
        while (await self.page_height) - (await self.viewport).bottom > 1:
            await self.scroll_by(height=pixel)
            await sleep(pause)

    async def scroll_to_left(
        self,
        value: int = 1,
        by: Literal["steps", "pixels"] = "steps",
        pause: int | float = 0.2,
    ) -> None:
        """Scroll the viewport to the left of the page.
        (Does not affect the vertical position of the viewport.)

        :param value: `<int>` The value for the sroll 'by' strategy.
        :param by: `<str>` The scrolling strategy. Defaults to `'steps'`.
            - `'steps'`: The 'value' sets the approximate steps it
               takes to scroll to the left of the page.
            - `'pixels'`: The 'value' sets the exact pixels to scroll
               for each step to the left of the page.

        :param pause: `<int/flaot>` Seconds to pause between each scroll. Defaults to `0.2`.

        ### Example:
        >>> await session.scroll_to_left(12, "count")
            # Try to scroll to the left of the page in 12 steps.
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        by = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixals
        if by == "steps":
            viewport = await self.viewport
            # . fast path - already at left
            if viewport.left <= 0:
                return None  # exit
            # . fast path - straight to left
            if value == 1:
                await self.scroll_to(x=0, y=viewport.y)
                return None  # exit
            # . calculate pixals
            pixel = ceil(viewport.left / value)
        else:
            pixel = value

        # Scroll to left
        await self.scroll_by(width=-pixel)
        await sleep(pause)
        while (await self.viewport).left > 0:
            await self.scroll_by(width=-pixel)
            await sleep(pause)

    async def scroll_to_right(
        self,
        value: int = 1,
        by: Literal["steps", "pixels"] = "steps",
        pause: int | float = 0.2,
    ) -> None:
        """Scroll the viewport to the right of the page.
        (Does not affect the vertical position of the viewport.)

        :param value: `<int>` The value for the sroll 'by' strategy.
        :param by: `<str>` The scrolling strategy. Defaults to `'steps'`.
            - `'steps'`: The 'value' sets the approximate steps it
               takes to scroll to the right of the page.
            - `'pixels'`: The 'value' sets the exact pixels to scroll
               for each step to the right of the page.

        :param pause: `<int/flaot>` Seconds to pause between each scroll. Defaults to `0.2`.

        ### Example:
        >>> await session.scroll_to_right(100, "pixel")
            # Scroll to the right of the page by 100 pixels each time.
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        by = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixal
        if by == "steps":
            right = (await self.viewport).right
            width = await self.page_width
            # . fast path - already at right
            if width - right <= 1:
                return None
            # . calculate pixals
            pixel = ceil((width - right) / value)
        else:
            pixel = value

        # Scroll to right
        await self.scroll_by(width=pixel)
        await sleep(pause)
        while (await self.page_width) - (await self.viewport).right > 1:
            await self.scroll_by(width=pixel)
            await sleep(pause)

    async def scroll_into_view(
        self,
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Scroll the viewport to the element by the given selector and strategy.

        :param value: `<str/Element>` The selector for the element, or an `<Element>` instance.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            If the given 'value' is an `<Element>`, this argument will be ignored.
        :param timeout: `<int/float/None>` Total seconds to wait for the element to scroll into view. Defaults to `5`.
        :return `<bool>`: True if the element is in the viewport, False if element not exists.

        ### Example:
        >>> viewable = await session.scroll_into_view("#element", by="css")
            # True / False
        """
        # Element already specified
        if self._is_element(value):
            return await value.scroll_into_view(timeout)

        # Find element & scroll
        strat = self._validate_selector_strategy(by)
        element = await self._find_element_no_wait(value, strat)
        if element is not None:
            return await element.scroll_into_view(timeout)
        elif timeout is None:
            return False

        # Wait for element & scroll
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            element = await self._find_element_no_wait(value, strat)
            if element is not None:
                return await element.scroll_into_view(
                    timeout - (unix_time() - start_time)
                )
        return False

    def _validate_scroll_strategy(self, by: Any) -> str:
        """(Internal) Validate the scroll 'by' strategy `<str>`"""
        if by not in Constraint.PAGE_SCROLL_BY_STRATEGIES:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid scroll 'by' strategy: {}. Available options: {}".format(
                    self.__class__.__name__,
                    repr(by),
                    sorted(Constraint.PAGE_SCROLL_BY_STRATEGIES),
                )
            )
        return by

    def _validate_scroll_value(self, value: Any) -> int:
        """(Internal) Validate the scroll by 'value' `<int>`"""
        if not isinstance(value, int):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid scroll by 'value': {} {}. Must be an integer.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        if value < 1:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid scroll by 'value': {}. Must be >= 1.".format(
                    self.__class__.__name__, repr(value)
                )
            )
        return value

    # Alert -------------------------------------------------------------------------------
    async def get_alert(self, timeout: int | float | None = 5) -> Alert | None:
        """Get the alert of the active page window.

        :param timeout: `<int/float/None>` Total seconds to wait for the alert to pop-up. Defaults to `5`.
        :return `<Alert>`: The alert of the active page window, or `None` if alert not exists.

        ### Example:
        >>> alert = await session.get_alert()
            # <Alert (session='5351...', service='http://...')>
        """

        async def find_alert() -> Alert | None:
            try:
                await self.execute_command(Command.W3C_GET_ALERT_TEXT)
                return Alert(self)
            except errors.AlertNotFoundError:
                return None

        # Get alert
        if (alert := await find_alert()) is not None:
            return alert
        elif timeout is None:
            return None

        # Wait for alert
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if (alert := await find_alert()) is not None:
                return alert
        return None

    # Frame -------------------------------------------------------------------------------
    async def switch_frame(
        self,
        value: str | Element | int,
        by: Literal["css", "xpath", "index"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Switch focus to a specific frame in the active page window.

        :param value: `<str/Element/int>` Accepts three kinds of input:
            - `<str>`: The selector for the element contains the frame.
            - `<Element>`: An element instance contains the frame.
            - `<int>`: The index (id) of the frame.

        :param by: `<str>` The selector strategy, accepts `'css'`, `'xpath'` or `'index'`. Defaults to `'css'`.
            If the given 'value' is an `<Element>`, this argument will be ignored.
        :param timeout: `<int/float/None>` Total seconds to wait for frame switching. Defaults to `5`.
        :return `<bool>`: True if successfully switched focus, False if frame not exists.

        ### Example:
        >>> # . switch by element selector
            await session.switch_frame("figure.demoarea > iframe", by="css")  # True / False

        >>> # . switch by element instance
            element = await session.find_element("figure.demoarea > iframe", by="css")
            await session.switch_frame(element)  # True / False

        >>> # . switch by frame index
            await session.switch_frame(1, by="index")  # True / False
        """

        async def switch(frame_id: Any) -> bool:
            try:
                await self.execute_command(
                    Command.SWITCH_TO_FRAME, body={"id": frame_id}
                )
                return True
            except (errors.FrameNotFoundError, errors.ElementNotFoundError):
                return False

        # Switch by Element instance
        if self._is_element(value):
            frame_id = {ELEMENT_KEY: value.id}
        # Switch by Element selector
        elif by != "index":
            element = await self.find_element(value, by)
            if element is None:
                return False  # exit: element not found
            frame_id = {ELEMENT_KEY: element.id}
        # Switch by frame index
        else:
            if not isinstance(value, int) or value < 0:
                raise errors.InvalidArgumentError(
                    "<{}>The 'value' for frame index must be an integer `>= 0`. "
                    "Instead of: {} {}.".format(
                        self.__class__.__name__, repr(value), type(value)
                    )
                )
            frame_id = value

        # Switch to frame
        if await switch(frame_id):
            return True
        elif timeout is None:
            return False

        # Switch with timeout
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await switch(frame_id):
                return True
        return False

    async def default_frame(self) -> bool:
        """Switch focus to the default frame (the `MAIN` document).

        :return `<bool>`: True if successfully switched focus, False if failed.

        ### Example:
        >>> await session.default_frame()  # True / False
        """
        try:
            await self.execute_command(Command.SWITCH_TO_FRAME, body={"id": None})
            return True
        except (errors.FrameNotFoundError, errors.ElementNotFoundError):
            return False

    async def parent_frame(self) -> bool:
        """Switch focus to the parent frame of the current frame.

        :return `<bool>`: True if successfully switched focus, False if failed.

        ### Example:
        >>> await session.parent_frame()  # True / False
        """
        try:
            await self.execute_command(Command.SWITCH_TO_PARENT_FRAME)
            return True
        except (errors.FrameNotFoundError, errors.ElementNotFoundError):
            return False

    # Element -----------------------------------------------------------------------------
    @property
    async def active_element(self) -> Element:
        """Access the element in focus `<Element>`.
        If no element is in focus, returns the `<BODY>` element.

        ### Example:
        >>> elements = await session.active_element
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
        """
        res = await self.execute_command(Command.W3C_GET_ACTIVE_ELEMENT)
        return self._create_element(res.get("value", None))

    async def element_exists(
        self,
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
    ) -> bool:
        """Check if an element exists. This method ignores the implicit wait
        timeout, and returns element existence immediately.

        :param value: `<str/Element>` The selector for the element *OR* an `<Element>` instance.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            If the given 'value' is an `<Element>`, this argument will be ignored.
        :return `<bool>`: True if the element exists, False otherwise.

        ### Example:
        >>> await session.element_exists("#input_box")  # True / False
        """
        if self._is_element(value):
            return await value.exists
        else:
            strat = self._validate_selector_strategy(by)
            return await self._element_exists_no_wait(value, strat)

    async def elements_exist(
        self,
        *values: str | Element,
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
    ) -> bool:
        """Check if multiple elements exist. This method ignores the implicit
        wait timeout, and returns elements existence immediately.

        :param values: `<str/Element>` The locators for multiple elements *OR* `<Element>` instances.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            For values that are `<Element>` instances, this argument will be ignored.
        :param all_: `<bool>` Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
            - `True`: All elements must exist to return True.
            - `False`: Any one of the elements exists returns True.

        :return `<bool>`: True if the elements exist, False otherwise.

        ### Example:
        >>> await session.elements_exist(
                "#input_box", "#input_box2", by="css", all_=True
            )  # True / False
        """

        async def check_existance(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        # Validate strategy
        strat = self._validate_selector_strategy(by)
        # Check existance
        if all_:
            for value in values:
                if not await check_existance(value):
                    return False
            return True
        else:
            for value in values:
                if await check_existance(value):
                    return True
            return False

    async def find_element(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
    ) -> Element | None:
        """Find the element by the given selector and strategy. The timeout for
        finding an element is determined by the implicit wait of the session.

        :param value: `<str>` The selector for the element.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<Element/None>`: The located element, or `None` if not found.

        ### Example:
        >>> await session.find_element("#input_box", by="css")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
        """
        # Locate element
        strat = self._validate_selector_strategy(by)
        try:
            res = await self.execute_command(
                Command.FIND_ELEMENT, body={"using": strat, "value": value}
            )
        except errors.ElementNotFoundError:
            return None
        except errors.InvalidArgumentError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid '{}' selector: {}".format(
                    self.__class__.__name__, by, repr(value)
                )
            ) from err
        # Create element
        try:
            return self._create_element(res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse element from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def find_elements(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
    ) -> list[Element]:
        """Find elements by the given selector and strategy. The timeout for
        finding the elements is determined by the implicit wait of the session

        :param value: `<str>` The selector for the elements.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<list[Element]>`: A list of located elements (empty if not found).

        ### Example:
        >>> await session.find_elements("#input_box", by="css")
            # [<Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>]
        """
        # Locate elements
        strat = self._validate_selector_strategy(by)
        try:
            res = await self.execute_command(
                Command.FIND_ELEMENTS, body={"using": strat, "value": value}
            )
        except errors.ElementNotFoundError:
            return []
        except errors.InvalidArgumentError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid '{}' selector: {}".format(
                    self.__class__.__name__, by, repr(value)
                )
            ) from err
        # Create elements
        try:
            return [self._create_element(value) for value in res["value"]]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse elements from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def find_1st_element(
        self,
        *values: str,
        by: Literal["css", "xpath"] = "css",
    ) -> Element | None:
        """Find the first located element among multiple locators. The timeout for
        finding the first element is determined by the implicit wait of the session.

        :param values: `<str>` The locators for multiple elements.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :return `<Element/None>`: The first located element among all locators, or `None` if not found.

        ### Example:
        >>> await session.find_1st_element("#input_box", "#input_box2", by="css")
            # <Element (id='289DEC2B8885F15A2BDD2E92AC0404F3_element_1', session='1e78...', service='http://...')>
        """
        # Validate strategy
        strat = self._validate_selector_strategy(by)

        # Locate 1st element
        timeout = (await self._get_timeouts()).implicit
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            for value in values:
                element = await self._find_element_no_wait(value, strat)
                if element is not None:
                    return element
                await sleep(0.2)
        return None

    async def wait_until_element(
        self,
        condition: Literal[
            "gone",
            "exist",
            "visible",
            "viewable",
            "enabled",
            "selected",
        ],
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until an element satisfies the given condition.

        :param condition: `<str>` The condition to satisfy. Available options:
            - `'gone'`: Wait until an element disappears from the DOM tree.
            - `'exist'`: Wait until an element appears in the DOM tree.
            - `'visible'`: Wait until an element not only is displayed but also not
                blocked by any other elements (e.g. an overlay or modal).
            - `'viewable'`: Wait until an element is displayed regardless whether it
                is blocked by other elements (e.g. an overlay or modal).
            - `'enabled'`: Wait until an element is enabled.
            - `'selected'`: Wait until an element is selected.

        :param value: `<str/Element>` The selector for the element *OR* an `<Element>` instance.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            If the given 'value' is an `<Element>`, this argument will be ignored.
        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return `<bool>`: True if the element satisfies the condition, False otherwise.

        ### Example:
        >>> await session.wait_until_element(
                "visible", "#input_box", by="css", timeout=5
            )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            if self._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_visible(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.visible
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.visible

        async def is_viewable(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.viewable
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.viewable

        async def is_enabled(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.selected

        # Validate strategy
        strat = self._validate_selector_strategy(by)

        # Determine condition
        if condition == "gone":
            condition_checker = is_gone
        elif condition == "exist":
            condition_checker = is_exist
        elif condition == "visible":
            condition_checker = is_visible
        elif condition == "viewable":
            condition_checker = is_viewable
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        # Check condition
        if await condition_checker(value):
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await condition_checker(value):
                return True
        return False

    async def wait_until_elements(
        self,
        condition: Literal[
            "gone",
            "exist",
            "visible",
            "viewable",
            "enabled",
            "selected",
        ],
        *values: str | Element,
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until multiple elements satisfy the given condition.

        :param condition: `<str>` The condition to satisfy. Available options:
            - `'gone'`: Wait until the elements disappear from the DOM tree.
            - `'exist'`: Wait until the elements appear in the DOM tree.
            - `'visible'`: Wait until the elements not only are displayed but also not
                blocked by any other elements (e.g. an overlay or modal).
            - `'viewable'`: Wait until the elements are displayed regardless whether
                blocked by other elements (e.g. an overlay or modal).
            - `'enabled'`: Wait until the elements are enabled.
            - `'selected'`: Wait until the elements are selected.

        :param values: `<str/Element>` The locators for multiple elements *OR* `<Element>` instances.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            For values that are `<Element>` instances, this argument will be ignored.
        :param all_: `<bool>` Determine how to satisfy the condition. Defaults to `True (all elements)`.
            - `True`: All elements must satisfy the condition to return True.
            - `False`: Any one of the elements satisfies the condition returns True.

        :param timeout: `<int/float/None>` Total seconds to wait until timeout. Defaults to `5`.
        :return `<bool>`: True if the elements satisfy the condition, False otherwise.

        ### Example:
        >>> await session.wait_until_elements(
                "visible", "#input_box1", "#search_button",
                by="css", all_=True, timeout=5
            )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            if self._is_element(value):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_visible(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.visible
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.visible

        async def is_viewable(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.viewable
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.viewable

        async def is_enabled(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            if self._is_element(value):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.selected

        async def check_condition(values: tuple, condition_checker: Awaitable) -> bool:
            if all_:
                for value in values:
                    if not await condition_checker(value):
                        return False
                return True
            else:
                for value in values:
                    if await condition_checker(value):
                        return True
                return False

        # Validate strategy
        strat = self._validate_selector_strategy(by)

        # Determine condition
        if condition == "gone":
            condition_checker = is_gone
        elif condition == "exist":
            condition_checker = is_exist
        elif condition == "visible":
            condition_checker = is_visible
        elif condition == "viewable":
            condition_checker = is_viewable
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        # Check condition
        if await check_condition(values, condition_checker):
            return True
        elif timeout is None:
            return False

        # Wait until satisfied
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if await check_condition(values, condition_checker):
                return True
        return False

    async def _element_exists_no_wait(self, value: str, strat: str) -> bool:
        """(Internal) Check if an element exists without implicit wait `<bool>`.
        Returns `False` immediately if element not exists.
        """
        try:
            return await self._execute_script(
                javascript.ELEMENT_EXISTS_IN_PAGE[strat], value
            )
        except errors.ElementNotFoundError:
            return False
        except errors.InvalidElementStateError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidXPathSelectorError(
                "<{}>\nInvalid 'xpath' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err

    async def _find_element_no_wait(self, value: str, strat: str) -> Element | None:
        """(Internal) Find element without implicit wait `<Element>`.
        Returns `None` immediately if element not exists.
        """
        try:
            res = await self._execute_script(
                javascript.FIND_ELEMENT_IN_PAGE[strat], value
            )
        except errors.ElementNotFoundError:
            return None
        except errors.InvalidElementStateError as err:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid 'css' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidXPathSelectorError(
                "<{}>\nInvalid 'xpath' selector: {}".format(
                    self.__class__.__name__, repr(value)
                )
            ) from err
        try:
            return self._create_element(res)
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse element from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    def _validate_selector_strategy(self, by: Any) -> str:
        """(Internal) Validate selector strategy `<str>`."""
        if by == "css":
            return "css selector"
        elif by == "xpath" or by == "css selector":
            return by
        else:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid selector strategy: {}. Available options: "
                "['css', 'xpath'].".format(self.__class__.__name__, repr(by))
            )

    def _create_element(self, element: dict[str, Any]) -> Element | None:
        """(Internal) Create the element `<Element>`."""
        if element is None:
            return None
        try:
            return Element(element[ELEMENT_KEY], self)
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse element from response: {}".format(
                    self.__class__.__name__, element
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid element response: {}".format(
                    self.__class__.__name__, element[ELEMENT_KEY]
                )
            ) from err

    # Shadow ------------------------------------------------------------------------------
    async def get_shadow(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> Shadow | None:
        """Get the shadow root of an element by the given selector and strategy.

        :param value: `<str>` The selector for the element contains the shadow root.
        :param by: `<str>` The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
        :param timeout: `<int/float/None>` Total seconds to wait for the shadow root. Defaults to `5`.
        :return `<Shadow>`: The shadow root of the element, or `None` if not exists.

        ### Example:
        >>> shadow = await session.get_shadow("#element", by="css")
            # <Shadow (id='72216A833579C94EF54047C00F423735_element_4', element='7221...', session='f8c2...', service='http://...)>
        """

        async def find_shadow() -> Shadow | None:
            element = await self._find_element_no_wait(value, strat)
            return None if element is None else await element.shadow

        # Validate strategy
        strat = self._validate_selector_strategy(by)

        # Get the shadow root
        if (shadow := await find_shadow()) is not None:
            return shadow
        elif timeout is None:
            return None

        # Wait for shadow root
        timeout = self._validate_timeout(timeout)
        start_time = unix_time()
        while unix_time() - start_time < timeout:
            await sleep(0.2)
            if (shadow := await find_shadow()) is not None:
                return shadow
        return None

    # Script ------------------------------------------------------------------------------
    @property
    def scripts(self) -> list[JavaScript]:
        """Access all the cached JavaScripts `<list[JavaScript]>`.
        `(NOT an asyncronous attribute)`.

        ### Example:
        >>> scripts = session.scripts
            # [
            #    <JavaScript (name='myscript1', script='return...', args=[])>
            #    <JavaScript (name='myscript2', script='return...', args=[])>
            # ]
        """
        return list(self._script_by_name.values())

    def get_script(self, script: str | JavaScript) -> JavaScript | None:
        """Get the JavaScript from cache `(NOT an asyncronous method)`.

        :param script: `<str/JavaScript>` Accepts both the name of the JavaScript, or the `<JavaScript>` instance.
        :return `<JavaScript>`: The cached JavaScript, or `None` if not exist.

        ### Example:
        >>> js = session.get_script("myscript")
            # <JavaScript (name='myscript', script='return...', args=[])>
        """
        return self._script_by_name.get(script)

    def cache_script(self, name: str, script: str, *args: Any) -> JavaScript:
        """Cache a javascript for later execution `(NOT an asyncronous method)`.

        :param name: `<str>` The name of the javascript (cache accessor).
        :param script: `<str>` The raw javascript code.
        :param args: `<Any>` The arguments for the javascript.
        :return `<JavaScript>`: The cached javascript.

        ### Example:
        >>> # . without arguments
            js = session.cache_script("get_title", "return document.title;")
            # <JavaScript (name='get_title', script='return...', args=[])>

        >>> # . with arguments
            js = session.cache_script("scroll_y", "window.scrollBy(0, arguments[0]);", 100)
            # <JavaScript (name='scroll_y', script='window.scrollBy(0, arguments[0]);', args=[100])>
        """
        js = JavaScript(self._validate_script_name(name), script, *args)
        self._script_by_name[name] = js
        return js

    def remove_script(self, script: str | JavaScript) -> bool:
        """Remove a previously cached JavaScript `(NOT an asyncronous method)`.

        :param script: `<str/JavaScript>` Accepts both the name of the javascript, or the `<JavaScript>` instance.
        :return `<bool>`: True if the script is removed from cache, False if script not exists.

        ### Example:
        >>> session.remove_script("myscript")  # True / False
        """
        try:
            self._script_by_name.pop(script)
            return True
        except KeyError:
            return False

    def rename_script(self, script: str | JavaScript, new_name: str) -> JavaScript:
        """Rename a previously cached JavaScript `(NOT an asyncronous method)`.

        :param script: `<str/JavaScript>` Accepts both the name of the javascript, or the `<JavaScript>` instance.
        :param new_name: `<str>` The new name for the javascript.
        :return `<JavaScript>`: The renamed javascript.

        ### Example:
        >>> # . cache a script
            js = session.cache_script("script1", "return document.title;")
            # <JavaScript (name='script1', script='return document.titile;', args=[])>

        >>> # . rename the script
            js = session.rename_script("script1", "script2")
            # <JavaScript (name='script2', script='return document.titile;', args=[])>
        """
        # Validate name
        name = self._validate_script_name(new_name)

        # Pop cached script
        try:
            js = self._script_by_name.pop(script)
        except KeyError as err:
            raise errors.JavaScriptNotFoundError(
                "<{}>\nCannot rename script {}. JavaScript "
                "not found.".format(self.__class__.__name__, repr(script))
            ) from err

        # Cache with new name
        return self.cache_script(name, js.script, *js.args)

    async def execute_script(self, script: str | JavaScript, *args: Any) -> Any:
        """Execute javascript synchronously.

        :param script: Accepts three kinds of input:
            - `<str>` The raw javascript code to execute.
            - `<str>` The name of a cached JavaScript.
            - `<JavaScript>` A cached JavaScript instance.

        :param args: `<Any>` The arguments for the javascript.
            - The '*args' will be passed along with the script as an array, and
              accessable in order by the script as `arguments[0]`, `arguments[1]`,
              etc.
            - If executing a cached JavaScript, the '*args' in this method is always
              prioritized over the cached arguments. Only when the '*args' is empty,
              the cached arguments will be used.

        :return `<Any>`: The responce from the script execution.

        ### Example:
        >>> # . execute raw javascript code
            script = "return document.title;"
            title = await session.execute_script(script)

        >>> # . execute cached JavaScript by name
            session.cache_script("get_title", "return document.title;")
            title = await session.execute_script("get_title")

        >>> # . execute cached JavaScript by instance
            js = session.cache_script("get_title", "return document.title;")
            title = await session.execute_script(js)
        """
        # Execute cached script
        js = self.get_script(script)
        if js is not None:
            return await self._execute_script(js.script, *args or js.args)
        # Execute raw script
        else:
            return await self._execute_script(script, *args)

    async def execute_async_script(self, script: str | JavaScript, *args: Any) -> Any:
        """Execute JavaScript asynchronously.

        :param script: Accepts three kinds of input:
            - `<str>` The raw async javascript code to execute.
            - `<str>` The name of a cached JavaScript.
            - `<JavaScript>` A cached JavaScript instance.

        :param args: `<Any>` The arguments for the javascript.
            - The '*args' will be passed along with the script as an array, and
              accessable in order by the script as `arguments[0]`, `arguments[1]`,
              etc.
            - If executing a cached JavaScript, the '*args' in this method is always 
              prioritized over the cached arguments. Only when the '*args' is empty, 
              the cached arguments will be used.

        :return `<Any>`: The responce from the async script execution.

        ### Example:
        >>> # . execute raw async javascript code
            script = "var callback = arguments[arguments.length - 1]; " \\
                     "window.setTimeout(function(){ callback('timeout') }, 3000);"
            await session.execute_async_script(script)

        >>> # . execute cached JavaScript by name
            script = "var callback = arguments[arguments.length - 1]; " \\
                     "window.setTimeout(function(){ callback('timeout') }, 3000);"
            session.cache_script("async_js1", script)
            await session.execute_async_script("async_js1")

        >>> # . execute cached JavaScript by instance
            script = "var callback = arguments[arguments.length - 1]; " \\
                     "window.setTimeout(function(){ callback('timeout') }, 3000);"
            js = session.cache_script("async_js1", script)
            await session.execute_async_script(js)
        """
        # Execute cached script
        js = self.get_script(script)
        if js is not None:
            return await self._execute_async_script(js.script, *args or js.args)
        # Execute raw script
        else:
            return await self._execute_async_script(script, *args)

    async def _execute_script(self, script: str, *args: Any) -> Any:
        """(Internal) Executes raw javascript synchronously.

        :param script: `<str>` The raw javascript code to execute.
        :param args: `<Any>` The arguments for the javascript.
            The '*args' will be passed along with the script as an array, and
            accessable in order by the script as `arguments[0]`, `arguments[1]`,
            etc.
        :return `<Any>`: The responce from the script execution.

        ### Example:
        >>> # . without argument
            script = "return document.title;"
            title = await session.execute_script(script)

        >>> # . with arguments
            script = "window.scrollBy(arguments[0], arguments[1]);"
            await session.execute_script(script, 100, 100)
        """
        res = await self.execute_command(
            Command.W3C_EXECUTE_SCRIPT,
            body={"script": script, "args": warp_tuple(args)},
        )
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse script value from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def _execute_async_script(self, script: str, *args: Any) -> Any:
        """(Internal) Executes raw javascript asynchronously.

        :param script: `<str>` The raw async javascript code to execute.
        :param args: `<Any>` Arguments for the async javascript.
            The '*args' will be passed along with the script as an array, and 
            accessable in order by the script as `arguments[0]`, `arguments[1]`, 
            etc.
        :return `<Any>`: The responce from the async script execution.

        ### Example:
        >>> script = "var callback = arguments[arguments.length - 1]; " \\
                     "window.setTimeout(function(){ callback('timeout') }, 3000);"
            await session.execute_async_script(script)
        """
        # Execute
        res = await self.execute_command(
            Command.W3C_EXECUTE_SCRIPT_ASYNC,
            body={"script": script, "args": warp_tuple(args)},
        )
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse script value from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    def _validate_script_name(self, name: Any) -> str:
        """(Internal) Validate script name `<str>`."""
        if not isinstance(name, str) or not name:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid script name: {} {}.".format(
                    self.__class__.__name__, repr(name), type(name)
                )
            )
        if name in self._script_by_name:
            raise errors.InvalidArgumentError(
                "<{}>\nScript name '{}' has been taken. "
                "Please choose another one.".format(self.__class__.__name__, name)
            )
        return name

    # Actions -----------------------------------------------------------------------------
    def actions(
        self,
        pointer: Literal["mouse", "pen", "touch"] = "mouse",
        duration: int | float = 0.25,
    ) -> Actions:
        """Start an actions chain to peform (automate) low level
        interactions such as mouse movements, key presses, and
        wheel scrolls.

        :param pointer: `<str>` The pointer type to use. Defaults to `'mouse'`.
            Available options are: `'mouse'`, `'pen'`, `'touch'`.
        :param duration: `<int/float>` The duration in seconds to perform a pointer move or wheel scroll action. Defaults to `0.2`.
        :return `<Actions>`: The actions chain.

        ### Example:
        >>> from aselenium import KeyboardKeys
            input_box = await session.find_element("#input_box")
            (
                await session.actions("mouse")
                .move_to(input_box)
                .click()
                .send_keys("Hello World!")
                .send_keys(KeyboardKeys.ENTER)
                .perform()
            )
        """
        return Actions(self, pointer, duration)

    # Utils -------------------------------------------------------------------------------
    async def pause(self, duration: int | float | None) -> None:
        """Pause the for a given duration.

        :param duration: `<int/float/None>` The duration to pause in seconds.
        """
        if duration is None:
            return None  # exit
        try:
            await sleep(duration)
        except Exception as err:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'duration' to pause: {}.".format(
                    self.__class__.__name__, repr(duration)
                )
            ) from err

    def _validate_pause(self, value: Any) -> int | float:
        """(Internal) Validate if pause value `> 0` `<int/float>`."""
        if not isinstance(value, (int, float)):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'pause'. Must be an integer or float, "
                "instead got: {}.".format(self.__class__.__name__, type(value))
            )
        if value <= 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'pause'. Must be greater than 0, "
                "instead got: {}.".format(self.__class__.__name__, value)
            )
        return value

    def _validate_timeout(self, value: Any) -> int | float:
        """(Internal) Validate if timeout value `> 0` `<int/float>`."""
        if not isinstance(value, (int, float)):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'timeout'. Must be an integer or float, "
                "instead got: {}.".format(self.__class__.__name__, type(value))
            )
        if value <= 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'timeout'. Must be greater than 0, "
                "instead got: {}.".format(self.__class__.__name__, value)
            )
        return value

    def _validate_wait_str_value(self, value: Any) -> str:
        """(Internal) Validate if wait until 'value' is a non-empty string `<str>`."""
        if not isinstance(value, str) or not value:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid wait until value: {} {}. "
                "Must an non-empty string.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        return value

    def _raise_invalid_wait_condition(self, condition: Any) -> None:
        """(Internal) Raise invalid wait until 'condition' error."""
        raise errors.InvalidArgumentError(
            "<{}>\nInvalid wait until condition: {} {}.".format(
                self.__class__.__name__, repr(condition), type(condition)
            )
        )

    def _is_element(self, element: Any) -> bool:
        """(Internal) Check if the given object is an `<Element>` instance."""
        return isinstance(element, Element)

    def _decode_base64(self, data: str, encoding: str) -> str:
        """(Internal) Decode base64 string to `<bytes>`."""
        return b64decode(data.encode(encoding))

    def _encode_base64(self, data: bytes, encoding: str) -> str:
        """(Internal) Encode bytes to base64 `<str>`."""
        return b64encode(data).decode(encoding)

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (id='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            self._service.url,
        )

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __del__(self):
        self._collect_garbage()

    def _collect_garbage(self) -> None:
        """(Internal) Collect garbage."""
        # Already closed
        if self.__closed:
            return None  # exit

        # Options
        self._options = None
        # Service
        self._service = None
        # Connection
        self._conn = None
        # Vender prefix
        self._vendor = None
        # Session
        self._id = None
        self._base_url = None
        self._body = None
        self._timeouts = None
        # Window
        self._window_by_name = None
        self._window_by_handle = None
        # Script
        self._script_by_name = None
        # Status
        self.__closed = True


# Chromium Base Session ---------------------------------------------------------------------------
class ChromiumBaseSession(Session):
    """Represents a session of the chromium based browser."""

    def __init__(
        self,
        options: ChromiumBaseOptions,
        service: ChromiumBaseService,
    ) -> None:
        super().__init__(options, service)
        # Devtools cmd
        self._cdp_cmd_by_name: dict[str, DevToolsCMD] = {}

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> ChromiumBaseOptions:
        """Access the browser options `<ChromiumBaseOptions>`."""
        return self._options

    @property
    def browser_version(self) -> ChromiumVersion:
        """Access the browser binary version of the session `<ChromiumVersion>`."""
        return super().browser_version

    @property
    def service(self) -> ChromiumBaseService:
        """Access the webdriver service `<ChromiumBaseService>`."""
        return self._service

    @property
    def driver_version(self) -> ChromiumVersion:
        """Access the webdriver binary version of the session `<ChromiumVersion>`."""
        return super().driver_version

    # Chromium - Permission ---------------------------------------------------------------
    @property
    async def permissions(self) -> list[Permission]:
        """Access all the permissions of the active page window `<list[Permission]>`.

        ### Example:
        >>> permissions = await session.permissions
            # [
            #    <Permission (name='geolocation', state='prompt')>,
            #    <Permission (name='camera', state='denied')>,
            #    ...
            # ]
        """
        return [
            permission
            for name in sorted(Constraint.PERMISSION_NAMES)
            if (permission := await self.get_permission(name))
        ]

    async def get_permission(self, name: str | Permission) -> Permission | None:
        """Get a specific permission from the active page window.

        :param name: `<str>` The name of the permission or a `<Permission>` instance.
        :return `<Permission>`: The specified permission, or `None` if not found.

        ### Example:
        >>> permission = await session.get_permission("geolocation")
            # <Permission (name='geolocation', state='prompt')>
        """
        # Validate permission name
        if isinstance(name, str):
            pass
        elif isinstance(name, Permission):
            name = name.name
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid permission name: {} {}.".format(
                    self.__class__.__name__, repr(name), type(name)
                )
            )
        # Request permission
        try:
            res = await self._execute_script(javascript.GET_PERMISSION, name)
        except (errors.InvalidJavaScriptError, errors.UnknownCommandError):
            return None
        try:
            return Permission(name, res["state"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse permission from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid permission response: "
                "{}".format(self.__class__.__name__, res)
            ) from err

    async def set_permission(
        self,
        name: str,
        state: Literal["granted", "denied", "prompt"],
    ) -> Permission:
        """Set a specific permission's state of the active page window.

        :param name: `<str>` The name of the permission.
        :param state: `<str>` The state of the permission, accepts: `'granted'`, `'denied'`, `'prompt'`.
        :return `<Permission>`: The permission after update.

        ### Example:
        >>> perm = await session.set_permission("geolocation", "granted")
            # <Permission (name='geolocation', state='granted')>
        """
        # Set permission
        permission = Permission(name, state)
        try:
            await self.execute_command(
                Command.SET_PERMISSION,
                body={
                    "descriptor": {"name": permission.name},
                    "state": permission.state,
                },
            )
        except errors.InvalidArgumentError as err:
            msg = str(err)
            if ErrorCode.INVALID_PERMISSION_STATE in msg:
                raise errors.InvalidPermissionStateError(
                    "<{}>\nInvalid permission state: {}.".format(
                        self.__class__.__name__, repr(state)
                    )
                ) from err
            if ErrorCode.INVALID_PERMISSION_NAME in msg:
                raise errors.InvalidPermissionNameError(
                    "<{}>\nInvalid permission name: {}.".format(
                        self.__class__.__name__, repr(name)
                    )
                ) from err
            raise err
        # Return permission
        return await self.get_permission(name)

    def _validate_permission_name(self, name: Any) -> str:
        """(Internal) Validate the name of a permission `<str>`"""
        if isinstance(name, Permission):
            return name.name
        if name not in Constraint.PERMISSION_NAMES:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid permission name: {}. "
                "Available options: {}".format(
                    self.__class__.__name__,
                    repr(name),
                    sorted(Constraint.PERMISSION_NAMES),
                )
            )
        return name

    # Chromium - Network ------------------------------------------------------------------
    @property
    async def network(self) -> Network:
        """Access the network conditions of the current session `<Network>`.

        ### Conditions explain:

        - offline: Whether to simulate an offline network condition.
        - latency: The minimum latency overhead.
        - upload_throughput: The maximum upload throughput in bytes per second.
        - download_throughput: The maximum download throughput in bytes per second.

        ### Default conditions:
        <Network (offline=False, latency=0, upload_throughput=-1, download_throughput=-1)>

        ### Example:
        >>> network = await session.network
            # <Network (offline=False, latency=30, upload_throughput=-1, download_throughput=-1)>
        """
        # Request condition
        try:
            res = await self.execute_command(Command.GET_NETWORK_CONDITIONS)
        except errors.UnknownError as err:
            if ErrorCode.NETWORK_CONDITIONS_NOT_SET in str(err):
                return Network()  # exit: default conditions
            raise err
        # Contruct condition
        try:
            return Network(**res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse network conditions from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid network conditions response: "
                "{}".format(self.__class__.__name__, res["value"])
            ) from err

    async def set_network(
        self,
        offline: bool | None = None,
        latency: int | None = None,
        upload_throughput: int | None = None,
        download_throughput: int | None = None,
    ) -> Network:
        """Set the network conditions of the current session.

        :param offline: `<bool/None>` Whether to simulate an offline network
        condition. If `None (default)`, keep the current offline condition.

        :param latency: `<int/None>` The minimum latency overhead in milliseconds.
        If `None (default)`, keep the current latency condition.

        :param upload_throughput: `<int/None>` The maximum upload throughput
        in bytes per second. If `None (default)`, keep the current condition.

        :param download_throughput: `<int/None>` The maximum download throughput
        in bytes per second. If `None (default)`, keep the current condition.

        :return `<Network>`: The network conditions after update.

        ### Example:
        >>> network = await session.set_network(
                offline=False, latency=10, download=10 * 1024, upload=10 * 1024,
            )
            # <Network (offline=False, latency=10, download=10240, upload=10240)>
        """
        # Update conditions
        network = await self.network
        if offline is not None:
            network.offline = offline
        if latency is not None:
            network.latency = latency
        if upload_throughput is not None:
            network.upload_throughput = upload_throughput
        if download_throughput is not None:
            network.download_throughput = download_throughput
        await self.execute_command(
            Command.SET_NETWORK_CONDITIONS, body={"network_conditions": network.dict}
        )
        # Return conditions
        return await self.network

    async def reset_network(self) -> Network:
        """Reset the network conditions of the current session to
        the default configuration, and returns the reset `<Network>`.

        ### Default conditions:
        <Network (offline=False, latency=0, upload_throughput=-1, download_throughput=-1)>

        ### Example:
        >>> network = await session.reset_network()
            # <Network (offline=False, latency=0, upload_throughput=-1, download_throughput=-1)>
        """
        await self.execute_command(
            Command.SET_NETWORK_CONDITIONS,
            body={"network_conditions": Network().dict},
        )
        return await self.network

    # Chromium - Casting ------------------------------------------------------------------
    @property
    async def cast_sinks(self) -> list[dict[str, Any]]:
        """Access the available sinks for a Cast session `<list[dict[str, Any]]>`."""
        res = await self.execute_command(Command.GET_SINKS, keys=self._vendor)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse cast sinks from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    @property
    async def cast_issue(self) -> str:
        """Access the issue of the Cast session `<str>`"""
        res = await self.execute_command(Command.GET_ISSUE_MESSAGE, keys=self._vendor)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                f"\nFailed to parse cast issue from response: {res}"
            ) from err

    async def set_cast_sink(self, sink_name: str) -> None:
        """Set a specific sink as the Cast session receiver target.

        :param sink_name: `<str>` Name of the sink to use as the receiver target.
        """
        await self.execute_command(
            Command.SET_SINK_TO_USE, body={"sinkName": sink_name}, keys=self._vendor
        )

    async def start_casting(
        self,
        sink_name: str,
        mirror: Literal["desktop", "tab"] = "tab",
    ) -> None:
        """Start a Cast session with a specific sink as the receiver target.

        :param sink_name: `<str>` Name of the sink to use as the casting receiver target.
        :param mirror: `<str>` The mirroring type, accepts `'desktop'` or `'tab'`. Defaults to `'tab'`.
        """
        if mirror == "tab":
            cmd = Command.START_TAB_MIRRORING
        elif mirror == "desktop":
            cmd = Command.START_DESKTOP_MIRRORING
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid cast mirroring type: {}. "
                "Available options: ['desktop', 'tab']".format(
                    self.__class__.__name__, repr(mirror)
                )
            )
        try:
            await self.execute_command(
                cmd, body={"sinkName": sink_name}, keys=self._vendor
            )
        except errors.UnknownError as err:
            if ErrorCode.SINK_NOT_FOUND in str(err):
                raise errors.CastSinkNotFoundError(
                    "<{}>\nFailed to start casting. Cast sink {} "
                    "not found.".format(self.__class__.__name__, repr(sink_name))
                ) from err
            raise err

    async def stop_casting(self, sink_name: str) -> None:
        """Stop an active Cast session.

        :param sink_name: `<str>` Name of the sink used by the Cast session .
        """
        try:
            await self.execute_command(
                Command.STOP_CASTING, body={"sinkName": sink_name}, keys=self._vendor
            )
        except errors.UnknownError as err:
            if ErrorCode.SINK_NOT_FOUND in str(err):
                raise errors.CastSinkNotFoundError(
                    "<{}>\nFailed to stop casting. Cast sink {} "
                    "not found.".format(self.__class__.__name__, repr(sink_name))
                ) from err
            raise err

    # Chromium - DevTools Command ---------------------------------------------------------
    @property
    def cdp_cmds(self):
        """Access all the cached Chrome Devtools Protocol commands
        `<list[DevToolsCMD]>`. `(NOT an asyncronous attribute)`.

        ### Example:
        >>> cmds = session.cdp_cmds
            # [
            #    <DevToolsCMD (name='mycmd1', cmd='...', kwargs={})>,
            #    <DevToolsCMD (name='mycmd2', cmd='...', kwargs={})>,
            # ]
        """
        return list(self._cdp_cmd_by_name.values())

    def get_cdp_cmd(self, cmd: str | DevToolsCMD) -> DevToolsCMD | None:
        """Get the Chrome Devtools Protocol command from cache
        `(NOT an asyncronous method)`.

        :param cmd: `<str/DevToolsCMD>` Accepts both the name of the DevToolsCMD, or the `<DevToolsCMD>` instance.
        :return `<DevToolsCMD>`: The cached DevToolsCMD, or `None` if not exist.

        ### Example:
        >>> cmd = session.get_cdp_cmd("mycmd")
            # <DevToolsCMD (name='mycmd', cmd='Browser.getVersion', kwargs={})>
        """
        return self._cdp_cmd_by_name.get(cmd)

    def cache_cdp_cmd(self, name: str, cmd: str, **kwargs: Any) -> DevToolsCMD:
        """Cache a Chrome Devtools Protocol command for later execution
        `(NOT an asyncronous method)`.

        :param name: `<str>` The name of the command (cache accessor).
        :param cmd: `<str>` The command line.
        :param kwargs: `<Any>` The keyword arguments for the command.
        :return `<DevToolsCMD>`: The cached CDP command.

        ### Example:
        >>> # . without arguments
            cmd = session.cache_cdp_cmd("get_version", "Browser.getVersion")
            # <DevToolsCMD (name='get_version', cmd='Browser.getVersion', kwargs={})>

        >>> # . with arguments
            cmd = session.cache_cdp_cmd(
                "get_url",
                "Runtime.evaluate",
                expression="window.location.href",
            )
            # <DevToolsCMD (name='get_url', cmd='Runtime.evaluate', kwargs={'expression': 'window.location.href'})>
        """
        cmd = DevToolsCMD(self._validate_cdp_cmd_name(name), cmd, **kwargs)
        self._cdp_cmd_by_name[name] = cmd
        return cmd

    def remove_cdp_cmd(self, cmd: str | DevToolsCMD) -> bool:
        """Remove a previously cached Chrome Devtools Protocol command
        `(NOT an asyncronous method)`.

        :param cmd: `<str/DevToolsCMD>` Accepts both the name of the DevToolsCMD, or the `<DevToolsCMD>` instance.
        :return `<bool>`: True if the command is removed from cache, False if command not exist.

        ### Example:
        >>> session.remove_cdp_cmd("mycmd")  # True / False
        """
        try:
            self._cdp_cmd_by_name.pop(cmd)
            return True
        except KeyError:
            return False

    def rename_cdp_cmd(self, cmd: str | DevToolsCMD, new_name: str) -> DevToolsCMD:
        """Rename a previously cached Chrome Devtools Protocol command
        `(NOT an asyncronous method)`.

        :param cmd: `<str/DevToolsCMD>` Accepts both the name of the DevToolsCMD, or the `<DevToolsCMD>` instance.
        :param new_name: `<str>` The new name for the command.
        :return `<DevToolsCMD>`: The renamed command.

        ### Example:
        >>> # . cache a command
            cmd = session.cache_cdp_cmd("cmd1", "Browser.getVersion")
            # <DevToolsCMD (name='cmd1', cmd='Browser.getVersion', kwargs={})>

        >>> # . rename the command
            cmd = session.rename_cdp_cmd("cmd1", "cmd2")
            # <DevToolsCMD (name='cmd2', cmd='Browser.getVersion', kwargs={})>
        """
        # Validate name
        name = self._validate_cdp_cmd_name(new_name)

        # Pop cached command
        try:
            cmd = self._cdp_cmd_by_name.pop(cmd)
        except KeyError as err:
            raise errors.DevToolsCMDNotFoundError(
                "<{}>\nCannot rename command {}. Chrome Devtools Protocol "
                "command not found.".format(self.__class__.__name__, repr(cmd))
            ) from err

        # Cache with new name
        return self.cache_cdp_cmd(name, cmd.cmd, **cmd.kwargs)

    async def execute_cdp_cmd(
        self, cmd: str | DevToolsCMD, **kwargs: Any
    ) -> dict[str, Any]:
        """Execute Chrome Devtools Protocol command and return the execution result.
        The command and params should follow chrome devtools protocol domains/commands.
        For more detail, please refer to:
        https://chromedevtools.github.io/devtools-protocol/

        :param cmd: Accepts three kinds of input:
            - `<str>` The command line for chrome devtools protocal.
            - `<str>` The name of a cached Chrome Devtools Protocol command.
            - `<DevToolsCMD>` A cached Chrome Devtools Protocol command instance.

        :param kwargs: `<Any>` Additional keyword arguments for the command.
            - If executing a cached Chrome Devtools Protocol command, the '*kwargs'
              in this method is always prioritized over the cached arguments. Only
              when the '*kwargs' is empty, the cached arguments will be used.

        :return `<dict>`: The responce from the command execution.

        ### Example:
        >>> # . execute command line
            cmd = "Browser.getVersion"
            await session.execute_cdp_cmd(cmd)

        >>> # . execute cached command by name
            session.cache_cdp_cmd("get_version", "Browser.getVersion")
            await session.execute_cdp_cmd("get_version")

        >>> # . execute cached command by instance
            cmd = session.cache_cdp_cmd("get_version", "Browser.getVersion")
            await session.execute_cdp_cmd(cmd)
        """
        # Execute cached command
        command = self.get_cdp_cmd(cmd)
        if command is not None:
            return await self._execute_cdp_cmd(command.cmd, **kwargs or command.kwargs)
        # Execute command line
        else:
            return await self._execute_cdp_cmd(cmd, **kwargs)

    async def _execute_cdp_cmd(self, cmd: str, **kwargs: Any) -> dict[str, Any]:
        """(Internal) Execute Chrome Devtools Protocol command and return the
        execution result.The command and params should follow chrome devtools
        protocol domains/commands. For more detail, please refer to:
        https://chromedevtools.github.io/devtools-protocol/

        :param cmd: `<str>` The command line for chrome devtools protocal.
        :param kwargs: `<Any>` Additional keyword arguments for the command.
        :return `<dict>`: The responce from the command execution.

        ### Example:
        >>> await session.execute_cdp_cmd(
                "Runtime.evaluate", expression="window.location.href",
            )
            # {'result': {'type': 'string', 'value': 'https://www.google.com/'}}
        """
        res = await self.execute_command(
            Command.EXECUTE_CDP_COMMAND,
            body={"cmd": cmd, "params": kwargs},
            keys=self._vendor,
        )
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse Chrome Devtools Protocol command exeuction "
                "result from response: {}".format(self.__class__.__name__, res)
            ) from err

    def _validate_cdp_cmd_name(self, name: str) -> None:
        """(Internal) Validate CDP command name `<str>`."""
        if not isinstance(name, str) or not name:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid Chrome Devtools Protocol command "
                "name: {} {}.".format(self.__class__.__name__, repr(name), type(name))
            )
        if name in self._cdp_cmd_by_name:
            raise errors.InvalidArgumentError(
                "<{}>\nChrome DevTools Protocol command name '{}' "
                "has been taken. Please choose another one.".format(
                    self.__class__.__name__, name
                )
            )
        return name

    # Chromium - Logs ---------------------------------------------------------------------
    @property
    async def log_types(self) -> list[str]:
        """Access the available log types of the session `<list[str]>`.

        ### Example:
        >>> log_types = await session.log_types
            # ['browser', 'driver', 'client', 'server']
        """
        # Request available log types
        res = await self.execute_command(Command.GET_AVAILABLE_LOG_TYPES)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse log types from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    async def get_logs(self, log_type: str) -> list[dict[str, Any]]:
        """Get a specific type of logs of the session.

        ### Notice
        Once the logs are retrieved, they will be cleared (removed) from the session.

        :param log_type: `<str>` The log type. e.g. `'browser'`, `'driver'`, `'client'`, `'server'`, etc.
        :return `<list[dict[str, Any]]>`: The logs for the specified log type.

        ### Example:
        >>> logs =  await session.get_logs("browser")
            # [
            #    {"level": "WARNING", "message": "...", "source": "..,", "timestamp": 1700...,}
            #    {"level": "SEVERE", "message": "...", "source": "..,", "timestamp": 1700...,}
            # ]
        """
        try:
            res = await self.execute_command(Command.GET_LOG, body={"type": log_type})
        except errors.InvalidArgumentError:
            return []
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse logs from "
                "response: {}".format(self.__class__.__name__, res)
            ) from err

    # Special methods ---------------------------------------------------------------------
    def _collect_garbage(self) -> None:
        """(Internal) Collect garbage."""
        super()._collect_garbage()
        # Devtools cmd
        self._cdp_cmd_by_name = None
