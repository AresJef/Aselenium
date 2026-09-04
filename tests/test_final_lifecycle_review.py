"""Regressions for partial service startup and side-effect-free diagnostics."""

from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from aselenium import errors
from aselenium import webdriver as webdriver_module
from aselenium._profiles import _OWNERS, claim_profile
from aselenium.chrome.options import ChromeOptions
from aselenium.manager.version import ChromiumVersion
from aselenium.service import ChromiumBaseService
from aselenium.webdriver import SessionContext


@pytest.fixture
def service(tmp_path: Path) -> ChromiumBaseService:
    """Construct a real service without launching a driver or allocating a port.

    Args:
        tmp_path: Disposable directory for an inert executable file.

    Returns:
        Unstarted service with a short teardown budget.
    """
    executable = tmp_path / "inert-driver"
    executable.touch()
    return ChromiumBaseService(ChromiumVersion("120.0.1.1"), str(executable), 0.1)


def test_partial_startup_escalates_and_reaps_authoritative_child(
    service: ChromiumBaseService,
) -> None:
    """Kill a terminate-resistant child even when psutil identity capture failed.

    Args:
        service: Unstarted real service with no psutil process identity.
    """
    child = Mock()
    child.wait.side_effect = [TimeoutExpired("inert-driver", 0.05), 0]
    service._popen = child

    service._stop_process()

    child.terminate.assert_called_once_with()
    child.kill.assert_called_once_with()
    assert child.wait.call_count == 2
    assert all(0 < call.kwargs["timeout"] <= 0.1 for call in child.wait.call_args_list)
    assert service._popen is None and service.process is None


def test_partial_startup_failed_kill_retains_child_for_retry(
    service: ChromiumBaseService,
) -> None:
    """Retain ownership and expose a typed failure when forceful cleanup fails.

    Args:
        service: Unstarted real service with no psutil process identity.
    """
    child = Mock()
    child.wait.side_effect = TimeoutExpired("inert-driver", 0.05)
    child.kill.side_effect = PermissionError("fixture cannot signal child")
    service._popen = child

    with pytest.raises(errors.ServiceProcessError, match="ownership retained") as error:
        service._stop_process()

    child.kill.assert_called_once_with()
    assert isinstance(error.value.__cause__, PermissionError)
    assert service._popen is child

    child.wait.side_effect = None
    child.wait.return_value = 0
    child.kill.side_effect = None
    service._stop_process()
    assert service._popen is None


def test_service_repr_does_not_allocate_a_port(
    service: ChromiumBaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logging an unstarted service must not perform socket operations.

    Args:
        service: Unstarted service whose diagnostic string is requested.
        monkeypatch: Fixture restoring the intercepted port allocator.
    """
    allocate = Mock(side_effect=AssertionError("Diagnostic allocated a port"))
    monkeypatch.setattr(service, "get_free_port", allocate)

    representation = repr(service)

    assert "ChromiumBaseService" in representation
    allocate.assert_not_called()
    assert service._port == -1 and service._url is None


def test_service_repr_preserves_an_existing_url(service: ChromiumBaseService) -> None:
    """Diagnostics still identify an already-initialized service endpoint.

    Args:
        service: Service with an explicitly initialized synthetic endpoint.
    """
    service._url = "http://localhost:41234"
    assert "http://localhost:41234" in repr(service)


@pytest.mark.asyncio
async def test_profile_path_resolution_runs_off_loop_and_releases_failed_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep filesystem path canonicalization off the loop without leaking ownership.

    Args:
        tmp_path: Disposable explicitly shared profile directory, never deleted by options.
        monkeypatch: Intercept ownership claiming to record the actual execution thread.
    """
    caller_thread = get_ident()
    claim_threads: list[int] = []
    options = ChromeOptions()
    options.add_arguments("--user-data-dir=" + str(tmp_path))

    def claim_in_thread(selected: ChromeOptions, owner: object) -> None:
        """Record thread identity and run the real profile reservation.

        Args:
            selected: Acquisition-time options snapshot.
            owner: Session context reserving the explicit profile path.
        """
        claim_threads.append(get_ident())
        claim_profile(selected, owner)

    monkeypatch.setattr(webdriver_module, "claim_profile", claim_in_thread)
    manager = SimpleNamespace(
        install_result=AsyncMock(
            side_effect=errors.InvalidDriverVersionError("fixture")
        )
    )
    context = SessionContext(manager, (), {}, ChromiumBaseService, 1, (), {}, options)
    try:
        with pytest.raises(errors.InvalidDriverVersionError, match="fixture"):
            await context.start()
        assert len(claim_threads) == 1 and claim_threads[0] != caller_thread
        assert context._state == "closed"
        assert all(owner is not context for owner in _OWNERS.values())
        assert tmp_path.is_dir()
    finally:
        await context.quit()
        options.close()
