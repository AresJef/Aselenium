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

"""Browser-session primitives and W3C WebDriver command orchestration."""

from __future__ import annotations

import asyncio
from asyncio import sleep
from base64 import b64decode
from collections.abc import Awaitable, Callable
from copy import deepcopy
from math import ceil, isfinite
from time import monotonic as unix_time
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NoReturn,
    TypeGuard,
    TypeVar,
)
from urllib.parse import quote
from uuid import uuid4

from aselenium import errors, javascript
from aselenium._async import finish_owned, run_blocking
from aselenium._output import save_bytes
from aselenium._paths import PathInput, save_file_path
from aselenium._response import response_value, typed_value
from aselenium._wait import first_match, poll, validate_delay
from aselenium.actions import Actions
from aselenium.alert import Alert
from aselenium.command import Command
from aselenium.connection import Connection
from aselenium.element import ELEMENT_KEY, Element
from aselenium.errors import ErrorCode
from aselenium.logs import logger
from aselenium.options import BaseOptions, ChromiumBaseOptions, Timeouts
from aselenium.settings import Constraint, DefaultNetworkConditions
from aselenium.utils import CustomDict, Rectangle
from aselenium.valuewrap import warp_tuple

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

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
        """Create a cookie value from WebDriver cookie fields.

        Args:
            **data: The cookie data.

        Raises:
            errors.InvalidArgumentError: The mapping lacks a canonical or
                vendor-capitalized name, or that name is not nonempty text.
        """
        super().__init__(**data)
        # Validate name
        self.__nkey: str
        if "name" in self._dict:
            self.__nkey = "name"
        elif "Name" in self._dict:
            self.__nkey = "Name"
        else:
            raise errors.InvalidArgumentError(
                "<{}>\nLack of required attribute 'name': {}.".format(
                    self.__class__.__name__, repr(self._dict)
                )
            )
        self.name = self._dict[self.__nkey]

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
        """Create a named, reusable Chrome DevTools Protocol command.

        Args:
            name: The name of the command.
            cmd: Chrome DevTools Protocol method name.
            **kwargs: Default parameters sent with the command.
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
        """Hash the immutable local cache name of this command.

        Returns:
            A hash consistent with command equality.
        """
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        """Compare the complete reusable command definition.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` when another command has the same cache name, CDP method,
            and default parameters; otherwise ``False``.
        """
        return (
            isinstance(__o, DevToolsCMD)
            and self._name == __o._name
            and self._cmd == __o._cmd
            and self._kwargs == __o._kwargs
        )

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
        """Create a named JavaScript snippet with default arguments.

        Args:
            name: The name of the javascript.
            script: JavaScript source code.
            *args: Default positional arguments passed when executing the script.
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
        """Hash the immutable local cache name of this script.

        Returns:
            A hash consistent with script equality.
        """
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        """Compare the complete reusable script definition.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` when another script has the same cache name, source, and
            default arguments; otherwise ``False``.
        """
        return (
            isinstance(__o, JavaScript)
            and self._name == __o._name
            and self._script == __o._script
            and self._args == __o._args
        )

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
    """Store Chromium network-emulation conditions as a reusable value."""

    def __init__(
        self,
        offline: bool | None = None,
        latency: int | None = None,
        upload_throughput: int | None = None,
        download_throughput: int | None = None,
    ) -> None:
        """Create a network-emulation configuration.

        Args:
            offline: Whether to simulate an offline network. ``None`` keeps the
                default of ``False``.
            latency: Nonnegative minimum latency in milliseconds. ``None`` keeps
                the default of zero.
            upload_throughput: Maximum upload throughput in bytes per second;
                ``-1`` disables the limit and ``None`` keeps that default.
            download_throughput: Maximum download throughput in bytes per second;
                ``-1`` disables the limit and ``None`` keeps that default.
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
    def dict(self) -> dict[str, bool | int]:
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
        """Return whether the emulated network is offline.

        Returns:
            ``True`` when offline mode is enabled; otherwise ``False``.
        """
        return self._offline

    @offline.setter
    def offline(self, value: bool | None) -> None:
        """Set or preserve the emulated offline state.

        Args:
            value: New offline state, or ``None`` to keep the current state.
        """
        if value is None:
            return
        elif not isinstance(value, bool):
            raise errors.InvalidArgumentError("Network offline state must be a bool")
        else:
            self._offline = value

    # Latency -----------------------------------------------------------------------------
    @property
    def latency(self) -> int:
        """Return the emulated minimum network latency.

        Returns:
            Latency in milliseconds.
        """
        return self._latency

    @latency.setter
    def latency(self, value: int | None) -> None:
        """Set or preserve the emulated network latency.

        Args:
            value: Nonnegative milliseconds, or ``None`` to keep the current value.
        """
        if value is None:
            return
        else:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid latency: {} {}.".format(
                        self.__class__.__name__, repr(value), type(value)
                    )
                )
            self._latency = value

    # Upload throughput -------------------------------------------------------------------
    @property
    def upload_throughput(self) -> int:
        """Return the emulated upload-throughput limit.

        Returns:
            Bytes per second, or ``-1`` when the limit is disabled.
        """
        return self._upload_throughput

    @upload_throughput.setter
    def upload_throughput(self, value: int | None) -> None:
        """Set or preserve the emulated upload-throughput limit.

        Args:
            value: Bytes per second at or above ``-1``, or ``None`` to keep the
                current value.
        """
        if value is None:
            return
        else:
            if isinstance(value, bool) or not isinstance(value, int) or value < -1:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid upload throughput: {} {}.".format(
                        self.__class__.__name__, repr(value), type(value)
                    )
                )
            self._upload_throughput = value

    # Download throughput -----------------------------------------------------------------
    @property
    def download_throughput(self) -> int:
        """Return the emulated download-throughput limit.

        Returns:
            Bytes per second, or ``-1`` when the limit is disabled.
        """
        return self._download_throughput

    @download_throughput.setter
    def download_throughput(self, value: int | None) -> None:
        """Set or preserve the emulated download-throughput limit.

        Args:
            value: Bytes per second at or above ``-1``, or ``None`` to keep the
                current value.
        """
        if value is None:
            return
        else:
            if isinstance(value, bool) or not isinstance(value, int) or value < -1:
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
        """Return a stable identity hash for this mutable configuration.

        Returns:
            The network object's identity.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether another reference is this exact session owner.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` only for this same object.
        """
        return self is __o

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
        """Create a validated browser-permission value.

        Args:
            name: WebDriver permission descriptor name.
            state: Requested permission state.
        """
        self.name = name
        self.state = state

    # Dict  --------------------------------------------------------------------------------
    @property
    def dict(self) -> dict[str, str]:
        """Return the permission as a dictionary.

        Returns:
            The permission as a dictionary.

        Example:
            >>> permission = Permission("geolocation", "prompt")
            >>> permission.dict
            {'name': 'geolocation', 'state': 'prompt'}
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
    def state(self) -> Literal["granted", "denied", "prompt"]:
        """Return the permission state.

        Expected values: `"granted"`, `"denied"`, `"prompt"`

        Returns:
            The permission state.
        """
        return self._state

    @state.setter
    def state(self, value: Literal["granted", "denied", "prompt"]) -> None:
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
        self._state: Literal["granted", "denied", "prompt"] = value

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<Permission (name='%s', state='%s')>" % (self._name, self._state)

    def __hash__(self) -> int:
        """Return a stable identity hash for this mutable permission.

        Returns:
            The permission object's identity.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether another reference is this exact permission object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` only for this same object.
        """
        return self is __o

    def __bool__(self) -> bool:
        """Return the truth value of this instance.

        Returns:
            True; instances of this value type are always truthy.
        """
        return True

    def copy(self) -> Permission:
        """Copy the permission object.

        Returns:
            An independent copy of this value object.
        """
        return Permission(name=self._name, state=self._state)


class Viewport(Rectangle):
    """Represent the size and relative position of a window viewport."""

    def __init__(self, width: int, height: int, x: int, y: int) -> None:
        """Create a viewport rectangle from CSS-pixel coordinates.

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
        """Create a named local reference to a remote browser window.

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
        self._name: str
        if isinstance(name, str) and name:
            self._name = name
        elif name is None:
            self._name = uuid4().hex
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
        """Hash the immutable local name of this window handle.

        Returns:
            A hash consistent with window equality.
        """
        return hash(self._name)

    def __eq__(self, __o: object) -> bool:
        """Compare a remote handle and its session-local lookup name.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` when another window has the same handle and local name;
            otherwise ``False``.
        """
        return (
            isinstance(__o, Window)
            and self._name == __o._name
            and self._handle == __o._handle
        )

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
        """Create a browser-window rectangle from CSS-pixel coordinates.

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
        """Create a not-yet-started browser session.

        Args:
            options: The browser options.
            service: The WebDriver service.
        """
        # Options
        self._options: BaseOptions | None = options
        self._browser_location: Path | None = options.browser_location
        self._browser_version: str | None = self._options.browser_version
        # Service
        self._service: BaseService | None = service
        # Connection
        self._conn: Connection | None = None
        # Vendor prefix
        vendor_prefix = options.VENDOR_PREFIX
        if vendor_prefix is None:
            raise errors.InvalidArgumentError(
                "Session options must define a WebDriver vendor prefix"
            )
        self._vendor: dict[str, str] = {"vendorPrefix": vendor_prefix}
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
        if self._options is None:
            raise errors.InvalidSessionError("Session options have been released")
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
    def browser_location(self) -> Path | None:
        """Return the browser binary location of the session.

        Returns:
            The browser executable path, or `None` when it was not configured.
        """
        return self._browser_location

    @property
    def service(self) -> BaseService:
        """Return the WebDriver service.

        Returns:
            The driver service owned by the session.
        """
        if self._service is None:
            raise errors.InvalidSessionError("Session service has been released")
        return self._service

    @property
    def driver_version(self) -> Version:
        """Return the WebDriver binary version of the session.

        Returns:
            The WebDriver binary version of the session.
        """
        return self.service.driver_version

    @property
    def driver_location(self) -> Path:
        """Return the WebDriver binary location of the session.

        Returns:
            The validated WebDriver executable path retained by the service.
        """
        return self.service.driver_location

    @property
    def connection(self) -> Connection | None:
        """Return the session connection.

        Returns:
            The session connection, or `None` before startup or after cleanup.
        """
        return self._conn

    @property
    def id(self) -> str | None:
        """Return the current remote session ID.

        Returns:
            The remote session ID, or `None` when no session is active.
        """
        return self._id

    @property
    def base_url(self) -> str | None:
        """Return the current remote session command URL.

        Returns:
            The command URL for the active remote session, or `None` otherwise.
        """
        return self._base_url

    def _active_transport(self) -> tuple[Connection, str]:
        """Return the connection and URL for an active remote session.

        Returns:
            The initialized connection and its session-specific command URL.

        Raises:
            errors.InvalidSessionError: If the session has not started or has closed.
        """
        connection = self._conn
        base_url = self._base_url
        if connection is None or base_url is None:
            raise errors.InvalidSessionError("Browser session is not active")
        return connection, base_url

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
        connection, base_url = self._active_transport()
        return await connection.execute(
            base_url,
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

        Admission uses the enclosing command/wait deadline when present, or the
        configured session timeout otherwise. This bounds waiting for ownership,
        not the entire context body; commands retain their individual budgets.

        Returns:
            An asynchronous context manager that serializes commands issued through
            this session connection. It does not roll back browser state on failure.

        Raises:
            errors.InvalidSessionError: The session has not started.
            errors.SessionTimeoutError: Entering the context exceeds its admission
                deadline before any command in the context is sent.

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
                window = await self.active_window
                if window is None:
                    raise errors.InvalidSessionError(
                        "Active session has no focused browser window"
                    )
                return window
            try:
                service = self.service
                await service.start()
                client = service.session
                if client is None:
                    raise errors.InvalidSessionError(
                        "WebDriver service started without an HTTP client session"
                    )
                self._conn = Connection(client, self._session_timeout)
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
        remote_shutdown_is_safe = True
        service = self._service
        if service is None:
            self.__closed = True
            return
        capture_children = getattr(service, "_capture_session_children", None)
        if capture_children is not None:
            try:
                # Capture renderers or helpers created after startup before the
                # remote quit command can orphan them from the browser tree.
                await capture_children()
            except Exception:
                # The service performs another snapshot before its own shutdown
                # request. Skip session deletion until that retry has succeeded.
                remote_shutdown_is_safe = False
        if self._conn is not None and self._id is not None:
            if remote_shutdown_is_safe:
                try:
                    await self.execute_command(Command.QUIT, timeout=1)
                except Exception:
                    # Deletion is best effort, local owned service teardown is not.
                    pass
        await service.stop()
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
        """Create a remote session and cache its initial browser window.

        The owned WebDriver service and HTTP connection must already be running.

        Args:
            name: The name of the first window for the session. Defaults to `'default'`.

        Returns:
            The initial cached browser window.
        """

        def parse_session_id(res: dict[str, Any]) -> str:
            """Extract the nested W3C new-session ID or reject the response.

            Args:
                res: Raw WebDriver new-session response.

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
        service = self.service
        if not await run_blocking(lambda: service.running):
            raise errors.InvalidSessionError(
                "<{}>\nFailed to create new session. Please `start()` "
                "the service of the session first.".format(self.__class__.__name__)
            )

        # Start session
        capabilities = await run_blocking(lambda: self.options.capabilities)
        connection = self._conn
        if connection is None:
            raise errors.InvalidSessionError(
                "Session connection is unavailable during startup"
            )
        try:
            res = await connection.execute(
                "",
                Command.NEW_SESSION,
                body={"capabilities": {"alwaysMatch": capabilities}},
                timeout=self._session_timeout,
            )
            # Retain the remote ID before ownership inspection can divert startup
            # into cleanup, so a valid but locally unsafe session can be deleted.
            self._id = parse_session_id(res)
            self._base_url = "/session/" + quote(self._id, safe="")
        except BaseException:
            # A driver can launch a browser even when its handshake fails. Capture
            # those identities now without replacing the original transport,
            # protocol, or cancellation failure if inspection also fails.
            try:
                await finish_owned(self._capture_service_children())
            except BaseException:
                logger.warning(
                    "Unable to snapshot browser processes after a failed "
                    "new-session handshake",
                    exc_info=True,
                )
            raise
        await self._capture_service_children()

        # Set default window of the session
        handle = await self._active_window_handle()
        if not handle:
            raise errors.InvalidSessionError(
                "<{}>\nFailed to create new session: {}".format(
                    self.__class__.__name__, self._id
                )
            )
        return self._cache_window(handle, name)

    async def _capture_service_children(self) -> None:
        """Retain browser processes launched by the owned driver when supported."""
        service = self._service
        if service is None:
            return
        capture_children = getattr(service, "_capture_session_children", None)
        if capture_children is not None:
            await capture_children()

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
                WebDriver fails to respond in time, a `SessionTimeoutError`
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
                WebDriver fails to respond in time, a `SessionTimeoutError`
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
                WebDriver fails to respond in time, a `SessionTimeoutError`
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
                WebDriver fails to respond in time, a `SessionTimeoutError`
                will be raised.

        Example:
            >>> await session.backward()
        """
        await self.execute_command(Command.GO_BACK, timeout=timeout)

    # Information -------------------------------------------------------------------------
    @staticmethod
    def _typed_response_value(
        response: object, expected_type: type[T], description: str
    ) -> T:
        """Extract a response value only when it has the promised runtime type.

        Args:
            response: Candidate W3C response envelope.
            expected_type: Required runtime type for the ``value`` member.
            description: Short result name included in diagnostics.

        Returns:
            The validated response value.

        Raises:
            errors.InvalidResponseError: The response has no ``value`` member or
                the member has the wrong runtime type.
        """
        return response_value(response, expected_type, description)

    @property
    async def url(self) -> str:
        """Return the URL of the active page window.

        Returns:
            The URL of the active page window.

        Example:
            >>> await session.url # "https://www.google.com/"
        """
        res = await self.execute_command(Command.GET_CURRENT_URL)
        return self._typed_response_value(res, str, "Current URL")

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
        return self._typed_response_value(res, str, "Page title")

    async def wait_until_title(
        self,
        condition: Literal["equals", "contains", "startswith", "endswith"],
        value: str,
        timeout: int | float | None = 5,
    ) -> bool:
        """Wait until the active page title satisfies a string condition.

        Args:
            condition: The condition the title needs to satisfy.
                Expected values: `"equals"`, `"contains"`, `"startswith"`, `"endswith"`.
            value: The value of the condition.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            True if the title satisfies the condition, False if timeout.

        Example:
            >>> await session.load("https://www.google.com/")
            >>> found = await session.wait_until_title("contains", "Google", 5)
            >>> isinstance(found, bool)
            True
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
            >>> await session.page_width  # 1200
        """
        try:
            value = await self._execute_script(javascript.GET_PAGE_WIDTH)
            return typed_value(value, int, "Page width")
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
            >>> await session.page_height  # 800
        """
        try:
            value = await self._execute_script(javascript.GET_PAGE_HEIGHT)
            return typed_value(value, int, "Page height")
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
        return self._typed_response_value(res, str, "Page source")

    async def take_screenshot(self) -> bytes:
        """Capture the active page viewport as PNG data.

        Returns:
            Decoded PNG bytes for the active viewport.

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

    async def save_screenshot(self, path: PathInput) -> bool:
        """Capture the active page and save it as PNG.

        Args:
            path: Destination supplied as a string, `pathlib.Path`, or compatible
                `os.PathLike[str]`. Relative paths are resolved from the current
                working directory, `~` is expanded, and `.png` is appended unless
                the filename already ends with that exact suffix.

        Returns:
            `True` if nonempty screenshot data was written; otherwise `False`.

        Example:
            >>> await session.save_screenshot("~/path/to/screenshot.png")  # True / False
        """
        # Validate screenshot path
        try:
            destination = save_file_path(path, ".png")
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
            return await save_bytes(destination, data)
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
            scale: Page-rendering scale from 0.1 through 2.0.
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

        def orie_validator(param: str, value: str | None) -> bool:
            """Validate the page-print orientation.

            Args:
                param: Name of the option being validated for error reporting.
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

        def scal_validator(param: str, value: int | float | None) -> bool:
            """Validate the page-print scale range.

            Args:
                param: Name of the option being validated for error reporting.
                value: The page-print scale range supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if value is None or not nums_validator(param, value):
                return False
            if not 0.1 <= value <= 2:
                raise errors.InvalidArgumentError(
                    "<{}>\nInvalid print {}: {}. Must be between 0.1 and 2.".format(
                        self.__class__.__name__, param, repr(value)
                    )
                )
            return True

        def bool_validator(param: str, value: bool | None) -> bool:
            """Validate a boolean page-print setting.

            Args:
                param: Name of the option being validated for error reporting.
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

        def nums_validator(param: str, value: int | float | None) -> bool:
            """Validate numeric page dimensions and margins.

            Args:
                param: Name of the option being validated for error reporting.
                value: Numeric page dimensions and margins supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if value is None:
                return False
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
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

        def list_validator(param: str, value: list[str] | None) -> bool:
            """Validate page ranges for the print command.

            Args:
                param: Name of the option being validated for error reporting.
                value: Page ranges for the print command supplied for validation.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if value is None:
                return False
            if not isinstance(value, list) or not all(
                isinstance(page_range, str) and page_range for page_range in value
            ):
                raise errors.InvalidArgumentError(
                    "{}\nInvalid {} argument: {} {}. Must be a list of "
                    "nonempty strings.".format(
                        self.__class__.__name__, param, repr(value), type(value)
                    )
                )
            return True

        # Print options
        options: dict[str, Any] = {}
        if orientation is not None and orie_validator("orientation", orientation):
            options["orientation"] = orientation
        if scale is not None and scal_validator("scale", scale):
            options["scale"] = scale
        if background is not None and bool_validator("background", background):
            options["background"] = background
        if page_width is not None and nums_validator("page_width", page_width):
            options["page"] = options.get("page", {}) | {"width": page_width}
        if page_height is not None and nums_validator("page_height", page_height):
            options["page"] = options.get("page", {}) | {"height": page_height}
        if margin_top is not None and nums_validator("margin_top", margin_top):
            options["margin"] = options.get("margin", {}) | {"top": margin_top}
        if margin_bottom is not None and nums_validator("margin_bottom", margin_bottom):
            options["margin"] = options.get("margin", {}) | {"bottom": margin_bottom}
        if margin_left is not None and nums_validator("margin_left", margin_left):
            options["margin"] = options.get("margin", {}) | {"left": margin_left}
        if margin_right is not None and nums_validator("margin_right", margin_right):
            options["margin"] = options.get("margin", {}) | {"right": margin_right}
        if shrink_to_fit is not None and bool_validator("shrink_to_fit", shrink_to_fit):
            options["shrinkToFit"] = shrink_to_fit
        if page_ranges is not None and list_validator("page_ranges", page_ranges):
            options["pageRanges"] = page_ranges.copy()

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
        path: PathInput,
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
        """Render the active page and save it as PDF.

        Args:
            path: Destination supplied as a string, `pathlib.Path`, or compatible
                `os.PathLike[str]`. Relative paths are resolved from the current
                working directory, `~` is expanded, and `.pdf` is appended unless
                the filename already ends with that exact suffix.
            orientation: The print orientation. Accepts: "portrait", "landscape".
            scale: Page-rendering scale from 0.1 through 2.0.
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
            `True` if nonempty PDF data was written; otherwise `False`.

        Example:
            >>> await session.save_page("~/path/to/page.pdf")  # True / False
        """
        # Validate pdf path
        try:
            destination = save_file_path(path, ".pdf")
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
            return await save_bytes(destination, data)
        finally:
            del data

    # Timeouts ----------------------------------------------------------------------------
    @property
    async def timeouts(self) -> Timeouts:
        """Return the timeouts of the current session.

        The three W3C timeout fields are:

        - `implicit`: Time spent locating an element that is not immediately present.

        - `pageLoad`: Time allowed for a page load to complete.

        - `script`: Time allowed for an asynchronous script to finish.

        Returns:
            The timeouts of the current session.

        Example:
            >>> timeouts = await session.timeouts
        """
        if self._timeouts is None:
            await self._refresh_timeouts()
        timeouts = self._timeouts
        if timeouts is None:
            raise errors.InvalidResponseError("WebDriver returned no timeout state")
        return timeouts.copy()

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
            connection, base_url = self._active_transport()
            await connection.execute(base_url, Command.SET_TIMEOUTS, body=timeouts.dict)
            await self._refresh_timeouts()
            refreshed = self._timeouts
            if refreshed is None:
                raise errors.InvalidResponseError("WebDriver returned no timeout state")
            return refreshed.copy()

    async def reset_timeouts(self) -> Timeouts:
        """Reset session timeouts atomically to the original option values.

        Returns:
            A copy of the restored session timeouts.

        Example:
            >>> timeouts = await session.reset_timeouts()
        """
        async with self.transaction():
            self._timeouts = None
            connection, base_url = self._active_transport()
            await connection.execute(
                base_url,
                Command.SET_TIMEOUTS,
                body=self.options.timeouts.dict,
            )
            await self._refresh_timeouts()
            refreshed = self._timeouts
            if refreshed is None:
                raise errors.InvalidResponseError("WebDriver returned no timeout state")
            return refreshed.copy()

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
        """Return the internal timeout state, refreshing it when absent.

        Returns:
            The mutable timeout object retained by this session. Public callers
            receive a copy through the ``timeouts`` property.

        Raises:
            errors.InvalidResponseError: Refreshing produces no timeout state.
        """
        if self._timeouts is None:
            await self._refresh_timeouts()
        timeouts = self._timeouts
        if timeouts is None:
            raise errors.InvalidResponseError("WebDriver returned no timeout state")
        return timeouts

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
            name: Cookie name or an existing `Cookie` object.

        Returns:
            The requested cookie, or `None` when it does not exist.

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
            cookie: Cookie data mapping or an existing `Cookie` object.

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
                "<{}>\nInvalid 'cookie' argument: {}. Must be "
                "a dictionary or `<'Cookie'>` instance".format(
                    self.__class__.__name__, cookie
                )
            )
        # Execute & return
        await self.execute_command(Command.ADD_COOKIE, {"cookie": cookie.dict})
        added = await self.get_cookie(cookie)
        if added is None:
            raise errors.InvalidResponseError(
                "WebDriver did not return the cookie after adding it"
            )
        return added

    async def delete_cookie(self, name: str | Cookie) -> None:
        """Delete a cookie from the active page window.

        Args:
            name: Cookie name or an existing `Cookie` object.

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
            name: Cookie name or `Cookie` object to normalize.

        Returns:
            The name of a cookie.
        """
        if isinstance(name, str) and name:
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
        """Return the session's focused browser window, if any.

        Returns:
            The focused window, or `None` when every window is closed.

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
            window: A cached window, or its name or remote handle.

        Returns:
            The matched open window of the session, or `None` if not found.

        Example:
            >>> win = await session.get_window("default")
        """
        name = window.name if isinstance(window, Window) else window
        handle = window.handle if isinstance(window, Window) else window
        # Match cache by name
        if name in self._window_by_name:
            return self._window_by_name[name]
        # Match cache by handle
        elif handle in self._window_by_handle:
            return self._window_by_handle[handle]
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
            window: An open window, or its cached name or remote handle.

        Returns:
            The new focused window.

        Example:
            >>> win = await session.switch_window("new")
        """
        # Get existing window
        win = await self.get_window(window)
        if not win:
            raise errors.WindowNotFoundError(
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
        except errors.WindowNotFoundError as err:
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
        """Rename a window in the local session cache.

        This changes only Aselenium's lookup name; it does not modify the remote
        browser window or its WebDriver handle.

        Args:
            window: An open window, or its cached name or remote handle.
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
            raise errors.WindowNotFoundError(
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
            switch_to: Window to focus after closing, supplied as a `Window`,
                cached name, or remote handle. If omitted or not found, the first
                remaining window returned by WebDriver is selected.

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
                except errors.WindowNotFoundError:
                    pass
            try:
                if wins := await self.windows:
                    await self.switch_window(wins[0])
                    return wins[0]
                return None
            except (errors.InvalidSessionError, errors.WindowNotFoundError):
                return None

    async def _active_window_handle(self) -> str | None:
        """Request the focused window's remote handle.

        Returns:
            The nonempty handle, or `None` if every window is closed.
        """
        # Get window handle
        try:
            res = await self.execute_command(Command.W3C_GET_CURRENT_WINDOW_HANDLE)
        except (errors.InvalidSessionError, errors.WindowNotFoundError):
            return None
        handle = response_value(res, str, "Active window handle")
        if not handle:
            raise errors.InvalidResponseError(
                "Active window handle response value must be nonempty"
            )
        return handle

    async def _match_session_window(self, window: str | Window) -> Window | None:
        """Refresh window metadata and match a name, handle, or window object.

        Args:
            window: Window reference, cached name, or remote handle to match.

        Returns:
            The matching open window, or `None` when no window matches.
        """
        for win in await self.windows:
            if window == win.handle or window == win.name:
                return win
        return None

    def _cache_window(self, handle: str, name: str | None = None) -> Window:
        """Cache a remote window under both its local name and handle.

        Args:
            handle: Nonempty WebDriver window handle.
            name: Optional local lookup name; a generated name is used when omitted.

        Returns:
            The cached window object.
        """
        win = Window(handle, name=name)
        self._window_by_name[win.name] = win
        self._window_by_handle[win.handle] = win
        return win

    def _remove_window(self, window: str | Window) -> bool:
        """Remove a window from both local lookup indexes.

        Args:
            window: Window object, local name, or remote handle to remove.

        Returns:
            `True` if a cached window was removed; otherwise `False`.
        """
        name = window.name if isinstance(window, Window) else window
        handle = window.handle if isinstance(window, Window) else window
        if name in self._window_by_name:
            win = self._window_by_name.pop(name)
            self._window_by_handle.pop(win.handle, None)
            return True
        elif handle in self._window_by_handle:
            win = self._window_by_handle.pop(handle)
            self._window_by_name.pop(win.name, None)
            return True
        else:
            return False

    def _validate_window_name(self, name: Any) -> str:
        """Validate window name.

        Args:
            name: Candidate local window name.

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
            The window rectangle reported after the update.

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
            retry: Maximum number of retries after the initial request.

        Returns:
            The raw WebDriver response from the successful command.
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
            pause: Finite, nonnegative delay after scrolling, in seconds.
                ``None`` means no delay. Validated before the script is sent.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid, including a boolean.
            errors.InvalidResponseError: The scrolling script fails.

        Example:
            >>> await session.scroll_by(100, 100)
        """
        validate_delay(pause)
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
            pause: Finite, nonnegative delay after scrolling, in seconds.
                ``None`` means no delay. Validated before the script is sent.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid, including a boolean.
            errors.InvalidResponseError: The scrolling script fails.

        Example:
            >>> await session.scroll_to(100, 100)
        """
        validate_delay(pause)
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
            value: Number of steps or pixels, according to `by`.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the top of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the top of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_top(12, "steps")
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        strategy = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixels
        if strategy == "steps":
            viewport = await self.viewport
            # . fast path - already at top
            if viewport.top <= 0:
                return None  # exit
            # . fast path - straight to top
            if value == 1:
                await self.scroll_to(x=viewport.x, y=0)
                return None  # exit
            # . calculate pixels
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
            value: Number of steps or pixels, according to `by`.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the bottom of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the bottom of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_bottom(100, "pixels")
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        strategy = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixels
        if strategy == "steps":
            bottom = (await self.viewport).bottom
            height = await self.page_height
            # . fast path - already at bottom
            if height - bottom <= 1:
                return None
            # . calculate pixels
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
            value: Number of steps or pixels, according to `by`.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the left of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the left of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_left(12, "steps")
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        strategy = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixels
        if strategy == "steps":
            viewport = await self.viewport
            # . fast path - already at left
            if viewport.left <= 0:
                return None  # exit
            # . fast path - straight to left
            if value == 1:
                await self.scroll_to(x=0, y=viewport.y)
                return None  # exit
            # . calculate pixels
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
            value: Number of steps or pixels, according to `by`.
            by: The scrolling strategy. Defaults to `'steps'`.
                - `'steps'`: The 'value' sets the approximate steps it
                takes to scroll to the right of the page.
                - `'pixels'`: The 'value' sets the exact pixels to scroll
                for each step to the right of the page.
            pause: Seconds to pause between each scroll. Defaults to `0.2`.

        Example:
            >>> await session.scroll_to_right(100, "pixels")
        """
        # Validate arguments
        value = self._validate_scroll_value(value)
        strategy = self._validate_scroll_strategy(by)
        pause = self._validate_pause(pause)

        # Calculate scroll pixels
        if strategy == "steps":
            right = (await self.viewport).right
            width = await self.page_width
            # . fast path - already at right
            if width - right <= 1:
                return None
            # . calculate pixels
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
            value: Element or selector identifying the scroll target.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                This argument is ignored when `value` is an `Element`.
            timeout: Total seconds to wait for the element to scroll into view. Defaults to `5`.

        Returns:
            `True` if the element was found and scrolled into view; otherwise `False`.

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

    def _validate_scroll_strategy(self, by: Any) -> Literal["steps", "pixels"]:
        """Validate the scroll 'by' strategy.

        Args:
            by: Candidate strategy, either `"steps"` or `"pixels"`.

        Returns:
            The scroll 'by' strategy.
        """
        if by == "steps":
            return "steps"
        if by == "pixels":
            return "pixels"
        raise errors.InvalidArgumentError(
            "<{}>\nInvalid scroll 'by' strategy: {}. Available options: {}".format(
                self.__class__.__name__,
                repr(by),
                sorted(Constraint.PAGE_SCROLL_BY_STRATEGIES),
            )
        )

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
            The active alert, or `None` when no alert appears before the deadline.

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
            value: A frame element, an element selector, or a nonnegative frame
                index when `by="index"`.
            by: The selector strategy, accepts `'css'`, `'xpath'` or `'index'`. Defaults to `'css'`.
                This argument is ignored when `value` is an `Element`.
            timeout: Total seconds to wait for frame switching. Defaults to `5`.

        Returns:
            `True` when focus changes to the frame; `False` if it is not found.

        Example:
            >>> # . switch by element selector
            >>> await session.switch_frame("figure.demoarea > iframe", by="css")  # True / False

            >>> # . switch by element instance
            >>> element = await session.find_element("figure.demoarea > iframe", by="css")
            >>> await session.switch_frame(element)  # True / False

            >>> # . switch by frame index
            >>> await session.switch_frame(1, by="index")  # True / False
        """
        frame_element = value if isinstance(value, Element) else None
        frame_index: int | None = None
        selector: str | None = None
        strategy: str | None = None
        if frame_element is None and by == "index":
            if type(value) is not int or value < 0:
                raise errors.InvalidArgumentError(
                    "Frame index must be a nonnegative integer"
                )
            frame_index = value
        elif frame_element is None:
            if not isinstance(value, str) or not value:
                raise errors.InvalidArgumentError(
                    "Frame selector must be a nonempty string"
                )
            selector = value
            strategy = self._validate_selector_strategy(by)

        async def attempt() -> bool:
            """Attempt one frame switch, treating a missing frame as not ready.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            try:
                frame_id: dict[str, str] | int
                if frame_element is not None:
                    frame_id = {ELEMENT_KEY: frame_element.id}
                elif frame_index is not None:
                    frame_id = frame_index
                else:
                    if selector is None or strategy is None:
                        raise errors.InvalidArgumentError(
                            "Frame selector and strategy are unavailable"
                        )
                    element = await self._find_element_no_wait(selector, strategy)
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
            `True` when focus changes to the top-level document; otherwise `False`.

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
            `True` when focus changes to the parent frame; otherwise `False`.

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
        """Return the element that currently has document focus.

        Returns:
            The focused element. WebDriver normally returns the document body when
            no form control or other focusable element has focus.

        Raises:
            errors.InvalidResponseError: If WebDriver does not return an element reference.

        Example:
            >>> element = await session.active_element
        """
        res = await self.execute_command(Command.W3C_GET_ACTIVE_ELEMENT)
        element = self._create_element(res.get("value"))
        if element is None:
            raise errors.InvalidResponseError(
                "Active-element response did not contain an element reference"
            )
        return element

    async def element_exists(
        self,
        value: str | Element,
        by: Literal["css", "xpath"] = "css",
    ) -> bool:
        """Check if an element exists. This method ignores the implicit wait timeout, and returns element existence immediately.

        Args:
            value: An element or a selector that identifies one.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                This argument is ignored when `value` is an `Element`.

        Returns:
            `True` if the element exists; otherwise `False`.

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
                This argument is ignored for values that are `Element` objects.
            all_: Determines what satisfies the existence of the elements. Defaults to `True (all elements)`.
                - `True`: All elements must exist to return True.
                - `False`: Any one of the elements exists returns True.
            *values: Elements or selectors that identify them.

        Returns:
            `True` when the requested all/any existence rule is satisfied.

        Example:
            >>> await session.elements_exist(
            ...     "#input_box", "#input_box2", by="css", all_=True
            ... )  # True / False
        """

        async def check_existence(value: str | Element) -> bool:
            """Perform one element-existence observation for the enclosing wait.

            Args:
                value: Element or selector to check once.

            Returns:
                True when the checked condition is satisfied; otherwise False.
            """
            if isinstance(value, Element):
                return await value.exists
            else:
                return await self._element_exists_no_wait(value, strat)

        # Validate strategy
        strat = self._validate_selector_strategy(by)
        # Check existence
        if all_:
            for value in values:
                if not await check_existence(value):
                    return False
            return True
        else:
            for value in values:
                if await check_existence(value):
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
            The located element, or `None` when no element matches.

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
            Located elements in response order, or an empty list when none match.

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
            The first located element in selector order, or `None` when none match.

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
            value: Element or selector to evaluate.
            by: The selector strategy, accepts `'css'` or `'xpath'`. Defaults to `'css'`.
                This argument is ignored when `value` is an `Element`.
            timeout: Total seconds to wait until timeout. Defaults to `5`.

        Returns:
            `True` if the condition is met before the deadline; otherwise `False`.

        Example:
            >>> await session.wait_until_element(
            ...     "unobscured", "#input_box", by="css", timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                This argument is ignored for values that are `Element` objects.
            all_: Determine how to satisfy the condition. Defaults to `True (all elements)`.
                - `True`: All elements must satisfy the condition to return True.
                - `False`: Any one of the elements satisfies the condition returns True.
            timeout: Total seconds to wait until timeout. Defaults to `5`.
            *values: Elements or selectors that identify them.

        Returns:
            `True` if the requested all/any rule is met before the deadline.

        Example:
            >>> await session.wait_until_elements(
            ...     "unobscured", "#input_box1", "#search_button",
            ...     by="css", all_=True, timeout=5
            ... )  # True / False
        """

        async def is_gone(value: str | Element) -> bool:
            """Check whether the previously identified element is absent from the DOM.

            Args:
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                value: Element or selector evaluated during this poll.

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
                condition_checker: Async predicate applied to each candidate.

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
        """Check for a matching element once, without applying implicit wait.

        Args:
            value: Element selector.
            strat: Validated WebDriver selector strategy.

        Returns:
            True if an element exists without implicit wait; otherwise False.
        """
        try:
            result = await self._execute_script(
                javascript.ELEMENT_EXISTS_IN_PAGE[strat], value
            )
            return typed_value(result, bool, "Page element existence state")
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
        """Find one matching element without applying implicit wait.

        Args:
            value: Element selector.
            strat: Validated WebDriver selector strategy.

        Returns:
            The matching element, or `None` when no element matches.
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
            by: Public selector name (`"css"` or `"xpath"`) or the internal
                WebDriver name `"css selector"`.

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
            The host element's shadow root, or `None` when no matching host or
            shadow root appears before the deadline.

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
        """Return a snapshot of the locally cached JavaScript snippets.

        Returns:
            Cached JavaScript objects in insertion order.

        Example:
            >>> scripts = session.scripts
        """
        return list(self._script_by_name.values())

    def get_script(self, script: str | JavaScript) -> JavaScript | None:
        """Look up a locally cached JavaScript snippet.

        Args:
            script: Cache name or JavaScript instance, matched by its name.

        Returns:
            The cached JavaScript, or `None` when the name is unknown.

        Raises:
            errors.InvalidArgumentError: If script is neither a string nor a JavaScript.

        Example:
            >>> js = session.get_script("myscript")
        """
        if not isinstance(script, (str, JavaScript)):
            raise errors.InvalidArgumentError(
                "Script must be a string or a cached JavaScript instance."
            )
        name = script.name if isinstance(script, JavaScript) else script
        return self._script_by_name.get(name)

    def cache_script(self, name: str, script: str, *args: Any) -> JavaScript:
        """Cache a named JavaScript snippet for later execution.

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
        """Remove a JavaScript snippet from the local cache.

        Args:
            script: Cached JavaScript object or its cache name.

        Returns:
            `True` if the script was cached and removed; otherwise `False`.

        Example:
            >>> session.remove_script("myscript")  # True / False
        """
        try:
            name = script.name if isinstance(script, JavaScript) else script
            self._script_by_name.pop(name)
            return True
        except KeyError:
            return False

    def rename_script(self, script: str | JavaScript, new_name: str) -> JavaScript:
        """Replace a cached JavaScript snippet's local lookup name.

        Args:
            script: Cached JavaScript object or its cache name.
            new_name: The new name for the javascript.

        Returns:
            The renamed javascript.

        Example:
            >>> # . cache a script
            >>> js = session.cache_script("script1", "return document.title;")
            >>> print(js.name)
            script1

            >>> # . rename the script
            >>> js = session.rename_script("script1", "script2")
        """
        # Validate name
        name = self._validate_script_name(new_name)

        # Pop cached script
        try:
            script_name = script.name if isinstance(script, JavaScript) else script
            js = self._script_by_name.pop(script_name)
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
            name: Candidate JavaScript cache name.

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
        """Create an action chain for pointer, keyboard, and wheel input.

        Args:
            pointer: The pointer type to use. Defaults to `'mouse'`.
                Available options are: `'mouse'`, `'pen'`, `'touch'`.
            duration: The duration in seconds to perform a pointer move or wheel scroll action. Defaults to `0.25`.

        Returns:
            The actions chain.

        Example:
            >>> from aselenium import KeyboardKeys
            >>> input_box = await session.find_element("#input_box")
            >>> assert input_box is not None
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
        """Pause command sequencing for a duration in seconds.

        Args:
            duration: Finite, nonnegative delay in seconds, or ``None`` for no
                delay.

        Raises:
            errors.InvalidArgumentError: ``duration`` is not a finite,
                nonnegative number or ``None``.
        """
        validate_delay(duration)
        if duration is not None:
            await sleep(duration)

    def _validate_pause(self, value: Any) -> int | float:
        """Validate a positive pause duration.

        Args:
            value: Candidate duration in seconds.

        Returns:
            The validated positive duration.

        Raises:
            errors.InvalidArgumentError: If `value` is not a positive number.
        """
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'pause'. Must be a finite integer or float, "
                "instead got: {}.".format(self.__class__.__name__, type(value))
            )
        if value <= 0:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'pause'. Must be greater than 0, "
                "instead got: {}.".format(self.__class__.__name__, value)
            )
        return value

    def _validate_wait_str_value(self, value: Any) -> str:
        """Validate a nonempty string used by a wait condition.

        Args:
            value: Candidate string value.

        Returns:
            The validated string.

        Raises:
            errors.InvalidArgumentError: If `value` is not a nonempty string.
        """
        if not isinstance(value, str) or not value:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid wait until value: {} {}. "
                "Must be a nonempty string.".format(
                    self.__class__.__name__, repr(value), type(value)
                )
            )
        return value

    def _raise_invalid_wait_condition(self, condition: Any) -> NoReturn:
        """Reject an unsupported element wait condition.

        Args:
            condition: Unsupported condition value.

        Raises:
            errors.InvalidArgumentError: Always raised with the supplied diagnostic context.
        """
        raise errors.InvalidArgumentError(
            "<{}>\nInvalid wait until condition: {} {}.".format(
                self.__class__.__name__, repr(condition), type(condition)
            )
        )

    def _is_element(self, element: object) -> TypeGuard[Element]:
        """Return whether an object is an `Element` instance.

        Args:
            element: Object to inspect.

        Returns:
            `True` when `element` is an `Element`; otherwise `False`.
        """
        return isinstance(element, Element)

    def _decode_base64(self, data: str, encoding: str) -> bytes:
        """Decode a base64-encoded text payload into bytes.

        Args:
            data: Base64 text returned by WebDriver.
            encoding: Character encoding used to convert the text to bytes.

        Returns:
            Decoded binary payload.
        """
        return b64decode(data.encode(encoding), validate=True)

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Describe the session without allocating a service endpoint.

        Returns:
            The session ID and already allocated service URL, if any.
        """
        service_url = getattr(self._service, "_url", None)
        return "<%s (id='%s', service='%s')>" % (
            self.__class__.__name__,
            self._id,
            service_url,
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
        return self is __o

    def __del__(self) -> None:
        """Release references during finalization without emitting unraisable errors."""
        try:
            self._collect_garbage()
        except Exception:
            # Construction can fail before subclass caches exist. Explicit
            # ``quit()`` remains the only error-reporting cleanup boundary.
            pass

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
        # Vendor prefix
        self._vendor.clear()
        # Session
        self._id = None
        self._base_url = None
        self._timeouts = None
        # Window
        self._window_by_name.clear()
        self._window_by_handle.clear()
        # Script
        self._script_by_name.clear()
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
        """Create a Chromium-family session with CDP command caching.

        Args:
            options: Chromium-family browser configuration snapshot.
            service: Chromium-family WebDriver service owned by the session.
        """
        super().__init__(options, service)
        self._options: ChromiumBaseOptions | None = options
        self._service: ChromiumBaseService | None = service
        # Devtools cmd
        self._cdp_cmd_by_name: dict[str, DevToolsCMD] = {}

    # Basic -------------------------------------------------------------------------------
    @property
    def options(self) -> ChromiumBaseOptions:
        """Return the browser options.

        Returns:
            The browser options owned by this facade or session.
        """
        options = self._options
        if options is None:
            raise errors.InvalidSessionError("Session options have been released")
        return options

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
        """Return the WebDriver service.

        Returns:
            The driver service owned by the session.
        """
        service = self._service
        if service is None:
            raise errors.InvalidSessionError("Session service has been released")
        return service

    @property
    def driver_version(self) -> ChromiumVersion:
        """Return the WebDriver binary version of the session.

        Returns:
            The WebDriver binary version of the session.
        """
        return self.service.driver_version

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
            name: Permission descriptor name or existing `Permission` object.

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
        """Set and observe a permission state under shared command ownership.

        The update and observation cannot interleave with another independent
        task's commands. Use ``session.transaction()`` around additional work
        that depends on the resulting page or permission state.

        Args:
            name: The name of the permission.
            state: The state of the permission, accepts: `'granted'`, `'denied'`, `'prompt'`.

        Returns:
            The permission after update.

        Example:
            >>> perm = await session.set_permission("geolocation", "granted")
        """
        permission = Permission(name, state)
        async with self.transaction():
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
                raise
            current = await self.get_permission(name)
            if current is None:
                raise errors.InvalidResponseError(
                    "WebDriver did not return the permission after setting it"
                )
            return current

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
        """Reset Chromium network emulation and return confirmed defaults.

        Default conditions:
        <Network (offline=False, latency=0, upload_throughput=-1, download_throughput=-1)>

        Returns:
            The confirmed default network conditions.

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
        sinks = self._typed_response_value(res, list, "Cast sinks")
        if not all(isinstance(sink, dict) for sink in sinks):
            raise errors.InvalidResponseError(
                "Cast sinks response value must contain only objects"
            )
        return sinks

    @property
    async def cast_issue(self) -> str:
        """Return the issue of the Cast session.

        Returns:
            The issue of the cast session.
        """
        res = await self.execute_command(Command.GET_ISSUE_MESSAGE, keys=self._vendor)
        return self._typed_response_value(res, str, "Cast issue")

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
        """Return a snapshot of locally cached Chrome DevTools commands.

        Returns:
            Cached DevTools commands in insertion order.

        Example:
            >>> cmds = session.cdp_cmds
        """
        return list(self._cdp_cmd_by_name.values())

    def get_cdp_cmd(self, cmd: str | DevToolsCMD) -> DevToolsCMD | None:
        """Look up a locally cached Chrome DevTools command.

        Args:
            cmd: Cache name or DevToolsCMD instance, matched by its name.

        Returns:
            The cached command, or `None` when the name is unknown.

        Raises:
            errors.InvalidArgumentError: If cmd is neither a string nor a DevToolsCMD.

        Example:
            >>> cmd = session.get_cdp_cmd("mycmd")
        """
        if not isinstance(cmd, (str, DevToolsCMD)):
            raise errors.InvalidArgumentError(
                "CDP command must be a string or a cached DevToolsCMD instance."
            )
        name = cmd.name if isinstance(cmd, DevToolsCMD) else cmd
        return self._cdp_cmd_by_name.get(name)

    def cache_cdp_cmd(self, name: str, cmd: str, **kwargs: Any) -> DevToolsCMD:
        """Cache a named Chrome DevTools Protocol command.

        Args:
            name: Unique local cache name.
            cmd: DevTools Protocol method name, such as `"Browser.getVersion"`.
            **kwargs: Default command parameters.

        Returns:
            The cached CDP command.

        Example:
            >>> cmd = session.cache_cdp_cmd("get_version", "Browser.getVersion")
            >>> print(cmd.name)
            get_version

            >>> cmd = session.cache_cdp_cmd(
            ...     "get_url",
            ...     "Runtime.evaluate",
            ...     expression="window.location.href",
            ... )
        """
        cached_cmd = DevToolsCMD(self._validate_cdp_cmd_name(name), cmd, **kwargs)
        self._cdp_cmd_by_name[name] = cached_cmd
        return cached_cmd

    def remove_cdp_cmd(self, cmd: str | DevToolsCMD) -> bool:
        """Remove a Chrome DevTools command from the local cache.

        Args:
            cmd: Cached DevTools command or its cache name.

        Returns:
            `True` if the command was cached and removed; otherwise `False`.

        Example:
            >>> session.remove_cdp_cmd("mycmd")  # True / False
        """
        try:
            name = cmd.name if isinstance(cmd, DevToolsCMD) else cmd
            self._cdp_cmd_by_name.pop(name)
            return True
        except KeyError:
            return False

    def rename_cdp_cmd(self, cmd: str | DevToolsCMD, new_name: str) -> DevToolsCMD:
        """Replace a cached Chrome DevTools command's local lookup name.

        Args:
            cmd: Cached DevTools command or its cache name.
            new_name: The new name for the command.

        Returns:
            The renamed command.

        Example:
            >>> cmd = session.cache_cdp_cmd("cmd1", "Browser.getVersion")
            >>> cmd = session.rename_cdp_cmd("cmd1", "cmd2")
            >>> print(cmd.name)
            cmd2
        """
        # Validate name
        name = self._validate_cdp_cmd_name(new_name)

        # Pop cached command
        try:
            cmd_name = cmd.name if isinstance(cmd, DevToolsCMD) else cmd
            cached_cmd = self._cdp_cmd_by_name.pop(cmd_name)
        except KeyError as err:
            raise errors.DevToolsCMDNotFoundError(
                "<{}>\nCannot rename command {}. Chrome Devtools Protocol "
                "command not found.".format(self.__class__.__name__, repr(cmd))
            ) from err

        # Cache with new name
        return self.cache_cdp_cmd(name, cached_cmd.cmd, **cached_cmd.kwargs)

    async def execute_cdp_cmd(
        self, cmd: str | DevToolsCMD, **kwargs: Any
    ) -> dict[str, Any]:
        """Execute a raw or cached Chrome DevTools Protocol command.

        Args:
            cmd: Raw DevTools method name, cached command name, or cached
                `DevToolsCMD` object.
            **kwargs: Command parameters. For a cached command, nonempty values
                replace all cached default parameters.

        Returns:
            The response from the command execution.

        Raises:
            errors.DevToolsCMDNotFoundError: If the supplied DevToolsCMD has no cached name.
            errors.InvalidArgumentError: If cmd is neither a string nor a DevToolsCMD.

        Example:
            >>> result = await session.execute_cdp_cmd("Browser.getVersion")
            >>> cached = session.cache_cdp_cmd("page_url", "Runtime.evaluate")
            >>> result = await session.execute_cdp_cmd(
            ...     cached, expression="window.location.href"
            ... )
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
        """Send one Chrome DevTools Protocol method and parse its result.

        Args:
            cmd: DevTools Protocol method name.
            **kwargs: Command parameters.

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
        return self._typed_response_value(res, dict, "DevTools command")

    def _validate_cdp_cmd_name(self, name: str) -> str:
        """Validate CDP command name.

        Args:
            name: Nonempty name that must not already identify a cached command.

        Returns:
            The unchanged name after validation.
        """
        if not isinstance(name, str) or not name:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid Chrome DevTools Protocol command name: {} {}.".format(
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
        log_types = self._typed_response_value(res, list, "Log types")
        if not all(isinstance(log_type, str) for log_type in log_types):
            raise errors.InvalidResponseError(
                "Log types response value must contain only strings"
            )
        return log_types

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
        logs = self._typed_response_value(res, list, "Logs")
        if not all(isinstance(entry, dict) for entry in logs):
            raise errors.InvalidResponseError(
                "Logs response value must contain only objects"
            )
        return logs

    # Special methods ---------------------------------------------------------------------
    def _collect_garbage(self) -> None:
        """Release Chromium command-cache references after base session cleanup."""
        super()._collect_garbage()
        commands = getattr(self, "_cdp_cmd_by_name", None)
        if commands is not None:
            commands.clear()
