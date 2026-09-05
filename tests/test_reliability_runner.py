"""Offline positive evidence and negative controls for the reliability release gate."""

from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATES = ("recovery", "browser-proxy", "manager-proxy-auth", "long-lived")


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Load the controller without invoking any child process.

    Args:
        monkeypatch: Reversibly expose adjacent standalone acceptance helpers.

    Returns:
        Script namespace containing actual validators and the entry point.
    """
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return runpy.run_path(str(ROOT / "scripts/run_reliability.py"))


def valid_report(
    name: str, browser: str = "chrome", duration: int = 1
) -> dict[str, Any]:
    """Build independent complete success evidence for one controlled child.

    Args:
        name: Reliability harness name, not a production constant lookup.
        browser: Expected browser identity.
        duration: Requested long-lived workload duration.

    Returns:
        A fresh report with realistic counters, identities, and cleanup proof.
    """
    data: dict[str, Any] = {
        "status": "passed",
        "browser": browser,
        "python": "3.13.12",
        "platform": "controlled-test-platform",
        "remaining_fixture_threads": [],
    }
    cleanup = {
        "remaining_owned_tasks": 0,
        "remaining_observed_processes": [],
        "browser_version": "144.0.1",
        "driver_version": "144.0.1",
    }
    if name == "recovery":
        data["scenarios"] = [
            {
                "scenario": scenario,
                "status": "passed",
                "command_acknowledged_before_fault": True,
                "fault_signal_sent": True,
                "command_failure_type": "SessionTimeoutError"
                if scenario.endswith("hang")
                else "SessionClientError",
                "failure_after_injection_seconds": 4.8
                if scenario.endswith("hang")
                else 0.2,
                "fault_session_id": f"fault-{index}",
                "target": {
                    "pid": 110 if scenario.startswith("driver-") else 120,
                    "owner_pid": 100,
                    "service_pid": 110,
                    "created": 1750000000.25,
                },
                "target_executable": "/fixture/driver"
                if scenario.startswith("driver-")
                else "/fixture/browser",
                "selected_launcher": "/fixture/browser",
                "library_cleanup_survivors": [],
                "harness_emergency_cleanup": [],
                "library_profile_removed": True,
                "template_profile_removed": True,
                "reacquisition": {
                    "session_id": f"fresh-{index}",
                    "profile_removed": True,
                },
                **cleanup,
            }
            for index, scenario in enumerate(
                ("browser-crash", "driver-crash", "browser-hang", "driver-hang")
            )
        ]
    elif name in ("browser-proxy", "manager-proxy-auth"):
        manager = name == "manager-proxy-auth"
        data.update(cleanup)
        data.update(
            {
                "scheme": "both",
                "client": "manager HTTPS transport",
                "authentication_required": True,
                "closed_clients": 5,
                "tls_verification": "Explicit fixture CA and IP hostname verification",
                "routing": {
                    "forwarded": 0 if manager else 1,
                    "origin_hits": 1 if manager else 2,
                    "rejected": 1 if manager else 0,
                    "direct_rejected": 1 if manager else 0,
                    "connects": 1,
                    "tls_origin_hits": 1,
                    "auth_rejected": 2 if manager else 0,
                    "credential_leaks": 0,
                    "active_tunnels": 0,
                    "tunnel_bytes": 4096,
                },
                "cases": {
                    case: "passed"
                    for case in (
                        "verified_tls_through_connect",
                        "direct_bypass_rejected",
                        "unallowlisted_connect_rejected",
                        "authenticated_connect",
                        "missing_credentials_rejected",
                        "wrong_credentials_rejected",
                    )
                },
            }
        )
    elif name == "long-lived":
        data.update(cleanup)
        baseline = {
            "rss_bytes": 50000000,
            "owned_rss_bytes": 250000000,
            "handles": 12,
            "owned_processes": 7,
        }
        data.update(
            {
                "mode": "long-lived",
                "session_id": "sustained-session",
                "requested_duration_seconds": duration,
                "workload_elapsed_seconds": duration + 0.25,
                "iterations": 12,
                "controlled_native_script_timeouts": 2,
                "session_profile_removed": True,
                "template_profile_removed": True,
                "growth_limits": {
                    "python_rss_mib": 128,
                    "browser_tree_rss_mib": 512,
                    "handles": 32,
                    "processes": 8,
                },
                "baseline": baseline,
                "resource_samples": [
                    {"iteration": 1, "elapsed_seconds": 0.2, **baseline},
                    {
                        "iteration": 10,
                        "elapsed_seconds": duration * 0.8,
                        **baseline,
                        "rss_bytes": 52000000,
                    },
                ],
                "last_sample": {
                    "iteration": 12,
                    "elapsed_seconds": duration + 0.2,
                    **baseline,
                    "rss_bytes": 53000000,
                },
            }
        )
    else:
        raise ValueError(f"Unknown fixture gate: {name}")
    return data


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize(
    "browser,duration", [("chrome", 1), ("edge", 30), ("chrome", 600)]
)
def test_complete_harness_evidence_passes(
    controller: dict[str, Any], gate: str, browser: str, duration: int
) -> None:
    """Accept independent short and scheduled-run success evidence.

    Args:
        controller: Loaded real validators.
        gate: Harness success schema exercised.
        browser: Requested browser identity.
        duration: Required sustained workload duration.
    """
    controller["validate_report"](
        gate, valid_report(gate, browser, duration), browser, duration
    )


@pytest.mark.parametrize(
    "value", [None, [], ["passed"], "passed", 0, True, {"status": "passed"}]
)
@pytest.mark.parametrize("gate", GATES)
def test_incomplete_json_never_counts_as_success(
    controller: dict[str, Any], gate: str, value: object
) -> None:
    """Reject non-objects and status-only JSON for every gate.

    Args:
        controller: Loaded real validators.
        gate: Expected child harness.
        value: Decoded JSON lacking required acceptance evidence.
    """
    with pytest.raises(ValueError):
        controller["validate_report"](gate, value, "chrome", 1)


@pytest.mark.parametrize(
    "gate,path,value",
    [
        ("recovery", ("browser",), "edge"),
        ("recovery", ("scenarios",), []),
        ("recovery", ("scenarios", 0), None),
        ("recovery", ("scenarios", 0, "scenario"), "driver-crash"),
        ("recovery", ("scenarios", 0, "status"), "failed"),
        ("recovery", ("scenarios", 0, "command_acknowledged_before_fault"), 1),
        ("recovery", ("scenarios", 0, "fault_signal_sent"), False),
        ("recovery", ("scenarios", 0, "command_failure_type"), "AssertionError"),
        (
            "recovery",
            ("scenarios", 0, "command_failure_type"),
            "JavaScriptTimeoutError",
        ),
        ("recovery", ("scenarios", 0, "failure_after_injection_seconds"), 7.01),
        ("recovery", ("scenarios", 0, "failure_after_injection_seconds"), float("nan")),
        ("recovery", ("scenarios", 0, "failure_after_injection_seconds"), True),
        ("recovery", ("scenarios", 0, "target", "pid"), 100),
        ("recovery", ("scenarios", 0, "target", "pid"), 110),
        ("recovery", ("scenarios", 0, "target", "created"), -1),
        ("recovery", ("scenarios", 0, "library_cleanup_survivors"), [120]),
        ("recovery", ("scenarios", 0, "harness_emergency_cleanup"), [120]),
        ("recovery", ("scenarios", 0, "reacquisition", "session_id"), "fault-0"),
        ("recovery", ("scenarios", 0, "reacquisition", "profile_removed"), False),
        ("recovery", ("scenarios", 0, "browser_version"), None),
        ("recovery", ("remaining_fixture_threads",), False),
        ("browser-proxy", ("browser",), "edge"),
        ("browser-proxy", ("scheme",), "http"),
        ("browser-proxy", ("routing", "forwarded"), 0),
        ("browser-proxy", ("routing", "origin_hits"), 1),
        ("browser-proxy", ("routing", "connects"), 0),
        ("browser-proxy", ("routing", "tls_origin_hits"), 0),
        ("browser-proxy", ("routing", "tunnel_bytes"), 0),
        ("browser-proxy", ("routing", "active_tunnels"), 1),
        ("browser-proxy", ("remaining_observed_processes",), [120]),
        ("manager-proxy-auth", ("client",), "browser"),
        ("manager-proxy-auth", ("authentication_required",), False),
        ("manager-proxy-auth", ("cases",), {}),
        ("manager-proxy-auth", ("cases", "wrong_credentials_rejected"), "skipped"),
        ("manager-proxy-auth", ("closed_clients",), 4),
        ("manager-proxy-auth", ("routing", "auth_rejected"), 1),
        ("manager-proxy-auth", ("routing", "direct_rejected"), 0),
        ("manager-proxy-auth", ("routing", "rejected"), 0),
        ("manager-proxy-auth", ("routing", "credential_leaks"), 1),
        ("manager-proxy-auth", ("routing", "tunnel_bytes"), True),
        ("manager-proxy-auth", ("remaining_owned_tasks",), False),
        ("manager-proxy-auth", ("tls_verification",), " "),
        ("long-lived", ("browser",), "edge"),
        ("long-lived", ("mode",), "fresh"),
        ("long-lived", ("requested_duration_seconds",), 600),
        ("long-lived", ("workload_elapsed_seconds",), 0.9),
        ("long-lived", ("workload_elapsed_seconds",), float("inf")),
        ("long-lived", ("iterations",), 0),
        ("long-lived", ("iterations",), True),
        ("long-lived", ("controlled_native_script_timeouts",), 1),
        ("long-lived", ("session_profile_removed",), False),
        ("long-lived", ("template_profile_removed",), False),
        ("long-lived", ("growth_limits", "handles"), 33),
        ("long-lived", ("baseline", "rss_bytes"), 0),
        ("long-lived", ("resource_samples",), []),
        ("long-lived", ("resource_samples", 0), "invalid"),
        ("long-lived", ("resource_samples", 0, "iteration"), 2),
        ("long-lived", ("resource_samples", 0, "rss_bytes"), 51000000),
        ("long-lived", ("resource_samples", 1, "iteration"), 1),
        ("long-lived", ("resource_samples", 1, "elapsed_seconds"), 10),
        ("long-lived", ("resource_samples", 1, "rss_bytes"), 190000000),
        ("long-lived", ("resource_samples", 1, "owned_rss_bytes"), 800000000),
        ("long-lived", ("resource_samples", 1, "handles"), 45),
        ("long-lived", ("resource_samples", 1, "owned_processes"), 16),
        ("long-lived", ("last_sample", "iteration"), 10),
        ("long-lived", ("last_sample", "elapsed_seconds"), 0.1),
        ("long-lived", ("last_sample", "rss_bytes"), 190000000),
        ("long-lived", ("last_sample", "handles"), -1),
        ("long-lived", ("remaining_owned_tasks",), 1),
        ("long-lived", ("remaining_observed_processes",), None),
        ("long-lived", ("driver_version",), ""),
    ],
)
def test_invalid_or_inconsistent_success_claim_is_rejected(
    controller: dict[str, Any], gate: str, path: tuple[str | int, ...], value: object
) -> None:
    """Alter one acceptance fact while preserving a deceptively passing status.

    Args:
        controller: Loaded report validators.
        gate: Harness whose complete report is mutated.
        path: Exact field with malformed or contradictory evidence.
        value: Replacement that must fail closed.
    """
    report = valid_report(gate)
    current: Any = report
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(ValueError):
        controller["validate_report"](gate, report, "chrome", 1)


def test_recovery_signal_proof_cannot_be_omitted(
    controller: dict[str, Any],
) -> None:
    """Reject recovery evidence that never proves the target received a signal.

    Args:
        controller: Loaded real reliability report validator.
    """
    report = valid_report("recovery")
    report["scenarios"][0].pop("fault_signal_sent")
    with pytest.raises(ValueError, match="requested signal"):
        controller["validate_report"]("recovery", report, "chrome", 1)


@pytest.mark.parametrize("gate", GATES)
def test_mandatory_top_level_evidence_cannot_be_omitted(
    controller: dict[str, Any], gate: str
) -> None:
    """Omit independently chosen fields to reject absent cleanup proof.

    Args:
        controller: Loaded report validators.
        gate: Harness whose required fields are individually removed.
    """
    required = {
        "recovery": (
            "status",
            "python",
            "platform",
            "browser",
            "scenarios",
            "remaining_fixture_threads",
        ),
        "browser-proxy": (
            "browser",
            "scheme",
            "routing",
            "remaining_fixture_threads",
            "remaining_owned_tasks",
            "remaining_observed_processes",
        ),
        "manager-proxy-auth": (
            "client",
            "authentication_required",
            "cases",
            "routing",
            "closed_clients",
            "tls_verification",
            "remaining_fixture_threads",
            "remaining_owned_tasks",
        ),
        "long-lived": (
            "mode",
            "session_id",
            "iterations",
            "controlled_native_script_timeouts",
            "requested_duration_seconds",
            "workload_elapsed_seconds",
            "baseline",
            "last_sample",
            "resource_samples",
            "growth_limits",
            "session_profile_removed",
            "template_profile_removed",
            "remaining_owned_tasks",
            "remaining_observed_processes",
        ),
    }
    for key in required[gate]:
        report = valid_report(gate)
        del report[key]
        with pytest.raises(ValueError):
            controller["validate_report"](gate, report, "chrome", 1)


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "no-report",
        "status-only",
        "bad-status",
        "exit-code",
        "timeout",
        "orphan",
        "null",
        "list",
        "bad-json",
    ],
)
def test_reliability_runner_keeps_later_gates_and_failure_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    controller: dict[str, Any],
    defect: str | None,
) -> None:
    """Retain all four gate results after a malformed or failed child.

    Args:
        tmp_path: Disposable executable and report directories.
        monkeypatch: Replace only the command boundary, never report validation.
        controller: Actual script entry point and validators.
        defect: Failure injected only in the first child invocation.
    """
    binary = tmp_path / "browser"
    binary.touch()
    calls: list[list[str]] = []

    def invoke(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Return a controlled process result and independent child JSON evidence.

        Args:
            command: Harness command with an explicit output path.
            **kwargs: Process isolation and deadline settings to validate.

        Returns:
            Simulated child result with no external process execution.
        """
        gate = GATES[len(calls)]
        calls.append(command)
        assert kwargs["timeout"] > 0
        if gate == "recovery":
            assert kwargs["timeout"] == 540
        assert "PYTHONPATH" not in kwargs["env"]
        path = Path(command[command.index("--output") + 1])
        assert kwargs["cwd"] == path.parent
        selected = defect if len(calls) == 1 else None
        if selected == "timeout":
            raise subprocess.TimeoutExpired(
                command,
                kwargs["timeout"],
                output="partial stdout",
                stderr="cleanup diagnostic",
            )
        if selected == "orphan":
            raise controller["OwnedProcessError"](
                command,
                0,
                "partial stdout",
                "cleanup diagnostic",
                [],
                "Owned descendant required forced cleanup",
            )
        if selected != "no-report":
            evidence: object = valid_report(gate)
            if selected == "status-only":
                evidence = {"status": "passed"}
            elif selected == "bad-status":
                evidence = {**valid_report(gate), "status": "failed"}
            elif selected == "null":
                evidence = None
            elif selected == "list":
                evidence = []
            path.write_text(
                "broken JSON" if selected == "bad-json" else json.dumps(evidence),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(
            command, 1 if selected == "exit-code" else 0, "fixture", ""
        )

    monkeypatch.setitem(controller["main"].__globals__, "run_owned", invoke)
    arguments = [
        "--python",
        str(binary),
        "--browser",
        "chrome",
        "--binary",
        str(binary),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--output-dir",
        str(tmp_path / "reports"),
        "--duration",
        "1",
    ]
    assert controller["main"](arguments) == int(defect is not None)
    assert len(calls) == 4
    summaries = list((tmp_path / "reports").glob("*/chrome-reliability.json"))
    assert len(summaries) == 1
    result = json.loads(summaries[0].read_text())
    assert result["status"] == ("failed" if defect else "passed")
    assert set(result["checks"]) == set(GATES)
    assert all(result["checks"][gate]["status"] == "passed" for gate in GATES[1:])
    assert result["checks"]["recovery"]["status"] == ("failed" if defect else "passed")
    assert calls[0][calls[0].index("--command-timeout") + 1] == "5"
    assert calls[1][calls[1].index("--scheme") + 1] == "both"
    assert "--proxy-auth" in calls[2]
    for flag, expected in (
        ("--duration", "1"),
        ("--max-rss-growth-mib", "128"),
        ("--max-browser-rss-growth-mib", "512"),
        ("--max-handle-growth", "32"),
        ("--max-process-growth", "8"),
    ):
        assert calls[3][calls[3].index(flag) + 1] == expected
    if defect in ("timeout", "orphan"):
        log = (summaries[0].parent / "chrome-recovery.log").read_text()
        assert "partial stdout" in log
        assert "cleanup diagnostic" in log


def test_recovery_annotation_retains_failed_scenario_after_verbose_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    controller: dict[str, Any],
) -> None:
    """Keep the failed scenario and cause at the tail of a bounded CI annotation.

    Args:
        tmp_path: Disposable executable and report directories.
        monkeypatch: Replace child execution and enable GitHub annotations.
        capsys: Capture controller progress and workflow commands.
        controller: Actual script entry point and summary builder.
    """
    binary = tmp_path / "browser"
    binary.touch()
    calls = 0

    def invoke(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Write one failed recovery report followed by valid gate reports.

        Args:
            command: Harness command containing the report destination.
            **kwargs: Owned-process runner options, intentionally unused.

        Returns:
            Controlled child result with deliberately verbose recovery output.
        """
        nonlocal calls
        gate = GATES[calls]
        calls += 1
        report = valid_report(gate, browser="edge")
        return_code = 0
        if gate == "recovery":
            report["status"] = "failed"
            scenario = report["scenarios"][0]
            scenario["status"] = "failed"
            scenario["failure_type"] = "ValueError"
            scenario["failure"] = "distinct recovery root cause"
            return_code = 1
        path = Path(command[command.index("--output") + 1])
        path.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            return_code,
            "verbose fixture output " + "x" * 8_000 if gate == "recovery" else "",
            "",
        )

    monkeypatch.setitem(controller["main"].__globals__, "run_owned", invoke)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    arguments = [
        "--python",
        str(binary),
        "--browser",
        "edge",
        "--binary",
        str(binary),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--output-dir",
        str(tmp_path / "reports"),
        "--duration",
        "1",
    ]

    assert controller["main"](arguments) == 1

    annotations = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("::error::")
    ]
    assert len(annotations) == 1
    annotation = annotations[0]
    assert "earlier diagnostic text truncated" in annotation
    assert 'Failure summary: {"gate":"recovery"' in annotation
    assert '"scenario":"browser-crash"' in annotation
    assert '"failure_type":"ValueError"' in annotation
    assert '"failure":"distinct recovery root cause"' in annotation
    assert annotation.endswith("}")


def test_recovery_failure_summary_is_bounded_for_malformed_verbose_reports(
    controller: dict[str, Any],
) -> None:
    """Bound summary size while preserving each expected failed scenario identity.

    Args:
        controller: Actual script namespace containing the summary builder.
    """
    report = valid_report("recovery")
    report["status"] = "failed"
    for index, scenario in enumerate(report["scenarios"]):
        scenario["status"] = "failed"
        scenario["failure_type"] = "SyntheticError"
        scenario["failure"] = f"failure-{index}-" + "x" * 8_000

    summary = controller["failure_summary"]("recovery", report)

    assert len(summary) <= controller["FAILURE_SUMMARY_LIMIT"]
    for scenario in ("browser-crash", "driver-crash", "browser-hang", "driver-hang"):
        assert f'"scenario":"{scenario}"' in summary
