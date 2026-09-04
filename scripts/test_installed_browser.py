"""Run the complete local feature tour from an installed wheel, outside the checkout.

The selected interpreter must already contain a non-editable Aselenium install.
This harness never installs dependencies, enables Safari, or reads personal profiles.
Vendor downloads require --allow-download. Unexpected skips fail acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from _owned_subprocess import OwnedProcessError, run_owned
from _workflow_commands import emit_workflow_error

ROOT = Path(__file__).resolve().parents[1]
STAGES = {
    "driver-management",
    "options",
    "navigation",
    "elements",
    "waits",
    "cookies",
    "windows",
    "frames",
    "alerts",
    "scripts",
    "actions",
    "artifacts",
    "vendor",
    "concurrency",
    "cancellation",
}
SAFARI_SKIPS = {
    "frames": "The current Safari facade disables frame switching",
    "actions": "The current Safari facade disables W3C action chains",
    "concurrency": "Safari's automation service is single-session; no concurrent tour",
}
IDENTITY = """import json, sys, aselenium
from pathlib import Path
from importlib.metadata import version
location = Path(aselenium.__file__).resolve()
prefix = Path(sys.prefix).resolve()
checkout = Path(sys.argv[1]).resolve()
if location.is_relative_to(checkout) or not location.is_relative_to(prefix):
    raise SystemExit('Acceptance requires a non-editable install in the selected environment')
print(json.dumps({'package': str(location), 'prefix': str(prefix),
                  'version': version('aselenium'), 'python': sys.version}))
"""


def browser_binary(browser: str, explicit: str | None = None) -> str:
    """Locate a preinstalled browser without downloading or launching it.

    Args:
        browser: Supported browser name.
        explicit: Optional executable override, never an application directory.

    Returns:
        Absolute executable path.

    Raises:
        FileNotFoundError: No candidate is installed.
    """
    names = {
        "chrome": ["google-chrome", "google-chrome-stable", "chrome"],
        "edge": ["microsoft-edge", "msedge"],
        "firefox": ["firefox"],
        "safari": [],
    }
    applications = {
        "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "firefox": "/Applications/Firefox.app/Contents/MacOS/firefox",
        "safari": "/Applications/Safari.app/Contents/MacOS/Safari",
    }
    windows = {
        "chrome": "Google/Chrome/Application/chrome.exe",
        "edge": "Microsoft/Edge/Application/msedge.exe",
        "firefox": "Mozilla Firefox/firefox.exe",
        "safari": "",
    }
    if explicit:
        candidates = [Path(explicit).expanduser()]
    else:
        candidates = [
            Path(path) for name in names[browser] if (path := shutil.which(name))
        ]
        if sys.platform == "darwin":
            candidates.append(Path(applications[browser]))
        elif sys.platform == "win32" and windows[browser]:
            candidates.extend(
                Path(base) / windows[browser]
                for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
                if (base := os.environ.get(name))
            )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.absolute())
    raise FileNotFoundError(f"Install {browser} or supply --binary with its executable")


def validate_report(report: dict[str, Any], browser: str) -> None:
    """Require every feature stage, permitting only documented Safari exclusions.

    Args:
        report: Feature-tour JSON report.
        browser: Browser expected for this acceptance job.

    Raises:
        ValueError: A required stage is absent, duplicated, skipped or unsuccessful.
    """
    if report.get("browser") != browser or report.get("status") != "passed":
        raise ValueError("Browser tour did not pass for the requested browser")
    entries = report.get("sections", [])
    names = [entry.get("section") for entry in entries]
    if len(names) != len(STAGES) or set(names) != STAGES:
        raise ValueError("Acceptance requires each feature stage exactly once")
    for entry in entries:
        name = entry["section"]
        if browser == "safari" and name in SAFARI_SKIPS:
            if (
                entry.get("status") == "skipped"
                and entry.get("reason") == SAFARI_SKIPS[name]
            ):
                continue
        if entry.get("status") != "passed":
            raise ValueError(
                f"Required stage {name} did not pass: {entry.get('status')}"
            )
    session = report.get("session", {})
    if not session.get("browser_version") or not session.get("driver_version"):
        raise ValueError("Acceptance must record actual browser and driver versions")


def firefox_profile_parent(browser: str) -> Path | None:
    """Select the shared filesystem parent required by containerized Firefox.

    Ubuntu's Firefox package uses Snap confinement and may not see the host
    process's private temporary directory. A non-hidden directory under the
    current user's home is visible to both Firefox and the host GeckoDriver.

    Args:
        browser: Browser selected for the installed-wheel acceptance tour.

    Returns:
        The existing home directory for Linux Firefox, or None when the
        platform/browser does not require the container workaround.
    """
    if browser == "firefox" and sys.platform.startswith("linux"):
        return Path.home()
    return None


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Copy only demo fixtures and execute them using the installed-package interpreter.

    Args:
        args: Validated command-line settings.

    Returns:
        Package identity and validated browser feature report.
    """
    binary = browser_binary(args.browser, args.binary)
    executable = str(args.python.absolute())
    parent = args.output_dir.absolute()
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(
        tempfile.mkdtemp(prefix="installed-" + args.browser + "-", dir=parent)
    )
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "MYPYPATH"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    with ExitStack() as resources:
        profile_root: Path | None = None
        working_parent = firefox_profile_parent(args.browser)
        if working_parent is not None:
            profile_root = Path(
                resources.enter_context(
                    tempfile.TemporaryDirectory(
                        prefix="aselenium-firefox-profile-root-", dir=working_parent
                    )
                )
            )
        directory = resources.enter_context(
            tempfile.TemporaryDirectory(
                prefix="aselenium-installed-tour-", dir=profile_root
            )
        )
        working = Path(directory)
        identity = subprocess.run(
            [executable, "-I", "-c", IDENTITY, str(ROOT)],
            cwd=working,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        for name in ("demo_local.py", "_demo_support.py"):
            shutil.copy2(ROOT / "src" / name, working / name)
        shutil.copytree(ROOT / "src/demo_assets", working / "demo_assets")
        # The bootstrap checks origin again in the very process running the tour.
        bootstrap = (
            IDENTITY
            + "\nimport runpy\nsys.argv = sys.argv[2:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
        )
        command = [
            executable,
            "-c",
            bootstrap,
            str(ROOT),
            str(working / "demo_local.py"),
            "run",
            "--browser",
            args.browser,
            "--binary",
            binary,
            "--cache-dir",
            str(args.cache_dir.absolute()),
            "--output-dir",
            str(output),
            "--timeout",
            str(args.timeout),
            "--session-timeout",
            "60" if working_parent is not None else "30",
        ]
        if args.allow_download:
            command.append("--allow-download")
        if args.browser != "safari":
            command.append("--profile-demo")
        if profile_root is not None:
            command.extend(["--profile-root", str(profile_root)])
        before = set(output.glob("local-*/report.json"))
        try:
            completed = run_owned(
                command, cwd=working, env=environment, timeout=args.timeout + 90
            )
        except (subprocess.TimeoutExpired, OwnedProcessError) as cause:
            (output / "harness-failure.log").write_text(
                str(cause)
                + "\n"
                + str(cause.stdout or "")
                + "\n"
                + str(cause.stderr or ""),
                encoding="utf-8",
            )
            raise
        reports = set(output.glob("local-*/report.json")) - before
        if completed.returncode or len(reports) != 1:
            (output / "harness-failure.log").write_text(
                completed.stdout + completed.stderr, encoding="utf-8"
            )
            raise RuntimeError(
                f"Installed tour failed ({completed.returncode})\n"
                f"{completed.stdout[-12000:]}\n{completed.stderr[-4000:]}"
            )
        report_path = reports.pop()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_report(report, args.browser)
        result = {
            "installed": json.loads(identity.stdout),
            "report": str(report_path),
            "tour": report,
        }
        (report_path.parent / "installed-acceptance.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run explicit installed-browser acceptance and return its exit status.

    Args:
        argv: Arguments, or None to read the process command line.

    Returns:
        Zero for a fully accepted tour; failures raise with retained diagnostics.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument(
        "--browser", choices=("chrome", "edge", "firefox", "safari"), required=True
    )
    parser.add_argument("--binary")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    if not 30 <= args.timeout <= 1800:
        parser.error("--timeout must be between 30 and 1800 seconds")
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as cause:
        emit_workflow_error(
            "Installed-browser acceptance failed",
            f"{type(cause).__name__}: {cause}",
        )
        raise
