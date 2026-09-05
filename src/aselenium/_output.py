"""Cancellation-owned, atomic screenshot/PDF output on a local filesystem."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from aselenium._async import run_blocking


def _write_atomic(path: Path, data: bytes) -> None:
    """Write bytes to a sibling temporary file and replace the destination.

    The sibling placement keeps the final replacement on one filesystem, where
    ``os.replace`` is atomic. The staging file is removed after any failed write
    or replacement.

    Args:
        path: Parsed destination path whose parent directory already exists.
        data: Complete PNG, PDF, or other binary payload to publish.

    Raises:
        OSError: The staging write, flush, sync, replacement, or cleanup fails.
    """
    destination = path
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


async def save_bytes(path: Path, data: bytes) -> bool:
    """Atomically save binary data without abandoning an in-flight write.

    Args:
        path: Parsed destination path whose parent directory already exists.
        data: Complete binary payload to publish.

    Returns:
        ``True`` after successful publication; ``False`` if the filesystem
        raises ``OSError``.

    Raises:
        asyncio.CancelledError: Cancellation propagates after the owned write
            finishes.
    """
    try:
        await run_blocking(_write_atomic, path, data)
    except OSError:
        return False
    return True
