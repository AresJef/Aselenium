"""Opt-in crash/hang acceptance for explicitly selected disposable browsers.

The fixture acknowledges a real, outstanding async WebDriver command before
fault injection. Signals target only a freshly acquired service and its observed
descendants, guarded by PID/create-time identities. Personal processes are never
searched by name or signalled. Native execution is intentionally opt-in.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from secrets import token_hex
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Iterator, cast

import psutil

from aselenium import Chrome, Edge, errors
from aselenium.command import Command

if TYPE_CHECKING:
    from aselenium.options import ChromiumBaseOptions
    from aselenium.session import Session

SCENARIOS = ("browser-crash", "driver-crash", "browser-hang", "driver-hang")
HOLD_SCRIPT = "fetch(arguments[0], {cache:'no-store'}).then(() => {window.recoveryCommandStarted=true;});"
PAGE = b"<!doctype html><title>Aselenium recovery fixture</title><link rel='icon' href='data:,'><input id='field'>"
USER_DATA_DIR_FLAG = "--user-data-dir"
SETUP_COMMAND_TIMEOUT = 30
SCENARIO_TIMEOUT = 120


@dataclass(frozen=True)
class OwnedProcess:
    """Record one process observed beneath the explicitly owned service.

    Attributes:
        pid: Observed process identifier.
        created: OS process creation time guarding against PID reuse.
        owner_pid: Python harness process that proved ownership at capture time.
        service_pid: Service root from which this process was discovered.
    """

    pid: int
    created: float
    owner_pid: int
    service_pid: int


@dataclass(frozen=True)
class FaultTarget:
    """Retain one selected process identity and its observed executable.

    Attributes:
        identity: Revalidated process identity eligible for fault injection.
        executable: Executable observed while the process was still selectable.
    """

    identity: OwnedProcess
    executable: str


def capture_owned(service_process: psutil.Process) -> list[OwnedProcess]:
    """Capture only the current harness's direct service and its descendants.

    Args:
        service_process: Service process returned by the acquired session.

    Returns:
        Stable process identities eligible for later observation and cleanup.

    Raises:
        RuntimeError: The supplied service is not a direct child of this harness.
    """
    owner = os.getpid()
    try:
        parent = service_process.ppid()
    except psutil.NoSuchProcess as cause:
        raise RuntimeError(
            "Owned service exited while its process tree was captured"
        ) from cause
    if parent != owner or service_process.pid == owner:
        raise RuntimeError("Refusing a service not directly owned by this harness")
    try:
        service_created = service_process.create_time()
        descendants = service_process.children(recursive=True)
    except psutil.NoSuchProcess as cause:
        raise RuntimeError(
            "Owned service exited while its process tree was captured"
        ) from cause
    identities = [
        OwnedProcess(service_process.pid, service_created, owner, service_process.pid)
    ]
    for process in descendants:
        try:
            identities.append(
                OwnedProcess(
                    process.pid, process.create_time(), owner, service_process.pid
                )
            )
        except psutil.NoSuchProcess:
            continue
    return identities


def current_process(identity: OwnedProcess) -> psutil.Process | None:
    """Revalidate ownership and creation time before any process observation/action.

    Args:
        identity: Identity previously captured from an owned service tree.

    Returns:
        The same live process, or None if it exited or its PID was reused.

    Raises:
        RuntimeError: Ownership identifies another Python harness or this process.
    """
    if identity.owner_pid != os.getpid() or identity.pid == os.getpid():
        raise RuntimeError("Refusing an identity not owned by this harness")
    try:
        process = psutil.Process(identity.pid)
        if (
            process.create_time() != identity.created
            or process.status() == psutil.STATUS_ZOMBIE
        ):
            return None
        return process
    except psutil.NoSuchProcess:
        return None


def signal_owned(identity: OwnedProcess, action: str) -> bool:
    """Apply one approved process action after rechecking the captured identity.

    Args:
        identity: Captured service-tree identity.
        action: One of kill, suspend, or resume.

    Returns:
        True if the same process received the action; False if it already exited.

    Raises:
        ValueError: The action is not explicitly allowlisted.
    """
    if action not in {"kill", "suspend", "resume"}:
        raise ValueError("Only kill, suspend, and resume are admitted")
    process = current_process(identity)
    if process is None:
        return False
    try:
        getattr(process, action)()
    except psutil.NoSuchProcess:
        return False
    return True


def _user_data_dir_argument(arguments: list[str]) -> str | None:
    """Extract one unambiguous Chromium profile argument without shell parsing.

    Args:
        arguments: Process arguments returned as already-tokenized strings.

    Returns:
        The profile value from either supported flag form, or None when the flag
        is absent, malformed, empty, or repeated.
    """
    values: list[str] = []
    index = 0
    assignment_prefix = USER_DATA_DIR_FLAG + "="
    while index < len(arguments):
        argument = arguments[index]
        if argument == USER_DATA_DIR_FLAG:
            index += 1
            if index >= len(arguments):
                return None
            values.append(arguments[index])
        elif argument.startswith(assignment_prefix):
            values.append(argument[len(assignment_prefix) :])
        index += 1
    if len(values) != 1 or not values[0]:
        return None
    return values[0]


def _windows_profile_path(value: str) -> PureWindowsPath | None:
    """Create a conservative lexical Windows path for identity comparison.

    Args:
        value: Native command-line path spelling.

    Returns:
        An absolute Windows path with a standard drive or UNC anchor, or None
        for relative, malformed, and unsupported device-namespace paths.
    """
    if not value or "\x00" in value:
        return None
    normalized = value.replace("/", "\\")
    if normalized.casefold().startswith("\\\\.\\".casefold()):
        return None
    extended_prefix = "\\\\?\\"
    if normalized.casefold().startswith(extended_prefix.casefold()):
        remainder = normalized[len(extended_prefix) :]
        if remainder.casefold().startswith("unc\\"):
            normalized = "\\\\" + remainder[4:]
        else:
            unprefixed = PureWindowsPath(remainder)
            if not (
                len(unprefixed.drive) == 2
                and unprefixed.drive.endswith(":")
                and bool(unprefixed.root)
            ):
                return None
            normalized = remainder
    try:
        parsed = PureWindowsPath(normalized)
    except ValueError:
        return None
    return parsed if parsed.is_absolute() else None


def _same_existing_path(candidate: Path, expected: Path) -> bool:
    """Compare existing paths by filesystem identity without resolving either.

    Args:
        candidate: Path reported by the owned browser process.
        expected: Fresh profile path created by this harness.

    Returns:
        True only when both paths exist and identify the same filesystem object.
    """
    try:
        return candidate.exists() and expected.exists() and candidate.samefile(expected)
    except (OSError, ValueError):
        return False


def _profile_path_matches(
    candidate_value: str, expected: Path, *, windows: bool
) -> bool:
    """Match a browser-reported profile to the harness-owned profile safely.

    Args:
        candidate_value: Value extracted from the browser command line.
        expected: Parsed fresh profile path owned by this acquisition.
        windows: Whether to apply native Windows lexical path rules.

    Returns:
        True for the same safe profile pathname or existing filesystem object.
    """
    if windows:
        candidate_lexical = _windows_profile_path(candidate_value)
        expected_lexical = _windows_profile_path(str(expected))
        if candidate_lexical is None or expected_lexical is None:
            return False
        if candidate_lexical == expected_lexical:
            return True
        # Limit filesystem probing to the already-selected drive/share. In
        # particular, a local expected path must never cause an arbitrary UNC
        # path from a process command line to be contacted.
        if candidate_lexical.anchor.casefold() != expected_lexical.anchor.casefold():
            return False
        try:
            candidate = Path(candidate_value)
        except (OSError, ValueError):
            return False
        return _same_existing_path(candidate, expected)

    if candidate_value == str(expected):
        return True
    try:
        candidate = Path(candidate_value)
    except (OSError, ValueError):
        return False
    if not candidate.is_absolute() or not expected.is_absolute():
        return False
    return _same_existing_path(candidate, expected)


def select_target(
    identities: list[OwnedProcess],
    scenario: str,
    binary: str,
    profile: str | os.PathLike[str],
) -> FaultTarget:
    """Select the service or unique fresh-profile browser from captured identities.

    Args:
        identities: Descendants captured from the owned service root.
        scenario: Driver/browser crash or hang scenario.
        binary: Explicit launcher chosen by the caller, retained for diagnostics.
            A Linux launcher may be a wrapper around the observed browser executable.
        profile: Fresh profile directory owned by this acquisition.

    Returns:
        Exactly one validated target and its observed executable.

    Raises:
        RuntimeError: The scenario does not identify exactly one safe target.
    """
    if scenario not in SCENARIOS:
        raise RuntimeError("Unknown recovery scenario")
    profile_path = profile if isinstance(profile, Path) else Path(profile)
    service_roots = [
        identity for identity in identities if identity.pid == identity.service_pid
    ]
    if len(service_roots) != 1 or current_process(service_roots[0]) is None:
        raise RuntimeError(
            "Expected one live owned service root before target selection"
        )
    selected: list[FaultTarget] = []
    for identity in identities:
        process = current_process(identity)
        if process is None:
            continue
        if scenario.startswith("driver-"):
            if identity.pid == identity.service_pid:
                try:
                    selected.append(FaultTarget(identity, process.exe()))
                except psutil.NoSuchProcess:
                    continue
        elif identity.pid != identity.service_pid:
            try:
                arguments = process.cmdline()
            except psutil.NoSuchProcess:
                # Chromium creates short-lived helpers. Their normal exit must
                # not abort selection of the still-live, uniquely owned browser.
                continue
            profile_argument = _user_data_dir_argument(arguments)
            if (
                profile_argument is not None
                and _profile_path_matches(
                    profile_argument, profile_path, windows=os.name == "nt"
                )
                and not any(
                    argument == "--type" or argument.startswith("--type=")
                    for argument in arguments
                )
            ):
                try:
                    selected.append(FaultTarget(identity, process.exe()))
                except psutil.NoSuchProcess:
                    continue
    if len(selected) != 1:
        raise RuntimeError(
            f"Expected one safely identified target for launcher {binary!r}, found {len(selected)}"
        )
    return selected[0]


async def wait_owned_exit(identity: OwnedProcess, timeout: float) -> bool:
    """Wait a bounded interval for a signalled process identity to disappear.

    Args:
        identity: Previously selected and signalled process identity.
        timeout: Maximum seconds to wait for operating-system exit observation.

    Returns:
        True when the same process has exited; False when it remains live at the
        deadline.
    """
    deadline = time.monotonic() + timeout
    while current_process(identity) is not None:
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.01)
    return True


def alive_owned(identities: list[OwnedProcess]) -> list[int]:
    """Find still-live captured identities without accepting reused PIDs.

    Args:
        identities: Previously observed owned process identities.

    Returns:
        Identifiers that still refer to the same non-zombie processes.
    """
    return [
        identity.pid for identity in identities if current_process(identity) is not None
    ]


def emergency_cleanup(identities: list[OwnedProcess]) -> list[int]:
    """Clean fixture-owned survivors after recording a library cleanup failure.

    This safety fallback must never make the acceptance result pass.

    Args:
        identities: Processes originally captured beneath the owned service root.

    Returns:
        Process identifiers on which guarded emergency termination was attempted.
    """
    killed = []
    processes = []
    for identity in reversed(identities):
        process = current_process(identity)
        if process is not None and signal_owned(identity, "kill"):
            killed.append(identity.pid)
            processes.append(process)
    psutil.wait_procs(processes, timeout=3)
    return killed


@dataclass
class PageState:
    """Store the per-scenario acknowledgement proving real browser execution.

    Attributes:
        token: Unpredictable acknowledgement path suffix.
        started: Event set only when the browser executes the async command.
    """

    token: str = field(default_factory=lambda: token_hex(16))
    started: threading.Event = field(default_factory=threading.Event)


class RecoveryServer(ThreadingHTTPServer):
    """Serve one controlled recovery page on an ephemeral IPv4 loopback port."""

    daemon_threads = False
    block_on_close = True

    def __init__(self, state: PageState) -> None:
        """Bind loopback only and retain acknowledgement state.

        Args:
            state: Per-scenario page acknowledgement state.
        """
        self.state = state
        super().__init__(("127.0.0.1", 0), RecoveryHandler)

    def handle_error(self, request: Any, client_address: tuple[str, int]) -> None:
        """Ignore only disconnects expected after an injected browser fault.

        Args:
            request: Client socket being handled when the exception occurred.
            client_address: Client host and port associated with the request.

        Notes:
            The recovery fixture deliberately kills or suspends a browser while
            an HTTP request is outstanding. Windows can surface the resulting
            socket close while the base handler is still reading the request,
            before :meth:`RecoveryHandler.do_GET` can catch it. All unrelated
            server exceptions continue through the standard error handler.
        """
        cause = sys.exc_info()[1]
        if isinstance(cause, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class RecoveryHandler(BaseHTTPRequestHandler):
    """Return a local page or acknowledge an exact per-scenario browser command."""

    def setup(self) -> None:
        """Bound idle HTTP request sockets before reading any client data."""
        self.request.settimeout(3)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:
        """Keep expected client disconnects out of JSON evidence output.

        Args:
            format: HTTP diagnostic format string, intentionally unused.
            *args: Diagnostic values, intentionally not printed.
        """

    def do_GET(self) -> None:
        """Serve only the local page and its exact acknowledgement endpoint."""
        state = cast(RecoveryServer, self.server).state
        if self.path == "/":
            status, content = 200, PAGE
        elif self.path == "/started/" + state.token:
            state.started.set()
            status, content = 200, b"acknowledged"
        else:
            status, content = 404, b"not found"
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            self.close_connection = True


@contextmanager
def local_page(state: PageState) -> Iterator[str]:
    """Own a loopback page server and always join its listener/request threads.

    Args:
        state: Per-scenario acknowledgement state.

    Yields:
        The root URL of the controlled loopback page.
    """
    server = RecoveryServer(state)
    listener = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        name="aselenium-recovery-fixture",
    )
    try:
        listener.start()
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        if listener.is_alive():
            server.shutdown()
        server.server_close()
        if listener.ident is not None:
            listener.join(timeout=5)
        if listener.is_alive():
            raise RuntimeError("Recovery fixture listener remained alive")


async def await_started(state: PageState, command: asyncio.Task[Any]) -> None:
    """Wait briefly for browser acknowledgement while checking command liveness.

    Args:
        state: Acknowledgement set by the local HTTP handler.
        command: The actual in-flight WebDriver command.

    Raises:
        RuntimeError: The command completed prematurely or no acknowledgement arrived.
    """
    deadline = time.monotonic() + 3
    while not state.started.is_set():
        if command.done():
            raise RuntimeError("Command finished before browser acknowledgement")
        if time.monotonic() >= deadline:
            raise RuntimeError("Browser did not acknowledge the outstanding command")
        await asyncio.sleep(0.01)
    if command.done():
        raise RuntimeError("Command was not outstanding at fault injection")


def validate_injection_window(
    command: asyncio.Task[Any], started: float, timeout: float
) -> None:
    """Reject a completed or nearly expired command immediately before signalling.

    Args:
        command: Acknowledged real command that must still be outstanding.
        started: Monotonic timestamp taken before the command task was created.
        timeout: Command's configured total timeout in seconds.

    Raises:
        RuntimeError: Completion or insufficient remaining time would confuse causality.
    """
    if command.done() or time.monotonic() - started >= timeout - 0.5:
        raise RuntimeError(
            "Command finished or approached its deadline before fault injection"
        )


def owned_profile_directory(options: ChromiumBaseOptions) -> Path:
    """Return the active owned Chromium profile directory as a concrete path.

    Args:
        options: Chromium options expected to own a cloned temporary profile.

    Returns:
        The active temporary profile directory.

    Raises:
        RuntimeError: The recovery fixture has no active owned profile directory.
    """
    profile = options.profile
    if profile is None or profile.directory_temp is None:
        raise RuntimeError("Recovery fixture requires an active owned profile")
    return Path(profile.directory_temp)


async def verify_fresh_session(
    driver: Chrome | Edge, binary: str, url: str
) -> dict[str, Any]:
    """Acquire a new independent session and verify DOM/script/input usability.

    Args:
        driver: Facade whose previous session underwent fault injection.
        binary: Explicit browser executable to reuse.
        url: Controlled local page URL.

    Returns:
        Fresh-session identifier and confirmation that its profile was removed.
    """
    context = driver.acquire("offline", binary=binary)
    async with context as session:
        profile = owned_profile_directory(session.options)
        identifier = session.id
        await session.load(url)
        element = await session.find_element("#field")
        if element is None:
            raise AssertionError("Fresh acquisition did not find its local input")
        await element.send("recovered")
        if await element.get_property("value") != "recovered":
            raise AssertionError("Fresh acquisition input did not retain typed text")
        if (
            await session.execute_script("return document.title")
            != "Aselenium recovery fixture"
        ):
            raise AssertionError(
                "Fresh acquisition script returned the wrong local page"
            )
    if profile.exists():
        raise AssertionError("Fresh acquisition left its owned profile behind")
    return {"session_id": identifier, "profile_removed": True}


async def execute_fault_command(
    session: Session, acknowledgement: str, timeout: float
) -> dict[str, Any]:
    """Dispatch the held script with its own strict transport deadline.

    Args:
        session: Active disposable session with a separate normal setup budget.
        acknowledgement: Exact local path proving the script began executing.
        timeout: Faulted-command deadline in seconds, independent of startup,
            navigation, teardown, and fresh-session verification.

    Returns:
        The WebDriver response if the held command unexpectedly succeeds.
        The recovery scenario requires an expected WebDriver error instead.
    """
    return await session.execute_command(
        Command.W3C_EXECUTE_SCRIPT_ASYNC,
        body={"script": HOLD_SCRIPT, "args": [acknowledgement]},
        timeout=timeout,
    )


async def scenario_run(args: argparse.Namespace, scenario: str) -> dict[str, Any]:
    """Inject one fault, record library cleanup, and verify independent reacquisition.

    Args:
        args: Browser binary/cache and configured command deadline.
        scenario: Explicit browser/driver crash/hang scenario.

    Returns:
        Acceptance evidence, including cleanup failures before harness intervention.
    """
    state = PageState()
    initial_tasks = set(asyncio.all_tasks())
    selected_launcher = await asyncio.to_thread(Path(args.binary).resolve)
    result: dict[str, Any] = {"scenario": scenario, "status": "failed"}
    with (
        TemporaryDirectory(prefix="aselenium-recovery-template-") as template,
        local_page(state) as url,
    ):
        (Path(template) / "Default").mkdir()
        driver = (Chrome if args.browser == "chrome" else Edge)(
            directory=args.cache_dir, service_timeout=3
        )
        driver.options.add_arguments(
            "--headless=new",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
        )
        driver.options.set_profile(template, "Default")
        driver.options.set_timeouts(implicit=0, pageLoad=10, script=30)
        # Cold startup and fixture navigation are not the fault-injection test.
        # Only the acknowledged held command uses the strict recovery deadline.
        driver.options.session_timeout = SETUP_COMMAND_TIMEOUT
        template_profile = owned_profile_directory(driver.options)
        identities: list[OwnedProcess] = []
        context = driver.acquire("offline", binary=args.binary)
        profile = owned_profile_directory(cast("ChromiumBaseOptions", context._options))
        pending: asyncio.Task[Any] | None = None
        suspended: OwnedProcess | None = None
        failure: BaseException | None = None
        try:
            try:
                async with context as session:
                    result["fault_session_id"] = session.id
                    await session.load(url)
                    identities = capture_owned(session.service.process)
                    command_started = time.monotonic()
                    pending = asyncio.create_task(
                        execute_fault_command(
                            session, "/started/" + state.token, args.command_timeout
                        )
                    )
                    await await_started(state, pending)
                    identities = capture_owned(session.service.process)
                    selected = select_target(identities, scenario, args.binary, profile)
                    target = selected.identity
                    result["target"] = asdict(target)
                    result["target_executable"] = selected.executable
                    result["selected_launcher"] = str(selected_launcher)
                    result["command_acknowledged_before_fault"] = True
                    validate_injection_window(
                        pending, command_started, args.command_timeout
                    )
                    injected = time.monotonic()
                    if scenario.endswith("hang"):
                        result["fault_signal_sent"] = signal_owned(target, "suspend")
                        if not result["fault_signal_sent"]:
                            raise RuntimeError("Target exited before hang injection")
                        suspended = target
                    else:
                        result["fault_signal_sent"] = signal_owned(target, "kill")
                        if not result["fault_signal_sent"]:
                            raise RuntimeError("Target exited before crash injection")
                        exit_timeout = min(3.0, args.command_timeout - 1)
                        if not await wait_owned_exit(target, exit_timeout):
                            raise RuntimeError(
                                "Target remained live after crash injection"
                            )
                    try:
                        await asyncio.wait_for(
                            pending, timeout=args.command_timeout + 2
                        )
                    except errors.WebDriverError as cause:
                        result["command_failure_type"] = type(cause).__name__
                        result["failure_after_injection_seconds"] = (
                            time.monotonic() - injected
                        )
                    else:
                        raise AssertionError(
                            "Outstanding command unexpectedly succeeded after fault injection"
                        )
                    finally:
                        if suspended is not None:
                            signal_owned(suspended, "resume")
                            suspended = None
            except Exception as cause:
                failure = cause
                result["failure_type"] = type(cause).__name__
                result["failure"] = str(cause)
            finally:
                if suspended is not None:
                    signal_owned(suspended, "resume")
                if pending is not None and not pending.done():
                    pending.cancel()
                if pending is not None:
                    await asyncio.gather(pending, return_exceptions=True)
                survivors = alive_owned(identities)
                result["library_cleanup_survivors"] = survivors
                result["library_profile_removed"] = not profile.exists()
                result["harness_emergency_cleanup"] = []
                if survivors:
                    result["harness_emergency_cleanup"] = await asyncio.to_thread(
                        emergency_cleanup, identities
                    )
                if survivors or profile.exists():
                    try:
                        await context.quit()
                    except Exception as cause:
                        result["cleanup_retry_error"] = type(cause).__name__
                    finally:
                        context._options.close()
            result["reacquisition"] = await verify_fresh_session(
                driver, args.binary, url
            )
            if result["reacquisition"]["session_id"] == result.get("fault_session_id"):
                raise AssertionError(
                    "Reacquisition reused the faulted session identifier"
                )
            result["status"] = (
                "passed"
                if failure is None
                and not result["library_cleanup_survivors"]
                and result["library_profile_removed"]
                and result.get("fault_signal_sent") is True
                and result.get("command_failure_type")
                else "failed"
            )
            installation = driver.manager.last_result
            result["browser_version"] = (
                installation.browser_version if installation else None
            )
            result["driver_version"] = (
                installation.driver_version if installation else None
            )
        finally:
            driver.options.close()
            result["template_profile_removed"] = not template_profile.exists()
        result["remaining_owned_tasks"] = len(
            [task for task in asyncio.all_tasks() - initial_tasks if not task.done()]
        )
        result["remaining_observed_processes"] = alive_owned(identities)
        if (
            result["remaining_owned_tasks"]
            or result["remaining_observed_processes"]
            or not result["template_profile_removed"]
        ):
            result["status"] = "failed"
    return result


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """Run selected scenarios sequentially with independent profiles and deadlines.

    Args:
        args: Explicit browser/binary/cache and scenario selection.

    Returns:
        Per-scenario acceptance results and environment metadata.
    """
    results = []
    for scenario in SCENARIOS if args.scenario == "all" else (args.scenario,):
        try:
            result = await asyncio.wait_for(
                scenario_run(args, scenario), timeout=SCENARIO_TIMEOUT
            )
        except Exception as cause:
            result = {
                "scenario": scenario,
                "status": "failed",
                "failure_type": type(cause).__name__,
                "failure": str(cause),
            }
        results.append(result)
    return {
        "status": "passed"
        if all(result["status"] == "passed" for result in results)
        else "failed",
        "browser": args.browser,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scenarios": results,
        "scope": "owned process faults during acknowledged in-flight commands; local page; offline cache; fresh profiles; no personal processes",
    }


def main() -> int:
    """Run explicitly requested process-fault acceptance and print JSON evidence.

    Returns:
        Zero only if every selected scenario fails safely, cleans up, and reacquires.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=("chrome", "edge"), required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=5,
        help="Faulted-command deadline; setup and fresh sessions retain 30 seconds",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 4 <= args.command_timeout <= 10:
        parser.error("command-timeout must be between 4 and 10 seconds")
    initial_threads = set(threading.enumerate())
    result = asyncio.run(run(args))
    result["remaining_fixture_threads"] = [
        thread.name
        for thread in set(threading.enumerate()) - initial_threads
        if thread.is_alive()
    ]
    if result["remaining_fixture_threads"]:
        result["status"] = "failed"
    serialized = json.dumps(result, indent=2)
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
