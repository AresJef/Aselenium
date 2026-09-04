"""Emit bounded, control-character-safe GitHub Actions diagnostics."""

from __future__ import annotations

import os

ANNOTATION_LIMIT = 3_500
ANNOTATION_LABEL_LIMIT = 240
TRUNCATION_NOTICE = "... earlier diagnostic text truncated ...\n"
LABEL_TRUNCATION_NOTICE = "..."


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


def _bounded_command_label(value: str, limit: int = ANNOTATION_LABEL_LIMIT) -> str:
    """Escape and bound a diagnostic label while preserving its beginning.

    Args:
        value: Short workflow-annotation label to encode and constrain.
        limit: Maximum number of encoded characters to return.

    Returns:
        Safe encoded label, with a suffix when later text was truncated.
    """
    encoded = _escape_command_data(value)
    if len(encoded) <= limit:
        return encoded
    notice = _escape_command_data(LABEL_TRUNCATION_NOTICE)
    if len(notice) >= limit:
        return notice[:limit]
    remaining = limit - len(notice)
    prefix: list[str] = []
    for character in value:
        token = _escape_command_data(character)
        if len(token) > remaining:
            break
        prefix.append(token)
        remaining -= len(token)
    return "".join(prefix) + notice


def emit_workflow_error(label: str, details: str) -> None:
    """Expose one safe error annotation only while running in GitHub Actions.

    Args:
        label: Short description of the failed acceptance boundary.
        details: Captured exception, process output, or validation diagnostic.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    heading = _bounded_command_label(label.strip())
    separator = "%0A" if heading and details.strip() else ""
    available = max(0, ANNOTATION_LIMIT - len(heading) - len(separator))
    diagnostic = heading + separator + _bounded_command_data(details.strip(), available)
    print(f"::error::{diagnostic}", flush=True)
