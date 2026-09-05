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

"""Lifecycle and process ownership for local WebDriver services."""

from __future__ import annotations

import asyncio
from asyncio import TimeoutError, sleep
from errno import EACCES, ENOENT
from math import isfinite
from os import PathLike, environ
from pathlib import Path
from platform import system
from socket import AF_INET, SOCK_STREAM, create_connection, socket
from subprocess import DEVNULL, Popen, TimeoutExpired
from time import monotonic as unix_time
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

from aiohttp import ClientError, ClientSession
from psutil import NoSuchProcess, Process

from aselenium import errors
from aselenium._async import finish_owned, run_blocking
from aselenium._paths import PathInput, file_path

if TYPE_CHECKING:
    from aselenium.manager.version import ChromiumVersion, Version


# Base Service ------------------------------------------------------------------------------------
class BaseService:
    """Manage a local WebDriver service process and status client.

    Service launch a subprocess as the interim process
    to communicate with the browser.
    """

    __PORTS: set[int] = set()

    def __init__(
        self,
        driver_version: Version,
        driver_location: PathInput,
        timeout: int | float = 10,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Validate an executable and configure one reusable driver service.

        Service launch a subprocess as the interim process to communicate with the browser.

        Args:
            driver_version: Version of the WebDriver executable.
            driver_location: Path to the WebDriver executable.
            timeout: Timeout in seconds for starting/stopping the service. Defaults to `10`.
            *args: Additional arguments for `subprocess.Popen` constructor.
            **kwargs: Additional keyword arguments for `subprocess.Popen` constructor.
        """
        # Driver
        try:
            self._driver_location = file_path(driver_location)
        except Exception as err:
            raise errors.ServiceExecutableNotFoundError(
                "`<{}>`\nService WebDriver executable not found at: {}".format(
                    self.__class__.__name__, repr(driver_location)
                )
            ) from err
        self._driver_version = driver_version
        # Timeout
        self.timeout = timeout
        # Process
        self._args: list[Any] = list(args)
        self._kwargs: dict[str, Any] = kwargs
        self._creation_flags: int = self._kwargs.pop("creation_flags", 0)
        self._close_fds: bool = self._kwargs.pop("close_fds", system() != "Windows")
        self._port: int = -1
        self._port_str: str | None = None
        self._process: Process | None = None
        self._popen: Popen[bytes] | None = None
        self._owned_children: list[Process] = []
        self._lifecycle_lock = asyncio.Lock()
        # Session
        self._session: ClientSession | None = None
        # Service
        self._url: str | None = None

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> Version:
        """Return the version of the WebDriver executable.

        Returns:
            The version of the WebDriver executable.
        """
        return self._driver_version

    @property
    def driver_location(self) -> Path:
        """Return the validated WebDriver executable path.

        Returns:
            The absolute ``Path`` retained by the service for its full lifecycle.
        """
        return self._driver_location

    # Timeout -----------------------------------------------------------------------------
    @property
    def timeout(self) -> int | float:
        """Return the timeout for starting/stopping the service in seconds.

        Returns:
            The timeout for starting/stopping the service in seconds.
        """
        return self._timeout

    @timeout.setter
    def timeout(self, timeout: int | float) -> None:
        """Set the timeout.

        Args:
            timeout: Finite positive startup/shutdown budget in seconds.
        """
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not isfinite(timeout)
            or timeout <= 0
        ):
            raise errors.InvalidArgumentError(
                "Service timeout must be finite and positive"
            )
        else:
            self._timeout = timeout

    # Socket ------------------------------------------------------------------------------
    @property
    def port(self) -> int:
        """Return the socket port of the service.

        Returns:
            The socket port of the service.
        """
        if self._port == -1:
            self._port = self.get_free_port()
            self._port_str = str(self._port)
        return self._port

    @property
    def port_str(self) -> str:
        """Return the socket port of the service in string format.

        Returns:
            The socket port of the service in string format.
        """
        if self._port == -1:
            self.port
        assert self._port_str is not None
        return self._port_str

    @property
    def port_connectable(self) -> bool:
        """Return whether the socket port of the service is connectable.

        Returns:
            True if the socket port of the service is connectable; otherwise False.
        """
        if self._port == -1:
            return False
        else:
            return self._ping_port(self._port)

    @property
    def port_args(self) -> list[str]:
        """Return browser-specific arguments that select the service's reserved port.

        Returns:
            Chromium and Gecko use ["--port=PORT"]; Safari uses ["-p", "PORT"].

        Raises:
            NotImplementedError: The base service has no browser-specific port syntax.
        """
        raise NotImplementedError(
            "<{}>\nAttribute 'port_args' must be implemented in the subclass.".format(
                self.__class__.__name__
            )
        )

    def get_free_port(self) -> int:
        """Acquire a free socket port for the service.

        Availability is advisory: another process can bind before the driver.

        Returns:
            An available local TCP port selected for this service. The reservation
            is process-local and does not prevent another process binding it.
        """
        port = self._free_port()
        attempts = 0
        while self._ping_port(port) or port in self.__PORTS:
            attempts += 1
            if attempts >= 100:
                raise errors.ServiceSocketError(
                    "Unable to allocate a free service port"
                )
            port = self._free_port()
        self.__PORTS.add(port)
        return port

    def _free_port(self) -> int:
        """Acquire a free socket port.

        Returns:
            Acquire a free socket port.
        """
        try:
            with socket(AF_INET, SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                sock.listen(5)
                return sock.getsockname()[1]
        except Exception as err:
            raise errors.ServiceSocketError(
                "<{}>\nFailed to acquire a free socket port for the service: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    def _ping_port(self, port: int) -> bool:
        """Check if the socket port is in use.

        Args:
            port: TCP port number to probe on localhost.

        Returns:
            True if the socket port is in use; otherwise False.
        """
        sock = None
        try:
            sock = create_connection(("localhost", port), 1)
            return True
        except Exception:
            return False
        finally:
            if sock is not None:
                sock.close()
            del sock

    def _remove_port(self, port: int) -> None:
        """Remove the socket port from the service.

        Args:
            port: Reserved TCP port number to release.
        """
        try:
            self.__PORTS.remove(port)
        except KeyError:
            pass

    def _reset_port(self) -> None:
        """Reset the socket port of the service."""
        self._remove_port(self._port)
        self._port = -1
        self._port_str = None
        self._url = None

    # Process -----------------------------------------------------------------------------
    @property
    def process(self) -> Process | None:
        """Return the process of the service.

        Returns:
            The owned process identity, or None before startup and after teardown.
        """
        return self._process

    @property
    def process_running(self) -> bool:
        """Return whether the service process is running.

        Returns:
            True if the service process is running; otherwise False.
        """
        process = self._process
        if process is None:
            return False
        try:
            return process.is_running()
        except Exception:
            return False

    def _start_process(self) -> None:
        """Start the process of the service."""
        # Already started
        if self._process is not None:
            return None

        # Start process
        try:
            options: dict[str, Any] = dict(
                stdin=DEVNULL,
                stdout=DEVNULL,
                stderr=DEVNULL,
                close_fds=self._close_fds,
                env=dict(environ),
                creationflags=self._creation_flags,
            )
            options.update(self._kwargs)
            if options.get("shell"):
                raise errors.ServiceProcessError("Service commands cannot use a shell")
            command: list[str | bytes | PathLike[str] | PathLike[bytes]] = [
                self._driver_location,
                *self.port_args,
            ]
            for argument in self._args:
                if not isinstance(argument, (str, bytes, PathLike)):
                    raise errors.ServiceProcessError(
                        "Service command arguments must be text, bytes, or path-like"
                    )
                command.append(argument)
            process: Popen[bytes] = Popen(command, **options)
            self._popen = process
            self._process = Process(process.pid)
        except OSError as err:
            if err.errno == ENOENT:
                raise errors.ServiceProcessError(
                    "<{}>\nService WebDriver executable not "
                    "found at: '{}'\nError: {}".format(
                        self.__class__.__name__, self._driver_location, err
                    )
                ) from err
            elif err.errno == EACCES:
                raise errors.ServiceProcessError(
                    "<{}>\nService WebDriver executable may not have the "
                    "correct permissions: '{}'\nError: {}".format(
                        self.__class__.__name__, self._driver_location, err
                    )
                ) from err
            else:
                raise errors.ServiceProcessError(
                    "<{}>\nFailed to start service process: {}".format(
                        self.__class__.__name__, err
                    )
                ) from err
        except Exception as err:
            raise errors.ServiceProcessError(
                "<{}>\nFailed to start service process: {}".format(
                    self.__class__.__name__, err
                )
            ) from err

    def _capture_owned_children(self) -> None:
        """Retain descendant identities reachable from this service's owned roots.

        Keep the original psutil handles, whose liveness, traversal, and signal
        operations detect PID reuse using creation times. A previously captured
        browser can reveal new renderers even after its driver has disappeared.
        Descendants covered by a live ancestor are not scanned a second time.

        Raises:
            ServiceProcessError: If descendants cannot be inspected safely. Existing
                ownership is retained so the operation can be retried.
        """
        roots = [self._process, *self._owned_children]
        covered: list[Process] = []
        try:
            for root in roots:
                if root is None or root in covered:
                    continue
                try:
                    if not root.is_running():
                        continue
                    children = root.children(recursive=True)
                except NoSuchProcess:
                    continue
                covered.extend(children)
                for child in children:
                    if child not in self._owned_children:
                        self._owned_children.append(child)
        except Exception as cause:
            raise errors.ServiceProcessError(
                "Service-owned descendants could not be inspected; ownership retained"
            ) from cause

    async def _capture_session_children(self) -> None:
        """Capture newly launched browser identities without blocking the event loop.

        Serialize with service teardown and drain an in-flight process query before
        propagating cancellation. Session creation invokes this once per handshake;
        normal browser commands do not incur process-tree scans.

        Raises:
            ServiceProcessError: If ownership cannot be captured safely.
        """
        async with self._lifecycle_lock:
            await run_blocking(self._capture_owned_children)

    def _stop_process(self) -> None:
        """Terminate owned descendants and driver, retaining identities on failure.

        Refresh known browser roots before signalling any process, including when
        their original driver has exited. Exited or reused identities are never
        traversed, signalled, or waited on through their old psutil handles.

        Raises:
            ServiceProcessError: If inspection, termination, or reaping fails. The
                remaining owned process handles are retained for a cleanup retry.
        """
        deadline = unix_time() + self._timeout
        process = self._process
        try:
            self._capture_owned_children()
            children = list(self._owned_children)
            for child in children:
                try:
                    if child.is_running():
                        child.terminate()
                except NoSuchProcess:
                    pass
            if process is not None:
                try:
                    if process.is_running():
                        process.terminate()
                        process.wait(timeout=max(0.01, (deadline - unix_time()) / 2))
                except NoSuchProcess:
                    pass
                except Exception:
                    try:
                        if process.is_running():
                            process.kill()
                            process.wait(timeout=max(0.01, deadline - unix_time()))
                    except NoSuchProcess:
                        pass
            elif self._popen is not None:
                # The driver may have launched before psutil identity capture
                # failed. The original Popen still owns that direct child.
                self._popen.terminate()
                try:
                    self._popen.wait(timeout=max(0.01, (deadline - unix_time()) / 2))
                except TimeoutExpired:
                    self._popen.kill()
            for child in children:
                try:
                    if child.is_running():
                        child.kill()
                        child.wait(timeout=max(0.01, deadline - unix_time()))
                except NoSuchProcess:
                    pass
                self._owned_children.remove(child)
            if self._popen is not None:
                self._popen.wait(timeout=max(0.01, deadline - unix_time()))
                self._popen = None
            self._process = None
        except Exception as cause:
            raise errors.ServiceProcessError(
                "Owned service process could not be stopped; ownership retained"
            ) from cause

    # Session -----------------------------------------------------------------------------
    @property
    def session(self) -> ClientSession | None:
        """Return the http session of the service.

        Returns:
            The owned HTTP client, or None before startup and after teardown.
        """
        return self._session

    @property
    def session_connectable(self) -> bool:
        """Return whether the service http session is connectable.

        Returns:
            True if the service http session is connectable; otherwise False.
        """
        session = self._session
        if session is None:
            return False
        try:
            return not session.closed
        except Exception:
            return False

    def _start_session(self) -> None:
        """Start the session of the service."""
        # Already started
        if self._session is not None:
            return None

        # Start session
        self._session = ClientSession(base_url=self.url)

    async def _stop_session(self) -> None:
        """Close the service-owned HTTP client session."""
        if self._session is None:
            return
        # Local process teardown follows. A failed HTTP shutdown is not a
        # reason to leave the client open or resend mutating commands.
        try:
            await self._shutdown_remote()
        except Exception:
            pass
        await self._session.close()
        self._session = None

    async def _shutdown_remote(self) -> None:
        """Request driver shutdown before local process cleanup."""
        session = self._session
        if session is None:
            return
        async with session.post("/shutdown", timeout=1):
            pass

    # Service -----------------------------------------------------------------------------
    @property
    def url(self) -> str:
        """Return the base url of the Service.

        Returns:
            The base url of the service.
        """
        if self._url is None:
            self._url = "http://localhost:" + self.port_str
        return self._url

    @property
    def running(self) -> bool:
        """Return whether the service is running.

        Returns:
            True if the service is running; otherwise False.
        """
        return (
            self.process_running and self.port_connectable and self.session_connectable
        )

    async def start(self) -> None:
        """Start the driver process and wait for its HTTP service to become ready."""
        async with self._lifecycle_lock:
            if (
                self._process is not None
                and self.process_running
                and self.session_connectable
            ):
                return
            try:
                if (
                    self._process is not None
                    or self._popen is not None
                    or self._session is not None
                ):
                    await self._stop_owned()
                await run_blocking(self._start_process)
                self._start_session()
                session = self._session
                assert session is not None
                deadline = unix_time() + self._timeout
                while unix_time() < deadline:
                    if not self.process_running:
                        raise errors.ServiceProcessError(
                            "Service exited during startup"
                        )
                    try:
                        async with session.get(
                            "/status", timeout=min(1, max(0.01, deadline - unix_time()))
                        ) as response:
                            if response.status == 200:
                                payload = await response.json()
                                if (
                                    isinstance(payload, dict)
                                    and isinstance(payload.get("value"), dict)
                                    and payload["value"].get("ready") is True
                                ):
                                    return
                    except (ClientError, TimeoutError, ValueError):
                        pass
                    await sleep(min(0.1, max(0, deadline - unix_time())))
                raise errors.ServiceStartError(
                    "Service did not report ready before startup deadline"
                )
            except BaseException:
                try:
                    await finish_owned(self._stop_owned())
                except BaseException:
                    pass
                raise

    async def _stop_owned(self) -> None:
        """Finish teardown of the service-owned processes and HTTP session."""
        # Never ask the driver to exit until every currently reachable descendant
        # has been retained. A remote shutdown can otherwise detach late browser
        # helpers before local process cleanup has a chance to discover them.
        await run_blocking(self._capture_owned_children)
        try:
            await self._stop_session()
        finally:
            await run_blocking(self._stop_process)
        self._reset_port()

    async def stop(self) -> None:
        """Stop the driver and await all service-owned cleanup work."""

        async def close() -> None:
            """Finish cleanup owned by the enclosing operation."""
            async with self._lifecycle_lock:
                await self._stop_owned()

        await finish_owned(close())

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return cached service state without opening sockets or reserving a port.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (url=%r)>" % (self.__class__.__name__, self._url)

    def __hash__(self) -> int:
        """Return a stable identity hash for this mutable process owner.

        Returns:
            The service object's identity.
        """
        return id(self)

    def __eq__(self, __o: object) -> bool:
        """Return whether another reference is this exact service owner.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` only for this same object.
        """
        return self is __o

    def __del__(self) -> None:
        """Release references during finalization; explicit cleanup remains preferred."""
        try:
            if getattr(self, "_port", -1) != -1:
                self._reset_port()
        except AttributeError:
            pass  # Partially constructed service; no process was started.


# Chromium Base Service ---------------------------------------------------------------------------
class ChromiumBaseService(BaseService):
    """Manage a Chromium-family WebDriver service process."""

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> ChromiumVersion:
        """Return the version of the WebDriver executable.

        Returns:
            The version of the WebDriver executable.
        """
        return cast("ChromiumVersion", self._driver_version)

    # Socket ------------------------------------------------------------------------------
    @property
    def port_args(self) -> list[str]:
        """Return the part arguments for the service Process constructor.

        Returns:
            `["--port=" + self.port_str]`
        """
        return ["--port=" + self.port_str]

    # Session -----------------------------------------------------------------------------
    async def _shutdown_remote(self) -> None:
        """Shutdown the remote connection of the session."""
        # Shutdown remote
        await super()._shutdown_remote()

        # The owned process is reaped by _stop_process; do not poll a port that
        # could already have been reused by an unrelated process.
