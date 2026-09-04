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
"""Aselenium session implementation and supporting types."""

from __future__ import annotations

import asyncio
from asyncio import sleep
from base64 import b64decode, b64encode
from collections.abc import Awaitable, Callable
from copy import deepcopy
from math import ceil
from time import monotonic as unix_time
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NoReturn,
    TypeVar,
)
from urllib.parse import quote
from uuid import uuid4

from aselenium import errors, javascript
from aselenium._async import finish_owned, run_blocking
from aselenium._output import save_bytes
from aselenium._wait import first_match, poll
from aselenium.actions import Actions
from aselenium.alert import Alert
from aselenium.command import Command
from aselenium.connection import Connection
from aselenium.element import ELEMENT_KEY, Element
from aselenium.errors import ErrorCode
from aselenium.options import BaseOptions, ChromiumBaseOptions, Timeouts
from aselenium.settings import Constraint, DefaultNetworkConditions
from aselenium.utils import CustomDict, Rectangle, validate_save_file_path
from aselenium.valuewrap import warp_tuple

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from aselenium.manager.version import ChromiumVersion, Version
    from aselenium.service import BaseService, ChromiumBaseService
    from aselenium.shadow import Shadow

T = TypeVar("T")

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
    """Represent a cookie of the webpage."""

    def __init__(self, **data: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            **data: The cookie data.
        """
        super().__init__(**data)
        # Validate name
        if "name" in self._dict:
            self.__nkey: str = "name"
        elif "Name" in self._dict:
            self.__nkey: str = "Name"
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nLack of required attribute 'name': {}.".format(
                    self.__class__.__name__, repr(self._dict)
                )
            )

    # Name --------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Return the name of the cookie.

        Returns:
            The name of the cookie.
        """
        return self._dict[self.__nkey]

    @name.setter
    def name(self, value: str) -> None:
        """Set the name.

        Args:
            value: New name value.
        """
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
        """Return the data of the cookie.

        Returns:
            The data of the cookie.
        """
        return self._dict

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<Cookie (name=%r, data=<redacted>)>" % self.name

    def copy(self) -> Cookie:
        """Copy the cookie object.

        Returns:
            An independent copy of this value object.
        """
        return Cookie(**self._dict)


class DevToolsCMD:
    """Represent a cached Chrome DevTools Protocol command."""

    def __init__(
        self,
        name: str,
        cmd: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            name: The name of the command.
            cmd: The command lines for the devtools protocol.
            **kwargs: Additional keyword arguments for the command.
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
        """Return the name of the command.

        Returns:
            The name of the command.
        """
        return self._name

    @property
    def cmd(self) -> str:
        """Return the command line.

        Returns:
            The command line.
        """
        return self._cmd

    @property
    def kwargs(self) -> dict[str, Any]:
        """Return the keyword arguments for the command.

        Returns:
            The keyword arguments for the command.
        """
        return self._kwargs

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<DevToolsCMD (name=%r, payload=<redacted>)>" % self._name

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        if isinstance(__o, str):
            return self._name == __o
        elif isinstance(__o, DevToolsCMD):
            return self._name == __o._name and self._cmd == __o._cmd
        else:
            return False

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self) -> DevToolsCMD:
        """Copy the DevTools Command object.

        Returns:
            An independent copy of this value object.
        """
        cmd = DevToolsCMD(self._name, self._cmd)
        cmd._kwargs = deepcopy(self._kwargs)
        return cmd


class JavaScript:
    """Represent a cached javascript of the session."""

    def __init__(self, name: str, script: str, *args: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            name: The name of the javascript.
            script: The raw javascript code.
            *args: The arguments for the javascript.
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
        """Return the name of the javascript.

        Returns:
            The name of the javascript.
        """
        return self._name

    @property
    def script(self) -> str:
        """Return the javascript code.

        Returns:
            The javascript code.
        """
        return self._script

    @property
    def args(self) -> list[Any]:
        """Return the arguments for the javascript.

        Returns:
            The arguments for the javascript.
        """
        return self._args

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<JavaScript (name=%r, payload=<redacted>)>" % self._name

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        if isinstance(__o, str):
            return self._name == __o
        elif isinstance(__o, JavaScript):
            return self._name == __o._name and self._script == __o._script
        else:
            return False

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self) -> JavaScript:
        """Copy the javascript object.

        Returns:
            An independent copy of this value object.
        """
        js = JavaScript(self._name, self._script)
        js._args = deepcopy(self._args)
        return js


class Network:
    """Represent the network condition of the session."""

    def __init__(
        self,
        offline: bool | None = None,
        latency: int | None = None,
        upload_throughput: int | None = None,
        download_throughput: int | None = None,
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            offline: Whether to simulate an offline
                network condition. If `None`, set to default condition.
            latency: The minimum latency overhead. If
                `None`, set to default condition.
            upload_throughput: The maximum upload throughput
                in bytes per second. If `None`, set to default condition.
            download_throughput: The maximum download
                throughput in bytes per second. If `None`, set to default condition.
        """
        self._offline: bool = DefaultNetworkConditions.OFFLINE
        self._latency: int = DefaultNetworkConditions.LATENCY
        self._upload_throughput: int = DefaultNetworkConditions.UPLOAD_THROUGHPUT
        self._download_throughput: int = DefaultNetworkConditions.DOWNLOAD_THROUGHPUT
        # Set values
        self.offline = offline
        self.latency = latency
        self.upload_throughput = upload_throughput
        self.download_throughput = download_throughput

    # Dict --------------------------------------------------------------------------------
    @property
    def dict(self) -> dict[str, int]:
        """Return the network condition as a dictionary.

        Returns:
            Offline state, latency in milliseconds, and throughput limits in bytes
            per second. A throughput of -1 disables that throughput limit.

        Example:
            >>> from aselenium import Network
            >>> Network().dict
            {'offline': False, 'latency': 0, 'upload_throughput': -1, 'download_throughput': -1}
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
        """Return the network offline condition.

        Returns:
            True when the checked condition is satisfied; otherwise False.
        """
        return self._offline

    @offline.setter
    def offline(self, value: bool | None) -> None:
        # Value is None
        """Set the offline.

        Args:
            value: New offline value. None is handled according to the property's reset/ignore semantics.
        """
        if value is None:
            if self._offline is None:
                self._offline = DefaultNetworkConditions.OFFLINE
        # Set value
        else:
            self._offline = bool(value)

    # Latency -----------------------------------------------------------------------------
    @property
    def latency(self) -> int:
        """Return the network latency condition.

        Returns:
            The network latency condition.
        """
        return self._latency

    @latency.setter
    def latency(self, value: int | None) -> None:
        # Value is None
        """Set the latency.

        Args:
            value: New latency value. None is handled according to the property's reset/ignore semantics.
        """
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
        """Return the network upload throughput condition.

        Returns:
            The network upload throughput condition.
        """
        return self._upload_throughput

    @upload_throughput.setter
    def upload_throughput(self, value: int | None) -> None:
        # Value is None
        """Set the upload throughput.

        Args:
            value: New upload throughput value. None is handled according to the property's reset/ignore semantics.
        """
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
        """Return the network download throughput condition.

        Returns:
            The network download throughput condition.
        """
        return self._download_throughput

    @download_throughput.setter
    def download_throughput(self, value: int | None) -> None:
        # Value is None
        """Set the download throughput.

        Args:
            value: New download throughput value. None is handled according to the property's reset/ignore semantics.
        """
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
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
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
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return hash(self) == hash(__o) if isinstance(__o, Network) else False

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self) -> Network:
        """Copy the network condition object.

        Returns:
            An independent copy of this value object.
        """
        return Network(
            offline=self._offline,
            latency=self._latency,
            upload_throughput=self._upload_throughput,
            download_throughput=self._download_throughput,
        )


class Permission:
    """Represent a permission of the session."""

    def __init__(
        self,
        name: str,
        state: Literal["granted", "denied", "prompt"],
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            name: Name identifying the requested item.
            state: State used by this operation.
        """
        self.name = name
        self.state = state

    # Dict  --------------------------------------------------------------------------------
    @property
    def dict(self) -> dict[str, str]:
        """Return the permission as a dictionary.

        Expected format:
        >>> {"name": "video_capture", "state": "prompt"}

        Returns:
            The permission as a dictionary.
        """
        return {"name": self._name, "state": self._state}

    # Name --------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Return the name of the permission.

        Returns:
            The name of the permission.
        """
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        """Set the name.

        Args:
            value: New name value.
        """
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
        """Return the permission state.

        Expected values: `"granted"`, `"denied"`, `"prompt"`

        Returns:
            The permission state.
        """
        return self._state

    @state.setter
    def state(self, value: str) -> None:
        """Set the state.

        Args:
            value: New state value.
        """
        if value not in Constraint.PERMISSION_STATES:
            raise errors.InvalidPermissionStateError(
                "<{}>\nInvalid permission state: {} {}.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        self._state: str = value

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<Permission (name='%s', state='%s')>" % (self._name, self._state)

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return hash(self) == hash(__o) if isinstance(__o, Permission) else False

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self) -> Permission:
        """Copy the network condition object.

        Returns:
            An independent copy of this value object.
        """
        return Permission(name=self._name, state=self._state)


class Viewport(Rectangle):
    """Represent the size and relative position of a window viewport."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            width: The width of the viewport.
            height: The height of the viewport.
            x: The x-coordinate of the viewport.
            y: The y-coordinate of the viewport.
        """
        super().__init__(width, height, x, y)

    # Special methods ---------------------------------------------------------------------
    def copy(self) -> Viewport:
        """Copy the viewport.

        Returns:
            An independent copy of this value object.
        """
        return super().copy()


class Window:
    """Represent a window of the session."""

    def __init__(self, handle: str, name: str | None = None) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            handle: The unique handle of the window.
            name: The name of the window. Defaults to `uuid4()`.
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
        """Return the name of the window.

        Returns:
            The name of the window.
        """
        return self._name

    @property
    def handle(self) -> str:
        """Return the unique handle of the window.

        Returns:
            The unique handle of the window.
        """
        return self._handle

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<Window (name='%s', handle='%s')>" % (self._name, self._handle)

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        if isinstance(__o, str):
            return self._name == __o
        elif isinstance(__o, Window):
            return self._name == __o._name and self._handle == __o._handle
        else:
            return False

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self) -> Window:
        """Copy the window object.

        Returns:
            An independent copy of this value object.
        """
        return Window(self._handle, name=self._name)


class WindowRect(Rectangle):
    """Represent the size and relative position of a window."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            width: The width of the window.
            height: The height of the window.
            x: The x-coordinate of the window.
            y: The y-coordinate of the window.
        """
        super().__init__(width, height, x, y)

    # Special methods ---------------------------------------------------------------------
    def copy(self) -> WindowRect:
        """Copy the window rectangle.

        Returns:
            An independent copy of this value object.
        """
        return super().copy()


# Session -----------------------------------------------------------------------------------------
class Session:
    """Represent a session of the browser."""

    def __init__(self, options: BaseOptions, service: BaseService) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            options: The browser options.
            service: The webdriver service.
        """
        # Options
        self._options: BaseOptions = options
        self._browser_location: str | None = self._options.browser_location
        self._browser_version: str | None = self._options.browser_version
        # Service
        self._service: BaseService = service
        # Connection
        self._conn: Connection | None = None
        # Vender prefix
        self._vendor: dict[str, str] = {"vendorPrefix": self._options.VENDOR_PREFIX}
        # Session
        self._id: str | None = None
        self._base_url: str | None = None
        self._timeouts: Timeouts | None = None
        self._session_timeout: int | float = options._session_timeout
        # Window
        self._window_by_name: dict[str, Window] = {}
        self._window_by_handle: dict[str, Window] = {}
        # Script
        self._script_by_name: dict[str, JavaScript] = {}
        # Status
        self.__closed: bool = False
        self._lifecycle_lock = asyncio.Lock()

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> BaseOptions:
        """Return the browser options.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    @property
    def browser_version(self) -> str | None:
        """Return the browser version string recorded for this configuration or session.

        Returns:
            The version string, or None when no browser version has been recorded.
            This property does not probe the browser or return a Version object.
        """
        return self._browser_version

    @property
    def browser_location(self) -> str:
        """Return the browser binary location of the session.

        Returns:
            The browser binary location of the session.
        """
        return self._browser_location

    @property
    def service(self) -> BaseService:
        """Return the webdriver service.

        Returns:
            The driver service owned by the session.
        """
        return self._service

    @property
    def driver_version(self) -> Version:
        """Return the webdriver binary version of the session.

        Returns:
            The webdriver binary version of the session.
        """
        return self._service._driver_version

    @property
    def driver_location(self) -> str:
        """Return the webdriver binary location of the session.

        Returns:
            The webdriver binary location of the session.
        """
        return self._service._driver_location

    @property
    def connection(self) -> Connection:
        """Return the session connection.

        Returns:
            The session connection.
        """
        return self._conn

    @property
    def id(self) -> str:
        """Return the ID of the session.

        Returns:
            The id of the session.
        """
        return self._id

    @property
    def base_url(self) -> str:
        """Return the base `service` URL of the session.

        Returns:
            The base `service` url of the session.
        """
        return self._base_url

    # Execute -----------------------------------------------------------------------------
    async def execute_command(
        self,
        command: str,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Executes a command from the session.

        Args:
            command: The command to execute.
            body: The body of the command. Defaults to `None`.
            keys: The keys to substitute in the command. Defaults to `None`.
            timeout: Session timeout for command execution. Defaults to `None`.
                This argument overrides the default `options.session_timeout`,
                which is designed to cope with a frozen session due to unknown
                errors. For more information about session timeout, please refer
                to the documentation of `options.session_timeout` attribute.

        Returns:
            The response from the command.
        """
        return await self._conn.execute(
            self._base_url,
            command,
            body=body,
            keys=keys,
            timeout=timeout,
        )

    # Start / Quit ------------------------------------------------------------------------
    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Own a sequence of commands on this session's mutable browser state.

        Ownership follows the inherited asynchronous context, including internal
        polling and wait-for tasks. Child tasks created inside this context share
        logical ownership; await dependent operations sequentially rather than
        running them concurrently within the same transaction.

        Returns:
            An asynchronous context manager that serializes commands issued through
            this session connection. It does not roll back browser state on failure.

        Example:
            >>> async with session.transaction():
            ...     await session.switch_window("details")
            ...     title = await session.title
        """
        if self._conn is None:
            raise errors.InvalidSessionError("Session has not started")
        return self._conn.transaction()

    async def wait_for(
        self, condition: Callable[[], Awaitable[T]], timeout: float | None = 5
    ) -> T | None:
        """Poll an async no-argument predicate under one total deadline.

        Returns its first truthy value, or a falsey value on timeout. Exceptions
        other than an expired wait deadline propagate; cancellation is preserved.

        Args:
            condition: Asynchronous no-argument predicate whose truthy result completes the wait.
            timeout: Nonnegative total budget in seconds. Zero or None performs one observation; it does not disable all underlying request timeouts.

        Returns:
            The first truthy predicate result, or a falsey result/None when the deadline expires.

        Example:
            >>> _ = await session.set_timeouts(implicit=0)
            >>> async def ready():
            ...     field = await session.find_element("#name")
            ...     return field if field is not None and await field.enabled else None

            >>> field = await session.wait_for(ready, timeout=5)
        """
        return await poll(condition, timeout)

    async def start(self) -> Window:
        """Start the owned service and create the default browser window once.

        Returns:
            The initial browser window, registered under the name "default".

        Example:
            >>> window = await session.start()
            >>> try:
            ...     await session.load("https://example.com")
            ... finally:
            ...     await session.quit()
        """
        async with self._lifecycle_lock:
            if self.__closed:
                raise errors.InvalidSessionError(
                    "Session is closed; acquire a new session"
                )
            if self._id is not None:
                return await self.active_window
            try:
                await self._service.start()
                self._conn = Connection(self._service.session, self._session_timeout)
                return await self._start_session("default")
            except BaseException:
                try:
                    await finish_owned(self._quit_owned())
                except BaseException:
                    pass
                raise

    async def _quit_owned(self) -> None:
        """Delete the remote session where possible and finish local service cleanup."""
        if self.__closed:
            return
        if self._conn is not None and self._id is not None:
            try:
                await self.execute_command(Command.QUIT, timeout=1)
            except Exception:
                # Deletion is best effort, local owned service teardown is not.
                pass
        await self._service.stop()
        self._collect_garbage()

    async def quit(self) -> None:
        """Close the browser session and await its owned service teardown.

        Example:
            >>> await session.quit()  # Safe to repeat after successful teardown.
        """

        async def close() -> None:
            """Finish cleanup owned by the enclosing operation."""
            async with self._lifecycle_lock:
                await self._quit_owned()

        await finish_owned(close())

    async def _start_session(self, name: str = "default") -> Window:
        """Start the default window of session, and returns it. This method should only be called when session service is started or all the windows of the session are closed.

        Args:
            name: The name of the first window for the session. Defaults to `'default'`.

        Returns:
            The Window value produced by this operation.
        """

        def parse_session_id(res: dict[str, Any]) -> str:
            """Extract the nested W3C new-session ID or reject the response.

            Args:
                res: Res used by this operation.

            Returns:
                The nonempty ID from value.sessionId in a W3C new-session response.
            """
            envelope = res.get("value") if isinstance(res, dict) else None
            if isinstance(envelope, dict):
                session_id = envelope.get("sessionId")
                if isinstance(session_id, str) and session_id:
                    return session_id
            raise errors.InvalidSessionError(
                "New Session response must contain a nonempty string value.sessionId"
            )

        # Validate service
        if not await run_blocking(lambda: self._service.running):
            raise errors.InvalidSessionError(
                "<{}>\nFailed to create new session. Please `start()` "
                "the service of the session first.".format(self.__class__.__name__)
            )

        # Start session
        capabilities = await run_blocking(lambda: self._options.capabilities)
        try:
            res = await self._conn.execute(
                "",
                Command.NEW_SESSION,
                body={"capabilities": {"alwaysMatch": capabilities}},
                timeout=10,
            )
        finally:
            # A driver can launch a browser even when its handshake fails. Capture
            # those identities now, while their service ancestry is still known.
            capture_children = getattr(self._service, "_capture_session_children", None)
            if capture_children is not None:
                await capture_children()
        self._id = parse_session_id(res)
        self._base_url = "/session/" + quote(self._id, safe="")

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
        retry: int | None = None,
    ) -> None:
        """Load a web page in the active window.

        Args:
            url: URL to be loaded.
            timeout: Session timeout for page loading. Defaults to `None`.
                This argument overrides the default `options.session_timeout`,
                which is designed to cope with a frozen session due to unknown
                errors. For more information about session timeout, please refer
                to the documentation of `options.session_timeout` attribute. If
                the webdriver fails to response in time, a `SessionTimeoutError`
                will be raised.
            retry: Number of additional attempts after a native page-load timeout.
                Must be a nonnegative integer or `None`; booleans are rejected.
                Both `None` and `0` perform one attempt without retrying.
                Retries are attempted only when the `WebDriverTimeoutError` is
                raised due to native `pageLoad` timeout. The function does not
                retry on `SessionTimeoutError` (as mentioned above).
                For example, if `retry=1`, the function will try to load the page
                one more time if the initial attempt #0 fails.

        Raises:
            errors.InvalidArgumentError: If retry is not a nonnegative integer or None.

        Example:
            >>> await session.load("https://www.google.com")
        """
        retries = self._validate_navigation_retry(retry)
        for i in range(retries + 1):
            try:
                await self.execute_command(
                    Command.GET, body={"url": url}, timeout=timeout
                )
                return None  # exit: success
            except errors.WebDriverTimeoutError:
                if i == retries:
                    raise
                await sleep(0.1)

    async def refresh(
        self,
        timeout: int | float | None = None,
        retry: int | None = None,
    ) -> None:
        """Refresh the active page window.

        Args:
            timeout: Session timeout for page loading. Defaults to `None`.
                This argument overrides the default `options.session_timeout`,
                which is designed to cope with a frozen session due to unknown
                errors. For more information about session timeout, please refer
                to the documentation of `options.session_timeout` attribute. If
                the webdriver fails to response in time, a `SessionTimeoutError`
                will be raised.
            retry: Number of additional attempts after a native page-load timeout.
                Must be a nonnegative integer or `None`; booleans are rejected.
                Both `None` and `0` perform one attempt without retrying.
                Retries are attempted only when the `WebDriverTimeoutError` is
                raised due to native `pageLoad` timeout. The function does not
                retry on `SessionTimeoutError` (as mentioned above).
                For example, if `retry=1`, the function will try to refresh the page
                one more time if the initial attempt #0 fails.

        Raises:
            errors.InvalidArgumentError: If retry is not a nonnegative integer or None.

        Example:
            >>> await session.refresh()
        """
        retries = self._validate_navigation_retry(retry)
        for i in range(retries + 1):
            try:
                await self.execute_command(Command.REFRESH, timeout=timeout)
                return None  # exit
            except errors.WebDriverTimeoutError:
                if i == retries:
                    raise
                await sleep(0.1)

    def _validate_navigation_retry(self, retry: int | None) -> int:
        """Validate and normalize the number of additional navigation attempts.

        Args:
            retry: Nonnegative integer or None for no retries.

        Returns:
            The additional attempt count, with None normalized to zero.

        Raises:
            errors.InvalidArgumentError: If retry is negative, boolean, or not an integer.
        """
        if retry is None:
            return 0
        if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
            raise errors.InvalidArgumentError(
                "Navigation retry must be a nonnegative integer or None."
            )
        return retry

    async def forward(self, timeout: int | float | None = None) -> None:
        """Navigate forwards in the browser history (if possible).

        Args:
            timeout: Session timeout for page loading. Defaults to `None`.
                This argument overrides the default `options.session_timeout`,
                which is designed to cope with a frozen session due to unknown
                errors. For more information about session timeout, please refer
                to the documentation of `options.session_timeout` attribute. If
                the webdriver fails to response in time, a `SessionTimeoutError`
                will be raised.

        Example:
            >>> await session.forward()
        """
        await self.execute_command(Command.GO_FORWARD, timeout=timeout)

    async def backward(self, timeout: int | float | None = None) -> None:
        """Navigate backwards in the browser history (if possible).

        Args:
            timeout: Session timeout for page loading. Defaults to `None`.
                This argument overrides the default `options.session_timeout`,
                which is designed to cope with a frozen session due to unknown
                errors. For more information about session timeout, please refer
                to the documentation of `options.session_timeout` attribute. If
                the webdriver fails to response in time, a `SessionTimeoutError`
                will be raised.

        Example:
            >>> await session.backward()
        """
        await self.execute_command(Command.GO_BACK, timeout=timeout)

    # Information -------------------------------------------------------------------------
    @property
    async def url(self) -> str:
        """Return the URL of the active page window.

        Returns:
            The url of the active page window.

        Example:
            >>> await session.url # "https://www.google.com/"
        """
        res = await self.execute_command(Command.GET_CURRENT_URL)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse page url from response: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def wait_until_url(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the URL of the active page window satisfies the given condition.

        Args:
            condition: The condition the URL needs to satisfy.
                Expected values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
            value: The value of the condition.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the URL satisfies the condition, False if timeout.

        Example:
            >>> await session.load("https://www.google.com/")
            >>> await session.wait_until_url("contains", "google", 5)  # True / False
        """

        async def equals() -> bool:
            """Check whether the current text exactly matches the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.url == value

        async def contains() -> bool:
            """Check whether the current text contains the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return value in await self.url

        async def startswith() -> bool:
            """Check whether the current text begins with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return (await self.url).startswith(value)

        async def endswith() -> bool:
            """Check whether the current text ends with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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

        return bool(await poll(lambda: condition_checker(), timeout))

    @property
    async def title(self) -> str:
        """Return the title of the active page window.

        Returns:
            The title of the active page window.

        Example:
            >>> await session.title # "Google"
        """
        res = await self.execute_command(Command.GET_TITLE)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse page title from response: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    async def wait_until_title(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the title of the active page window satisfies the given condition.

        >>> await session.load("https://www.google.com/")
            await session.wait_until_title("contains", "Google", 5)  # True / False

        Args:
            condition: The condition the title needs to satisfy.
                Expected values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
            value: The value of the condition.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the title satisfies the condition, False if timeout.
        """

        async def equals() -> bool:
            """Check whether the current text exactly matches the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return await self.title == value

        async def contains() -> bool:
            """Check whether the current text contains the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return value in await self.title

        async def startswith() -> bool:
            """Check whether the current text begins with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            return (await self.title).startswith(value)

        async def endswith() -> bool:
            """Check whether the current text ends with the expected value.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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

        return bool(await poll(lambda: condition_checker(), timeout))

    @property
    async def viewport(self) -> Viewport:
        """Return the size and relative position of the viewport for active page window.

        Returns:
            The size and relative position of the viewport for active page window.

        Example:
            >>> viewport = await session.viewport
        """
        try:
            res = await self._execute_script(javascript.GET_PAGE_VIEWPORT)
        except errors.InvalidJavaScriptError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to request page viewport: {}".format(
                    self.__class__.__name__, err
                )
            ) from err
        try:
            return Viewport(**res)
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid page viewport response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    @property
    async def page_width(self) -> int:
        """Return the width of the active page window.

        Returns:
            The width of the active page window.

        Example:
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
        """Return the height of the active page window.

        Returns:
            The height of the active page window.

        Example:
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
        """Return the source of the active page window.

        Returns:
            The source of the active page window.

        Example:
            >>> source = await session.page_source
        """
        res = await self.execute_command(Command.GET_PAGE_SOURCE)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse page source from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def take_screenshot(self) -> bytes:
        """Take a screenshot of the active page window.

        Returns:
            Take a screenshot of the active page window.

        Example:
            >>> screenshot = await session.take_screenshot()
        """
        res = await self.execute_command(Command.SCREENSHOT)
        try:
            return self._decode_base64(res["value"], "ascii")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse screenshot data from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid screenshot response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    async def save_screenshot(self, path: str) -> bool:
        """Take & save the screenshot of the active page window into a local PNG file.

        Args:
            path: The path to save the screenshot. e.g. `~/path/to/screenshot.png`.

        Returns:
            True if the screenshot has been saved, False if failed.

        Example:
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
            return await save_bytes(path, data)
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

        Args:
            orientation: The print orientation. Accepts: "portrait", "landscape".
            scale: The scale of the page rendering. Must between 0.1 - 2.
            background: Whether to print the CSS backgrounds.
            page_width: Paper width.
            page_height: Paper height.
            margin_top: Top margin size.
            margin_bottom: Bottom margin size.
            margin_left: Left margin size.
            margin_right: Right margin size.
            shrink_to_fit: Whether to scale page to fit paper size.
            page_ranges: Paper ranges to print, e.g., ['1-5', '8', '11-13'].

        Returns:
            The page PDF data.

        Example:
            >>> await session.print_page()
        """

        def orie_validator(param: str, value: str) -> bool:
            """Validate the page-print orientation.

            Args:
                param: Param used by this operation.
                value: The page-print orientation supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if value is None:
                return False
            if value not in Constraint.PAGE_ORIENTATIONS:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid print {}: {}. Available options: {}".format(
                        self.__class__.__name__,
                        param,
                        repr(value),
                        sorted(Constraint.PAGE_ORIENTATIONS),
                    )
                )
            return True

        def scal_validator(param: str, value: float) -> bool:
            """Validate the page-print scale range.

            Args:
                param: Param used by this operation.
                value: The page-print scale range supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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
            """Validate a boolean page-print setting.

            Args:
                param: Param used by this operation.
                value: A boolean page-print setting supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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
            """Validate numeric page dimensions and margins.

            Args:
                param: Param used by this operation.
                value: Numeric page dimensions and margins supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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
            """Validate page ranges for the print command.

            Args:
                param: Param used by this operation.
                value: Page ranges for the print command supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
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
                "<{}>\nFailed to parse print data from response: {}".format(
                    self.__class__.__name__, res
                )
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

        Args:
            path: The path to save the PDF. e.g. `~/path/to/screenshot.png`.
            orientation: The print orientation. Accepts: "portrait", "landscape".
            scale: The scale of the page rendering. Must between 0.1 - 2.
            background: Whether to print the CSS backgrounds.
            page_width: Paper width.
            page_height: Paper height.
            margin_top: Top margin size.
            margin_bottom: Bottom margin size.
            margin_left: Left margin size.
            margin_right: Right margin size.
            shrink_to_fit: Whether to scale page to fit paper size.
            page_ranges: Paper ranges to print, e.g., ['1-5', '8', '11-13'].

        Returns:
            True if the PDF has been saved, False if failed.

        Example:
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
            return await save_bytes(path, data)
        finally:
            del data

    # Timeouts ----------------------------------------------------------------------------
    @property
    async def timeouts(self) -> Timeouts:
        """Return the timeouts of the current session.

        Timeouts explain:

        - implicit: The amount of time the current sessions will wait when
        searching for an element if not immediately present.

        - pageLoad: The amount of time the current sessions will wait for
        a page load to complete before raising an error.

        - script: The amount of time the current sessions will wait for an
        asynchronous script to finish execution before raising an error.

        Returns:
            The timeouts of the current session.

        Example:
            >>> timeouts = await session.timeouts
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
        """Set session timeouts using seconds, converted to protocol milliseconds.

        The read, update, and refresh share command ownership so concurrent
        partial updates preserve each other's fields. An interrupted mutation
        invalidates the cached snapshot because its remote outcome is unknown.

        Args:
            implicit: Total `seconds` the current session
                should wait when searching for an element if not immediately present.
                If `None (default)`, keep the current implicit timeout.
            pageLoad: Total `seconds` the current session
                should wait for a page load to complete before returning an error. if
                `None (default)`, keep the current pageLoad timeout.
            script: Total `seconds` the current session
                should wait for an asynchronous script to finish execution before
                returning an error. if `None (default)`, keep the current script timeout.

        Returns:
            The timeouts after update.

        Example:
            >>> timeouts = await session.set_timeouts(
            ...     implicit=0.1, pageLoad=30, script=3
            ... )
        """
        async with self.transaction():
            timeouts = await self.timeouts
            if implicit is not None:
                timeouts.implicit = implicit
            if pageLoad is not None:
                timeouts.pageLoad = pageLoad
            if script is not None:
                timeouts.script = script
            self._timeouts = None
            await self._conn.execute(
                self._base_url, Command.SET_TIMEOUTS, body=timeouts.dict
            )
            await self._refresh_timeouts()
            return self._timeouts.copy()

    async def reset_timeouts(self) -> Timeouts:
        """Reset session timeouts atomically to the original option values.

        Returns:
            The Timeouts value produced by this operation.

        Example:
            >>> timeouts = await session.reset_timeouts()
        """
        async with self.transaction():
            self._timeouts = None
            await self._conn.execute(
                self._base_url,
                Command.SET_TIMEOUTS,
                body=self._options.timeouts.dict,
            )
            await self._refresh_timeouts()
            return self._timeouts.copy()

    async def _refresh_timeouts(self) -> None:
        """Refresh the timeouts of the current session."""
        res = await self.execute_command(Command.GET_TIMEOUTS)
        try:
            self._timeouts = Timeouts(**res["value"], unit="ms")
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse timeouts from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid timeouts response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    async def _get_timeouts(self) -> Timeouts:
        """Get the cached timeouts of the current session.

        Returns:
            The stored timeouts.
        """
        if self._timeouts is None:
            await self._refresh_timeouts()
        return self._timeouts

    # Cookies -----------------------------------------------------------------------------
    @property
    async def cookies(self) -> list[Cookie]:
        """Return all the cookies of the active page window.

        Returns:
            Cookies in response order, or an empty list when none are present.

        Raises:
            errors.InvalidResponseError: If the response is not a list of cookie objects.

        Example:
            >>> cookies = await session.cookies
        """
        # Request cookies
        res = await self.execute_command(Command.GET_ALL_COOKIES)
        cookies = res.get("value")
        if not isinstance(cookies, list):
            raise errors.InvalidResponseError(
                "Cookie collection response must contain a list of cookie objects."
            )
        # Create cookies
        return [self._create_cookie(cookie) for cookie in cookies]

    async def get_cookie(self, name: str | Cookie) -> Cookie | None:
        """Get a specific cookie from the active page window.

        Args:
            name: The name of the cookie or a  instance.

        Returns:
            The specified cookie, or `None` if not found.

        Example:
            >>> cookie = await session.get_cookie("ZFY")
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
                "<{}>\nFailed to parse cookie data from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def add_cookie(self, cookie: dict[str, Any] | Cookie) -> Cookie:
        """Add a cookie to the active page window.

        Args:
            cookie: Cookie as a dictionary or a  instance.

        Returns:
            The newly added cookie.

        Example:
            >>> cookie = await session.add_cookie({'name' : 'foo', 'value' : 'bar'})
        """
        # Construct cookie
        if isinstance(cookie, Cookie):
            pass
        elif isinstance(cookie, dict):
            cookie = self._create_cookie(cookie)
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'cookie' arguement: {}. Must be "
                "a dictionary or `<'Cookie'>` instance".format(
                    self.__class__.__name__, cookie
                )
            )
        # Execute & return
        await self.execute_command(Command.ADD_COOKIE, {"cookie": cookie.dict})
        return await self.get_cookie(cookie)

    async def delete_cookie(self, name: str | Cookie) -> None:
        """Delete a cookie from the active page window.

        Args:
            name: The name of the cookie or a  instance.

        Example:
            >>> await session.delete_cookie("ZFY")
        """
        await self.execute_command(
            Command.DELETE_COOKIE,
            keys={"name": self._validate_cookie_name(name)},
        )

    async def delete_cookies(self) -> None:
        """Delete all cookies from the active page window.

        Example:
            >>> await session.delete_cookies()
        """
        await self.execute_command(Command.DELETE_ALL_COOKIES)

    def _validate_cookie_name(self, name: Any) -> str:
        """Validate the name of a cookie.

        Args:
            name: Name identifying the requested item.

        Returns:
            The name of a cookie.
        """
        if isinstance(name, str):
            return name
        elif isinstance(name, Cookie):
            return name.name
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid cookie 'name': {} {}. Must be "
                "a string or `<'Cookie'>` instance.".format(
                    self.__class__.__name__, repr(name), type(name)
                )
            )

    def _create_cookie(self, cookie: dict[str, Any]) -> Cookie:
        """Construct a cookie without exposing its payload in parsing errors.

        Args:
            cookie: Cookie fields, including the name required by Cookie.

        Returns:
            A new Cookie instance constructed from the current values.

        Raises:
            errors.InvalidResponseError: If the value cannot be constructed as a cookie.
        """
        if not isinstance(cookie, dict):
            raise errors.InvalidResponseError("Cookie data must be an object.")
        try:
            return Cookie(**cookie)
        except (TypeError, errors.InvalidArgumentError):
            raise errors.InvalidResponseError(
                "Cookie data must contain valid named fields, including a cookie name."
            ) from None

    # Window ------------------------------------------------------------------------------
    @property
    async def windows(self) -> list[Window]:
        """Return all the open windows of the session.

        Returns:
            All the open windows of the session.

        Example:
            >>> windows = await session.windows
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
                "<{}>\nFailed to parse window handles from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

        # Remove closed windows
        if not isinstance(handles, list) or any(
            not isinstance(handle, str) or not handle for handle in handles
        ):
            raise errors.InvalidResponseError(
                "Window handles response must contain a list of nonempty strings"
            )
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
        """Return the active (focused) window of the session. Returns `None` if no window is active.

        Returns:
            The active (focused) window of the session. returns `none` if no window is active.

        Example:
            >>> win = await session.active_window
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

        Args:
            window: Accepts three kinds of input:
                -: The name of the window.
                -: The handle of the window.
                -: A window instance.

        Returns:
            The matched open window of the session, or `None` if not found.

        Example:
            >>> win = await session.get_window("default")
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

        Name validation, creation, caching, and optional switching share command
        ownership. If every previous window has closed, a replacement session is
        started on the same service with the requested name and a new session ID.

        Args:
            name: The name of the new window.
            win_type: The type of the window to create, accepts: `'tab'` or `'window'`. Defaults to `'tab'`.
            switch: Whether to switch focus to the new window. Defaults to `True`.

        Returns:
            The newly created window.

        Example:
            >>> win = await session.new_window("new", "tab")
        """
        # Validate window type & name
        if win_type not in Constraint.WINDOW_TYPES:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid window win_type: {}. Available options: {}".format(
                    self.__class__.__name__,
                    repr(win_type),
                    sorted(Constraint.WINDOW_TYPES),
                )
            )
        async with self.transaction():
            name = self._validate_window_name(name)
            try:
                res = await self.execute_command(
                    Command.NEW_WINDOW, body={"type": win_type}
                )
            except errors.InvalidSessionError:
                # All windows are closed: start a new session.
                self._window_by_name = {}
                self._window_by_handle = {}
                return await self._start_session(name)
            try:
                win = self._cache_window(res["value"]["handle"], name=name)
            except KeyError as err:
                raise errors.InvalidResponseError(
                    "<{}>\nFailed to parse new window handle from response: {}".format(
                        self.__class__.__name__, res
                    )
                ) from err
            except Exception as err:
                raise errors.InvalidResponseError(
                    "<{}>\nInvalid new window response: {}".format(
                        self.__class__.__name__, res["value"]
                    )
                ) from err
            return await self.switch_window(win) if switch else win

    async def switch_window(self, window: str | Window) -> Window:
        """Switch to a specific open window of the session.

        Args:
            window: Accepts three kinds of input:
                -: The name of the window.
                -: The handle of the window.
                -: A window instance.

        Returns:
            The new focused window.

        Example:
            >>> win = await session.switch_window("new")
        """
        # Get existing window
        win = await self.get_window(window)
        if not win:
            raise errors.WindowNotFountError(
                "<{}>\nCan't switch to window {}. Window not found.".format(
                    self.__class__.__name__, repr(window)
                )
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

        Notice
        This method does not affect or make changes to the webdriver,
        but simple changes the name of the window cached in the program.

        Args:
            window: Accepts three kinds of input:
                -: The name of the window.
                -: The handle of the window.
                -: A window instance.
            new_name: The new name for the window.

        Returns:
            The window after name update.

        Example:
            >>> # Create a new window
            >>> win = await session.new_window("new")
            >>> # <Window (name='new', handle='9C03D8A1739E049EF6EE92ECE4032CD1')>

            >>> # Rename the window
            >>> win = await session.rename_window("new", "new_renamed")
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

        Window discovery, closing, and selection of a remaining window share
        command ownership; another task cannot switch windows between them.

        Args:
            switch_to: The window to switch to after closing the active window. Accepts four kinds of input:
                - `None (default)`: Switch to a random open window.
                -: Switch to an open window by window name.
                -: Switch to an open window by window handle.
                -: Switch to an open window by window instance.
                - `*Notice*` If the specified window does not exist, will automatically
                switch to a random open window.

        Returns:
            The new active (focus) window, or `None` if all windows are closed.

        Example:
            >>> win = await session.close_window()
        """
        async with self.transaction():
            if not (win := await self.active_window):
                return None
            await self.execute_command(Command.CLOSE)
            self._remove_window(win)
            if switch_to is not None:
                try:
                    return await self.switch_window(switch_to)
                except errors.InvalidSessionError:
                    return None
                except errors.WindowNotFountError:
                    pass
            try:
                if wins := await self.windows:
                    await self.switch_window(wins[0])
                    return wins[0]
                return None
            except (errors.InvalidSessionError, errors.WindowNotFountError):
                return None

    async def _active_window_handle(self) -> str | None:
        """Request the handle of the active (focus) window. Returns `None` if all windows are closed.

        Returns:
            Request the handle of the active (focus) window. Returns `None` if all windows are closed.
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
                "<{}>\nFailed to parse window handle from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def _match_session_window(self, window: str | Window) -> Window | None:
        """Match window from the current session.

        Args:
            window: Window used by this operation.

        Returns:
            The Window value produced by this operation. None indicates that no value is available.
        """
        for win in await self.windows:
            if window == win.handle or window == win.name:
                return win
        return None

    def _cache_window(self, handle: str, name: str = None) -> Window:
        """Cache the new window.

        Args:
            handle: Handle used by this operation.
            name: Name identifying the requested item.

        Returns:
            The Window value produced by this operation.
        """
        win = Window(handle, name=name)
        self._window_by_name[win.name] = win
        self._window_by_handle[win.handle] = win
        return win

    def _remove_window(self, window: str | Window) -> bool:
        """Remove cached window.

        Args:
            window: Window used by this operation.

        Returns:
            True when the checked condition is satisfied; otherwise False.
        """
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
        """Validate window name.

        Args:
            name: Name identifying the requested item.

        Returns:
            Window name.
        """
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
        """Return the size and relative position of the active window.

        Returns:
            The size and relative position of the active window.

        Example:
            >>> rect = await session.window_rect
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

        Reading the current rectangle and applying the partial update are
        serialized together, preserving concurrent updates to other dimensions.

        Args:
            width: The new width of the window. If `None (default)`, keep the current width.
            height: The new height of the window. If `None (default)`, keep the current height.
            x: The new x coordinate of the window. If `None (default)`, keep the current x coordinate.
            y: The new y coordinate of the window. If `None (default)`, keep the current y coordinate.

        Returns:
            The WindowRect value produced by this operation.

        Example:
            >>> rect = await session.set_window_rect(800, 500, 22, 60)
        """
        async with self.transaction():
            rect = await self.window_rect
            rect.width = width
            rect.height = height
            rect.x = x
            rect.y = y
            res = await self._change_windows_state(
                Command.SET_WINDOW_RECT, rect.dict, 20
            )
            return self._create_window_rect(res)

    async def maximize_window(self) -> WindowRect:
        """Maximize the active window.

        Returns:
            The window rectangle after maximization.

        Example:
            >>> rect = await session.maximize_window()
        """
        res = await self._change_windows_state(Command.W3C_MAXIMIZE_WINDOW, None, 20)
        return self._create_window_rect(res)

    async def minimize_window(self) -> None:
        """Minimize the active window.

        Example:
            >>> await session.minimize_window()
        """
        await self._change_windows_state(Command.MINIMIZE_WINDOW, None, 20)

    async def fullscreen_window(self) -> None:
        """Set the active window to fullscreen.

        Example:
            >>> await session.fullscreen_window()
        """
        await self._change_windows_state(Command.FULLSCREEN_WINDOW, None, 20)

    async def _change_windows_state(
        self,
        command: str,
        body: dict[str, Any] | None,
        retry: int,
    ) -> Any:
        """Change the state of the active window with retry.

        Args:
            command: Command identifier from aselenium.command.Command.
            body: JSON command parameters, or None when the command has no explicit payload.
            retry: Retry used by this operation.

        Returns:
            The Any value produced by this operation.
        """
        window_state_retry = 0
        while True:
            try:
                return await self.execute_command(command, body=body)
            except errors.ChangeWindowStateError:
                if window_state_retry >= retry:
                    raise
                window_state_retry += 1
                await sleep(0.2)

    def _create_window_rect(self, res: dict[str, Any]) -> WindowRect:
        """Parse & create window rect from response.

        Args:
            res: The direct response for window rect related response.

        Returns:
            The size and relative position of the window.
        """
        try:
            return WindowRect(**res["value"])
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse window rect from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception:
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

        Args:
            width: The width to scroll. Defaults to `0`.
            height: The height to scroll. Defaults to `0`.
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.

        Example:
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

        Args:
            x: The x-coordinate to scroll to. Defaults to `0`.
            y: The y-coordinate to scroll to. Defaults to `0`.
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.

        Example:
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
        """Scroll the viewport to the top of the page. (Does not affect the horizontal position of the viewport.).

        Args:
            value: The value for the sroll 'by' strategy.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the top of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the top of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_top(12, "count")
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
        scroll_deadline = unix_time() + 30
        previous = None
        stalled = 0
        steps = 0
        while (await self.viewport).top > 0:
            viewport = await self.viewport
            position = (viewport.x, viewport.y)
            stalled = stalled + 1 if position == previous else 0
            previous = position
            steps += 1
            if stalled >= 3 or steps >= 1000 or unix_time() >= scroll_deadline:
                raise errors.WebDriverTimeoutError(
                    "Scrolling stopped: no progress or safety budget exceeded"
                )
            await self.scroll_by(height=-pixel)
            await sleep(pause)

    async def scroll_to_bottom(
        self,
        value: int = 1,
        by: Literal["steps", "pixels"] = "steps",
        pause: int | float = 0.2,
    ) -> None:
        """Scroll the viewport to the bottom of the page. (Does not affect the horizontal position of the viewport.).

        Args:
            value: The value for the sroll 'by' strategy.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the bottom of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the bottom of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_bottom(100, "pixel")
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
        scroll_deadline = unix_time() + 30
        previous = None
        stalled = 0
        steps = 0
        while (await self.page_height) - (await self.viewport).bottom > 1:
            viewport = await self.viewport
            position = (viewport.x, viewport.y)
            stalled = stalled + 1 if position == previous else 0
            previous = position
            steps += 1
            if stalled >= 3 or steps >= 1000 or unix_time() >= scroll_deadline:
                raise errors.WebDriverTimeoutError(
                    "Scrolling stopped: no progress or safety budget exceeded"
                )
            await self.scroll_by(height=pixel)
            await sleep(pause)

    async def scroll_to_left(
        self,
        value: int = 1,
        by: Literal["steps", "pixels"] = "steps",
        pause: int | float = 0.2,
    ) -> None:
        """Scroll the viewport to the left of the page. (Does not affect the vertical position of the viewport.).

        Args:
            value: The value for the sroll 'by' strategy.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the left of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the left of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_left(12, "count")
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
        scroll_deadline = unix_time() + 30
        previous = None
        stalled = 0
        steps = 0
        while (await self.viewport).left > 0:
            viewport = await self.viewport
            position = (viewport.x, viewport.y)
            stalled = stalled + 1 if position == previous else 0
            previous = position
            steps += 1
            if stalled >= 3 or steps >= 1000 or unix_time() >= scroll_deadline:
                raise errors.WebDriverTimeoutError(
                    "Scrolling stopped: no progress or safety budget exceeded"
                )
            await self.scroll_by(width=-pixel)
            await sleep(pause)

    async def scroll_to_right(
        self,
        value: int = 1,
        by: Literal["steps", "pixels"] = "steps",
        pause: int | float = 0.2,
    ) -> None:
        """Scroll the viewport to the right of the page. (Does not affect the vertical position of the viewport.).

        Args:
            value: The value for the sroll 'by' strategy.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the right of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the right of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_right(100, "pixel")
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
        scroll_deadline = unix_time() + 30
        previous = None
        stalled = 0
        steps = 0
        while (await self.page_width) - (await self.viewport).right > 1:
            viewport = await self.viewport
            position = (viewport.x, viewport.y)
            stalled = stalled + 1 if position == previous else 0
            previous = position
            steps += 1
            if stalled >= 3 or steps >= 1000 or unix_time() >= scroll_deadline:
                raise errors.WebDriverTimeoutError(
                    "Scrolling stopped: no progress or safety budget exceeded"
                )
            await self.scroll_by(width=pixel)
            await sleep(pause)

    async def scroll_into_view(
        self,
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Scroll the viewport to the element by the given selector and strategy.

        Args:
            value: The selector for the element, or an  instance.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                If the given 'value' is an, this argument will be ignored.
            timeout: Total seconds to wait for the element to scroll into view. Defaults to `5`.

        Returns:
            True if the element is in the viewport, False if element not exists.

        Example:
            >>> in_viewport = await session.scroll_into_view("#element", by="css")
        """
        # Element already specified
        if isinstance(value, Element):
            return await value.scroll_into_view()

        strat = self._validate_selector_strategy(by)

        async def attempt() -> bool:
            """Locate and scroll the target once within the enclosing polling deadline.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            element = await self._find_element_no_wait(value, strat)
            return False if element is None else await element.scroll_into_view()

        return bool(await poll(attempt, timeout))

    def _validate_scroll_strategy(self, by: Any) -> str:
        """Validate the scroll 'by' strategy.

        Args:
            by: By used by this operation.

        Returns:
            The scroll 'by' strategy.
        """
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
        """Validate the scroll by 'value'.

        Args:
            value: The scroll by 'value' supplied for validation.

        Returns:
            The scroll by 'value'.
        """
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

        Args:
            timeout: Total seconds to wait for the alert to pop-up. Defaults to `5`.

        Returns:
            The alert of the active page window, or `None` if alert not exists.

        Example:
            >>> alert = await session.get_alert()
        """

        async def find_alert() -> Alert | None:
            """Return an alert handle when a dialog is currently present.

            Returns:
                An alert handle when a dialog is currently present.
            """
            try:
                await self.execute_command(Command.W3C_GET_ALERT_TEXT)
                return Alert(self)
            except errors.AlertNotFoundError:
                return None

        return await poll(find_alert, timeout)

    # Frame -------------------------------------------------------------------------------
    async def switch_frame(
        self,
        value: str | Element | int,
        by: Literal["css", "xpath", "index"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Switch focus to a specific frame in the active page window.

        Args:
            value: Accepts three kinds of input:
                -: The selector for the element contains the frame.
                -: An element instance contains the frame.
                -: The index (id) of the frame.
            by: The selector strategy, accepts `'css'`, `'xpath'` or `'index'`. Defaults to `'css'`.
                If the given 'value' is an, this argument will be ignored.
            timeout: Total seconds to wait for frame switching. Defaults to `5`.

        Returns:
            True if successfuly switched focus, False if frame not exists.

        Example:
            >>> # . switch by element selector
            >>> await session.switch_frame("figure.demoarea > iframe", by="css")  # True / False

            >>> # . switch by element instance
            >>> element = await session.find_element("figure.demoarea > iframe", by="css")
            >>> await session.switch_frame(element)  # True / False

            >>> # . switch by frame index
            >>> await session.switch_frame(1, by="index")  # True / False
        """
        if by == "index" and (type(value) is not int or value < 0):
            raise errors.InvalidArgumentError(
                "Frame index must be a nonnegative integer"
            )
        strat = (
            self._validate_selector_strategy(by)
            if by != "index" and not isinstance(value, Element)
            else None
        )

        async def attempt() -> bool:
            """Attempt one frame switch, treating a missing frame as not ready.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            try:
                if isinstance(value, Element):
                    frame_id = {ELEMENT_KEY: value.id}
                elif by == "index":
                    frame_id = value
                else:
                    element = await self._find_element_no_wait(value, strat)
                    if element is None:
                        return False
                    frame_id = {ELEMENT_KEY: element.id}
                await self.execute_command(
                    Command.SWITCH_TO_FRAME, body={"id": frame_id}
                )
                return True
            except (errors.FrameNotFoundError, errors.ElementNotFoundError):
                return False

        return bool(await poll(attempt, timeout))

    async def default_frame(self) -> bool:
        """Switch focus to the default frame (the `MAIN` document).

        Returns:
            True if successfuly switched focus, False if failed.

        Example:
            >>> await session.default_frame()  # True / False
        """
        try:
            await self.execute_command(Command.SWITCH_TO_FRAME, body={"id": None})
            return True
        except (errors.FrameNotFoundError, errors.ElementNotFoundError):
            return False

    async def parent_frame(self) -> bool:
        """Switch focus to the parent frame of the current frame.

        Returns:
            True if successfuly switched focus, False if failed.

        Example:
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
        """Return the element in focus. If no element is in focus, returns the  element.

        Returns:
            The element in focus. if no element is in focus, returns the  element.

        Example:
            >>> elements = await session.active_element
        """
        res = await self.execute_command(Command.W3C_GET_ACTIVE_ELEMENT)
        return self._create_element(res.get("value", None))

    async def element_exists(
        self,
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
    ) -> bool:
        """Check if an element exists. This method ignores the implicit wait timeout, and returns element existence immediately.

        Args:
            value: The selector for the element *OR* an  instance.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                If the given 'value' is an, this argument will be ignored.

        Returns:
            True if the element exists, False otherwise.

        Example:
            >>> await session.element_exists("#input_box")  # True / False
        """
        if isinstance(value, Element):
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
        """Check if multiple elements exist. This method ignores the implicit wait timeout, and returns elements existence immediately.

        Args:
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                For values that are  instances, this argument will be ignored.
            all_: Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
                - `True`: All elements must exist to return True.
                - `False`: Any one of the elements exists returns True.
            *values: The locators for multiple elements *OR*  instances.

        Returns:
            True if the elements exist, False otherwise.

        Example:
            >>> await session.elements_exist(
            ...     "#input_box", "#input_box2", by="css", all_=True
            ... )  # True / False
        """

        async def check_existance(value: str | Element) -> bool:
            """Perform one element-existence observation for the enclosing wait.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
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
        """Find the element by the given selector and strategy. The timeout for finding an element is determined by the implicit wait of the session.

        Args:
            value: The selector for the element.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.

        Returns:
            The located element, or `None` if not found.

        Example:
            >>> await session.find_element("#input_box", by="css")
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
        """Find elements by the given selector and strategy. The timeout for finding the elements is determined by the implicit wait of the session.

        Args:
            value: The selector for the elements.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.

        Returns:
            A list of located elements (empty if not found).

        Example:
            >>> await session.find_elements("#input_box", by="css")
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
            return self._create_elements(res["value"])
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
        """Find the first located element among multiple locators. The timeout for finding the first element is determined by the implicit wait of the session.

        Args:
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            *values: The locators for multiple elements.

        Returns:
            The first located element among all locators, or `None` if not found.

        Example:
            >>> await session.find_1st_element("#input_box", "#input_box2", by="css")
        """
        # Validate strategy
        strat = self._validate_selector_strategy(by)

        # Locate 1st element
        timeout = (await self._get_timeouts()).implicit
        return await first_match(
            values, lambda value: self._find_element_no_wait(value, strat), timeout
        )

    async def wait_until_element(
        self,
        condition: Literal[
            "gone", "exist", "unobscured", "in_viewport", "enabled", "selected"
        ],
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until an element satisfies the given condition.

        Args:
            condition: The condition to satisfy. Available options:
                - `'gone'`: Wait until an element disappears from the DOM tree.
                - `'exist'`: Wait until an element appears in the DOM tree.
                - `'unobscured'`: Wait for center-point hit testing to reach the element.
                - `'in_viewport'`: Wait for a nonempty rectangle intersecting the viewport.
                - `'enabled'`: Wait until an element is enabled.
                - `'selected'`: Wait until an element is selected.
            value: The selector for the element *OR* an  instance.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                If the given 'value' is an, this argument will be ignored.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the element satisfies the condition, False otherwise.

        Example:
            >>> await session.wait_until_element(
            ...     "unobscured", "#input_box", by="css", timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            """Check whether a matching element currently exists.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_unobscured(value: str | Element) -> bool:
            """Check the matched element using a center-point hit test.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.unobscured
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.unobscured

        async def is_in_viewport(value: str | Element) -> bool:
            """Check whether the matched element intersects the viewport.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.in_viewport
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.in_viewport

        async def is_enabled(value: str | Element) -> bool:
            """Check whether the matched element is enabled.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            """Check whether the matched element is selected.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
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
        elif condition == "unobscured":
            condition_checker = is_unobscured
        elif condition == "in_viewport":
            condition_checker = is_in_viewport
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        return bool(await poll(lambda: condition_checker(value), timeout))

    async def wait_until_elements(
        self,
        condition: Literal[
            "gone", "exist", "unobscured", "in_viewport", "enabled", "selected"
        ],
        *values: str | Element,
        by: Literal["css", "xpath"] = "css",
        all_: bool = True,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until multiple elements satisfy the given condition.

        Args:
            condition: The condition to satisfy. Available options:
                - `'gone'`: Wait until the elements disappear from the DOM tree.
                - `'exist'`: Wait until the elements appear in the DOM tree.
                - `'unobscured'`: Wait for center-point hit testing to reach the element.
                - `'in_viewport'`: Wait for nonempty rectangles intersecting the viewport.
                - `'enabled'`: Wait until the elements are enabled.
                - `'selected'`: Wait until the elements are selected.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                For values that are  instances, this argument will be ignored.
            all_: Determine how to satisfy the condition. Defaults to `True (all elements)`.
                - `True`: All elements must satisfy the condition to return True.
                - `False`: Any one of the elements satisfies the condition returns True.
            timeout: Total seconds to wait until timeout. Defaults to `5`.
            *values: The locators for multiple elements *OR*  instances.

        Returns:
            True if the elements satisfy the condition, False otherwise.

        Example:
            >>> await session.wait_until_elements(
            ...     "unobscured", "#input_box1", "#search_button",
            ...     by="css", all_=True, timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return not await value.exists
            else:
                return not await self._element_exists_no_wait(value, strat)

        async def is_exist(value: str | Element) -> bool:
            """Check whether a matching element currently exists.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        async def is_unobscured(value: str | Element) -> bool:
            """Check the matched element using a center-point hit test.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.unobscured
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.unobscured

        async def is_in_viewport(value: str | Element) -> bool:
            """Check whether the matched element intersects the viewport.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.in_viewport
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.in_viewport

        async def is_enabled(value: str | Element) -> bool:
            """Check whether the matched element is enabled.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.enabled
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.enabled

        async def is_selected(value: str | Element) -> bool:
            """Check whether the matched element is selected.

            Args:
                value: Value to inspect, normalize, or assign as described above.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.selected
            else:
                element = await self._find_element_no_wait(value, strat)
                return False if element is None else await element.selected

        async def check_condition(
            values: tuple[Any, ...],
            condition_checker: Callable[[str | Element], Awaitable[bool]],
        ) -> bool:
            """Evaluate the condition for each requested selector in the current poll.

            Args:
                values: Input values evaluated in order by this operation.
                condition_checker: Condition checker used by this operation.

            Returns:
                True when the requested condition holds for all candidates if all_ is True, or for any candidate otherwise; False if the requirement is not met.
            """
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
        elif condition == "unobscured":
            condition_checker = is_unobscured
        elif condition == "in_viewport":
            condition_checker = is_in_viewport
        elif condition == "enabled":
            condition_checker = is_enabled
        elif condition == "selected":
            condition_checker = is_selected
        else:
            self._raise_invalid_wait_condition(condition)

        return bool(
            await poll(lambda: check_condition(values, condition_checker), timeout)
        )

    async def _element_exists_no_wait(self, value: str, strat: str) -> bool:
        """Check if an element exists without implicit wait. Returns `False` immediately if element not exists.

        Args:
            value: Value to inspect, normalize, or assign as described above.
            strat: Strat used by this operation.

        Returns:
            True if an element exists without implicit wait; otherwise False.
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
        """Find element without implicit wait. Returns `None` immediately if element not exists.

        Args:
            value: Value to inspect, normalize, or assign as described above.
            strat: Strat used by this operation.

        Returns:
            The Element value produced by this operation. None indicates that no value is available.
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
        """Validate selector strategy.

        Args:
            by: By used by this operation.

        Returns:
            Selector strategy.
        """
        if by == "css":
            return "css selector"
        elif by == "xpath" or by == "css selector":
            return by
        else:
            raise errors.InvalidSelectorError(
                "<{}>\nInvalid selector strategy: {}. Available options: "
                "['css', 'xpath'].".format(self.__class__.__name__, repr(by))
            )

    def _create_element(self, element: object) -> Element | None:
        """Decode a nullable W3C element reference into a session-bound handle.

        Args:
            element: A decoded element-reference mapping, or None for no match.

        Returns:
            The element handle, or None when the remote value is null.

        Raises:
            errors.InvalidResponseError: The reference does not contain a
                nonempty string W3C element ID.
        """
        if element is None:
            return None
        if not isinstance(element, dict):
            raise errors.InvalidResponseError("Element reference must be a mapping")
        identifier = element.get(ELEMENT_KEY)
        if not isinstance(identifier, str) or not identifier:
            raise errors.InvalidResponseError("Invalid W3C element ID")
        return Element(identifier, self)

    def _create_elements(self, value: object) -> list[Element]:
        """Validate and construct a list of W3C element references.

        Args:
            value: The decoded value returned by a plural element lookup.

        Returns:
            Element handles in response order, or an empty list for no matches.

        Raises:
            errors.InvalidResponseError: The value is not a list of nonempty
                string element references. Null entries are not valid matches.
        """
        if not isinstance(value, list):
            raise errors.InvalidResponseError("Element-list response must be a list")
        elements = []
        for reference in value:
            if (
                not isinstance(reference, dict)
                or not isinstance(reference.get(ELEMENT_KEY), str)
                or not reference[ELEMENT_KEY]
            ):
                raise errors.InvalidResponseError("Invalid element-list reference")
            elements.append(Element(reference[ELEMENT_KEY], self))
        return elements

    # Shadow ------------------------------------------------------------------------------
    async def get_shadow(
        self,
        value: str,
        by: Literal["css", "xpath"] = "css",
        timeout: int | float | None = 5,
    ) -> Shadow | None:
        """Get the shadow root of an element by the given selector and strategy.

        Args:
            value: The selector for the element contains the shadow root.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
            timeout: Total seconds to wait for the shadow root. Defaults to `5`.

        Returns:
            The shadow root of the element, or `None` if not exists.

        Example:
            >>> shadow = await session.get_shadow("#element", by="css")
        """

        async def find_shadow() -> Shadow | None:
            """Resolve the shadow root of the currently matching host element.

            Returns:
                The host's shadow-root handle, or None while no matching host/root is present.
            """
            element = await self._find_element_no_wait(value, strat)
            return None if element is None else await element.shadow

        # Validate strategy
        strat = self._validate_selector_strategy(by)

        return await poll(find_shadow, timeout)

    # Script ------------------------------------------------------------------------------
    @property
    def scripts(self) -> list[JavaScript]:
        """Return all the cached JavaScripts. `(NOT an asynchronous attribute)`.

        Returns:
            All the cached javascripts. `(not an asynchronous attribute)`.

        Example:
            >>> scripts = session.scripts
        """
        return list(self._script_by_name.values())

    def get_script(self, script: str | JavaScript) -> JavaScript | None:
        """Get the JavaScript from cache `(NOT an asynchronous method)`.

        Args:
            script: Cache name or JavaScript instance, matched by its name.

        Returns:
            The cached JavaScript, or `None` if not exist.

        Raises:
            errors.InvalidArgumentError: If script is neither a string nor a JavaScript.

        Example:
            >>> js = session.get_script("myscript")
        """
        if not isinstance(script, (str, JavaScript)):
            raise errors.InvalidArgumentError(
                "Script must be a string or a cached JavaScript instance."
            )
        return self._script_by_name.get(script)

    def cache_script(self, name: str, script: str, *args: Any) -> JavaScript:
        """Cache a javascript for later execution `(NOT an asynchronous method)`.

        Args:
            name: The name of the javascript (cache accessor).
            script: The raw javascript code.
            *args: The arguments for the javascript.

        Returns:
            The cached javascript.

        Example:
            >>> # . without arguments
            >>> js = session.cache_script("get_title", "return document.title;")
            >>> print(js.name)
            get_title

            >>> # . with arguments
            >>> js = session.cache_script("scroll_y", "window.scrollBy(0, arguments[0]);", 100)
        """
        js = JavaScript(self._validate_script_name(name), script, *args)
        self._script_by_name[name] = js
        return js

    def remove_script(self, script: str | JavaScript) -> bool:
        """Remove a previously cached JavaScript `(NOT an asynchronous method)`.

        Args:
            script: Accepts both the name of the javascript, or the  instance.

        Returns:
            True if the script is removed from cache, False if script not exists.

        Example:
            >>> session.remove_script("myscript")  # True / False
        """
        try:
            self._script_by_name.pop(script)
            return True
        except KeyError:
            return False

    def rename_script(self, script: str | JavaScript, new_name: str) -> JavaScript:
        """Rename a previously cached JavaScript `(NOT an asynchronous method)`.

        Args:
            script: Accepts both the name of the javascript, or the  instance.
            new_name: The new name for the javascript.

        Returns:
            The renamed javascript.

        Example:
            >>> # . cache a script
            >>> js = session.cache_script("script1", "return document.title;")
            >>> # <JavaScript (name='script1', script='return document.titile;', args=[])>

            >>> # . rename the script
            >>> js = session.rename_script("script1", "script2")
        """
        # Validate name
        name = self._validate_script_name(new_name)

        # Pop cached script
        try:
            js = self._script_by_name.pop(script)
        except KeyError as err:
            raise errors.JavaScriptNotFoundError(
                "<{}>\nCannot rename script {}. JavaScript not found.".format(
                    self.__class__.__name__, repr(script)
                )
            ) from err

        # Cache with new name
        return self.cache_script(name, js.script, *js.args)

    async def execute_script(self, script: str | JavaScript, *args: Any) -> Any:
        """Execute javascript synchronously.

        Args:
            script: Accepts three kinds of input:
                -  The raw javascript code to execute.
                -  The name of a cached JavaScript.
                -  A cached JavaScript instance.
            *args: The arguments for the javascript.
                - The '*args' will be passed along with the script as an array, and
                accessible in order by the script as `arguments[0]`, `arguments[1]`,
                etc.
                - If executing a cached JavaScript, the '*args' in this method is always
                prioritized over the cached arguments. Only when the '*args' is empty,
                the cached arguments will be used.

        Returns:
            The response from the script execution.

        Raises:
            errors.JavaScriptNotFoundError: If the supplied JavaScript has no cached name.
            errors.InvalidArgumentError: If script is neither a string nor a JavaScript.

        Example:
            >>> # . execute raw javascript code
            >>> script = "return document.title;"
            >>> title = await session.execute_script(script)

            >>> # . execute cached JavaScript by name
            >>> session.cache_script("get_title", "return document.title;")
            >>> title = await session.execute_script("get_title")

            >>> # . execute cached JavaScript by instance
            >>> js = session.get_script("get_title")
            >>> if js is None:
            ...     raise LookupError("The title script has not been cached")
            >>> title = await session.execute_script(js)
        """
        # Execute cached script
        js = self.get_script(script)
        if js is not None:
            return await self._execute_script(js.script, *args or js.args)
        # Execute raw script
        elif isinstance(script, str):
            return await self._execute_script(script, *args)
        raise errors.JavaScriptNotFoundError(
            "JavaScript instance is not cached in this session. Cache it before execution."
        )

    async def execute_async_script(self, script: str | JavaScript, *args: Any) -> Any:
        r"""Execute JavaScript asynchronously.

        Args:
            script: Accepts three kinds of input:
                -  The raw async javascript code to execute.
                -  The name of a cached JavaScript.
                -  A cached JavaScript instance.
            *args: The arguments for the javascript.
                - The '*args' will be passed along with the script as an array, and
                accessible in order by the script as `arguments[0]`, `arguments[1]`,
                etc.
                - If executing a cached JavaScript, the '*args' in this method is always
                prioritized over the cached arguments. Only when the '*args' is empty,
                the cached arguments will be used.

        Returns:
            The response from the async script execution.

        Raises:
            errors.JavaScriptNotFoundError: If the supplied JavaScript has no cached name.
            errors.InvalidArgumentError: If script is neither a string nor a JavaScript.

        Example:
            >>> # . execute raw async javascript code
            >>> script = "var callback = arguments[arguments.length - 1]; " \
            ...          "window.setTimeout(function(){ callback('timeout') }, 3000);"
            >>> await session.execute_async_script(script)

            >>> # . execute cached JavaScript by name
            >>> script = "var callback = arguments[arguments.length - 1]; " \
            ...          "window.setTimeout(function(){ callback('timeout') }, 3000);"
            >>> session.cache_script("async_js1", script)
            >>> await session.execute_async_script("async_js1")

            >>> # . execute cached JavaScript by instance
            >>> script = "var callback = arguments[arguments.length - 1]; " \
            ...          "window.setTimeout(function(){ callback('timeout') }, 3000);"
            >>> js = session.get_script("async_js1")
            >>> if js is None:
            ...     raise LookupError("The asynchronous script has not been cached")
            >>> await session.execute_async_script(js)
        """
        # Execute cached script
        js = self.get_script(script)
        if js is not None:
            return await self._execute_async_script(js.script, *args or js.args)
        # Execute raw script
        elif isinstance(script, str):
            return await self._execute_async_script(script, *args)
        raise errors.JavaScriptNotFoundError(
            "JavaScript instance is not cached in this session. Cache it before execution."
        )

    async def _execute_script(self, script: str, *args: Any) -> Any:
        """Executes raw javascript synchronously.

        Args:
            script: The raw javascript code to execute.
            *args: The arguments for the javascript.
                The '*args' will be passed along with the script as an array, and
                accessible in order by the script as `arguments[0]`, `arguments[1]`,
                etc.

        Returns:
            The response from the script execution.

        Example:
            >>> # . without argument
            >>> script = "return document.title;"
            >>> title = await session.execute_script(script)

            >>> # . with arguments
            >>> script = "window.scrollBy(arguments[0], arguments[1]);"
            >>> await session.execute_script(script, 100, 100)
        """
        res = await self.execute_command(
            Command.W3C_EXECUTE_SCRIPT,
            body={"script": script, "args": warp_tuple(args)},
        )
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse script value from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def _execute_async_script(self, script: str, *args: Any) -> Any:
        r"""Executes raw javascript asynchronously.

        Args:
            script: The raw async javascript code to execute.
            *args: Arguments for the async javascript.
                The '*args' will be passed along with the script as an array, and
                accessible in order by the script as `arguments[0]`, `arguments[1]`,
                etc.

        Returns:
            The response from the async script execution.

        Example:
            >>> script = "var callback = arguments[arguments.length - 1]; " \
            ...          "window.setTimeout(function(){ callback('timeout') }, 3000);"
            >>> await session.execute_async_script(script)
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
                "<{}>\nFailed to parse script value from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    def _validate_script_name(self, name: Any) -> str:
        """Validate script name.

        Args:
            name: Name identifying the requested item.

        Returns:
            Script name.
        """
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
        """Start an actions chain to peform (automate) low level interactions such as mouse movements, key presses, and wheel scrolls.

        Args:
            pointer: The pointer type to use. Defaults to `'mouse'`.
                Available options are: `'mouse'`, `'pen'`, `'touch'`.
            duration: The duration in seconds to perform a pointer move or wheel scroll action. Defaults to `0.25`.

        Returns:
            The actions chain.

        Example:
            >>> from aselenium import KeyboardKeys
            >>> input_box = await session.find_element("#input_box")
            >>> (
            ...     await session.actions("mouse")
            ...     .move_to(input_box)
            ...     .click()
            ...     .send_keys("Hello World!")
            ...     .send_keys(KeyboardKeys.ENTER)
            ...     .perform()
            ... )
        """
        return Actions(self, pointer, duration)

    # Utils -------------------------------------------------------------------------------
    async def pause(self, duration: int | float | None) -> None:
        """Pause the for a given duration.

        Args:
            duration: The duration to pause in seconds.
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
        """Validate if pause value `> 0`.

        Args:
            value: If pause value `> 0` supplied for validation.

        Returns:
            If pause value `> 0`.
        """
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
        """Validate if timeout value `> 0`.

        Args:
            value: If timeout value `> 0` supplied for validation.

        Returns:
            If timeout value `> 0`.
        """
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
        """Validate if wait until 'value' is a non-empty string.

        Args:
            value: If wait until 'value' is a non-empty string supplied for validation.

        Returns:
            If wait until 'value' is a non-empty string.
        """
        if not isinstance(value, str) or not value:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid wait until value: {} {}. "
                "Must an non-empty string.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        return value

    def _raise_invalid_wait_condition(self, condition: Any) -> NoReturn:
        """Raise invalid wait until 'condition' error.

        Args:
            condition: Asynchronous no-argument predicate whose truthy result completes the wait.

        Raises:
            errors.InvalidArgumentError: Always raised with the supplied diagnostic context.
        """
        raise errors.InvalidArgumentError(
            "<{}>\nInvalid wait until condition: {} {}.".format(
                self.__class__.__name__, repr(condition), type(condition)
            )
        )

    def _is_element(self, element: Any) -> bool:
        """Check if the given object is an  instance.

        Args:
            element: Element used by this operation.

        Returns:
            True if the given object is an  instance; otherwise False.
        """
        return isinstance(element, Element)

    def _decode_base64(self, data: str, encoding: str) -> bytes:
        """Decode base64 string to.

        Args:
            data: Data used by this operation.
            encoding: Encoding used by this operation.

        Returns:
            Decode base64 string to.
        """
        return b64decode(data.encode(encoding), validate=True)

    def _encode_base64(self, data: bytes, encoding: str) -> str:
        """Encode bytes to base64.

        Args:
            data: Data used by this operation.
            encoding: Encoding used by this operation.

        Returns:
            The encode base64 string.
        """
        return b64encode(data).decode(encoding)

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (id='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            self._service.url,
        )

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __del__(self) -> None:
        """Release references during finalization; explicit cleanup remains preferred."""
        self._collect_garbage()

    def _collect_garbage(self) -> None:
        """Collect garbage."""
        # Already closed
        if getattr(self, "_Session__closed", True):
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
    """Represent a session of the chromium based browser."""

    def __init__(
        self,
        options: ChromiumBaseOptions,
        service: ChromiumBaseService,
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            options: Options used by this operation.
            service: Service used by this operation.
        """
        super().__init__(options, service)
        # Devtools cmd
        self._cdp_cmd_by_name: dict[str, DevToolsCMD] = {}

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> ChromiumBaseOptions:
        """Return the browser options.

        Returns:
            The browser options owned by this facade or session.
        """
        return self._options

    @property
    def browser_version(self) -> str | None:
        """Return the browser version string recorded for this configuration or session.

        Returns:
            The version string, or None when no browser version has been recorded.
            This property does not probe the browser or return a Version object.
        """
        return super().browser_version

    @property
    def service(self) -> ChromiumBaseService:
        """Return the webdriver service.

        Returns:
            The driver service owned by the session.
        """
        return self._service

    @property
    def driver_version(self) -> ChromiumVersion:
        """Return the webdriver binary version of the session.

        Returns:
            The webdriver binary version of the session.
        """
        return super().driver_version

    # Chromium - Permission ---------------------------------------------------------------
    @property
    async def permissions(self) -> list[Permission]:
        """Return all the permissions of the active page window.

        Returns:
            All the permissions of the active page window.

        Example:
            >>> permissions = await session.permissions
        """
        return [
            permission
            for name in sorted(Constraint.PERMISSION_NAMES)
            if (permission := await self.get_permission(name))
        ]

    async def get_permission(self, name: str | Permission) -> Permission | None:
        """Get a specific permission from the active page window.

        Args:
            name: The name of the permission or a  instance.

        Returns:
            The specified permission, or `None` if not found.

        Example:
            >>> permission = await session.get_permission("geolocation")
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
                "<{}>\nFailed to parse permission from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid permission response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def set_permission(
        self,
        name: str,
        state: Literal["granted", "denied", "prompt"],
    ) -> Permission:
        """Set a specific permission's state of the active page window.

        Args:
            name: The name of the permission.
            state: The state of the permission, accepts: `'granted'`, `'denied'`, `'prompt'`.

        Returns:
            The permission after update.

        Example:
            >>> perm = await session.set_permission("geolocation", "granted")
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
        """Validate the name of a permission.

        Args:
            name: Name identifying the requested item.

        Returns:
            The name of a permission.
        """
        if isinstance(name, Permission):
            return name.name
        if name not in Constraint.PERMISSION_NAMES:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid permission name: {}. Available options: {}".format(
                    self.__class__.__name__,
                    repr(name),
                    sorted(Constraint.PERMISSION_NAMES),
                )
            )
        return name

    # Chromium - Network ------------------------------------------------------------------
    @property
    async def network(self) -> Network:
        """Return the network conditions of the current session.

        Conditions explain:

        - offline: Whether to simulate an offline network condition.
        - latency: The minimum latency overhead.
        - upload_throughput: The maximum upload throughput in bytes per second.
        - download_throughput: The maximum download throughput in bytes per second.

        Default conditions:
        <Network (offline=False, latency=0, upload_throughput=-1, download_throughput=-1)>

        Returns:
            The network conditions of the current session.

        Example:
            >>> network = await session.network
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
                "<{}>\nFailed to parse network conditions from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err
        except Exception as err:
            raise errors.InvalidResponseError(
                "<{}>\nInvalid network conditions response: {}".format(
                    self.__class__.__name__, res["value"]
                )
            ) from err

    async def set_network(
        self,
        offline: bool | None = None,
        latency: int | None = None,
        upload_throughput: int | None = None,
        download_throughput: int | None = None,
    ) -> Network:
        """Set the network conditions of the current session.

        Reading, updating, and confirming the conditions share command ownership,
        preserving unrelated fields when separate tasks make partial updates.

        Args:
            offline: Whether to simulate an offline network
                condition. If `None (default)`, keep the current offline condition.
            latency: The minimum latency overhead in milliseconds.
                If `None (default)`, keep the current latency condition.
            upload_throughput: The maximum upload throughput
                in bytes per second. If `None (default)`, keep the current condition.
            download_throughput: The maximum download throughput
                in bytes per second. If `None (default)`, keep the current condition.

        Returns:
            The network conditions after update.

        Example:
            >>> network = await session.set_network(
            ...     offline=False, latency=10,
            ...     download_throughput=10 * 1024, upload_throughput=10 * 1024,
            ... )
        """
        async with self.transaction():
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
                Command.SET_NETWORK_CONDITIONS,
                body={"network_conditions": network.dict},
            )
            return await self.network

    async def reset_network(self) -> Network:
        """Reset the network conditions of the current session to the default configuration, and returns the reset.

        Default conditions:
        <Network (offline=False, latency=0, upload_throughput=-1, download_throughput=-1)>

        Returns:
            The Network value produced by this operation.

        Example:
            >>> network = await session.reset_network()
        """
        async with self.transaction():
            await self.execute_command(
                Command.SET_NETWORK_CONDITIONS,
                body={"network_conditions": Network().dict},
            )
            return await self.network

    # Chromium - Casting ------------------------------------------------------------------
    @property
    async def cast_sinks(self) -> list[dict[str, Any]]:
        """Return the available sinks for a Cast session.

        Returns:
            The available sinks for a cast session.
        """
        res = await self.execute_command(Command.GET_SINKS, keys=self._vendor)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse cast sinks from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    @property
    async def cast_issue(self) -> str:
        """Return the issue of the Cast session.

        Returns:
            The issue of the cast session.
        """
        res = await self.execute_command(Command.GET_ISSUE_MESSAGE, keys=self._vendor)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                f"\nFailed to parse cast issue from response: {res}"
            ) from err

    async def set_cast_sink(self, sink_name: str) -> None:
        """Set a specific sink as the Cast session receiver target.

        Args:
            sink_name: Name of the sink to use as the receiver target.
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

        Args:
            sink_name: Name of the sink to use as the casting receiver target.
            mirror: The mirroring type, accepts `'desktop'` or `'tab'`. Defaults to `'tab'`.
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
                    "<{}>\nFailed to start casting. Cast sink {} not found.".format(
                        self.__class__.__name__, repr(sink_name)
                    )
                ) from err
            raise err

    async def stop_casting(self, sink_name: str) -> None:
        """Stop an active Cast session.

        Args:
            sink_name: Name of the sink used by the Cast session.
        """
        try:
            await self.execute_command(
                Command.STOP_CASTING, body={"sinkName": sink_name}, keys=self._vendor
            )
        except errors.UnknownError as err:
            if ErrorCode.SINK_NOT_FOUND in str(err):
                raise errors.CastSinkNotFoundError(
                    "<{}>\nFailed to stop casting. Cast sink {} not found.".format(
                        self.__class__.__name__, repr(sink_name)
                    )
                ) from err
            raise err

    # Chromium - DevTools Command ---------------------------------------------------------
    @property
    def cdp_cmds(self) -> list[DevToolsCMD]:
        """Return all the cached Chrome Devtools Protocol commands. `(NOT an asynchronous attribute)`.

        Returns:
            All the cached chrome devtools protocol commands. `(not an asynchronous attribute)`.

        Example:
            >>> cmds = session.cdp_cmds
        """
        return list(self._cdp_cmd_by_name.values())

    def get_cdp_cmd(self, cmd: str | DevToolsCMD) -> DevToolsCMD | None:
        """Get the Chrome Devtools Protocol command from cache `(NOT an asynchronous method)`.

        Args:
            cmd: Cache name or DevToolsCMD instance, matched by its name.

        Returns:
            The cached DevToolsCMD, or `None` if not exist.

        Raises:
            errors.InvalidArgumentError: If cmd is neither a string nor a DevToolsCMD.

        Example:
            >>> cmd = session.get_cdp_cmd("mycmd")
        """
        if not isinstance(cmd, (str, DevToolsCMD)):
            raise errors.InvalidArgumentError(
                "CDP command must be a string or a cached DevToolsCMD instance."
            )
        return self._cdp_cmd_by_name.get(cmd)

    def cache_cdp_cmd(self, name: str, cmd: str, **kwargs: Any) -> DevToolsCMD:
        """Cache a Chrome Devtools Protocol command for later execution `(NOT an asynchronous method)`.

        Args:
            name: The name of the command (cache accessor).
            cmd: The command line.
            **kwargs: The keyword arguments for the command.

        Returns:
            The cached CDP command.

        Example:
            >>> # . without arguments
            >>> cmd = session.cache_cdp_cmd("get_version", "Browser.getVersion")
            >>> # <DevToolsCMD (name='get_version', cmd='Browser.getVersion', kwargs={})>

            >>> # . with arguments
            >>> cmd = session.cache_cdp_cmd(
            ...     "get_url",
            ...     "Runtime.evaluate",
            ...     expression="window.location.href",
            ... )
        """
        cmd = DevToolsCMD(self._validate_cdp_cmd_name(name), cmd, **kwargs)
        self._cdp_cmd_by_name[name] = cmd
        return cmd

    def remove_cdp_cmd(self, cmd: str | DevToolsCMD) -> bool:
        """Remove a previously cached Chrome Devtools Protocol command `(NOT an asynchronous method)`.

        Args:
            cmd: Accepts both the name of the DevToolsCMD, or the  instance.

        Returns:
            True if the command is removed from cache, False if command not exist.

        Example:
            >>> session.remove_cdp_cmd("mycmd")  # True / False
        """
        try:
            self._cdp_cmd_by_name.pop(cmd)
            return True
        except KeyError:
            return False

    def rename_cdp_cmd(self, cmd: str | DevToolsCMD, new_name: str) -> DevToolsCMD:
        """Rename a previously cached Chrome Devtools Protocol command `(NOT an asynchronous method)`.

        Args:
            cmd: Accepts both the name of the DevToolsCMD, or the  instance.
            new_name: The new name for the command.

        Returns:
            The renamed command.

        Example:
            >>> # . cache a command
            >>> cmd = session.cache_cdp_cmd("cmd1", "Browser.getVersion")
            >>> # <DevToolsCMD (name='cmd1', cmd='Browser.getVersion', kwargs={})>

            >>> # . rename the command
            >>> cmd = session.rename_cdp_cmd("cmd1", "cmd2")
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
        """Execute Chrome Devtools Protocol command and return the execution result. The command and params should follow chrome devtools protocol domains/commands. For more detail, please refer to: https://chromedevtools.github.io/devtools-protocol/.

        Args:
            cmd: Accepts three kinds of input:
                -  The command line for chrome devtools protocol.
                -  The name of a cached Chrome Devtools Protocol command.
                -  A cached Chrome Devtools Protocol command instance.
            **kwargs: Additional keyword arguments for the command.
                - If executing a cached Chrome Devtools Protocol command, the '*kwargs'
                in this method is always prioritized over the cached arguments. Only
                when the '*kwargs' is empty, the cached arguments will be used.

        Returns:
            The response from the command execution.

        Raises:
            errors.DevToolsCMDNotFoundError: If the supplied DevToolsCMD has no cached name.
            errors.InvalidArgumentError: If cmd is neither a string nor a DevToolsCMD.

        Example:
            >>> # . execute command line
            >>> cmd = "Browser.getVersion"
            >>> await session.execute_cdp_cmd(cmd)

            >>> # . execute cached command by name
            >>> session.cache_cdp_cmd("get_version", "Browser.getVersion")
            >>> await session.execute_cdp_cmd("get_version")

            >>> # . execute cached command by instance
            >>> cmd = session.cache_cdp_cmd("get_version", "Browser.getVersion")
            >>> await session.execute_cdp_cmd(cmd)
        """
        # Execute cached command
        command = self.get_cdp_cmd(cmd)
        if command is not None:
            return await self._execute_cdp_cmd(command.cmd, **kwargs or command.kwargs)
        # Execute command line
        elif isinstance(cmd, str):
            return await self._execute_cdp_cmd(cmd, **kwargs)
        raise errors.DevToolsCMDNotFoundError(
            "DevToolsCMD instance is not cached in this session. Cache it before execution."
        )

    async def _execute_cdp_cmd(self, cmd: str, **kwargs: Any) -> dict[str, Any]:
        """Execute Chrome Devtools Protocol command and return the execution result.The command and params should follow chrome devtools protocol domains/commands. For more detail, please refer to: https://chromedevtools.github.io/devtools-protocol/.

        Args:
            cmd: The command line for chrome devtools protocol.
            **kwargs: Additional keyword arguments for the command.

        Returns:
            The response from the command execution.

        Example:
            >>> await session.execute_cdp_cmd(
            ...     "Runtime.evaluate", expression="window.location.href",
            ... )
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

    def _validate_cdp_cmd_name(self, name: str) -> str:
        """Validate CDP command name.

        Args:
            name: Nonempty name that must not already identify a cached command.

        Returns:
            The unchanged name after validation.
        """
        if not isinstance(name, str) or not name:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid Chrome Devtools Protocol command name: {} {}.".format(
                    self.__class__.__name__, repr(name), type(name)
                )
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
        """Return the available log types of the session.

        Returns:
            The available log types of the session.

        Example:
            >>> log_types = await session.log_types
        """
        # Request available log types
        res = await self.execute_command(Command.GET_AVAILABLE_LOG_TYPES)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse log types from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    async def get_logs(self, log_type: str) -> list[dict[str, Any]]:
        """Get a specific type of logs of the session.

        Notice
        Once the logs are retrieved, they will be cleared (removed) from the session.

        Args:
            log_type: The log type. e.g. `'browser'`, `'driver'`, `'client'`, `'server'`, etc.

        Returns:
            The logs for the specified log type.

        Example:
            >>> logs =  await session.get_logs("browser")
        """
        try:
            res = await self.execute_command(Command.GET_LOG, body={"type": log_type})
        except errors.InvalidArgumentError:
            return []
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to parse logs from response: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    # Special methods ---------------------------------------------------------------------
    def _collect_garbage(self) -> None:
        """Collect garbage."""
        super()._collect_garbage()
        # Devtools cmd
        self._cdp_cmd_by_name = None
