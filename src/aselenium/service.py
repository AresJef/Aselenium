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
from psutil import Process as psutil_Process
from aiohttp import ClientSession, ClientConnectorError
from aselenium import errors
from aselenium.utils import validate_file
from aselenium.manager.version import Version, ChromiumVersion


# Base Service ------------------------------------------------------------------------------------
class BaseService:
    """The base class for the webdriver service.

    Service launch a subprocess as the interim process
    to communicate with the browser.
    """

    __PORTS: set[int] = set()

    def __init__(
        self,
        driver_version: Version,
        driver_location: str,
        timeout: int | float = 10,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """The webdriver service.

        Service launch a subprocess as the interim process to communicate with the browser.

        :param driver_version: `<Version>` The version of the webdriver executable.
        :param driver_location: `<str>` The path to the webdriver executable.
        :param timeout: `<int/float>` Timeout in seconds for starting/stopping the service. Defaults to `10`.
        :param args: `<Any>` Additional arguments for `subprocess.Popen` constructor.
        :param kwargs: `<Any>` Additional keyword arguments for `subprocess.Popen` constructor.
        """
        # Driver
        try:
            self._driver_location = validate_file(driver_location)
        except Exception as err:
            raise errors.ServiceExecutableNotFoundError(
                "`<{}>`\nService webdriver executable not found at: {}".format(
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
        self._port_str: str = None
        self._env: Any = environ
        self._process: Process | None = None
        # Session
        self._session: ClientSession | None = None
        # Service
        self._url: str | None = None

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> Version:
        """Access the version of the webdriver executable `<Version>`."""
        return self._driver_version

    @property
    def driver_location(self) -> str:
        """Access the location for the webdriver executable `<str>`."""
        return self._driver_location

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
            self._port = self.get_free_port()
            self._port_str = str(self._port)
        return self._port

    @property
    def port_str(self) -> str:
        """Access the socket port of the service in string format `<str>`."""
        if self._port == -1:
            self.port
        return self._port_str

    @property
    def port_connectable(self) -> bool:
        """Access whether the socket port of the service
        is connectable `<bool>`.
        """
        if self._port == -1:
            return False
        else:
            return self._ping_port(self._port)

    @property
    def port_args(self) -> list[str]:
        """Access the part arguments for the service Process constructor.
        This must be implemented in the subclass.

        Returns:
        - `["--port=" + self.port_str]` for the Chromium & Gecko based webdriver.
        - `["-p", self.port_str]` for Safari webdriver.
        """
        raise NotImplementedError(
            "<{}>\nAttribute 'port_args' must be implemented in the "
            "subclass.".format(self.__class__.__name__)
        )

    def get_free_port(self) -> int:
        """Acquire a free socket port for the service `<int>`.

        This port is garanteed to be available and conflicts
        free from other service instances.
        """
        port = self._free_port()
        while self._ping_port(port) or port in self.__PORTS:
            port = self._free_port()
        self.__PORTS.add(port)
        return port

    def _free_port(self) -> int:
        """(Internal) Acquire a free socket port `<int>`."""
        sock = None
        try:
            sock = socket(AF_INET, SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sock.listen(5)
            return sock.getsockname()[1]
        except Exception as err:
            raise errors.ServiceSocketError(
                "<{}>\nFailed to acquire a free socket port for "
                "the service: {}".format(self.__class__.__name__, err)
            ) from err
        finally:
            if sock is not None:
                sock.close()
            del sock

    def _ping_port(self, port: int) -> bool:
        """(Internal) Check if the socket port is in use `<bool>`."""
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
        """(Internal) Remove the socket port from the service."""
        try:
            self.__PORTS.remove(port)
        except KeyError:
            pass

    def _reset_port(self) -> None:
        """(Internal) Reset the socket port of the service."""
        self._remove_port(self._port)
        self._port = -1
        self._port_str = None
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
                    self._driver_location,
                    *self.port_args,
                    *self._args,
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
            raise errors.ServiceTimeoutError(
                "<{}>\nFailed to start process in time: {}s.".format(
                    self.__class__.__name__, self._timeout
                )
            )
        except OSError as err:
            if err.errno == ENOENT:
                raise errors.ServiceProcessError(
                    "<{}>\nService webdriver executable not "
                    "found at: '{}'\nError: {}".format(
                        self.__class__.__name__, self._driver_location, err
                    )
                ) from err
            elif err.errno == EACCES:
                raise errors.ServiceProcessError(
                    "<{}>\nService webdriver executable may not have the "
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

    async def _stop_process(self) -> None:
        """(Internal) Stop the process of the service."""

        # . Kill unclosed child processes
        def kill_unclosed_child_processes() -> None:
            try:
                driver_process = psutil_Process(self._process.pid)
            except Exception:
                return None
            for child in driver_process.children(recursive=False):
                try:
                    child.kill()
                except Exception:
                    pass

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
                raise errors.ServiceProcessError(
                    f"\nFailed to kill service process '{self._process.pid}': {err}"
                ) from err
            # Verify killed
            try:
                await wait_for(self._process.wait(), self._timeout)
            except TimeoutError as err:
                raise errors.ServiceProcessError(
                    f"\nFailed to stop service process '{self._process.pid}'"
                ) from err

        # Already stopped
        if self._process is None:
            return None  # exit

        # Kill unclosed child processes
        kill_unclosed_child_processes()

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
        # Already stopped
        if self._session is None:
            return None  # exit

        try:
            exceptions = []
            # . shutdown remote
            try:
                await self._shutdown_remote()
            except BaseException as err:
                exceptions.append(str(err))

            # . close session
            try:
                await self._session.close()
            except BaseException as err:
                exceptions.append(str(err))

            # . raise errors
            if exceptions:
                raise errors.SessionShutdownError("\n".join(exceptions))

        finally:
            self._session = None

    async def _shutdown_remote(self) -> None:
        """(Internal) Shutdown the remote connection of the session."""
        while True:
            try:
                await self._session.post("/shutdown", timeout=1)
                break
            except CancelledError:
                continue  # retry
            except ClientConnectorError:
                return None  # exit
            except TimeoutError:
                return None  # exit

    # Service -----------------------------------------------------------------------------
    @property
    def url(self) -> str:
        """Access the base url of the Service `<str>`."""
        if self._url is None:
            self._url = "http://localhost:" + self.port_str
        return self._url

    @property
    def running(self) -> bool:
        """Access whether the service is running `<bool>`."""
        return (
            self.process_running and self.port_connectable and self.session_connectable
        )

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
                        "<{}> Service exited unexpectedly: {}".format(
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
            except BaseException:
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

    # Driver ------------------------------------------------------------------------------
    @property
    def driver_version(self) -> ChromiumVersion:
        """Access the version of the webdriver executable `<ChromiumVersion>`."""
        return self._driver_version

    # Socket ------------------------------------------------------------------------------
    @property
    def port_args(self) -> list[str]:
        """Access the part arguments for the service Process constructor.

        :return `<list[str]>`: `["--port=" + self.port_str]`
        """
        return ["--port=" + self.port_str]

    # Session -----------------------------------------------------------------------------
    async def _shutdown_remote(self) -> None:
        """(Internal) Shutdown the remote connection of the session."""
        # Shutdown remote
        await super()._shutdown_remote()

        # Verify shutdown
        if not self.port_connectable:
            return None  # exit

        # Wait for shutdown
        start_time = unix_time()
        while (unix_time() - start_time) < self._timeout:
            if not self.port_connectable:
                return None  # exit
            await sleep(0.2)
