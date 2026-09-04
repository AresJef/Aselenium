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
    assert selected.pid == (40001 if scenario.startswith("driver") else 40002)
    for process in processes.values():
        process.kill.assert_not_called()
        process.suspend.assert_not_called()


def test_ambiguous_browser_target_fails_closed(
    recovery: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Refuse fault injection when multiple processes match the browser identity.

    Args:
        recovery: Imported recovery harness.
        monkeypatch: Fixture restoring process lookup.
        tmp_path: Synthetic executable and profile directory.
    """
    processes = {pid: fake_process(pid) for pid in (40002, 40003)}
    for process in processes.values():
        process.exe.return_value = str(tmp_path / "browser")
        process.cmdline.return_value = ["--user-data-dir=" + str(tmp_path / "profile")]
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
    processes = {40002: browser, 40003: renderer}
    monkeypatch.setattr(recovery.psutil, "Process", lambda pid: processes[pid])
    identities = [
        recovery.OwnedProcess(pid, 10, os.getpid(), 40001) for pid in processes
    ]
    selected = recovery.select_target(
        identities, "browser-hang", "/usr/bin/google-chrome", profile
    )
    assert selected.pid == 40002
    browser.suspend.assert_not_called()
    renderer.suspend.assert_not_called()


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
    identity = recovery.OwnedProcess(40002, 10, os.getpid() + 1, 40001)
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
