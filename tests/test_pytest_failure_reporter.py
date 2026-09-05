"""Tests for the GitHub Actions pytest diagnostic reporter."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.report_pytest_failures import (
    ANNOTATION_LIMIT,
    JUnitIssue,
    format_annotation,
    format_summary,
    main,
    read_issues,
    report_issues,
)


def _write_report(path: Path) -> None:
    """Write a representative pytest JUnit report.

    Args:
        path: Destination XML path.
    """
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.test_demo" name="test_failure">
      <failure message="expected 1% but got 2">line one\nline two</failure>
    </testcase>
    <testcase classname="tests.test_demo" name="test_error">
      <error message="collection failed">traceback</error>
    </testcase>
    <testcase classname="tests.test_demo" name="test_passed" />
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )


def test_read_issues_extracts_failures_and_errors(tmp_path: Path) -> None:
    """Extract failed and errored cases without including passed tests."""
    report = tmp_path / "results.xml"
    _write_report(report)

    issues = read_issues(report)

    assert issues == [
        JUnitIssue(
            node_id="tests.test_demo::test_failure",
            kind="failure",
            message="expected 1% but got 2",
            details="line one\nline two",
        ),
        JUnitIssue(
            node_id="tests.test_demo::test_error",
            kind="error",
            message="collection failed",
            details="traceback",
        ),
    ]


def test_annotation_escapes_workflow_control_characters() -> None:
    """Prevent diagnostic text from injecting additional workflow commands."""
    line = format_annotation(
        JUnitIssue("tests::test_case", "failure", "100%\r\nbad", "")
    )

    assert line.startswith("::error::tests::test_case [failure]%0A")
    assert "100%25%0D%0Abad" in line
    assert "\n" not in line


def test_annotation_bounds_the_encoded_workflow_payload() -> None:
    """Apply the size ceiling after expansion of newlines and percent signs."""
    line = format_annotation(
        JUnitIssue("tests::test_case", "failure", ("%\n" * 5_000), "")
    )

    prefix = "::error::"
    assert line.startswith(prefix)
    assert len(line.removeprefix(prefix)) <= ANNOTATION_LIMIT
    assert "... earlier diagnostic text truncated ..." in line


def test_reporter_bounds_node_id_before_preserving_diagnostic() -> None:
    """Keep a pathological parameter ID from hiding the useful failure cause."""
    issue = JUnitIssue(
        "tests::test_case[" + ("x" * 65_537) + "]",
        "error",
        "PYTEST_CURRENT_TEST exceeds the Windows environment limit",
        "",
    )

    line = format_annotation(issue)
    summary = format_summary([issue])

    assert "... node id truncated ..." in line
    assert "PYTEST_CURRENT_TEST exceeds the Windows environment limit" in line
    assert "... node id truncated ..." in summary
    assert "PYTEST_CURRENT_TEST exceeds the Windows environment limit" in summary
    assert len(line) < 1_000


def test_summary_uses_indented_diagnostic_text() -> None:
    """Render traceback text as inert Markdown rather than executable markup."""
    summary = format_summary(
        [JUnitIssue("tests::test_case", "failure", "message", "line 1\n```\nline 2")]
    )

    assert "### `tests::test_case` (failure)" in summary
    assert "    ```" in summary
    assert "    line 2" in summary


def test_report_issues_emits_annotations_and_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish bounded annotations and append a readable job summary."""
    report = tmp_path / "results.xml"
    summary = tmp_path / "summary.md"
    _write_report(report)

    assert report_issues(report, summary) == 0

    output = capsys.readouterr().out
    assert output.count("::error::") == 2
    assert "expected 1%25 but got 2" in output
    assert "tests.test_demo::test_failure" in summary.read_text(encoding="utf-8")


def test_report_issues_handles_missing_or_malformed_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep diagnostics secondary when the JUnit file is unavailable or invalid."""
    missing = tmp_path / "missing.xml"
    malformed = tmp_path / "malformed.xml"
    malformed.write_text("<testsuite>", encoding="utf-8")

    assert report_issues(missing) == 0
    assert report_issues(malformed) == 0

    output = capsys.readouterr().out
    assert output.count("::warning::") == 2


def test_main_reads_github_summary_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the job-summary path supplied by the GitHub Actions environment."""
    report = tmp_path / "results.xml"
    summary = tmp_path / "summary.md"
    _write_report(report)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    assert main([str(report)]) == 0
    assert "Pytest failure diagnostics" in summary.read_text(encoding="utf-8")
