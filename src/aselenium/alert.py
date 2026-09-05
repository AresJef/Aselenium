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

"""JavaScript alert, confirm, and prompt commands for active sessions."""

from __future__ import annotations

from asyncio import sleep
from typing import (
    TYPE_CHECKING,
    Any,
)

from aselenium import errors
from aselenium._response import response_value
from aselenium._wait import validate_delay
from aselenium.command import Command

if TYPE_CHECKING:
    from aselenium.session import Session

__all__ = ["Alert"]


# Alert -------------------------------------------------------------------------------------------
class Alert:
    """Represent a JavaScript alert."""

    def __init__(self, session: Session) -> None:
        """Bind alert commands to an active browser session.

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
        return response_value(res, str, "Alert text")

    # Control ------------------------------------------------------------------------------
    async def dismiss(self, pause: int | float | None = None) -> None:
        """Dismiss the alert.

        Args:
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before dismissing the alert.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid, including a boolean.
        """
        validate_delay(pause)
        await self._session.execute_command(Command.W3C_DISMISS_ALERT)
        await self.pause(pause)

    async def accept(self, pause: int | float | None = None) -> None:
        """Accept the alert.

        Args:
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before accepting the alert.

        Raises:
            errors.InvalidArgumentError: ``pause`` is invalid, including a boolean.
        """
        validate_delay(pause)
        await self._session.execute_command(Command.W3C_ACCEPT_ALERT)
        await self.pause(pause)

    async def send(
        self,
        *values: object,
        sep: str = " ",
        pause: int | float | None = None,
    ) -> None:
        """Send text to the currently open JavaScript prompt.

        This command supplies prompt text; it is not a keyboard action sequence.
        Accept or dismiss the prompt separately after supplying its value.

        Args:
            *values: Values converted to strings and joined into the prompt text.
            sep: Separator between values; defaults to one space.
            pause: Finite, nonnegative delay after the command, in seconds.
                ``None`` means no delay. Validated before prompt text is sent.

        Raises:
            errors.InvalidArgumentError: ``pause`` or ``sep`` is invalid, or an
                input value cannot be converted to text.

        Example:
            >>> await alert.send("Hello", "world!")
            >>> await alert.accept()
        """
        validate_delay(pause)
        if not isinstance(sep, str):
            raise errors.InvalidArgumentError("Alert separator must be text")
        try:
            text_values = [str(value) for value in values]
        except Exception as err:
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
        """Pause alert-command sequencing without blocking the event loop.

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

    # Special methods ---------------------------------------------------------------------
    def __repr__(self) -> str:
        """Describe the alert handle without allocating a service endpoint.

        Returns:
            The parent session ID and already allocated service URL, if any.
        """
        service = self._session._service
        return "<%s (session='%s', service='%s')>" % (
            self.__class__.__name__,
            self._session._id,
            getattr(service, "_url", None),
        )

    def __hash__(self) -> int:
        """Hash the owning session shared by equivalent alert handles.

        Returns:
            The owning session's identity hash.
        """
        return hash(self._session)

    def __eq__(self, __o: Any) -> bool:
        """Return whether another alert handle belongs to the same session.

        Args:
            __o: Object to compare with this instance.

        Returns:
            ``True`` for another alert handle bound to the identical session.
        """
        return isinstance(__o, Alert) and self._session is __o._session
