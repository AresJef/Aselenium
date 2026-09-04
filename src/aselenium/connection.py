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
"""Aselenium connection implementation and supporting types."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from math import isfinite
from platform import system
from string import Template
from time import monotonic
from typing import (
    Any,
)
from urllib.parse import quote, urljoin, urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout
from orjson import dumps, loads

from aselenium import errors
from aselenium._wait import DEADLINE
from aselenium.command import COMMANDS
from aselenium.errors import webdriver_error_handler
from aselenium.logs import logger

__all__ = ["Connection"]


# Constants ---------------------------------------------------------------------------------------
HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "User-Agent": f"aselenium (python {system()})",
}


# Connection --------------------------------------------------------------------------------------
class Connection:
    """Represent a connection to a remote server (Browser driver)."""

    def __init__(self, session: ClientSession, session_timeout: int | float) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            session: The async session of the connection.
            session_timeout: Session timeout used by this operation.
        """
        self._session: ClientSession = session
        self._session_timeout: int | float = session_timeout
        self._command_lock = asyncio.Lock()
        self._wire_lock = asyncio.Lock()
        self._owner: object | None = None
        self._ownership: ContextVar[object | None] = ContextVar(
            "aselenium_command_owner", default=None
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Serialize a command sequence, reentrant in its logical async context.

        Internal deadline and polling tasks inherit this ownership. User-created
        child tasks inherit it too: await dependent operations sequentially inside
        an explicit transaction instead of gathering them concurrently.

        Yields:
            The resource managed by this context; cleanup runs when the context exits.
        """
        if self._owner is not None and self._ownership.get() is self._owner:
            yield
            return
        async with self._command_lock:
            self._owner = object()
            token = self._ownership.set(self._owner)
            try:
                yield
            finally:
                self._ownership.reset(token)
                self._owner = None

    async def execute(
        self,
        base_url: str,
        command: str,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Serialize and execute one WebDriver command within its total deadline.

        Args:
            base_url: Driver URL prefix for the current session, element, or shadow root.
            command: Command identifier from aselenium.command.Command.
            body: JSON command parameters, or None when the command has no explicit payload.
            keys: Values substituted into the command URL template.
            timeout: Total time budget in seconds; None follows the documented no-wait/default behavior.

        Returns:
            The decoded W3C response envelope, including its value field.

        Example:
            >>> response = await connection.execute(
            ...     "http://127.0.0.1:9515/session/session-id", Command.GET_TITLE
            ... )
            >>> title = response["value"]
        """
        budget = self._session_timeout if timeout is None else timeout
        if (
            isinstance(budget, bool)
            or not isinstance(budget, (int, float))
            or not isfinite(budget)
            or budget <= 0
        ):
            raise errors.InvalidArgumentError(
                "Command timeout must be a finite positive number"
            )
        deadline = monotonic() + budget
        outer = DEADLINE.get()
        if outer is not None:
            deadline = min(deadline, outer)

        async def dispatch() -> dict[str, Any]:
            """Acquire command ownership and the wire lock before sending the request.

            Returns:
                The W3C response received while holding both ownership and wire locks.
            """
            async with self.transaction():
                async with self._wire_lock:
                    return await self._execute(base_url, command, body, keys, timeout)

        token = DEADLINE.set(deadline)
        try:
            # Include both command ownership and wire queueing in the budget.
            return await asyncio.wait_for(dispatch(), max(0, deadline - monotonic()))
        except errors.AseleniumError:
            # Native WebDriver timeouts also inherit TimeoutError; preserve their
            # protocol type instead of mistaking them for this command's deadline.
            raise
        except asyncio.TimeoutError as cause:
            raise errors.SessionTimeoutError(
                "WebDriver command deadline exceeded; outcome may be unknown"
            ) from cause
        finally:
            DEADLINE.reset(token)

    # Execution ---------------------------------------------------------------------------
    async def _execute(
        self,
        base_url: str,
        command: str,
        body: dict[str, Any] | None = None,
        keys: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        """Execute a command.

        Args:
            base_url: The base url of the command.
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
        # Map command
        method, cmd = self.map_command(command)
        if body is None and method == "POST":
            body = {}  # W3C commands without parameters still send a JSON object.

        # Substitute keywords
        if "$" in cmd:
            try:
                cmd = Template(cmd).substitute(
                    {
                        key: quote(str(value), safe="")
                        for key, value in (keys or {}).items()
                    }
                )
            except Exception as err:
                raise errors.InvalidArgumentError(
                    "<{}>\nCommand keyword substitution failed for: {}\n"
                    "Error: {}".format(self.__class__.__name__, repr(cmd), err)
                ) from err

        # Execute command
        res = await self._request(method, base_url + cmd, body, timeout)

        # Return response
        return res

    async def _request(
        self, method: str, url: str, body: dict[str, Any] | None, timeout: float | None
    ) -> dict[str, Any]:
        """One command, one deadline. Mutating commands are never replayed.

        Args:
            method: Method being wrapped or HTTP verb used for the request.
            url: URL used for the request or browser navigation.
            body: JSON command parameters, or None when the command has no explicit payload.
            timeout: Total time budget in seconds; None follows the documented no-wait/default behavior.

        Returns:
            Decoded response data for the requested transport operation.
        """
        timeout = self._session_timeout if timeout is None else timeout
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not isfinite(timeout)
            or timeout <= 0
        ):
            raise errors.InvalidArgumentError(
                "Command timeout must be a finite positive number"
            )
        deadline = monotonic() + timeout
        outer_deadline = DEADLINE.get()
        if outer_deadline is not None:
            deadline = min(deadline, outer_deadline)
        origin = urlsplit(url)[:2]
        logger.debug("WebDriver request: %s (payload and URL redacted)", method)
        try:
            for redirect in range(4):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                async with self._session.request(
                    method,
                    url,
                    headers=HEADERS,
                    proxy=None,
                    data=dumps(body) if body is not None else None,
                    timeout=ClientTimeout(total=remaining),
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status < 400:
                        target = urljoin(url, response.headers.get("Location", ""))
                        if (
                            method != "GET"
                            or redirect == 3
                            or urlsplit(target)[:2] != origin
                            or target == url
                        ):
                            raise errors.SessionDataError(
                                "Unsafe or excessive WebDriver redirect"
                            )
                        url = target
                        continue
                    data = await response.read()
                    if response.status == 204:
                        return {"value": None}
                    try:
                        decoded = loads(data)
                    except (ValueError, UnicodeError) as cause:
                        if response.status >= 400:
                            raise errors.SessionDataError(
                                "Non-JSON WebDriver error response"
                            ) from cause
                        raise errors.SessionDataError(
                            "Malformed JSON in WebDriver success response"
                        ) from cause
                    if not isinstance(decoded, dict):
                        raise errors.SessionDataError(
                            "WebDriver response must be an object"
                        )
                    if "value" not in decoded:
                        raise errors.SessionDataError(
                            "WebDriver success response has no value"
                        )
                    webdriver_error_handler(decoded, http_status=response.status)
                    return decoded
            raise errors.SessionDataError(
                "WebDriver redirect loop ended without a response"
            )
        except errors.AseleniumError:
            raise
        except (asyncio.TimeoutError, TimeoutError) as cause:
            raise errors.SessionTimeoutError(
                "WebDriver command deadline exceeded; outcome may be unknown"
            ) from cause
        except ClientError as cause:
            raise errors.SessionClientError(
                "WebDriver transport failed; command was not replayed"
            ) from cause

    # Utils -------------------------------------------------------------------------------
    def map_command(self, command: str) -> tuple[str, str]:
        """Map a command to its method and command value.

        Args:
            command: The command to map.

        Returns:
            The method and command value of the command.
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
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (client_session=%s)>" % (self.__class__.__name__, self._session)

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
        return hash(self) == hash(__o) if isinstance(__o, Connection) else False
