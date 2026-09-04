"""Process contracts use fakes plus two explicitly scoped Python-child checks.

No browser, driver or shell is launched. Real child commands are fixed Python
snippets without filesystem/network operations.
"""

from __future__ import annotations

import json
import subprocess
import sys
from base64 import b64decode
from io import BytesIO
from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired
from typing import Any

import pytest

from aselenium import errors
from aselenium.manager import driver as drivers


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Probe.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.

    Returns:
        Fixture value or simulated response used by the regression.
    """

    class Process:
        """Represent Process using the inherited implementation."""

        calls = []
        instances = []
        result = b"Chrome 120.0.6000.1\n"
        code = 0
        failure = None
        wait_failure = False

        def __init__(self, argv: Any, **kwargs: Any) -> None:
            """Initialize the instance with the supplied configuration.

            Args:
                argv: Fixture or parametrized argv input for this regression.
                **kwargs: Fixture or parametrized kwargs input for this regression.
            """
            self.calls.append((argv, kwargs))
            self.instances.append(self)
            self.stdout = BytesIO()
            self.returncode = self.code
            self.events = []

        def communicate(self, *, timeout: Any) -> Any:
            """Communicate.

            Args:
                timeout: Fixture or parametrized timeout input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            self.events.append(("communicate", timeout))
            if self.failure is not None:
                raise self.failure
            return self.result, None

        def kill(self) -> None:
            """Kill."""
            self.events.append(("kill",))

        def wait(self, *, timeout: Any) -> Any:
            """Wait.

            Args:
                timeout: Fixture or parametrized timeout input for this regression.

            Returns:
                Fixture value or simulated response used by the regression.
            """
            self.events.append(("wait", timeout))
            if self.wait_failure:
                raise TimeoutExpired("fixture", timeout)
            return -9

    monkeypatch.setattr(drivers, "Popen", Process)
    return Process


@pytest.mark.parametrize("platform", ["linux", "mac"])
@pytest.mark.parametrize(
    "name",
    [
        "plain",
        "浏览 器",
        "browser;echo injected",
        "$(touch x)",
        "quote'\"`$&|<>[]{}",
        "line\nbreak",
    ],
)
def test_unix_probe_uses_literal_path_and_deadline(
    tmp_path: Path, platform: Any, name: Any, probe: Any
) -> None:
    """Verify unix probe uses literal path and deadline.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        platform: Fixture or parametrized platform input for this regression.
        name: Fixture or parametrized name input for this regression.
        probe: Fixture or parametrized probe input for this regression.
    """
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    manager._DriverManager__os_name = platform
    path = str(tmp_path / name)
    assert manager._detect_browser_version(path).version == "120.0.6000.1"
    argv, kwargs = probe.calls[0]
    assert argv == [path, "--version"]
    assert kwargs["shell"] is False
    instance = probe.instances[0]
    assert instance.events == [("communicate", 10.0)]
    assert instance.stdout.closed


@pytest.mark.parametrize(
    "name",
    [
        r"C:\Browser\chrome.exe",
        r"C:\O'Brien\[chrome].exe",
        "C:\\Browser\\a'; $(Write-Output HACKED); 'b.exe",
        "C:\\浏览器\\a\n'b.exe",
    ],
)
def test_windows_probe_encodes_a_literal_noninteractive_script(
    tmp_path: Path, name: Any, probe: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify windows probe encodes a literal noninteractive script.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        name: Fixture or parametrized name input for this regression.
        probe: Fixture or parametrized probe input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    manager._DriverManager__os_name = "win"
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    assert manager._detect_browser_version(name).version == "120.0.6000.1"
    assert len(probe.calls) == 1
    argv, kwargs = probe.calls[0]
    assert argv[0].endswith("powershell.exe")
    assert argv[1:5] == ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
    script = b64decode(argv[5]).decode("utf-16le")
    assert script == (
        "$ErrorActionPreference='Stop'; (Get-Item -LiteralPath '%s').VersionInfo.FileVersion"
        % name.replace("'", "''")
    )
    assert kwargs["shell"] is False


@pytest.mark.parametrize("wait_failure", [False, True])
def test_probe_timeout_kills_and_bounds_reaping_without_second_pipe_read(
    tmp_path: Path, probe: Any, wait_failure: Any
) -> None:
    """Verify probe timeout kills and bounds reaping without second pipe read.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        probe: Fixture or parametrized probe input for this regression.
        wait_failure: Fixture or parametrized wait failure input for this regression.
    """
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    manager._DriverManager__os_name = "linux"
    original = TimeoutExpired("fixture", 10)
    probe.failure = original
    probe.wait_failure = wait_failure
    with pytest.raises(errors.BrowserBinaryNotDetectedError) as failure:
        manager._detect_browser_version("/synthetic/browser")
    assert failure.value.__cause__ is original
    instance = probe.instances[0]
    assert instance.events == [("communicate", 10.0), ("kill",), ("wait", 1.0)]
    assert instance.stdout.closed


def test_probe_nonzero_exit_is_not_parsed_as_success(
    tmp_path: Path, probe: Any
) -> None:
    """Verify probe nonzero exit is not parsed as success.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        probe: Fixture or parametrized probe input for this regression.
    """
    probe.code = 17
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    manager._DriverManager__os_name = "linux"
    with pytest.raises(errors.BrowserBinaryNotDetectedError) as failure:
        manager._detect_browser_version("/synthetic/browser")
    assert isinstance(failure.value.__cause__, CalledProcessError)
    assert failure.value.__cause__.returncode == 17
    assert probe.instances[0].stdout.closed


def test_invalid_output_encoding_preserves_cause(tmp_path: Path, probe: Any) -> None:
    """Verify invalid output encoding preserves cause.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        probe: Fixture or parametrized probe input for this regression.
    """
    probe.result = b"\xff"
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    manager._DriverManager__os_name = "linux"
    with pytest.raises(errors.BrowserBinaryNotDetectedError) as failure:
        manager._detect_browser_version("/synthetic/browser")
    assert isinstance(failure.value.__cause__, UnicodeDecodeError)


def test_exit_during_kill_still_reaps_and_preserves_timeout(
    tmp_path: Path, probe: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify exit during kill still reaps and preserves timeout.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        probe: Fixture or parametrized probe input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    cause = TimeoutExpired("fixture", 10)
    probe.failure = cause

    def fail_kill(self: Any) -> None:
        """Fail kill.

        Args:
            self: Patched class or instance used by this regression.
        """
        self.events.append(("kill",))
        raise ProcessLookupError("already exited")

    monkeypatch.setattr(probe, "kill", fail_kill)
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    manager._DriverManager__os_name = "linux"
    with pytest.raises(errors.BrowserBinaryNotDetectedError) as failure:
        manager._detect_browser_version("/synthetic/browser")
    assert failure.value.__cause__ is cause
    assert probe.instances[0].events[-1] == ("wait", 1.0)
    assert probe.instances[0].stdout.closed


@pytest.mark.parametrize("command", ["echo unsafe", (), [], [123]])
def test_probe_rejects_non_argument_lists_before_process_creation(
    tmp_path: Path, probe: Any, command: Any
) -> None:
    """Verify probe rejects non argument lists before process creation.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        probe: Fixture or parametrized probe input for this regression.
        command: Fixture or parametrized command input for this regression.
    """
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(TypeError):
        manager._read_from_cmd(command)
    assert probe.calls == []


def test_real_python_child_receives_metacharacters_as_literal_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify real python child receives metacharacters as literal arguments.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    monkeypatch.setattr(drivers, "Popen", subprocess.Popen)
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    argument = str(tmp_path / "浏览器 ; $(NEVER_EXECUTE) ' \" & | [x]")
    code = "import json, sys; print(json.dumps(sys.argv[1:]))"
    output = manager._read_from_cmd([sys.executable, "-I", "-c", code, argument])
    assert json.loads(output) == [argument]


def test_real_timed_out_python_child_is_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify real timed out python child is reaped.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    children = []

    def start(*args: Any, **kwargs: Any) -> Any:
        """Start.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(drivers, "Popen", start)
    manager = drivers.ChromeDriverManager(directory=str(tmp_path))
    manager._PROBE_TIMEOUT = 0.1
    with pytest.raises(TimeoutExpired):
        manager._read_from_cmd(
            [sys.executable, "-I", "-c", "import time; time.sleep(5)"]
        )
    assert len(children) == 1
    assert children[0].poll() is not None
    assert children[0].stdout.closed
