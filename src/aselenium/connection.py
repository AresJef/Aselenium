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
from string import Template
from platform import system
from orjson import dumps, loads
from aiohttp import ClientSession, ClientError, ClientTimeout
from aselenium import errors
from aselenium.logs import logger
from aselenium.command import COMMANDS
from aselenium.errors import ErrorCode, webdriver_error_handler

__all__ = ["Connection"]


# Constants ---------------------------------------------------------------------------------------
HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "User-Agent": f"aselenium (python {system()})",
}


# Connection --------------------------------------------------------------------------------------
class Connection:
    """Represents a connection to a remote server (Browser driver)."""

    def __init__(self, session: ClientSession, session_timeout: int | float) -> None:
        """The connection to a remote server (Browser driver).

        :param session: `<ClientSession>` The async session of the connection.
        """
        self._session: ClientSession = session
        self._session_timeout: int | float = session_timeout

    # Execution ---------------------------------------------------------------------------
    async def execute(
        self,
        base_url: str,
        command: str,
        body: dict | None = None,
        keys: dict | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Execute a command.

        :param base_url: `<str>` The base url of the command.
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
        # Map command
        method, cmd = self.map_command(command)

        # Substitute keywords
        if "$" in cmd:
            try:
                cmd = Template(cmd).substitute(keys)
            except Exception as err:
                raise errors.InvalidArgumentError(
                    "<{}>\nCommand keyword substitution failed for: {}\n"
                    "Error: {}".format(self.__class__.__name__, repr(cmd), err)
                ) from err

        # Execute command
        res = await self._request(method, base_url + cmd, body, timeout)
        webdriver_error_handler(res)

        # Return response
        return res

    async def _request(
        self,
        method: str,
        url: str,
        body: dict | None,
        timeout: int | float | None,
    ) -> dict[str, Any]:
        "(Internal) Send a request to the remote server (Browser driver)."
        # Adjust timeout
        timeout = timeout or self._session_timeout
        # Request
        logger.debug("Request: %s %s %s", method, url, body)
        try:
            async with self._session.request(
                # fmt: off
                method, url, headers=HEADERS, proxy=None,
                data=dumps(body) if body else None,
                timeout=ClientTimeout(total=timeout),
                # fmt: on
            ) as res:
                # . request data
                data = await res.read()

                # . code: 300 - 304
                if 300 <= res.status < 304:
                    return await self._request(
                        "GET", res.headers.get("location"), None, timeout
                    )

                # . decode data
                try:
                    data = data.decode("utf-8")
                except UnicodeDecodeError as err:
                    raise errors.SessionDataError(
                        "<{}>\nFailed to decode data from: {} {} {}\n"
                        "Response: {}\nError: {}".format(
                            self.__class__.__name__, method, url, body, repr(data), err
                        )
                    ) from err

                # . code: 399 - 500
                if 399 < res.status <= 500:
                    return {"status": res.status, "value": data}

                # . code: all the rest
                content_type = res.headers.get("Content-Type", None)

                # . image/png request
                if content_type is not None and any(
                    x.startswith("image/png") for x in content_type.split(";")
                ):
                    return {"status": 0, "value": data}
                # . successful request
                try:
                    data = loads(data.strip())
                    if "value" not in data:
                        data["value"] = None
                    return data
                # . failed request
                except ValueError:
                    if 199 < res.status < 300:
                        status = ErrorCode.SUCCESS
                    else:
                        status = ErrorCode.UNKNOWN_ERROR
                    return {"status": status, "value": data.strip()}

        except errors.AseleniumError:
            raise
        except errors.TimeoutError as err:
            raise errors.SessionTimeoutError(
                "<{}>\nSession timeout is reached for: {} {} {}\n"
                "Error: A force timeout of the command has been reached, "
                "and the browser failed to response in time: {}s.".format(
                    self.__class__.__name__, method, url, body, timeout
                )
            ) from err
        except ClientError as err:
            raise errors.SessionClientError(
                "<{}>\nSession request failed at: {} {} {}\n"
                "Error: {}".format(self.__class__.__name__, method, url, body, err)
            ) from err
        except Exception as err:
            raise errors.SessionError(
                "<{}>\nUnknown session failure at: {} {} {}\n"
                "Error: {}".format(self.__class__.__name__, method, url, body, err)
            ) from err

    # Utils -------------------------------------------------------------------------------
    def map_command(self, command: str) -> tuple[str, str]:
        """Map a command to its method and commond value.

        :param command: `<str>` The command to map.
        :return: `<tuple>` The method and commond value of the command.
        """
        try:
            return COMMANDS[command]
        except KeyError as err:
            raise errors.InvalidArgumentError(
                "<{}>\nUnrecognised session command: {}".format(
                    self.__class__.__name__, command
                )
            ) from err

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (client_session=%s)>" % (self.__class__.__name__, self._session)

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, __o: object) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, Connection) else False

    def __del__(self):
        self._session = None
