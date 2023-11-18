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
from asyncio import sleep
from typing import Any, TYPE_CHECKING
from aselenium import errors
from aselenium.command import Command

if TYPE_CHECKING:
    from aselenium.session import Session

__all__ = ["Alert"]


# Alert -------------------------------------------------------------------------------------------
class Alert:
    """Represents a JavaScript alert."""

    def __init__(self, session: Session) -> None:
        """The JavaScript alert.

        :param session: `<Session>` The session the alert raises.
        """
        self._session: Session = session

    # Properties --------------------------------------------------------------------------
    @property
    async def text(self) -> str:
        """Access the text of the alert `<str>`."""
        res = await self._session.execute_command(Command.W3C_GET_ALERT_TEXT)
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get the text message from alert: "
                "{}".format(self.__class__.__name__, res)
            ) from err

    # Control ------------------------------------------------------------------------------
    async def dismiss(self, pause: int | float | None = None) -> None:
        """Dismiss the alert.

        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.
        """
        await self._session.execute_command(Command.W3C_DISMISS_ALERT)
        await self.pause(pause)

    async def accept(self, pause: int | float | None = None) -> None:
        """Accept the alert.

        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.
        """
        await self._session.execute_command(Command.W3C_ACCEPT_ALERT)
        await self.pause(pause)

    async def send(
        self,
        *values: str,
        sep: str = " ",
        pause: int | float | None = None,
    ) -> None:
        """Simulate typing or keyboard keys pressing into the alert.

        :param values: `<str>` strings to be typed or keyboard keys to be pressed.
        :param sep: `<str>` The separator between each values. Defaults to `' '`.
        :param pause: `<int/float/None>` The pause in seconds after execution. Defaults to `None`.
            This can be useful to wait for the command to take effect,
            before executing the next command. Defaults to `None` - no pause.

        ### Example:
        >>> await alert.send("Hello", "world!")
        ### -> "Hello world!"
        """
        # Validate
        try:
            values = map(str, values)
        except ValueError as err:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'values' to send to alert: {}".format(
                    self.__class__.__name__,
                    ["%s %s" % (type(i), i) for i in values],
                )
            ) from err
        values = list(values)
        # Sent values
        await self._session.execute_command(
            Command.W3C_SET_ALERT_VALUE,
            body={"text": sep.join(values), "value": values},
        )
        # Pause
        await self.pause(pause)

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

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return "<%s (session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._session._id,
            self._session._service.url,
        )

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, hash(self._session)))

    def __eq__(self, __o: Any) -> bool:
        return hash(self) == hash(__o) if isinstance(__o, Alert) else False

    def __del__(self):
        self._session = None
