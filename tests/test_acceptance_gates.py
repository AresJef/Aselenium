"""Fail-closed checks for installed-browser reports and coverage acceptance."""

from __future__ import annotations

import argparse
import copy
import json
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_IMPORT_PATH = sys.path[:]
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    NATIVE = runpy.run_path(str(ROOT / "scripts/test_installed_browser.py"))
finally:
    sys.path[:] = _IMPORT_PATH
COVERAGE = runpy.run_path(str(ROOT / "scripts/check_coverage.py"))


def report(browser: str = "chrome") -> dict[str, Any]:
    """Construct a complete success report for validator negative controls.

    Args:
        browser: Browser named in the generated report.

    Returns:
        Independent report object with all stages and version evidence.
    """
    return {
        "browser": browser,
        "status": "passed",
        "sections": [
            {"section": name, "status": "passed"} for name in sorted(NATIVE["STAGES"])
        ],
        "session": {"browser_version": "123", "driver_version": "123"},
    }


@pytest.mark.parametrize("browser", ["chrome", "edge", "firefox", "safari"])
def test_complete_native_report_passes(browser: str) -> None:
    """Accept complete reports and only the exact documented Safari skips.

    Args:
        browser: Browser under acceptance.
    """
    value = report(browser)
    if browser == "safari":
        for entry in value["sections"]:
            if entry["section"] in NATIVE["SAFARI_SKIPS"]:
                entry.update(
                    status="skipped", reason=NATIVE["SAFARI_SKIPS"][entry["section"]]
                )
    NATIVE["validate_report"](value, browser)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "skip",
        "failed",
        "not-run",
        "wrong-browser",
        "no-version",
        "wrong-safari-reason",
    ],
)
def test_native_report_rejects_false_success(defect: str) -> None:
    """Reject reports that would hide an incomplete or incorrectly targeted run.

    Args:
        defect: Missing evidence or fabricated success to reject.
    """
    value = report("safari" if defect == "wrong-safari-reason" else "chrome")
    if defect == "missing":
        value["sections"].pop()
    elif defect == "duplicate":
        value["sections"].append(value["sections"][0])
    elif defect == "wrong-browser":
        value["browser"] = "firefox"
    elif defect == "no-version":
        value["session"].pop("browser_version")
    elif defect == "wrong-safari-reason":
        next(
            entry for entry in value["sections"] if entry["section"] == "frames"
        ).update(status="skipped", reason="missing browser")
    else:
        value["sections"][0]["status"] = defect
    with pytest.raises(ValueError):
        NATIVE["validate_report"](
            value, "safari" if defect == "wrong-safari-reason" else "chrome"
        )


def test_native_binary_override_must_be_a_file(tmp_path: Path) -> None:
    """Never silently replace an invalid explicit browser executable.

    Args:
        tmp_path: Directory deliberately supplied in place of an executable.
    """
    with pytest.raises(FileNotFoundError):
        NATIVE["browser_binary"]("firefox", str(tmp_path))
    executable = tmp_path / "firefox"
    executable.touch()
    assert NATIVE["browser_binary"]("firefox", str(executable)) == str(executable)


def test_installed_tours_isolate_concurrent_report_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ignore another browser's report arriving under the same output parent.

    Args:
        tmp_path: Isolated launcher and output directories.
        monkeypatch: Replace only child process boundaries with deterministic reports.
    """
    executable = tmp_path / "browser"
    executable.touch()
    parent = tmp_path / "reports"
    identity = {"package": "installed-package", "prefix": "installed-environment"}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(identity), ""
        ),
    )

    def run_tour(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Emit the owned result and an unrelated concurrent result.

        Args:
            command: Copied demo command naming its unique output directory.
            **kwargs: Owned child execution settings, unused by this double.

        Returns:
            Successful child result after both reports become visible.
        """
        owned = Path(command[command.index("--output-dir") + 1]) / "local-chrome-owned"
        owned.mkdir()
        (owned / "report.json").write_text(json.dumps(report()))
        foreign = parent / "local-firefox-unrelated"
        foreign.mkdir()
        (foreign / "report.json").write_text(json.dumps(report("firefox")))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setitem(NATIVE["run"].__globals__, "run_owned", run_tour)
    args = argparse.Namespace(
        python=executable,
        browser="chrome",
        binary=str(executable),
        cache_dir=tmp_path / "cache",
        output_dir=parent,
        allow_download=False,
        timeout=30,
    )
    result = NATIVE["run"](args)
    assert result["tour"]["browser"] == "chrome"
    assert Path(result["report"]).parent.parent != parent


def coverage_report() -> dict[str, Any]:
    """Create full-coverage counters for every gated critical component.

    Returns:
        Independent synthetic coverage.py report.
    """
    summary = {
        "covered_lines": 100,
        "num_statements": 100,
        "covered_branches": 100,
        "num_branches": 100,
    }
    return {
        "totals": copy.deepcopy(summary),
        "files": {
            name: {"summary": copy.deepcopy(summary)}
            for name in COVERAGE["FLOORS"]
            if name != "total"
        },
    }


def test_coverage_floors_accept_complete_measurements() -> None:
    """Allow complete statement and branch counters meeting every floor."""
    assert COVERAGE["check"](coverage_report()) == []


@pytest.mark.parametrize(
    "defect",
    ["missing-file", "missing-branches", "low-lines", "low-branches", "nan", "empty"],
)
def test_coverage_floors_reject_incomplete_or_regressed_data(defect: str) -> None:
    """Reject missing measurements and independently reduced line or branch coverage.

    Args:
        defect: Counter/report defect to introduce.
    """
    data = coverage_report()
    if defect == "missing-file":
        data["files"].pop("src/aselenium/service.py")
    elif defect == "missing-branches":
        data["totals"].pop("covered_branches")
    elif defect == "low-lines":
        data["totals"]["covered_lines"] = 50
    elif defect == "low-branches":
        data["totals"]["covered_branches"] = 50
    elif defect == "nan":
        data["totals"]["covered_branches"] = float("nan")
    else:
        data = {}
    assert COVERAGE["check"](data)
