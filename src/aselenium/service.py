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
from os import environ
from platform import system
from errno import ENOENT, EACCES
from time import time as unix_time
from asyncio.subprocess import Process, PIPE, DEVNULL
from asyncio.subprocess import create_subprocess_exec
from asyncio import wait_for, sleep, TimeoutError, CancelledError
from socket import socket, AF_INET, SOCK_STREAM, create_connection
from aiohttp import ClientSession, ClientConnectorError
from aselenium import errors
from aselenium.utils import is_file_exists

__all__ = ["BaseService", "ChromiumBaseService"]

# Base Service ------------------------------------------------------------------------------------
class BaseService:
    """The base class for the webdriver service.

    Service launch a subprocess as the interim process
    to communicate with the browser.
    """

    __PORTS: set[int] = set()

    def __init__(
        self,
        executable: str | None = None,
        timeout: int | float = 10,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """The webdriver service.

        Service launch a subprocess as the interim process
        to communicate with the browser.

        :param executable: `<str>` The location for the webdriver executable. Defaults to `None`.
        :param timeout: `<int/float>` Timeout in seconds for starting/stopping the service. Defaults to `10`.
        :param args: `<Any>` Additional arguments for `subprocess.Popen` constructor.
        :param kwargs: `<Any>` Additional keyword arguments for `subprocess.Popen` constructor.
        """
        # Executable
        self.executable = executable
        # Timeout
        self.timeout = timeout
        # Process
        self._args: tuple[Any] = args
        self._kwargs: dict[str, Any] = kwargs
        self._creation_flags: int = self._kwargs.pop("creation_flags", 0)
        self._close_fds: bool = self._kwargs.pop("close_fds", system() != "Windows")
        self._port: int = -1
        self._env: Any = environ
        self._process: Process | None = None
        # Session
        self._session: ClientSession | None = None
        # Service
        self._url: str | None = None

    # Executable --------------------------------------------------------------------------
    @property
    def executable(self) -> str:
        """Access the location for the webdriver executable `<str>`."""
        return self._executable

    @executable.setter
    def executable(self, executable: str | None) -> None:
        # Reset executable
        if executable is None:
            self._executable = None
            return None  # exit

        # Set executable
        if not is_file_exists(executable):
            raise errors.ServiceExecutableNotFoundError(
                "`<{}>`\nService (webdriver) executable not found at: {}".format(
                    self.__class__.__name__, repr(executable)
                )
            )
        self._executable = executable

    # Timeout -----------------------------------------------------------------------------
    @property
    def timeout(self) -> int | float:
        """Access the timeout for starting/stopping the service
        in seconds `<int/float>`.
        """
        return self._timeout

    @timeout.setter
    def timeout(self, timeout: int | float) -> None:
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            self._timeout = 10
        else:
            self._timeout = timeout

    # Socket ------------------------------------------------------------------------------
    @property
    def port(self) -> int:
        """Access the socket port of the service `<int>`."""
        if self._port == -1:
            port = self._free_port()
            while self._ping_port(port) or port in self.__PORTS:
                port = self._free_port()
            self.__PORTS.add(port)
            self._port = port
        return self._port

    @property
    def port_connectable(self) -> bool:
        """Access whether the socket port of the service
        is connectable `<bool>`.
        """
        if self._port == -1:
            return False
        else:
            return self._ping_port(self._port)

    def _free_port(self) -> int:
        """(Internal) Acquire a free socket port for the service."""
        sock = None
        try:
            sock = socket(AF_INET, SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sock.listen(5)
            return sock.getsockname()[1]
        except Exception as err:
            raise errors.ServiceSocketOSError(
                "<{}>\nFailed to acquire a free socket port for "
                "the service: {}".format(self.__class__.__name__, err)
            ) from err
        finally:
            if sock is not None:
                sock.close()
            del sock

    def _ping_port(self, port: int) -> bool:
        """(Internal) Check if the socket port is in used `<bool>`."""
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

    def _reset_port(self) -> None:
        """(Internal) Reset the socket port of the service."""
        try:
            self.__PORTS.remove(self._port)
        except KeyError:
            pass
        self._port = -1
        self._url = None

    # Process -----------------------------------------------------------------------------
    @property
    def process(self) -> Process:
        """Access the process of the service `<Process>`."""
        return self._process

    @property
    def process_running(self) -> bool:
        """Access whether the service process is running `<bool>`."""
        try:
            return self._process.returncode is None
        except Exception:
            return False

    async def _start_process(self) -> None:
        """(Internal) Start the process of the service."""
        try:
            process = await wait_for(
                create_subprocess_exec(
                    self._executable,
                    "--port=%d" % self.port,
                    env=self._env,
                    close_fds=self._close_fds,
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                    stdin=PIPE,
                    creationflags=self._creation_flags,
                    **self._kwargs,
                ),
                self._timeout,
            )
            self._process = process
        except TimeoutError:
            raise errors.ServiceProcessTimeoutError(
                "<{}>\nFailed to start process in time: {}s.".format(
                    self.__class__.__name__, self._timeout
                )
            )
        except OSError as err:
            if err.errno == ENOENT:
                raise errors.ServiceProcessOSError(
                    "<{}>\nService (webdriver) executable not found at: '{}'\n"
                    "Error: {}".format(self.__class__.__name__, self._executable, err)
                ) from err
            elif err.errno == EACCES:
                raise errors.ServiceProcessOSError(
                    "<{}>\nService (webdriver) executable may not have the correct permissions: '{}'\n"
                    "Error: {}".format(self.__class__.__name__, self._executable, err)
                ) from err
            else:
                raise errors.ServiceProcessOSError(
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

    async def _stop_process(self) -> None:
        """(Internal) Stop the process of the service."""

        # . Kill (SIGKILL) the process
        async def kill() -> None:
            # Force kill (SIGKILL)
            try:
                self._process.kill()
            # Process stopped
            except ProcessLookupError:
                return None  # exit
            # Failed to kill
            except Exception as err:
                raise errors.ServiceProcessOSError(
                    f"\nFailed to kill service process '{self._process.pid}': {err}"
                ) from err
            # Verify killed
            try:
                await wait_for(self._process.wait(), self._timeout)
            except TimeoutError as err:
                raise errors.ServiceProcessOSError(
                    f"\nFailed to stop service process '{self._process.pid}'"
                ) from err

        # Already stopped
        if self._process is None:
            return None  # exit

        # Terminate (SIGTERM)
        try:
            for stream in (
                self._process.stdin,
                self._process.stdout,
                self._process.stderr,
            ):
                try:
                    stream.close()
                except AttributeError:
                    pass
            self._process.terminate()
        # Process stopped
        except ProcessLookupError:
            return None  # exit
        # Force kill (SIGKILL)
        except Exception:
            await kill()
        # Verify closed
        else:
            try:
                await wait_for(self._process.wait(), self._timeout)
            except TimeoutError:
                await kill()

        finally:
            self._process = None

    # Session -----------------------------------------------------------------------------
    @property
    def session(self) -> ClientSession:
        """Access the http session of the service `<ClientSession>."""
        return self._session

    @property
    def session_connectable(self) -> bool:
        """Access whether the service http session is connectable `<bool>`."""
        try:
            return not self._session.closed
        except Exception:
            return False

    async def _start_session(self) -> None:
        """(Internal) Start the session of the service."""
        self._session = ClientSession(base_url=self.url)

    async def _stop_session(self) -> None:
        """(Internal) Stop the session of the service."""

        async def shutdown_remote() -> None:
            while True:
                try:
                    await self._session.post("/shutdown")
                    break
                except CancelledError:
                    continue
                except ClientConnectorError:
                    return None

            # Verify shutdown
            if not self.port_connectable:
                return None  # exit

            # Wait for shutdown
            start_time = unix_time()
            while (unix_time() - start_time) < self._timeout:
                if not self.port_connectable:
                    return None  # exit
                await sleep(0.2)

        # Already stopped
        if self._session is None:
            return None  # exit

        try:
            exceptions = []
            # Shutdown remote
            try:
                await shutdown_remote()
            except Exception as err:
                exceptions.append(str(err))

            # Close session
            try:
                await self._session.close()
            except Exception as err:
                exceptions.append(str(err))

            # Raise errors
            if exceptions:
                raise errors.SessionShutdownError("\n".join(exceptions))

        finally:
            self._session = None

    # Service -----------------------------------------------------------------------------
    @property
    def url(self) -> str:
        """Access the base url of the Service `<str>`."""
        if self._url is None:
            self._url = "http://localhost:%d" % self.port
        return self._url

    @property
    def started(self) -> bool:
        """Access whether the service is started `<bool>`."""
        return self.process_running and self.port_connectable and self.session_connectable

    async def start(self) -> None:
        """Start the Service."""
        try:
            # Start Process & Session
            await self._start_process()
            await self._start_session()

            # Verify Connection
            start_time = unix_time()
            while (unix_time() - start_time) < self._timeout:
                if not self.process_running:
                    raise errors.ServiceProcessError(
                        "<{}>\nService exited unexpectedly: {}".format(
                            self.__class__.__name__,
                            self._process.returncode if self._process else 0,
                        )
                    )
                if self.port_connectable and self.session_connectable:
                    return None
                await sleep(0.2)

            raise errors.ServiceStartError(
                "<{}>\nFailed to start Service: socket connection - {} | "
                "client connection - {}.".format(
                    self.__class__.__name__,
                    self.port_connectable,
                    self.session_connectable,
                )
            )

        except Exception as err:
            try:
                await self.stop()
            except Exception:
                pass
            raise err

    async def stop(self) -> None:
        """Stop the Service."""
        try:
            exceptions = []
            # Stop session
            try:
                await self._stop_session()
            except Exception as err:
                exceptions.append(str(err))

            # Stop process
            try:
                await self._stop_process()
            except Exception as err:
                exceptions.append(str(err))

            # Raise error
            if exceptions:
                raise errors.ServiceStopError("\n".join(exceptions))

        finally:
            self._reset_port()

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (url='%s')>" % (self.__class__.__name__, self.url)

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, self.__class__) else False

    def __del__(self):
        self._reset_port()


# Chromium Base Service ---------------------------------------------------------------------------
class ChromiumBaseService(BaseService):
    """The base class for the chromium based webdriver service."""
