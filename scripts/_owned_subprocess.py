"""Run explicit acceptance commands with bounded, identity-checked tree cleanup.

Only descendants observed below the launched child or its remembered descendants
are inspected. No process-name or system-wide process search is performed. Polling
cannot discover a process that forks and is reparented entirely between samples;
this helper is containment for cooperative acceptance harnesses, not a sandbox for
hostile executables. POSIX children start a fresh session as an additional boundary.
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psutil

POLL_SECONDS = 0.025
TERMINATE_SECONDS = 0.75
KILL_SECONDS = 2.0


class OwnedProcessError(RuntimeError):
    """Report unsafe or incomplete command teardown without losing child output.

    Attributes:
        command: Original explicit argument vector.
        returncode: Parent exit code, if the parent was reaped.
        stdout: Captured standard output decoded as UTF-8 with replacement.
        stderr: Captured standard error, including cleanup diagnostics.
        surviving_pids: Observed identities still alive after guarded cleanup.
        diagnostic: Reason the command cannot be accepted as successful.
    """

    def __init__(
        self,
        command: list[str],
        returncode: int | None,
        stdout: str,
        stderr: str,
        surviving_pids: list[int],
        diagnostic: str,
    ) -> None:
        """Retain evidence for a command whose process ownership check failed.

        Args:
            command: Explicit launched argument vector.
            returncode: Reaped parent exit code, or None if still alive.
            stdout: Captured child standard output.
            stderr: Captured child standard error with cleanup diagnostics.
            surviving_pids: Observed processes remaining after cleanup.
            diagnostic: Human-readable reason for rejecting the command.
        """
        super().__init__(diagnostic)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.surviving_pids = surviving_pids
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class ProcessIdentity:
    """Retain the original psutil handle and creation time across parent exit.

    Attributes:
        process: Original handle, whose signal methods also guard PID reuse.
        created: Creation timestamp captured while ownership was established.
        owner: Harness process that established this identity.
    """

    process: psutil.Process
    created: float
    owner: int

    def alive(self) -> bool:
        """Check ownership and creation identity without adopting a reused PID.

        Returns:
            Whether this same owned process remains alive and non-zombie.

        Raises:
            RuntimeError: The identity claims another owner or the harness itself.
            psutil.AccessDenied: A live identity cannot be safely inspected.
        """
        if self.owner != os.getpid() or self.process.pid == self.owner:
            raise RuntimeError("Refusing a foreign-owned or self process identity")
        try:
            return (
                self.process.is_running()
                and self.process.create_time() == self.created
                and self.process.status() != psutil.STATUS_ZOMBIE
            )
        except psutil.NoSuchProcess:
            return False

    def signal(self, *, force: bool) -> None:
        """Terminate or kill only the still-matching original owned identity.

        Args:
            force: Whether to use kill instead of graceful termination.
        """
        if self.alive():
            try:
                if force:
                    self.process.kill()
                else:
                    self.process.terminate()
            except psutil.NoSuchProcess:
                pass


class OwnedTree:
    """Remember observed descendants even when their original parent disappears."""

    def __init__(self, parent: subprocess.Popen[bytes]) -> None:
        """Capture the directly launched parent before polling its descendants.

        Args:
            parent: Child created by the calling harness without a shell.

        """
        self.parent = parent
        self.identities: dict[tuple[int, float], ProcessIdentity] = {}
        self.inspection_errors: set[str] = set()
        try:
            root = psutil.Process(parent.pid)
            if root.ppid() != os.getpid():
                self.inspection_errors.add("Launched process is not directly owned")
                return
            self.remember(root)
            if not self.identities:
                self.inspection_errors.add(
                    "Initial root identity could not be captured"
                )
        except (psutil.Error, OSError, RuntimeError) as cause:
            self.inspection_errors.add(
                f"Initial root identity could not be captured: {type(cause).__name__}"
            )

    def remember(self, process: psutil.Process) -> None:
        """Capture one already-proven descendant without replacing old identities.

        Args:
            process: Handle returned by a verified owned parent's children query.
        """
        if process.pid == os.getpid():
            raise RuntimeError("Owned descendant enumeration included the harness")
        try:
            created = process.create_time()
        except psutil.NoSuchProcess:
            return
        key = (process.pid, created)
        if key not in self.identities:
            self.identities[key] = ProcessIdentity(process, created, os.getpid())

    def refresh(self) -> list[ProcessIdentity]:
        """Inspect only remembered identities and their current descendant trees.

        Returns:
            Matching live identities, with parent-loss and PID reuse accounted for.
        """
        for identity in list(self.identities.values()):
            try:
                if identity.alive():
                    for child in identity.process.children(recursive=True):
                        self.remember(child)
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                self.inspection_errors.add(
                    f"Cannot inspect owned process {identity.process.pid}"
                )
        living = []
        for identity in self.identities.values():
            try:
                if identity.alive():
                    living.append(identity)
            except (psutil.AccessDenied, OSError):
                self.inspection_errors.add(
                    f"Cannot inspect owned process {identity.process.pid}"
                )
                living.append(identity)
        return living

    def cleanup(self) -> list[int]:
        """Bound termination and escalation while preserving ownership failures.

        Returns:
            PIDs still alive or uninspectable after bounded guarded cleanup.
        """
        for force, grace in ((False, TERMINATE_SECONDS), (True, KILL_SECONDS)):
            deadline = time.monotonic() + grace
            signalled: set[tuple[int, float]] = set()
            parent_signalled = False
            while True:
                living = self.refresh()
                for identity in reversed(living):
                    key = (identity.process.pid, identity.created)
                    if key not in signalled:
                        try:
                            identity.signal(force=force)
                        except (psutil.AccessDenied, OSError):
                            self.inspection_errors.add(
                                f"Cannot stop owned process {identity.process.pid}"
                            )
                        signalled.add(key)
                if self.parent.poll() is None and not parent_signalled:
                    # Popen retains the authoritative direct-child relationship even
                    # when the optional psutil identity lookup was denied or raced.
                    try:
                        if force:
                            self.parent.kill()
                        else:
                            self.parent.terminate()
                    except OSError as cause:
                        self.inspection_errors.add(
                            f"Cannot stop launched parent {self.parent.pid}: "
                            f"{type(cause).__name__}"
                        )
                    parent_signalled = True
                if (
                    not living and self.parent.poll() is not None
                ) or time.monotonic() >= deadline:
                    break
                time.sleep(min(POLL_SECONDS, max(0, deadline - time.monotonic())))
        survivors = [identity.process.pid for identity in self.refresh()]
        if self.parent.poll() is None and self.parent.pid not in survivors:
            survivors.append(self.parent.pid)
        return survivors


class BinaryCapture(Protocol):
    """Describe the operations required from native files and temporary wrappers."""

    def seek(self, offset: int, /) -> int:
        """Reposition the binary capture stream.

        Args:
            offset: Absolute byte offset from the beginning of the file.

        Returns:
            The resulting byte position.
        """
        ...

    def read(self) -> bytes:
        """Read the remaining captured bytes.

        Returns:
            All bytes from the current position through the end of the file.
        """
        ...


def read_output(stream: BinaryCapture) -> str:
    """Read seekable child output without waiting on inherited pipe handles.

    Args:
        stream: Seekable binary capture positioned anywhere. Both a native file
            and the temporary-file wrapper used by Windows are supported.

    Returns:
        Captured bytes decoded as UTF-8, replacing invalid sequences.
    """
    stream.seek(0)
    return stream.read().decode("utf-8", errors="replace")


def run_owned(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run an explicit command and reject surviving observed child processes.

    The deadline covers command execution; guarded cleanup may take an additional
    2.75 seconds. Capturing into temporary files prevents pipe-buffer deadlocks and
    avoids waiting forever on a descriptor inherited by a detached child. A normal
    nonzero exit code is returned to the caller, not converted into an exception.

    Args:
        command: Nonempty argument vector executed directly without a shell.
        cwd: Child working directory.
        env: Exact child environment, or None to inherit this process environment.
        timeout: Finite positive execution deadline in seconds.

    Returns:
        Parent exit code and UTF-8-decoded captured standard output and error.

    Raises:
        ValueError: The command or execution deadline is invalid.
        OSError: The requested executable cannot be launched.
        subprocess.TimeoutExpired: Execution timed out; output includes diagnostics.
        OwnedProcessError: Owned descendants survived normal completion or ownership
            inspection failed. Cleanup is attempted before raising, never hidden.

    Example:
        >>> from pathlib import Path
        >>> from _owned_subprocess import run_owned
        >>> result = run_owned(
        ...     ["python", "-c", "print('ready')"],
        ...     cwd=Path.cwd(), env=None, timeout=5,
        ... )
        >>> result.stdout.strip()
        'ready'
    """
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(argument, str) for argument in command)
        or not command[0]
    ):
        raise ValueError("command must be a string argument list with an executable")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    started = time.monotonic()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        parent = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=os.name == "posix",
            shell=False,
        )
        try:
            tree = OwnedTree(parent)
        except BaseException:
            try:
                parent.kill()
                parent.wait(timeout=KILL_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
            raise
        reason = ""
        timed_out = False
        initial_survivors: list[int] = []
        try:
            while True:
                living = tree.refresh()
                returncode = parent.poll()
                if tree.inspection_errors:
                    reason = "Owned process inspection failed"
                    break
                if returncode is not None:
                    initial_survivors = [
                        identity.process.pid
                        for identity in living
                        if identity.process.pid != parent.pid
                    ]
                    if initial_survivors:
                        reason = (
                            "Command exited with owned descendants still alive: "
                            f"{initial_survivors}"
                        )
                    break
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    reason = f"Command exceeded its {timeout:g}-second deadline"
                    break
                time.sleep(min(POLL_SECONDS, remaining))
        except BaseException:
            tree.cleanup()
            raise
        survivors = tree.cleanup() if reason else []
        output = read_output(stdout)
        error = read_output(stderr)
        if reason:
            diagnostic = (
                f"{reason}; survivors after cleanup: {survivors}; "
                f"inspection errors: {sorted(tree.inspection_errors)}"
            )
            error += f"\n[owned subprocess] {diagnostic}\n"
            if timed_out:
                raise subprocess.TimeoutExpired(
                    command, timeout, output=output, stderr=error
                )
            raise OwnedProcessError(
                command, parent.returncode, output, error, survivors, diagnostic
            )
        return subprocess.CompletedProcess(command, parent.returncode, output, error)
