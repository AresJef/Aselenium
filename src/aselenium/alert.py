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
"""Aselenium alert implementation and supporting types."""

from __future__ import annotations

from asyncio import sleep
from typing import (
    TYPE_CHECKING,
    Any,
)

from aselenium import errors
from aselenium.command import Command

if TYPE_CHECKING:
    from aselenium.session import Session

__all__ = ["Alert"]


# Alert -------------------------------------------------------------------------------------------
class Alert:
    """Represent a JavaScript alert."""

    def __init__(self, session: Session) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            session: The session the alert raises.
        """
        self._session: Session = session

    # Properties --------------------------------------------------------------------------
    @property
    async def text(self) -> str | None:
        """Return the text of the alert.

        Returns:
            The text of the alert.
        """
        try:
            res = await self._session.execute_command(Command.W3C_GET_ALERT_TEXT)
        except errors.InvalidMethodError:
            return None
        try:
            return res["value"]
        except KeyError as err:
            raise errors.InvalidResponseError(
                "<{}>\nFailed to get the text message from alert: {}".format(
                    self.__class__.__name__, res
                )
            ) from err

    # Control ------------------------------------------------------------------------------
    async def dismiss(self, pause: int | float | None = None) -> None:
        """Dismiss the alert.

        Args:
            pause: The pause in seconds after execution. Defaults to `None`.
                This can be useful to wait for the command to take effect,
                before executing the next command. Defaults to `None` - no pause.
        """
        await self._session.execute_command(Command.W3C_DISMISS_ALERT)
        await self.pause(pause)

    async def accept(self, pause: int | float | None = None) -> None:
        """Accept the alert.

        Args:
            pause: The pause in seconds after execution. Defaults to `None`.
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
        """Send text to the currently open JavaScript prompt.

        This command supplies prompt text; it is not a keyboard action sequence.
        Accept or dismiss the prompt separately after supplying its value.

        Args:
            *values: Values converted to strings and joined into the prompt text.
            sep: Separator between values; defaults to one space.
            pause: Optional delay in seconds after the command completes.

        Example:
            >>> await alert.send("Hello", "world!")
            >>> await alert.accept()
        """
        # Validate
        try:
            text_values = [str(value) for value in values]
        except ValueError as err:
            raise errors.InvalidArgumentError(
                "<{}>\nInvalid 'values' to send to alert: {}".format(
                    self.__class__.__name__,
                    ["%s %s" % (type(i), i) for i in values],
                )
            ) from err
        # Sent values
        await self._session.execute_command(
            Command.W3C_SET_ALERT_VALUE,
            body={"text": sep.join(text_values), "value": text_values},
        )
        # Pause
        await self.pause(pause)

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

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Return a diagnostic representation of this instance.

        Returns:
            A diagnostic representation of this instance.
        """
        return "<%s (session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._session._id,
            self._session._service.url,
        )

    def __hash__(self) -> int:
        """Return the hash used by sets and dictionary keys.

        Returns:
            The hash used by sets and dictionary keys.
        """
        return hash((self.__class__.__name__, hash(self._session)))

    def __eq__(self, __o: Any) -> bool:
        """Return whether this instance compares equal to another object.

        Args:
            __o: Object to compare with this instance.

        Returns:
            True if this instance compares equal to another object; otherwise False.
        """
        return hash(self) == hash(__o) if isinstance(__o, Alert) else False
