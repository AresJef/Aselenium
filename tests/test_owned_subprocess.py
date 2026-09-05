"""Exercise owned subprocess cleanup with inert doubles and disposable Python trees."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import psutil
import pytest


@pytest.fixture
def owned_runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the helper without changing default network or browser guards.

    Args:
        monkeypatch: Fixture restoring the temporary module registration.

    Returns:
        Helper module with no process launched during import.
    """
    path = Path(__file__).resolve().parents[1] / "scripts/_owned_subprocess.py"
    spec = importlib.util.spec_from_file_location("owned_subprocess_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def process_double(pid: int = 654321, created: float = 123.0) -> Mock:
    """Build an inert process identity with controllable liveness and descendants.

    Args:
        pid: Synthetic PID that will never be passed to the operating system.
        created: Synthetic process creation time.

    Returns:
        Process double recording any attempted signals.
    """
    process = Mock()
    process.pid = pid
    process.create_time.return_value = created
    process.is_running.return_value = True
    process.status.return_value = psutil.STATUS_RUNNING
    process.ppid.return_value = os.getpid()
    process.children.return_value = []
    return process


@pytest.mark.parametrize("named", [False, True])
def test_capture_reads_native_files_and_temporary_wrappers(
    owned_runner: ModuleType, tmp_path: Path, named: bool
) -> None:
    """Accept both platform-specific temporary capture implementations.

    Args:
        owned_runner: Imported process helper providing the capture reader.
        tmp_path: Disposable parent for the binary capture file.
        named: Whether to use the wrapper also returned by TemporaryFile on Windows.
    """
    factory = tempfile.NamedTemporaryFile if named else tempfile.TemporaryFile
    with factory(dir=tmp_path) as stream:
        stream.write(b"captured\xffoutput")
        stream.seek(4)
        assert owned_runner.read_output(stream) == "captured\ufffdoutput"


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_signals_require_matching_creation_identity(
    owned_runner: ModuleType, force: bool, changed: bool
) -> None:
    """Never signal a PID that now represents a different process.

    Args:
        owned_runner: Imported command helper.
        force: Whether to exercise termination or forced killing.
        changed: Whether the current creation time differs from the captured one.
    """
    process = process_double()
    identity = owned_runner.ProcessIdentity(process, 123.0, os.getpid())
    if changed:
        process.create_time.return_value = 124.0
    identity.signal(force=force)
    assert process.kill.call_count == int(force and not changed)
    assert process.terminate.call_count == int(not force and not changed)


@pytest.mark.parametrize("defect", ["foreign-owner", "self", "not-running", "zombie"])
def test_unsafe_or_dead_identities_are_never_signalled(
    owned_runner: ModuleType, defect: str
) -> None:
    """Reject invalid ownership and skip processes no longer capable of running.

    Args:
        owned_runner: Imported command helper.
        defect: Ownership or liveness condition that must prevent any signal.
    """
    process = process_double(os.getpid() if defect == "self" else 654321)
    owner = os.getpid() + 1 if defect == "foreign-owner" else os.getpid()
    identity = owned_runner.ProcessIdentity(process, 123.0, owner)
    if defect == "not-running":
        process.is_running.return_value = False
    if defect == "zombie":
        process.status.return_value = psutil.STATUS_ZOMBIE
    if defect in {"foreign-owner", "self"}:
        with pytest.raises(RuntimeError, match="foreign-owned or self"):
            identity.signal(force=True)
        process.is_running.assert_not_called()
    else:
        identity.signal(force=True)
    process.kill.assert_not_called()
    process.terminate.assert_not_called()


def test_tree_remembers_owned_roots_after_parent_loss(
    owned_runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Find later grandchildren from a previously captured orphaned owned child.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture replacing only the initial root lookup.
    """
    parent = Mock(pid=654321)
    root = process_double(parent.pid)
    child = process_double(parent.pid + 1, 124.0)
    grandchild = process_double(parent.pid + 2, 125.0)
    monkeypatch.setattr(owned_runner.psutil, "Process", Mock(return_value=root))
    tree = owned_runner.OwnedTree(parent)
    root.children.return_value = [child]
    assert [item.process.pid for item in tree.refresh()] == [root.pid, child.pid]
    root.is_running.return_value = False
    child.children.return_value = [grandchild]
    assert [item.process.pid for item in tree.refresh()] == [child.pid, grandchild.pid]
    root.children.assert_called_once_with(recursive=True)
    assert owned_runner.psutil.Process.call_count == 1


def test_tree_rejects_foreign_parent_before_descendant_query(
    owned_runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never adopt an unrelated process as the command's ownership root.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture replacing the root handle with an unrelated double.
    """
    parent = Mock(pid=654321)
    parent.poll.return_value = None
    root = process_double(parent.pid)
    root.ppid.return_value = os.getpid() + 1
    monkeypatch.setattr(owned_runner.psutil, "Process", Mock(return_value=root))
    tree = owned_runner.OwnedTree(parent)
    assert tree.inspection_errors == {"Launched process is not directly owned"}
    assert tree.identities == {}
    root.children.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_deadline_is_rejected_before_launch(
    owned_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    timeout: float,
) -> None:
    """Fail validation without starting a process when no finite deadline exists.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture capturing any unintended executable launch.
        tmp_path: Disposable working directory.
        timeout: Invalid execution deadline.
    """
    launch = Mock()
    monkeypatch.setattr(owned_runner.subprocess, "Popen", launch)
    with pytest.raises(ValueError, match="finite positive"):
        owned_runner.run_owned(
            [sys.executable, "-V"], cwd=tmp_path, env=None, timeout=timeout
        )
    launch.assert_not_called()


@pytest.mark.parametrize("command", [[], [""], "python", [None]])
def test_invalid_argument_vector_is_rejected_before_launch(
    owned_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: object,
) -> None:
    """Reject shell-like strings and invalid command vectors without execution.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture capturing any unintended executable launch.
        tmp_path: Disposable working directory.
        command: Invalid argument vector supplied deliberately.
    """
    launch = Mock()
    monkeypatch.setattr(owned_runner.subprocess, "Popen", launch)
    with pytest.raises(ValueError, match="argument list"):
        owned_runner.run_owned(command, cwd=tmp_path, env=None, timeout=1)
    launch.assert_not_called()


def test_real_command_captures_streams_cwd_environment_and_exit_code(
    owned_runner: ModuleType, tmp_path: Path
) -> None:
    """Return normal nonzero exit evidence without shell interpretation.

    Args:
        owned_runner: Imported command helper.
        tmp_path: Disposable working directory.
    """
    environment = os.environ.copy()
    environment["ASELENIUM_OWNED_FIXTURE"] = "isolated"
    code = (
        "import json, os, sys; "
        "print(json.dumps([os.getcwd(), os.environ['ASELENIUM_OWNED_FIXTURE'], sys.argv[1]])); "
        "print('fixture stderr', file=sys.stderr); sys.exit(7)"
    )
    result = owned_runner.run_owned(
        [sys.executable, "-c", code, "$(must-not-run);"],
        cwd=tmp_path,
        env=environment,
        timeout=5,
    )
    assert result.returncode == 7
    assert json.loads(result.stdout) == [
        str(tmp_path.resolve()),
        "isolated",
        "$(must-not-run);",
    ]
    assert result.stderr == f"fixture stderr{os.linesep}"


def test_real_command_large_output_does_not_deadlock(
    owned_runner: ModuleType, tmp_path: Path
) -> None:
    """Capture output larger than ordinary pipe buffers without blocking the child.

    Args:
        owned_runner: Imported command helper.
        tmp_path: Disposable working directory.
    """
    result = owned_runner.run_owned(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'x' * 200000); os.write(2, b'\\xff')",
            "",
        ],
        cwd=tmp_path,
        env=None,
        timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout == "x" * 200000
    assert result.stderr == "\ufffd"


def real_tree_command(*, parent_exits: bool, resistant: bool) -> list[str]:
    """Construct a bounded disposable Python parent and child without networking.

    Args:
        parent_exits: Whether the parent exits normally while its child is alive.
        resistant: Whether the child ignores graceful POSIX termination.

    Returns:
        Explicit Python argument vector emitting the child's PID and creation time.
    """
    child_code = "import time; time.sleep(8)"
    if resistant and os.name == "posix":
        child_code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(8)"
    parent_code = (
        "import json, subprocess, sys, time, psutil; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(json.dumps([child.pid, psutil.Process(child.pid).create_time()]), flush=True); "
        "print('parent fixture error', file=sys.stderr, flush=True); "
        f"time.sleep({0.4 if parent_exits else 8})"
    )
    return [sys.executable, "-c", parent_code]


def matching_process_alive(pid: int, created: float) -> bool:
    """Check one emitted fixture identity without adopting PID reuse.

    Args:
        pid: PID emitted by the explicitly launched disposable parent.
        created: Creation time emitted alongside that PID.

    Returns:
        Whether the original fixture process remains alive and non-zombie.
    """
    try:
        process = psutil.Process(pid)
        return (
            process.create_time() == created
            and process.status() != psutil.STATUS_ZOMBIE
        )
    except psutil.NoSuchProcess:
        return False


@pytest.mark.parametrize("resistant", [False, True])
def test_timeout_stops_owned_child_and_preserves_output(
    owned_runner: ModuleType, tmp_path: Path, resistant: bool
) -> None:
    """Stop observed descendants after timeout, escalating when termination fails.

    Args:
        owned_runner: Imported command helper.
        tmp_path: Disposable working directory.
        resistant: Whether the controlled child ignores graceful termination.
    """
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as captured:
        owned_runner.run_owned(
            real_tree_command(parent_exits=False, resistant=resistant),
            cwd=tmp_path,
            env=None,
            timeout=1.0,
        )
    assert time.monotonic() - started < 5
    pid, created = json.loads(captured.value.stdout)
    assert not matching_process_alive(pid, created)
    assert "parent fixture error" in captured.value.stderr
    assert "survivors after cleanup: []" in captured.value.stderr


def test_normal_parent_exit_with_surviving_child_is_a_failure(
    owned_runner: ModuleType, tmp_path: Path
) -> None:
    """Record a normal-exit orphan as failure even when emergency cleanup succeeds.

    Args:
        owned_runner: Imported command helper.
        tmp_path: Disposable working directory.
    """
    with pytest.raises(owned_runner.OwnedProcessError, match="still alive") as captured:
        owned_runner.run_owned(
            real_tree_command(parent_exits=True, resistant=False),
            cwd=tmp_path,
            env=None,
            timeout=5,
        )
    pid, created = json.loads(captured.value.stdout)
    assert captured.value.returncode == 0
    assert captured.value.surviving_pids == []
    assert str(pid) in captured.value.diagnostic
    assert not matching_process_alive(pid, created)


def test_completed_owned_tree_is_accepted(
    owned_runner: ModuleType, tmp_path: Path
) -> None:
    """Accept a command that explicitly waits for and reaps its own child.

    Args:
        owned_runner: Imported command helper.
        tmp_path: Disposable working directory.
    """
    code = (
        "import subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.1)']); "
        "child.wait(); print('complete')"
    )
    result = owned_runner.run_owned(
        [sys.executable, "-c", code], cwd=tmp_path, env=None, timeout=5
    )
    assert result.returncode == 0
    assert result.stdout == f"complete{os.linesep}"


def test_cleanup_access_denial_is_retained_and_bounded(
    owned_runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep uninspectable identities visible instead of reporting clean teardown.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture replacing process access and shortening inert deadlines.
    """
    parent = Mock(pid=654321)
    parent.poll.return_value = None
    root = process_double(parent.pid)
    monkeypatch.setattr(owned_runner.psutil, "Process", Mock(return_value=root))
    tree = owned_runner.OwnedTree(parent)
    root.status.side_effect = psutil.AccessDenied(root.pid)
    monkeypatch.setattr(owned_runner, "TERMINATE_SECONDS", 0)
    monkeypatch.setattr(owned_runner, "KILL_SECONDS", 0)
    assert tree.cleanup() == [root.pid]
    assert tree.inspection_errors == {
        f"Cannot inspect owned process {root.pid}",
        f"Cannot stop owned process {root.pid}",
    }
    root.kill.assert_not_called()
    root.terminate.assert_not_called()
    parent.terminate.assert_called_once_with()
    parent.kill.assert_called_once_with()


@pytest.mark.parametrize(
    "failure", [PermissionError("denied"), psutil.AccessDenied(654321)]
)
def test_inspection_failure_stops_known_parent_and_reports_failure(
    owned_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: Exception,
) -> None:
    """Treat platform-level permission failures as errors without abandoning the root.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture replacing process creation and identity operations.
        tmp_path: Disposable capture-file working directory.
        failure: Inspection denial surfaced either by Python or by psutil.
    """
    root = process_double()
    root.children.side_effect = failure
    root.terminate.side_effect = lambda: setattr(root.is_running, "return_value", False)
    parent = Mock(pid=root.pid, returncode=-15)
    parent.poll.side_effect = lambda: None if root.is_running.return_value else -15
    monkeypatch.setattr(owned_runner.subprocess, "Popen", Mock(return_value=parent))
    monkeypatch.setattr(owned_runner.psutil, "Process", Mock(return_value=root))
    with pytest.raises(
        owned_runner.OwnedProcessError, match="inspection failed"
    ) as captured:
        owned_runner.run_owned(["inert-command"], cwd=tmp_path, env=None, timeout=1)
    root.terminate.assert_called_once_with()
    assert captured.value.surviving_pids == []
    assert "Cannot inspect owned process" in captured.value.stderr


def test_interruption_cleans_the_known_tree_before_propagating(
    owned_runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Preserve cancellation-like interruption only after attempting owned cleanup.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture replacing process operations and the first polling wait.
        tmp_path: Disposable capture-file working directory.
    """
    root = process_double()
    root.terminate.side_effect = lambda: setattr(root.is_running, "return_value", False)
    parent = Mock(pid=root.pid, returncode=-15)
    parent.poll.side_effect = lambda: None if root.is_running.return_value else -15
    monkeypatch.setattr(owned_runner.subprocess, "Popen", Mock(return_value=parent))
    monkeypatch.setattr(owned_runner.psutil, "Process", Mock(return_value=root))
    sleep = Mock(side_effect=[KeyboardInterrupt, None])
    monkeypatch.setattr(owned_runner.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        owned_runner.run_owned(["inert-command"], cwd=tmp_path, env=None, timeout=1)
    root.terminate.assert_called_once_with()
    assert not root.is_running()


def test_timeout_never_stops_an_unrelated_sibling_fixture(
    owned_runner: ModuleType, tmp_path: Path
) -> None:
    """Keep an independently launched sibling alive while cleaning the command tree.

    Args:
        owned_runner: Imported command helper.
        tmp_path: Disposable working directory.
    """
    sibling = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(8)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            owned_runner.run_owned(
                real_tree_command(parent_exits=False, resistant=False),
                cwd=tmp_path,
                env=None,
                timeout=1,
            )
        assert sibling.poll() is None
    finally:
        sibling.kill()
        sibling.wait(timeout=3)


@pytest.mark.parametrize("exited", [False, True])
@pytest.mark.parametrize(
    "failure", [psutil.NoSuchProcess(654321), psutil.AccessDenied(654321)]
)
def test_initial_identity_failure_cannot_be_accepted_or_abandon_parent(
    owned_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exited: bool,
    failure: Exception,
) -> None:
    """Fail closed and reap the direct child even when no tree identity was captured.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture replacing the Popen handle and failing root lookup.
        tmp_path: Disposable capture-file working directory.
        exited: Whether the launched parent already exited before root lookup.
        failure: Initial process identity failure deliberately injected.
    """
    parent = Mock(pid=654321, returncode=0 if exited else None)
    parent.poll.side_effect = lambda: parent.returncode
    parent.terminate.side_effect = lambda: setattr(parent, "returncode", -15)
    monkeypatch.setattr(owned_runner.subprocess, "Popen", Mock(return_value=parent))
    monkeypatch.setattr(owned_runner.psutil, "Process", Mock(side_effect=failure))
    with pytest.raises(owned_runner.OwnedProcessError) as captured:
        owned_runner.run_owned(["inert-command"], cwd=tmp_path, env=None, timeout=1)
    assert "Initial root identity could not be captured" in captured.value.stderr
    assert captured.value.returncode == (0 if exited else -15)
    assert captured.value.surviving_pids == []
    assert parent.terminate.call_count == int(not exited)


def test_uncaptured_parent_cleanup_failure_is_not_hidden(
    owned_runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retain a still-live authoritative parent and cleanup errors in diagnostics.

    Args:
        owned_runner: Imported command helper.
        monkeypatch: Fixture replacing process operations with bounded failures.
        tmp_path: Disposable capture-file working directory.
    """
    parent = Mock(pid=654321, returncode=None)
    parent.poll.return_value = None
    parent.terminate.side_effect = PermissionError("denied")
    parent.kill.side_effect = PermissionError("denied")
    monkeypatch.setattr(owned_runner.subprocess, "Popen", Mock(return_value=parent))
    monkeypatch.setattr(
        owned_runner.psutil,
        "Process",
        Mock(side_effect=psutil.NoSuchProcess(parent.pid)),
    )
    monkeypatch.setattr(owned_runner, "TERMINATE_SECONDS", 0)
    monkeypatch.setattr(owned_runner, "KILL_SECONDS", 0)
    with pytest.raises(owned_runner.OwnedProcessError) as captured:
        owned_runner.run_owned(["inert-command"], cwd=tmp_path, env=None, timeout=1)
    assert captured.value.surviving_pids == [parent.pid]
    assert captured.value.returncode is None
    assert "Cannot stop launched parent" in captured.value.stderr
    assert "Initial root identity could not be captured" in captured.value.stderr
