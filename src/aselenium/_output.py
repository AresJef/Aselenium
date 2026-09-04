"""Cancellation-owned, atomic screenshot/PDF output on a local filesystem."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from aselenium._async import run_blocking


def _write_atomic(path: str, data: bytes) -> None:
    """Write bytes to a sibling temporary file and atomically replace the destination.

    Args:
        path: Filesystem path to inspect or operate on.
        data: Complete PNG, PDF, or other binary payload to publish.
    """
    destination = Path(path)
    # Replaces the output directory entry; never writes through an output link.
    staging = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".aselenium-output-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            staging = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, destination)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


async def save_bytes(path: str, data: bytes) -> bool:
    """Atomically save binary data without abandoning an in-flight write.

    Args:
        path: Filesystem path to inspect or operate on.
        data: Complete binary payload to publish.

    Returns:
        True after successful publication; False if the filesystem raises OSError.

    Raises:
        asyncio.CancelledError: Cancellation propagates after the owned write finishes.
    """
    try:
        await run_blocking(_write_atomic, path, data)
    except OSError:
        return False
    return True
