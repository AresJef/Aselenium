"""Emit bounded, control-character-safe GitHub Actions diagnostics."""

from __future__ import annotations

import os

ANNOTATION_LIMIT = 3_500
TRUNCATION_NOTICE = "... earlier diagnostic text truncated ...\n"


def _escape_command_data(value: str) -> str:
    """Escape untrusted text for a GitHub workflow-command data field.

    Args:
        value: Arbitrary diagnostic text.

    Returns:
        Text with workflow-command control characters percent-encoded.
    """
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _bounded_command_data(value: str, limit: int = ANNOTATION_LIMIT) -> str:
    """Escape and bound a diagnostic while preserving its exception tail.

    Args:
        value: Diagnostic text to encode and constrain.
        limit: Maximum number of encoded characters to return.

    Returns:
        Safe encoded data, with earlier text explicitly truncated when necessary.
    """
    encoded = _escape_command_data(value)
    if len(encoded) <= limit:
        return encoded
    notice = _escape_command_data(TRUNCATION_NOTICE)
    if len(notice) >= limit:
        return notice[:limit]
    remaining = limit - len(notice)
    tail: list[str] = []
    for character in reversed(value):
        token = _escape_command_data(character)
        if len(token) > remaining:
            break
        tail.append(token)
        remaining -= len(token)
    return notice + "".join(reversed(tail))


def emit_workflow_error(label: str, details: str) -> None:
    """Expose one safe error annotation only while running in GitHub Actions.

    Args:
        label: Short description of the failed acceptance boundary.
        details: Captured exception, process output, or validation diagnostic.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    diagnostic = _bounded_command_data(f"{label}\n{details}".strip())
    print(f"::error::{diagnostic}", flush=True)
