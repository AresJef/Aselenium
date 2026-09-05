"""Process-local ownership for Chromium user-data directories."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import (
    TYPE_CHECKING,
)

from aselenium import errors
from aselenium._paths import parse_path

if TYPE_CHECKING:
    from aselenium.options import BaseOptions

_OWNERS: dict[Path, object] = {}
_LOCK = RLock()


def claim_profile(options: BaseOptions, owner: object) -> None:
    """Reserve each Chromium user-data directory selected by an options snapshot.

    Managed profile clones are already stored as ``Path`` objects and remain
    typed here. Raw ``--user-data-dir`` browser arguments are text protocol
    values, so this ownership boundary parses them once before registration.
    Canonical paths prevent two textual aliases from claiming the same directory.

    Args:
        options: Browser options whose launch arguments select the directories.
        owner: Session-specific identity token receiving the reservations.

    Raises:
        errors.InvalidProfileError: Another live owner has already reserved one
            of the selected directories.
        errors.AseleniumInvalidPathError: A raw user-data argument is not a
            valid host filesystem path.
    """
    args = getattr(options, "arguments", ())
    raw_paths: list[str] = []
    for index, arg in enumerate(args):
        if arg.startswith("--user-data-dir="):
            raw_paths.append(arg.split("=", 1)[1])
        elif arg == "--user-data-dir" and index + 1 < len(args):
            raw_paths.append(args[index + 1])

    paths: list[Path] = []
    profile = getattr(options, "_profile", None)
    managed_path = getattr(profile, "_temp_directory", None)
    if isinstance(managed_path, Path):
        # Browser arguments are text protocol values. Compare at that boundary
        # so the retained managed ``Path`` does not enter the parser again.
        managed_argument = str(managed_path)
        paths.append(managed_path.resolve())
        raw_paths = [path for path in raw_paths if path != managed_argument]

    # Canonicalize only at this ownership boundary so aliases to the same raw
    # profile cannot bypass the process-local reservation.
    paths.extend(parse_path(path).resolve() for path in raw_paths)
    with _LOCK:
        if any(path in _OWNERS and _OWNERS[path] is not owner for path in paths):
            raise errors.InvalidProfileError(
                "A session already owns this user-data directory; use "
                "set_profile() for independent clones"
            )
        for path in paths:
            _OWNERS[path] = owner


def release_profile(owner: object) -> None:
    """Release every process-local profile reservation held by an owner.

    Args:
        owner: Session-specific identity token whose reservations are released.
    """
    with _LOCK:
        for path in tuple(_OWNERS):
            if _OWNERS[path] is owner:
                del _OWNERS[path]
