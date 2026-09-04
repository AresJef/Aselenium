"""Expose pytest JUnit failures as safe GitHub Actions annotations."""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

ANNOTATION_LIMIT = 3_500
SUMMARY_DETAIL_LIMIT = 8_000
NODE_ID_LIMIT = 300


@dataclass(frozen=True, slots=True)
class JUnitIssue:
    """Describe one failed or errored pytest test case.

    Args:
        node_id: Human-readable pytest test identifier.
        kind: JUnit result type: ``failure`` or ``error``.
        message: Short failure message supplied by pytest.
        details: Captured traceback or collection-error details.
    """

    node_id: str
    kind: Literal["failure", "error"]
    message: str
    details: str


def read_issues(report: Path) -> list[JUnitIssue]:
    """Parse failed and errored test cases from a pytest JUnit report.

    Args:
        report: Path to the JUnit XML file produced by pytest.

    Returns:
        Failed and errored cases in document order.

    Raises:
        OSError: If the report cannot be read.
        xml.etree.ElementTree.ParseError: If the report is not valid XML.

    Example:
        >>> issues = read_issues(Path("pytest-results.xml"))
        >>> all(issue.kind in {"failure", "error"} for issue in issues)
        True
    """
    root = ET.parse(report).getroot()
    issues: list[JUnitIssue] = []
    for case in root.iter("testcase"):
        class_name = case.get("classname", "").strip()
        test_name = case.get("name", "unknown test").strip()
        node_id = f"{class_name}::{test_name}" if class_name else test_name
        for result in case:
            kind = result.tag.rpartition("}")[-1]
            if kind not in {"failure", "error"}:
                continue
            issues.append(
                JUnitIssue(
                    node_id=node_id,
                    kind=kind,
                    message=result.get("message", "").strip(),
                    details=(result.text or "").strip(),
                )
            )
    return issues


def _bounded(value: str, limit: int) -> str:
    """Bound diagnostic text while making truncation explicit.

    Args:
        value: Diagnostic text to constrain.
        limit: Maximum number of characters to return.

    Returns:
        Original text or a visibly truncated representation.
    """
    if len(value) <= limit:
        return value
    suffix = "\n... diagnostic truncated ..."
    return value[: max(0, limit - len(suffix))] + suffix


def _bounded_node_id(value: str) -> str:
    """Bound a test identifier without consuming its diagnostic budget.

    Args:
        value: Fully qualified pytest node identifier.

    Returns:
        Original identifier, or an explicitly truncated representation.
    """
    if len(value) <= NODE_ID_LIMIT:
        return value
    suffix = "... node id truncated ..."
    return value[: NODE_ID_LIMIT - len(suffix)] + suffix


def _escape_command_data(value: str) -> str:
    """Escape untrusted text for the GitHub workflow-command data field.

    Args:
        value: Arbitrary test diagnostic text.

    Returns:
        Text with workflow-command control characters percent-encoded.
    """
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def format_annotation(issue: JUnitIssue) -> str:
    """Format one issue as a bounded GitHub error annotation.

    Args:
        issue: Parsed failed or errored test case.

    Returns:
        A single safe ``::error::`` workflow-command line.
    """
    diagnostic = issue.message or issue.details or "pytest reported no diagnostic text"
    if issue.message and issue.details and issue.message not in issue.details:
        diagnostic = f"{issue.message}\n{issue.details}"
    node_id = _bounded_node_id(issue.node_id)
    content = _bounded(f"{node_id} [{issue.kind}]\n{diagnostic}", ANNOTATION_LIMIT)
    return f"::error::{_escape_command_data(content)}"


def format_summary(issues: Sequence[JUnitIssue]) -> str:
    """Build a readable Markdown summary for failed pytest cases.

    Args:
        issues: Failed and errored test cases to summarize.

    Returns:
        Markdown suitable for ``GITHUB_STEP_SUMMARY``.
    """
    lines = ["## Pytest failure diagnostics", ""]
    for issue in issues:
        lines.extend((f"### `{_bounded_node_id(issue.node_id)}` ({issue.kind})", ""))
        diagnostic = (
            issue.details or issue.message or "pytest reported no diagnostic text"
        )
        for line in _bounded(diagnostic, SUMMARY_DETAIL_LIMIT).splitlines() or [""]:
            lines.append(f"    {line}")
        lines.append("")
    return "\n".join(lines)


def report_issues(report: Path, summary_path: Path | None = None) -> int:
    """Emit annotations and optionally append a GitHub job summary.

    Args:
        report: Path to the pytest JUnit XML report.
        summary_path: Optional GitHub step-summary file.

    Returns:
        Zero so the original pytest step remains the authoritative failure.
    """
    try:
        issues = read_issues(report)
    except (OSError, ET.ParseError) as exc:
        message = _escape_command_data(
            f"Could not read pytest diagnostics from {report.name}: {exc}"
        )
        print(f"::warning::{message}")
        return 0

    if not issues:
        print("::warning::Pytest failed without a failed or errored JUnit test case")
        return 0

    for issue in issues:
        print(format_annotation(issue))
    if summary_path is not None:
        try:
            with summary_path.open("a", encoding="utf-8") as summary:
                summary.write(format_summary(issues))
                summary.write("\n")
        except OSError as exc:
            message = _escape_command_data(
                f"Could not append the pytest job summary: {exc}"
            )
            print(f"::warning::{message}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the JUnit-to-GitHub diagnostic reporter.

    Args:
        argv: Optional command-line arguments excluding the executable name.

    Returns:
        Process exit status. Diagnostic reporting intentionally returns zero.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: report_pytest_failures.py JUNIT_XML", file=sys.stderr)
        return 2
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    return report_issues(Path(arguments[0]), Path(summary) if summary else None)


if __name__ == "__main__":
    raise SystemExit(main())
