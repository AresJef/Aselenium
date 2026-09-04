"""Regression tests for safe native-browser GitHub Actions annotations."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW: dict[str, Any] = runpy.run_path(str(ROOT / "scripts/_workflow_commands.py"))


def test_workflow_error_is_silent_outside_github_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Avoid leaking acceptance diagnostics during ordinary local execution.

    Args:
        monkeypatch: Reversibly remove the GitHub Actions environment marker.
        capsys: Capture standard output from the diagnostic helper.
    """
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    WORKFLOW["emit_workflow_error"]("failed", "sensitive detail")

    assert capsys.readouterr().out == ""


def test_workflow_error_escapes_control_characters_and_preserves_failure_tail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Emit one bounded command without allowing diagnostic command injection.

    Args:
        monkeypatch: Reversibly enable the GitHub Actions environment marker.
        capsys: Capture the generated workflow command.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    details = "x" * 4_000 + "%\r\nROOT CAUSE"

    WORKFLOW["emit_workflow_error"]("Safari failed", details)

    output = capsys.readouterr().out
    assert output.startswith("::error::")
    assert "%25" in output
    assert "%0D%0A" in output
    assert "earlier diagnostic text truncated" in output
    assert output.endswith("ROOT CAUSE\n")
    assert len(output) <= WORKFLOW["ANNOTATION_LIMIT"] + len("::error::\n")
