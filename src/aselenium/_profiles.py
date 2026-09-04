"""Fail-fast ownership of explicitly shared user-data directories in a process."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import (
    TYPE_CHECKING,
)

from aselenium import errors

if TYPE_CHECKING:
    from aselenium.options import BaseOptions

_OWNERS: dict[str, object] = {}
_LOCK = RLock()


def claim_profile(options: BaseOptions, owner: object) -> None:
    """Reserve explicitly shared user-data directories for one session owner.

    Args:
        options: Options used by this operation.
        owner: Identity token that owns the resource or profile reservation.
    """
    args = getattr(options, "arguments", ())
    paths = []
    for index, arg in enumerate(args):
        if arg.startswith("--user-data-dir="):
            paths.append(arg.split("=", 1)[1])
        elif arg == "--user-data-dir" and index + 1 < len(args):
            paths.append(args[index + 1])
    paths = [str(Path(path).expanduser().resolve()) for path in paths]
    with _LOCK:
        if any(path in _OWNERS and _OWNERS[path] is not owner for path in paths):
            raise errors.InvalidProfileError(
                "A session already owns this user-data directory; use set_profile() for independent clones"
            )
        for path in paths:
            _OWNERS[path] = owner


def release_profile(owner: object) -> None:
    """Release all in-process user-data directory reservations held by an owner.

    Args:
        owner: Identity token that owns the resource or profile reservation.
    """
    with _LOCK:
        for path in list(_OWNERS):
            if _OWNERS[path] is owner:
                del _OWNERS[path]
