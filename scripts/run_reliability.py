"""Run bounded owned-process, proxy and sustained-session acceptance as one CI gate.

Provision the selected browser's cache with the installed-wheel tour first.
No downloads, browser installation or system-setting changes occur in this runner.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from math import isfinite
from pathlib import Path
from typing import Any, cast

from _owned_subprocess import OwnedProcessError, run_owned
from _workflow_commands import emit_workflow_error
from test_installed_browser import browser_binary

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_SCENARIOS = {"browser-crash", "driver-crash", "browser-hang", "driver-hang"}
RECOVERY_FAILURES = {
    "SessionTimeoutError",
    "SessionClientError",
    "ConnectionClosedError",
    "InvalidSessionError",
    "UnknownError",
    "WindowNotFountError",
}
RECOVERY_COMMAND_TIMEOUT = 5
MANAGER_PROXY_CASES = {
    "verified_tls_through_connect",
    "direct_bypass_rejected",
    "unallowlisted_connect_rejected",
    "authenticated_connect",
    "missing_credentials_rejected",
    "wrong_credentials_rejected",
}
GROWTH_LIMITS = {
    "python_rss_mib": 128,
    "browser_tree_rss_mib": 512,
    "handles": 32,
    "processes": 8,
}


def require(condition: bool, message: str) -> None:
    """Reject incomplete acceptance evidence without relying on removable asserts.

    Args:
        condition: Required evidence property.
        message: Failure diagnostic identifying the absent or inconsistent evidence.

    Raises:
        ValueError: The required evidence property is false.
    """
    if not condition:
        raise ValueError(message)


def mapping(value: object, label: str) -> dict[str, Any]:
    """Require a JSON object before examining nested acceptance fields.

    Args:
        value: Decoded JSON value.
        label: Evidence field named in a failure diagnostic.

    Returns:
        The object after validating its shape.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def number(data: dict[str, Any], key: str, minimum: float = 0) -> int | float:
    """Require a finite non-boolean JSON number meeting a lower bound.

    Args:
        data: Evidence object containing the numeric field.
        key: Field to validate.
        minimum: Inclusive lower bound.

    Returns:
        Validated integer or floating-point value.
    """
    value: Any = data.get(key)
    if (
        type(value) not in (int, float)
        or (type(value) is float and not isfinite(value))
        or value < minimum
    ):
        raise ValueError(f"{key} must be a finite number >= {minimum}")
    return value


def integer(data: dict[str, Any], key: str, minimum: int = 0) -> int:
    """Require a non-boolean integer counter meeting a lower bound.

    Args:
        data: Evidence object containing the counter.
        key: Counter to validate.
        minimum: Inclusive lower bound.

    Returns:
        Validated integer counter.
    """
    value = data.get(key)
    if type(value) is not int or value < minimum:
        raise ValueError(f"{key} must be an integer >= {minimum}")
    return value


def text_field(data: dict[str, Any], key: str) -> str:
    """Require nonempty textual identity or version evidence.

    Args:
        data: Evidence object containing the string.
        key: Field to validate.

    Returns:
        Nonempty string after validation.
    """
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must contain nonempty text")
    return value


def empty_list(data: dict[str, Any], key: str) -> None:
    """Require an explicitly empty cleanup list, not missing or falsey evidence.

    Args:
        data: Evidence object containing cleanup observations.
        key: List field that must prove no remaining resource.
    """
    require(
        type(data.get(key)) is list and data[key] == [],
        f"{key} must be an explicit empty list",
    )


def clean_session(data: dict[str, Any]) -> None:
    """Require session process/task cleanup and actual browser/driver versions.

    Args:
        data: Browser/session result containing cleanup and version evidence.
    """
    empty_list(data, "remaining_observed_processes")
    require(integer(data, "remaining_owned_tasks") == 0, "Owned tasks remain")
    text_field(data, "browser_version")
    text_field(data, "driver_version")


def validate_recovery(data: dict[str, Any]) -> None:
    """Require all four fault injections, independent reacquisition, and clean ownership.

    Args:
        data: Aggregate owned-process recovery report.
    """
    empty_list(data, "remaining_fixture_threads")
    scenarios = data.get("scenarios")
    require(
        type(scenarios) is list and len(scenarios) == 4,
        "Recovery requires four scenario reports",
    )
    observed = set()
    for raw in cast(list[object], scenarios):
        scenario = mapping(raw, "Recovery scenario")
        name = text_field(scenario, "scenario")
        require(
            name in RECOVERY_SCENARIOS and name not in observed,
            "Recovery scenarios are missing, duplicated, or unsupported",
        )
        observed.add(name)
        require(
            scenario.get("status") == "passed", f"Recovery scenario {name} did not pass"
        )
        require(
            scenario.get("command_acknowledged_before_fault") is True,
            "Fault was not proven to occur during an acknowledged command",
        )
        require(
            text_field(scenario, "command_failure_type") in RECOVERY_FAILURES,
            "Fault did not cause an expected connection/session failure",
        )
        require(
            number(scenario, "failure_after_injection_seconds")
            <= RECOVERY_COMMAND_TIMEOUT + 2,
            "Faulted command exceeded the bounded recovery deadline",
        )
        fault_id = text_field(scenario, "fault_session_id")
        target = mapping(scenario.get("target"), "Fault target")
        pid = integer(target, "pid", 1)
        owner = integer(target, "owner_pid", 1)
        service = integer(target, "service_pid", 1)
        number(target, "created", 1)
        require(
            pid != owner and service != owner,
            "Fault target must not be the owning harness",
        )
        require(
            (pid == service) == name.startswith("driver-"),
            "Fault target does not match the requested browser/driver scenario",
        )
        text_field(scenario, "target_executable")
        text_field(scenario, "selected_launcher")
        for key in ("library_cleanup_survivors", "harness_emergency_cleanup"):
            empty_list(scenario, key)
        for key in ("library_profile_removed", "template_profile_removed"):
            require(scenario.get(key) is True, f"{key} did not prove cleanup")
        clean_session(scenario)
        reacquisition = mapping(scenario.get("reacquisition"), "Reacquisition")
        require(
            text_field(reacquisition, "session_id") != fault_id,
            "Reacquisition reused the faulted session",
        )
        require(
            reacquisition.get("profile_removed") is True,
            "Reacquired profile was not removed",
        )
    require(observed == RECOVERY_SCENARIOS, "A required recovery scenario is absent")


def validate_proxy(data: dict[str, Any], manager: bool) -> None:
    """Require actual routing, rejection, credential isolation, and cleanup counters.

    Args:
        data: Browser-routing or manager-authentication proxy result.
        manager: Whether the expected run is the manager authentication acceptance.
    """
    empty_list(data, "remaining_fixture_threads")
    require(integer(data, "remaining_owned_tasks") == 0, "Proxy run retained tasks")
    routing = mapping(data.get("routing"), "Proxy routing")
    for key in (
        "forwarded",
        "origin_hits",
        "rejected",
        "direct_rejected",
        "connects",
        "tls_origin_hits",
        "auth_rejected",
        "credential_leaks",
        "active_tunnels",
        "tunnel_bytes",
    ):
        integer(routing, key)
    for key in ("origin_hits", "connects", "tls_origin_hits", "tunnel_bytes"):
        require(routing[key] > 0, f"{key} contains no actual HTTPS proxy evidence")
    require(
        routing["active_tunnels"] == 0 and routing["credential_leaks"] == 0,
        "Proxy retained tunnels or leaked credentials",
    )
    if manager:
        require(
            data.get("client") == "manager HTTPS transport", "Wrong proxy client kind"
        )
        require(
            data.get("authentication_required") is True,
            "Manager proxy authentication was not enabled",
        )
        cases = mapping(data.get("cases"), "Manager proxy cases")
        require(
            set(cases) == MANAGER_PROXY_CASES
            and all(value == "passed" for value in cases.values()),
            "Manager proxy must pass every required authentication/routing case",
        )
        require(
            integer(data, "closed_clients", 5) >= 5,
            "Manager proxy did not close every request client",
        )
        require(
            routing["auth_rejected"] >= 2
            and routing["direct_rejected"] >= 1
            and routing["rejected"] >= 1,
            "Manager proxy rejection evidence is incomplete",
        )
        text_field(data, "tls_verification")
    else:
        require(
            data.get("scheme") == "both", "Browser proxy must exercise HTTP and HTTPS"
        )
        require(
            routing["forwarded"] >= 1 and routing["origin_hits"] >= 2,
            "Browser proxy did not prove both HTTP and HTTPS routing",
        )
        clean_session(data)


def validate_soak(data: dict[str, Any], duration: int) -> None:
    """Require the requested sustained workload and independently recheck resource budgets.

    Args:
        data: Long-lived session report with resource observations.
        duration: Exact sustained duration requested by the parent controller.
    """
    require(data.get("mode") == "long-lived", "Wrong soak mode")
    require(
        number(data, "requested_duration_seconds", 1) == duration,
        "Soak used a different requested duration",
    )
    elapsed = number(data, "workload_elapsed_seconds", duration)
    iterations = integer(data, "iterations", 1)
    require(
        integer(data, "controlled_native_script_timeouts", 1) == (iterations + 9) // 10,
        "Controlled script-timeout count is inconsistent",
    )
    text_field(data, "session_id")
    clean_session(data)
    for key in ("session_profile_removed", "template_profile_removed"):
        require(data.get(key) is True, f"{key} did not prove cleanup")
    limits = mapping(data.get("growth_limits"), "Soak growth limits")
    for key, expected in GROWTH_LIMITS.items():
        require(number(limits, key) == expected, f"Unexpected {key} growth budget")
    baseline = mapping(data.get("baseline"), "Soak baseline")
    bound = {
        "rss_bytes": limits["python_rss_mib"] * 1024 * 1024,
        "owned_rss_bytes": limits["browser_tree_rss_mib"] * 1024 * 1024,
        "handles": limits["handles"],
        "owned_processes": limits["processes"],
    }
    for key in bound:
        integer(baseline, key, 1 if key != "handles" else 0)
    samples = data.get("resource_samples")
    require(
        type(samples) is list and len(samples) > 0, "Soak resource samples are missing"
    )
    previous_iteration, previous_time = 0, -1.0
    for raw in cast(list[object], samples):
        sample = mapping(raw, "Soak resource sample")
        sample_iteration = integer(sample, "iteration", 1)
        sample_time = number(sample, "elapsed_seconds")
        require(
            previous_iteration < sample_iteration <= iterations
            and previous_time <= sample_time <= elapsed,
            "Soak samples are out of order or exceed the measured workload",
        )
        previous_iteration, previous_time = sample_iteration, sample_time
        for key, maximum in bound.items():
            require(
                integer(sample, key) - baseline[key] <= maximum,
                f"Observed {key} exceeds its growth budget",
            )
    first = mapping(cast(list[object], samples)[0], "First soak sample")
    require(
        first["iteration"] == 1 and all(first[key] == baseline[key] for key in bound),
        "Soak baseline does not match its first post-warmup sample",
    )
    last = mapping(data.get("last_sample"), "Final soak sample")
    require(
        integer(last, "iteration", 1) == iterations,
        "Final sample does not match the workload iteration count",
    )
    require(
        previous_time <= number(last, "elapsed_seconds") <= elapsed,
        "Final sample timing is inconsistent",
    )
    for key, maximum in bound.items():
        require(
            integer(last, key) - baseline[key] <= maximum,
            f"Final {key} exceeds its growth budget",
        )


def validate_report(name: str, value: object, browser: str, duration: int) -> None:
    """Accept only complete evidence for the specifically requested child harness.

    Args:
        name: Named reliability gate selected by this controller.
        value: Decoded child report, not assumed to be an object or successful.
        browser: Browser requested by the parent controller.
        duration: Sustained workload duration requested by the parent controller.
    """
    data = mapping(value, f"{name} report")
    require(data.get("status") == "passed", f"{name} did not pass")
    for key in ("python", "platform"):
        text_field(data, key)
    if name != "manager-proxy-auth":
        require(data.get("browser") == browser, f"{name} ran the wrong browser")
    if name == "recovery":
        validate_recovery(data)
    elif name == "browser-proxy":
        validate_proxy(data, manager=False)
    elif name == "manager-proxy-auth":
        validate_proxy(data, manager=True)
    elif name == "long-lived":
        validate_soak(data, duration)
    else:
        raise ValueError(f"Unknown reliability gate: {name}")


def commands(args: argparse.Namespace, binary: str) -> list[tuple[str, list[str], int]]:
    """Build explicit argument vectors for the existing independently testable harnesses.

    Args:
        args: Interpreter, browser, cache, duration and output configuration.
        binary: Verified preinstalled browser executable.

    Returns:
        Named command vectors and bounded external timeouts in seconds.
    """
    python = str(args.python.absolute())
    common = [
        "--browser",
        args.browser,
        "--binary",
        binary,
        "--cache-dir",
        str(args.cache_dir.absolute()),
    ]
    return [
        (
            "recovery",
            [
                python,
                str(ROOT / "scripts/test_browser_recovery.py"),
                *common,
                "--scenario",
                "all",
                "--command-timeout",
                str(RECOVERY_COMMAND_TIMEOUT),
            ],
            240,
        ),
        (
            "browser-proxy",
            [
                python,
                str(ROOT / "scripts/test_browser_proxy.py"),
                *common,
                "--scheme",
                "both",
            ],
            120,
        ),
        (
            "manager-proxy-auth",
            [
                python,
                str(ROOT / "scripts/test_browser_proxy.py"),
                "--client",
                "manager",
                "--proxy-auth",
            ],
            120,
        ),
        (
            "long-lived",
            [
                python,
                str(ROOT / "scripts/soak_browser.py"),
                *common,
                "--mode",
                "long-lived",
                "--duration",
                str(args.duration),
                "--max-rss-growth-mib",
                str(GROWTH_LIMITS["python_rss_mib"]),
                "--max-browser-rss-growth-mib",
                str(GROWTH_LIMITS["browser_tree_rss_mib"]),
                "--max-handle-growth",
                str(GROWTH_LIMITS["handles"]),
                "--max-process-growth",
                str(GROWTH_LIMITS["processes"]),
            ],
            args.duration + 120,
        ),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Run every reliability gate and retain reports even when another gate fails.

    Args:
        argv: Arguments, or None to read the process command line.

    Returns:
        Zero only if every harness finishes successfully and reports passed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--browser", choices=("chrome", "edge"), required=True)
    parser.add_argument("--binary")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=30)
    args = parser.parse_args(argv)
    if not 1 <= args.duration <= 3600:
        parser.error("duration must be between 1 and 3600 seconds")
    binary = browser_binary(args.browser, args.binary)
    parent = args.output_dir.absolute()
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=args.browser + "-", dir=parent))
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "MYPYPATH"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    results: dict[str, Any] = {}
    for name, command, timeout in commands(args, binary):
        report = output / f"{args.browser}-{name}.json"
        try:
            result = run_owned(
                [*command, "--output", str(report)],
                timeout=timeout,
                cwd=output,
                env=environment,
            )
            (output / f"{args.browser}-{name}.log").write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
            data = (
                json.loads(report.read_text(encoding="utf-8"))
                if report.is_file()
                else {}
            )
            require(result.returncode == 0, f"{name} exited with {result.returncode}")
            validate_report(name, data, args.browser, args.duration)
            results[name] = {
                "status": "passed",
                "exit_code": result.returncode,
                "report": str(report),
            }
        except (
            OSError,
            ValueError,
            subprocess.TimeoutExpired,
            OwnedProcessError,
        ) as cause:
            if isinstance(cause, (subprocess.TimeoutExpired, OwnedProcessError)):
                (output / f"{args.browser}-{name}.log").write_text(
                    str(cause.stdout or "")
                    + str(cause.stderr or "")
                    + "\n"
                    + str(cause),
                    encoding="utf-8",
                )
            results[name] = {
                "status": "failed",
                "error": type(cause).__name__,
                "message": str(cause),
            }
            log = output / f"{args.browser}-{name}.log"
            try:
                details = log.read_text(encoding="utf-8")
            except OSError:
                details = ""
            emit_workflow_error(
                f"{args.browser} {name} reliability gate failed",
                f"{details}\n{type(cause).__name__}: {cause}".strip(),
            )
        print(json.dumps({name: results[name]}), flush=True)
    passed = all(result["status"] == "passed" for result in results.values())
    summary = {
        "status": "passed" if passed else "failed",
        "browser": args.browser,
        "duration_seconds": args.duration,
        "checks": results,
    }
    (output / f"{args.browser}-reliability.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return int(not passed)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as cause:
        emit_workflow_error(
            "Native-browser reliability controller failed",
            f"{type(cause).__name__}: {cause}",
        )
        raise
