"""Offline safety and teardown checks for opt-in browser recovery acceptance."""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psutil
import pytest

from aselenium import errors
from aselenium.manager.version import ChromiumVersion
from aselenium.service import ChromiumBaseService


@pytest.fixture
def recovery(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the opt-in fixture without binding sockets or launching processes.

    Args:
        monkeypatch: Fixture restoring temporary module registration.

    Returns:
        Recovery harness module with native operations still explicitly opt-in.
    """
    path = Path(__file__).resolve().parents[1] / "scripts" / "test_browser_recovery.py"
    spec = importlib.util.spec_from_file_location("aselenium_recovery_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def fake_process(pid: int, created: float = 10, parent: int | None = None) -> Mock:
    """Create an inert process double with controllable identity and ancestry.

    Args:
        pid: Synthetic process identifier.
        created: Synthetic process creation time.
        parent: Parent ID, defaulting to this test process.

    Returns:
        Process double whose signal methods only record calls.
    """
    process = Mock()
    process.pid = pid
    process.create_time.return_value = created
    process.ppid.return_value = os.getpid() if parent is None else parent
    process.status.return_value = psutil.STATUS_RUNNING
    process.children.return_value = []
    return process


@pytest.mark.parametrize(
    "error_type", (BrokenPipeError, ConnectionResetError, TimeoutError)
)
def test_recovery_server_ignores_expected_fault_disconnects(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[OSError],
) -> None:
    """Suppress only socket failures caused by deliberate browser interruption.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture replacing the standard fallback error handler.
        error_type: Expected disconnect raised while a request is being handled.
    """
    delegated: list[BaseException | None] = []

    def base_handle_error(
        server: object, request: object, client_address: tuple[str, int]
    ) -> None:
        """Record an unexpected delegation without printing a traceback."""
        delegated.append(sys.exc_info()[1])

    monkeypatch.setattr(recovery.ThreadingHTTPServer, "handle_error", base_handle_error)
    server = object.__new__(recovery.RecoveryServer)
    try:
        raise error_type("expected fixture disconnect")
    except error_type:
        server.handle_error(object(), ("127.0.0.1", 12345))
    assert delegated == []


def test_recovery_server_delegates_unexpected_request_errors(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve standard traceback handling for genuine fixture-server defects.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture replacing the standard fallback error handler.
    """
    delegated: list[BaseException | None] = []

    def base_handle_error(
        server: object, request: object, client_address: tuple[str, int]
    ) -> None:
        """Record the active exception delegated by the recovery server."""
        delegated.append(sys.exc_info()[1])

    monkeypatch.setattr(recovery.ThreadingHTTPServer, "handle_error", base_handle_error)
    server = object.__new__(recovery.RecoveryServer)
    failure = ValueError("unexpected fixture defect")
    try:
        raise failure
    except ValueError:
        server.handle_error(object(), ("127.0.0.1", 12345))
    assert delegated == [failure]


def test_capture_requires_owned_service(recovery: ModuleType) -> None:
    """Reject a service with foreign ancestry before enumerating its children.

    Args:
        recovery: Imported recovery harness.
    """
    process = fake_process(40001, parent=os.getpid() + 1)
    with pytest.raises(RuntimeError, match="directly owned"):
        recovery.capture_owned(process)
    process.children.assert_not_called()


def test_capture_preserves_root_and_descendant_identity(recovery: ModuleType) -> None:
    """Capture creation times and harness ownership for the exact service tree.

    Args:
        recovery: Imported recovery harness.
    """
    service = fake_process(40001)
    child = fake_process(40002, created=11, parent=40001)
    service.children.return_value = [child]
    identities = recovery.capture_owned(service)
    assert [
        (item.pid, item.created, item.owner_pid, item.service_pid)
        for item in identities
    ] == [(40001, 10, os.getpid(), 40001), (40002, 11, os.getpid(), 40001)]
    service.children.assert_called_once_with(recursive=True)


@pytest.mark.parametrize("lookup", ["ppid", "create_time", "children"])
def test_capture_reports_a_vanished_service(recovery: ModuleType, lookup: str) -> None:
    """Convert service-root observation races into a controlled harness failure.

    Args:
        recovery: Imported recovery harness.
        lookup: Root process observation that races with service exit.
    """
    service = fake_process(40001)
    getattr(service, lookup).side_effect = psutil.NoSuchProcess(service.pid)
    with pytest.raises(RuntimeError, match="service exited"):
        recovery.capture_owned(service)


def test_capture_skips_a_descendant_that_exits_during_identity_read(
    recovery: ModuleType,
) -> None:
    """Retain the stable root while ignoring an already-exited child.

    Args:
        recovery: Imported recovery harness.
    """
    service = fake_process(40001)
    child = fake_process(40002, parent=service.pid)
    child.create_time.side_effect = psutil.NoSuchProcess(child.pid)
    service.children.return_value = [child]
    assert recovery.capture_owned(service) == [
        recovery.OwnedProcess(service.pid, 10, os.getpid(), service.pid)
    ]


@pytest.mark.parametrize("action", ["kill", "suspend", "resume"])
def test_signal_requires_unchanged_identity(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """Signal only a matching creation-time identity and ignore PID reuse.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring the inert process lookup.
        action: Explicitly admitted process action.
    """
    identity = recovery.OwnedProcess(40001, 10, os.getpid(), 40001)
    process = fake_process(40001)
    monkeypatch.setattr(recovery.psutil, "Process", Mock(return_value=process))
    assert recovery.signal_owned(identity, action)
    getattr(process, action).assert_called_once_with()
    process.create_time.return_value = 12
    assert not recovery.signal_owned(identity, action)
    getattr(process, action).assert_called_once_with()


@pytest.mark.parametrize("kind", ["foreign-owner", "self", "unknown-action"])
def test_unsafe_signal_requests_never_lookup_processes(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Reject unsafe ownership, self-signalling, and unapproved operations.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring process lookup.
        kind: Safety precondition deliberately violated by this case.
    """
    process = Mock()
    monkeypatch.setattr(recovery.psutil, "Process", process)
    owner = os.getpid() + 1 if kind == "foreign-owner" else os.getpid()
    pid = os.getpid() if kind == "self" else 40001
    identity = recovery.OwnedProcess(pid, 10, owner, 40001)
    with pytest.raises((RuntimeError, ValueError)):
        recovery.signal_owned(
            identity, "terminate" if kind == "unknown-action" else "kill"
        )
    process.assert_not_called()


def test_exited_process_is_not_signalled(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tolerate a captured process exiting before fault injection or cleanup.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring process lookup.
    """
    identity = recovery.OwnedProcess(40001, 10, os.getpid(), 40001)
    monkeypatch.setattr(
        recovery.psutil, "Process", Mock(side_effect=psutil.NoSuchProcess(40001))
    )
    assert not recovery.signal_owned(identity, "kill")


@pytest.mark.parametrize(
    "scenario", ["browser-crash", "browser-hang", "driver-crash", "driver-hang"]
)
def test_fault_target_requires_owned_tree_and_exact_profile(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scenario: str
) -> None:
    """Select the intended root/browser without matching unrelated profile arguments.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring process lookup.
        tmp_path: Synthetic paths for an explicit executable and fresh profile.
        scenario: Browser or driver fault to target.
    """
    browser = tmp_path / "browser"
    profile = tmp_path / "profile"
    service = fake_process(40001)
    service.exe.return_value = str(browser)
    child = fake_process(40002)
    child.exe.return_value = str(browser)
    child.cmdline.return_value = [str(browser), "--user-data-dir=" + str(profile)]
    helper = fake_process(40003)
    helper.exe.return_value = str(browser)
    helper.cmdline.return_value = [str(browser), "--user-data-dir=/personal/profile"]
    processes = {item.pid: item for item in (service, child, helper)}
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), 40001) for pid in processes
    ]
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    selected = recovery.select_target(identities, scenario, str(browser), profile)
    assert selected.identity.pid == (40001 if scenario.startswith("driver") else 40002)
    assert selected.executable == str(browser)
    for process in processes.values():
        process.kill.assert_not_called()
        process.suspend.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["browser", "--user-data-dir=/owned/profile"],
        ["browser", "--user-data-dir", "/owned/profile"],
    ],
)
def test_profile_argument_accepts_assignment_and_split_forms(
    recovery: ModuleType, arguments: list[str]
) -> None:
    """Extract both Chromium profile flag forms without interpreting a shell.

    Args:
        recovery: Imported recovery target selector.
        arguments: Already-tokenized process command line under test.
    """
    assert recovery._user_data_dir_argument(arguments) == "/owned/profile"


@pytest.mark.parametrize(
    "arguments",
    [
        ["browser"],
        ["browser", "--user-data-dir"],
        ["browser", "--user-data-dir="],
        [
            "browser",
            "--user-data-dir=/owned/profile",
            "--user-data-dir",
            "/other/profile",
        ],
    ],
)
def test_profile_argument_rejects_missing_empty_and_repeated_values(
    recovery: ModuleType, arguments: list[str]
) -> None:
    """Fail closed when a browser profile flag cannot identify one value.

    Args:
        recovery: Imported recovery target selector.
        arguments: Malformed or ambiguous process command line under test.
    """
    assert recovery._user_data_dir_argument(arguments) is None


@pytest.mark.parametrize(
    "candidate",
    [
        r"c:/users/jef/appdata/local/aselenium/profile",
        r"C:\Users\JEF\AppData\Local\Aselenium\Profile",
        r"\\?\C:\Users\Jef\AppData\Local\Aselenium\Profile",
        r"//?/C:/Users/Jef/AppData/Local/Aselenium/Profile",
    ],
)
def test_windows_profile_matching_accepts_equivalent_native_spellings(
    recovery: ModuleType, candidate: str
) -> None:
    """Treat Windows case, separator, and valid extended-prefix forms equally.

    Args:
        recovery: Imported recovery target selector.
        candidate: Equivalent command-line spelling to compare.
    """
    expected = Path(r"C:\Users\Jef\AppData\Local\Aselenium\Profile")
    assert recovery._profile_path_matches(candidate, expected, windows=True)


def test_windows_profile_matching_accepts_extended_unc_spelling(
    recovery: ModuleType,
) -> None:
    """Map an extended UNC profile to the same ordinary UNC path.

    Args:
        recovery: Imported recovery target selector.
    """
    expected = Path(r"\\server\share\Aselenium\Profile")
    candidate = r"\\?\UNC\SERVER\SHARE\aselenium\profile"
    assert recovery._profile_path_matches(candidate, expected, windows=True)


@pytest.mark.parametrize(
    "candidate",
    [
        r"C:Users\Jef\Aselenium\Profile",
        r"\\.\C:\Users\Jef\Aselenium\Profile",
        r"\\?\GLOBALROOT\Device\HarddiskVolume1\Aselenium\Profile",
        r"D:\Users\Jef\Aselenium\Profile",
    ],
)
def test_windows_profile_matching_rejects_unsafe_or_different_paths(
    recovery: ModuleType, candidate: str
) -> None:
    """Reject drive-relative, device-namespace, and different-volume paths.

    Args:
        recovery: Imported recovery target selector.
        candidate: Non-equivalent command-line path spelling.
    """
    expected = Path(r"C:\Users\Jef\Aselenium\Profile")
    assert not recovery._profile_path_matches(candidate, expected, windows=True)


def test_windows_profile_parser_rejects_device_namespace(
    recovery: ModuleType,
) -> None:
    """Reject a device namespace before any filesystem identity comparison.

    Args:
        recovery: Imported recovery target selector.
    """
    assert recovery._windows_profile_path(r"\\.\C:\Aselenium\Profile") is None


def test_windows_profile_matching_does_not_probe_a_foreign_unc_share(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid filesystem access when an unexpected UNC anchor cannot be owned.

    Args:
        recovery: Imported recovery target selector.
        monkeypatch: Fixture replacing the filesystem identity helper.
    """
    samefile = Mock(return_value=True)
    monkeypatch.setattr(recovery, "_same_existing_path", samefile)
    expected = Path(r"C:\Users\Jef\Aselenium\Profile")
    assert not recovery._profile_path_matches(
        r"\\foreign\share\Aselenium\Profile", expected, windows=True
    )
    samefile.assert_not_called()


def test_posix_profile_matching_remains_case_sensitive(
    recovery: ModuleType,
) -> None:
    """Keep POSIX lexical matching exact when no filesystem alias exists.

    Args:
        recovery: Imported recovery target selector.
    """
    expected = Path("/tmp/Aselenium/Profile")
    assert recovery._profile_path_matches(str(expected), expected, windows=False)
    assert not recovery._profile_path_matches(
        "/tmp/aselenium/profile", expected, windows=False
    )


def test_profile_matching_uses_samefile_for_existing_alias(
    recovery: ModuleType, tmp_path: Path
) -> None:
    """Recognize a distinct absolute spelling of the same existing directory.

    Args:
        recovery: Imported recovery target selector.
        tmp_path: Parent for an owned profile and harmless path alias.
    """
    profile = tmp_path / "profile"
    profile.mkdir()
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    alias = intermediate / ".." / profile.name
    assert str(alias) != str(profile)
    assert recovery._profile_path_matches(str(alias), profile, windows=False)


def test_browser_target_accepts_split_profile_flag(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Select an owned browser whose profile flag and value are separate tokens.

    Args:
        recovery: Imported recovery target selector.
        monkeypatch: Fixture restoring controlled process lookups.
        tmp_path: Owned profile path represented in the command line.
    """
    profile = tmp_path / "profile"
    service = fake_process(40001)
    browser = fake_process(40002)
    browser.cmdline.return_value = ["browser", "--user-data-dir", str(profile)]
    processes = {service.pid: service, browser.pid: browser}
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), service.pid) for pid in processes
    ]
    selected = recovery.select_target(identities, "browser-crash", "browser", profile)
    assert selected.identity == identities[1]


def test_ambiguous_browser_target_fails_closed(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Refuse fault injection when multiple processes match the browser identity.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring process lookup.
        tmp_path: Synthetic executable and profile directory.
    """
    service = fake_process(40001)
    browsers = {pid: fake_process(pid) for pid in (40002, 40003)}
    for process in browsers.values():
        process.exe.return_value = str(tmp_path / "browser")
        process.cmdline.return_value = ["--user-data-dir=" + str(tmp_path / "profile")]
    processes = {service.pid: service, **browsers}
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), 40001) for pid in processes
    ]
    with pytest.raises(RuntimeError, match="exactly|Expected one"):
        recovery.select_target(
            identities, "browser-crash", str(tmp_path / "browser"), tmp_path / "profile"
        )


def test_browser_launcher_wrapper_does_not_require_same_runtime_executable(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Admit an owned real browser behind a launcher wrapper, excluding renderer helpers.

    Args:
        recovery: Imported recovery target selector.
        monkeypatch: Fixture restoring controlled process lookups.
        tmp_path: Fresh-profile identity used by the owned browser and renderer.
    """
    profile = tmp_path / "profile"
    service = fake_process(40001)
    browser = fake_process(40002)
    browser.exe.return_value = "/opt/google/chrome/chrome"
    browser.cmdline.return_value = [
        "/opt/google/chrome/chrome",
        "--user-data-dir=" + str(profile),
    ]
    renderer = fake_process(40003)
    renderer.exe.return_value = "/opt/google/chrome/chrome"
    renderer.cmdline.return_value = [
        "/opt/google/chrome/chrome",
        "--type=renderer",
        "--user-data-dir=" + str(profile),
    ]
    processes = {service.pid: service, browser.pid: browser, renderer.pid: renderer}
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), 40001) for pid in processes
    ]
    selected = recovery.select_target(
        identities, "browser-hang", "/usr/bin/google-chrome", profile
    )
    assert selected.identity.pid == 40002
    assert selected.executable == "/opt/google/chrome/chrome"
    browser.suspend.assert_not_called()
    renderer.suspend.assert_not_called()


def test_target_selection_skips_a_helper_that_exits_during_cmdline(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ignore a transient helper without losing the unique live browser target.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring controlled process lookups.
        tmp_path: Fresh profile used to identify the owned browser.
    """
    profile = tmp_path / "profile"
    service = fake_process(40001)
    helper = fake_process(40002)
    helper.cmdline.side_effect = psutil.NoSuchProcess(helper.pid)
    browser = fake_process(40003)
    browser.cmdline.return_value = ["browser", "--user-data-dir=" + str(profile)]
    browser.exe.return_value = str(tmp_path / "browser")
    processes = {service.pid: service, helper.pid: helper, browser.pid: browser}
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), 40001) for pid in processes
    ]
    selected = recovery.select_target(
        identities, "browser-crash", str(tmp_path / "browser"), profile
    )
    assert selected.identity.pid == browser.pid


@pytest.mark.parametrize("observation", ["cmdline", "exe"])
def test_target_selection_fails_cleanly_when_candidate_exits(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    observation: str,
) -> None:
    """Report no selectable target when its metadata disappears during inspection.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring controlled process lookups.
        tmp_path: Fresh profile used to identify the candidate.
        observation: Process metadata call that races with candidate exit.
    """
    profile = tmp_path / "profile"
    service = fake_process(40001)
    browser = fake_process(40002)
    browser.cmdline.return_value = ["browser", "--user-data-dir=" + str(profile)]
    getattr(browser, observation).side_effect = psutil.NoSuchProcess(browser.pid)
    processes = {service.pid: service, browser.pid: browser}
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), service.pid) for pid in processes
    ]
    with pytest.raises(RuntimeError, match="found 0"):
        recovery.select_target(
            identities, "browser-crash", str(tmp_path / "browser"), profile
        )


def test_target_selection_keeps_access_denied_fail_closed(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Do not reinterpret an access-control failure as a harmless process exit.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring controlled process lookups.
        tmp_path: Fresh profile used to invoke browser selection.
    """
    service = fake_process(40001)
    browser = fake_process(40002)
    browser.cmdline.side_effect = psutil.AccessDenied(browser.pid)
    processes = {service.pid: service, browser.pid: browser}
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), service.pid) for pid in processes
    ]
    with pytest.raises(psutil.AccessDenied):
        recovery.select_target(
            identities,
            "browser-crash",
            str(tmp_path / "browser"),
            tmp_path / "profile",
        )


def test_browser_selection_requires_a_live_service_root(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject a browser candidate after its owned driver root has disappeared.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring controlled process lookups.
        tmp_path: Fresh profile used to identify the browser candidate.
    """
    service = fake_process(40001)
    browser = fake_process(40002)
    profile = tmp_path / "profile"
    browser.cmdline.return_value = ["browser", "--user-data-dir=" + str(profile)]
    processes = {service.pid: service, browser.pid: browser}

    def lookup(pid: int) -> Mock:
        """Return the browser but report the captured service as exited."""
        if pid == service.pid:
            raise psutil.NoSuchProcess(pid)
        return processes[pid]

    monkeypatch.setattr(recovery.psutil, "Process", lookup)
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), service.pid) for pid in processes
    ]
    with pytest.raises(RuntimeError, match="live owned service root"):
        recovery.select_target(identities, "browser-crash", "browser", profile)


@pytest.mark.asyncio
async def test_wait_owned_exit_allows_normal_signal_delivery_delay(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wait for a killed process instead of misclassifying kernel exit latency.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring controlled identity observations.
    """
    identity = recovery.OwnedProcess(40002, 10, os.getpid(), 40001)
    live = fake_process(identity.pid)
    observations = iter((live, live, None))
    monkeypatch.setattr(recovery, "current_process", lambda item: next(observations))
    assert await recovery.wait_owned_exit(identity, 1)


@pytest.mark.asyncio
async def test_wait_owned_exit_reports_a_live_process_at_deadline(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return false without hiding a process that outlives the bounded wait.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture pinning process and clock observations.
    """
    identity = recovery.OwnedProcess(40002, 10, os.getpid(), 40001)
    process = fake_process(identity.pid)
    monkeypatch.setattr(recovery, "current_process", lambda item: process)
    assert not await recovery.wait_owned_exit(identity, 0)


def test_same_profile_with_foreign_ownership_is_never_a_target(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject an unowned identity even if its claimed profile and executable match.

    Args:
        recovery: Imported recovery target selector.
        monkeypatch: Fixture restoring controlled process lookups.
        tmp_path: Claimed profile that must not override failed ownership validation.
    """
    lookup = Mock()
    monkeypatch.setattr(recovery.psutil, "Process", lookup)
    identity = recovery.OwnedProcess(40001, 10, os.getpid() + 1, 40001)
    with pytest.raises(RuntimeError, match="not owned"):
        recovery.select_target(
            [identity], "browser-crash", "/usr/bin/google-chrome", tmp_path
        )
    lookup.assert_not_called()


@pytest.mark.asyncio
async def test_acknowledgement_requires_outstanding_command(
    recovery: ModuleType,
) -> None:
    """Accept browser acknowledgement only while the actual command remains pending.

    Args:
        recovery: Imported recovery harness.
    """
    state = recovery.PageState()
    state.started.set()
    pending = asyncio.create_task(asyncio.sleep(60))
    try:
        await recovery.await_started(state, pending)
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    with pytest.raises(RuntimeError, match="not outstanding"):
        await recovery.await_started(state, pending)


@pytest.mark.asyncio
async def test_command_failure_before_acknowledgement_prevents_fault(
    recovery: ModuleType,
) -> None:
    """Do not inject a process fault when the browser never began the command.

    Args:
        recovery: Imported recovery harness.
    """
    state = recovery.PageState()
    completed = asyncio.create_task(asyncio.sleep(0))
    await completed
    with pytest.raises(RuntimeError, match="before browser acknowledgement"):
        await recovery.await_started(state, completed)


@pytest.mark.asyncio
async def test_scenario_failure_is_not_hidden_by_later_success(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep aggregate acceptance failed even when later independent scenarios pass.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring the inert scenario runner.
    """
    scenario = AsyncMock(
        side_effect=[
            {"status": "failed"},
            {"status": "passed"},
            {"status": "passed"},
            {"status": "passed"},
        ]
    )
    monkeypatch.setattr(recovery, "scenario_run", scenario)
    result = await recovery.run(argparse.Namespace(browser="chrome", scenario="all"))
    assert result["status"] == "failed"
    assert scenario.await_count == 4


def test_recovery_http_acknowledgement_is_exact(recovery: ModuleType) -> None:
    """Ignore unknown acknowledgement paths and recognize only the fixture token.

    Args:
        recovery: Imported recovery harness.
    """
    state = recovery.PageState(token="fixture")
    handler = object.__new__(recovery.RecoveryHandler)
    handler.server = SimpleNamespace(state=state)
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = Mock()
    handler.path = "/started/wrong"
    handler.do_GET()
    assert not state.started.is_set()
    handler.path = "/started/fixture"
    handler.do_GET()
    assert state.started.is_set()
    assert handler.close_connection


def test_terminate_resistant_owned_service_escalates_and_reaps(tmp_path: Path) -> None:
    """Exercise the real service teardown algorithm against a terminate-resistant double.

    Args:
        tmp_path: Disposable executable placeholder used only for service construction.
    """
    executable = tmp_path / "driver"
    executable.touch()
    service = ChromiumBaseService(
        ChromiumVersion("120.0.1.1"), str(executable), timeout=0.1
    )
    process = fake_process(40001)
    process.wait.side_effect = [psutil.TimeoutExpired(0.05), 0]
    child = fake_process(40002)
    child.is_running.return_value = True
    process.children.return_value = [child]
    popen = Mock()
    service._process = process
    service._popen = popen
    service._stop_process()
    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2
    child.terminate.assert_called_once_with()
    child.kill.assert_called_once_with()
    popen.wait.assert_called_once()
    assert service._process is None and service._popen is None
    assert service._owned_children == []


def test_unstoppable_service_retains_ownership_for_retry(tmp_path: Path) -> None:
    """Do not discard process ownership when even forced termination cannot finish.

    Args:
        tmp_path: Disposable executable placeholder used only for service construction.
    """
    executable = tmp_path / "driver"
    executable.touch()
    service = ChromiumBaseService(
        ChromiumVersion("120.0.1.1"), str(executable), timeout=0.1
    )
    process = fake_process(40001)
    process.wait.side_effect = psutil.TimeoutExpired(0.05)
    popen = Mock()
    service._process = process
    service._popen = popen
    with pytest.raises(errors.ServiceProcessError, match="ownership retained"):
        service._stop_process()
    assert service._process is process and service._popen is popen
    process.wait.side_effect = None
    process.wait.return_value = 0
    service._stop_process()
    assert service._process is None and service._popen is None


def test_recovery_acceptance_checks_survive_optimized_python(
    recovery: ModuleType,
) -> None:
    """Keep safety and acceptance conditions active even when Python removes asserts.

    Args:
        recovery: Imported recovery harness.
    """
    tree = ast.parse(Path(recovery.__file__).read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))


@pytest.mark.parametrize("done,elapsed", [(True, 0.1), (False, 4.5), (False, 5.1)])
def test_injection_rejects_elapsed_command_deadlines(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, done: bool, elapsed: float
) -> None:
    """Do not misclassify a command that expired before injection as fault evidence.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring the monotonic clock.
        done: Whether the command task has already completed.
        elapsed: Seconds elapsed since its task was created.
    """
    pending = Mock()
    pending.done.return_value = done
    monkeypatch.setattr(recovery.time, "monotonic", lambda: 100 + elapsed)
    with pytest.raises(RuntimeError, match="before fault injection"):
        recovery.validate_injection_window(pending, 100, 5)
