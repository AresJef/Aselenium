"""Offline workload and resource-bound checks for opt-in browser soak modes."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from aselenium import Chrome, errors


class AwaitableElement(SimpleNamespace):
    """Provide the async text property used by the mixed-workload controller."""

    @property
    async def text(self) -> str:
        """Return a controlled marker value without interacting with a browser.

        Returns:
            Text configured on the inert element.
        """
        return self.text_value


class WorkloadSession(SimpleNamespace):
    """Model async properties at the acceptance controller's session boundary."""

    @property
    async def title(self) -> str:
        """Return the next expected temporary/original window title.

        Returns:
            Next title observation in the controlled sequence.
        """
        return self.title_values.pop(0)

    @property
    async def active_window(self) -> SimpleNamespace:
        """Return the next original/temporary active-window observation.

        Returns:
            Controlled window handle for this point in the workload.
        """
        return self.active_values.pop(0)

    @property
    async def windows(self) -> list[SimpleNamespace]:
        """Return the modeled window registry after temporary-tab cleanup.

        Returns:
            Current fixture window handles.
        """
        return self.window_values


@pytest.fixture
def soak_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the opt-in soak script without acquiring any browser.

    Args:
        monkeypatch: Fixture restoring temporary module registration.

    Returns:
        The maintenance script whose workload controller is being tested.
    """
    path = Path(__file__).resolve().parents[1] / "scripts" / "soak_browser.py"
    spec = importlib.util.spec_from_file_location("aselenium_soak_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workload() -> WorkloadSession:
    """Build a deterministic mixed workload with independently specified responses.

    Returns:
        Session double representing iteration seven and an original/temporary tab.
    """
    field = AwaitableElement(
        clear=AsyncMock(), get_property=AsyncMock(return_value="iteration-7")
    )
    marker = AwaitableElement(text_value="iteration-7")
    actions = Mock()
    actions.move_to.return_value = actions
    actions.click.return_value = actions
    actions.send_keys.return_value = actions
    actions.perform = AsyncMock()
    original = SimpleNamespace(handle="original")
    temporary = SimpleNamespace(handle="temporary")
    return WorkloadSession(
        field=field,
        marker=marker,
        action_chain=actions,
        original=original,
        find_element=AsyncMock(side_effect=[field, marker]),
        set_timeouts=AsyncMock(),
        actions=Mock(return_value=actions),
        execute_script=AsyncMock(side_effect=[7, None, None]),
        execute_async_script=AsyncMock(return_value=7),
        new_window=AsyncMock(),
        close_window=AsyncMock(),
        load=AsyncMock(),
        active_values=[original, temporary],
        window_values=[original],
        title_values=["Aselenium temporary tab", "Aselenium sustained fixture"],
    )


@pytest.mark.asyncio
async def test_mixed_workload_checks_each_feature_family(
    soak_module: ModuleType, workload: WorkloadSession
) -> None:
    """Exercise inputs, scripts, DOM markers, windows, and timeout changes per iteration.

    Args:
        soak_module: Imported soak controller.
        workload: Controlled iteration-seven responses.
    """
    await soak_module.mixed_iteration(workload, 7)
    workload.set_timeouts.assert_awaited_once_with(implicit=0, pageLoad=10, script=5)
    workload.field.clear.assert_awaited_once_with()
    workload.action_chain.move_to.assert_called_once_with(workload.field)
    workload.action_chain.send_keys.assert_called_once_with("iteration-7")
    workload.action_chain.perform.assert_awaited_once_with()
    assert workload.execute_script.await_args_list[0].args == ("soak-identity", 7)
    assert workload.execute_script.await_args_list[1].args[1] == "iteration-7"
    workload.new_window.assert_awaited_once_with("iteration-7")
    workload.close_window.assert_awaited_once_with(switch_to=workload.original)


@pytest.mark.asyncio
async def test_periodic_native_timeout_is_followed_by_successful_mixed_work(
    soak_module: ModuleType, workload: WorkloadSession
) -> None:
    """Recover from the scheduled native script timeout before verifying normal APIs.

    Args:
        soak_module: Imported mixed-workload controller.
        workload: Controlled responses adjusted to the first timeout-enabled iteration.
    """
    workload.field.get_property.return_value = "iteration-0"
    workload.marker.text_value = "iteration-0"
    workload.execute_script.side_effect = [0, None, None]
    workload.execute_async_script.side_effect = [
        errors.JavaScriptTimeoutError("native timeout"),
        0,
    ]
    await soak_module.mixed_iteration(workload, 0)
    assert [call.kwargs for call in workload.set_timeouts.await_args_list] == [
        {"implicit": 0, "pageLoad": 10, "script": 5},
        {"script": 0.05},
        {"script": 5},
    ]
    assert workload.execute_async_script.await_args_list[0].args == ("void 0;",)
    workload.action_chain.perform.assert_awaited_once_with()
    workload.close_window.assert_awaited_once_with(switch_to=workload.original)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["success", "wrong-timeout", "driver-error"])
async def test_native_timeout_restores_budget_and_rejects_wrong_outcome(
    soak_module: ModuleType, failure: str
) -> None:
    """Restore normal timeouts for unexpected success or a different driver failure.

    Args:
        soak_module: Imported timeout-recovery workload.
        failure: Unexpected outcome returned by the controlled async-script call.
    """
    errors_by_case = {
        "success": None,
        "wrong-timeout": errors.SessionTimeoutError("transport timeout"),
        "driver-error": errors.InvalidSessionError("session lost"),
    }
    session = SimpleNamespace(
        set_timeouts=AsyncMock(),
        execute_async_script=AsyncMock(side_effect=errors_by_case[failure]),
    )
    expected = AssertionError if failure == "success" else type(errors_by_case[failure])
    with pytest.raises(expected):
        await soak_module.exercise_script_timeout(session)
    assert [call.kwargs for call in session.set_timeouts.await_args_list] == [
        {"script": 0.05},
        {"script": 5},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "missing-input",
        "wrong-input",
        "cached-script",
        "async-script",
        "marker",
        "temporary-title",
        "extra-window",
    ],
)
async def test_mixed_workload_does_not_accept_wrong_results(
    soak_module: ModuleType, workload: WorkloadSession, failure: str
) -> None:
    """Fail the acceptance iteration when any exercised feature returns incorrect state.

    Args:
        soak_module: Imported soak controller.
        workload: Controlled responses whose selected feature will be corrupted.
        failure: Feature observation deliberately changed to an invalid result.
    """
    if failure == "missing-input":
        workload.find_element.side_effect = [None]
    elif failure == "wrong-input":
        workload.field.get_property.return_value = "stale"
    elif failure == "cached-script":
        workload.execute_script.side_effect = [6]
    elif failure == "async-script":
        workload.execute_async_script.return_value = 6
    elif failure == "marker":
        workload.marker.text_value = "stale"
    elif failure == "temporary-title":
        workload.title_values[0] = "wrong page"
    else:
        workload.window_values.append(SimpleNamespace(handle="leaked"))
    with pytest.raises(AssertionError):
        await soak_module.mixed_iteration(workload, 7)
    if failure == "temporary-title":
        workload.close_window.assert_awaited_once_with(switch_to=workload.original)


@pytest.mark.parametrize(
    "key,limit",
    [
        ("rss_bytes", 1024 * 1024),
        ("owned_rss_bytes", 2 * 1024 * 1024),
        ("handles", 3),
        ("owned_processes", 4),
    ],
)
def test_resource_growth_limits_have_strict_boundaries(
    soak_module: ModuleType, key: str, limit: int
) -> None:
    """Allow growth through the configured limit and reject the next increment.

    Args:
        soak_module: Imported resource-budget checker.
        key: Resource dimension being independently tested.
        limit: Its expected byte/count limit after unit conversion.
    """
    args = argparse.Namespace(
        max_rss_growth_mib=1,
        max_browser_rss_growth_mib=2,
        max_handle_growth=3,
        max_process_growth=4,
    )
    baseline = {
        "rss_bytes": 1000,
        "owned_rss_bytes": 2000,
        "handles": 10,
        "owned_processes": 5,
    }
    current = baseline | {key: baseline[key] + limit}
    soak_module.enforce_resource_bounds(baseline, current, args)
    with pytest.raises(AssertionError, match=key):
        soak_module.enforce_resource_bounds(
            baseline, current | {key: current[key] + 1}, args
        )


def test_owned_resource_measurement_excludes_unrelated_processes(
    soak_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aggregate only the supplied service and its explicitly enumerated descendants.

    Args:
        soak_module: Imported resource sampler.
        monkeypatch: Fixture restoring the inert Python-process resource sample.
    """
    monkeypatch.setattr(
        soak_module, "resources", lambda: {"rss_bytes": 50, "handles": 4}
    )
    root = Mock()
    child = Mock()
    zombie = Mock()
    root.children.return_value = [child, zombie]
    root.status.return_value = child.status.return_value = (
        soak_module.psutil.STATUS_RUNNING
    )
    zombie.status.return_value = soak_module.psutil.STATUS_ZOMBIE
    root.memory_info.return_value = SimpleNamespace(rss=100)
    child.memory_info.return_value = SimpleNamespace(rss=200)
    result = soak_module.long_resources(SimpleNamespace(process=root))
    assert result == {
        "rss_bytes": 50,
        "handles": 4,
        "owned_rss_bytes": 300,
        "owned_processes": 2,
    }
    root.children.assert_called_once_with(recursive=True)
    zombie.memory_info.assert_not_called()


def test_soak_acceptance_checks_survive_optimized_python(
    soak_module: ModuleType,
) -> None:
    """Do not let Python optimization remove native acceptance checks.

    Args:
        soak_module: Imported workload controller.
    """
    tree = ast.parse(Path(soak_module.__file__).read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))


@pytest.mark.parametrize(
    "arguments",
    [
        ("--duration", "nan"),
        ("--interval", "inf"),
        ("--max-rss-growth-mib", "nan"),
        ("--max-process-growth", "-1"),
        ("--max-iterations", "0"),
    ],
)
def test_invalid_cli_budgets_fail_without_acquisition(
    soak_module: ModuleType, monkeypatch: pytest.MonkeyPatch, arguments: tuple[str, str]
) -> None:
    """Reject invalid sustained-workload limits before constructing a browser facade.

    Args:
        soak_module: Imported CLI entry point.
        monkeypatch: Fixture restoring command-line arguments and facade construction.
        arguments: Invalid budget option/value pair.
    """
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "soak_browser.py",
            "--browser",
            "chrome",
            "--binary",
            "/unused",
            "--cache-dir",
            "/unused",
            "--mode",
            "long-lived",
            *arguments,
        ],
    )
    facade = Mock(side_effect=AssertionError("Invalid CLI launched a browser"))
    monkeypatch.setattr(soak_module, "Chrome", facade)
    with pytest.raises(SystemExit) as failure:
        soak_module.main()
    assert failure.value.code == 2
    facade.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_sustained_controller_cleans_profiles_and_preserves_teardown_failure(
    soak_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cleanup_fails: bool,
) -> None:
    """Run the one-iteration controller without a browser and preserve cleanup failures.

    Args:
        soak_module: Imported long-lived workload controller.
        monkeypatch: Fixture restoring facade, resource and process boundaries.
        tmp_path: Disposable cache directory for real option/profile ownership.
        cleanup_fails: Whether context teardown raises after releasing its profile.
    """
    driver = Chrome(directory=str(tmp_path))
    process = Mock()
    process.pid = 40001
    process.create_time.return_value = 10
    process.children.return_value = []
    process.status.return_value = soak_module.psutil.STATUS_RUNNING
    session = SimpleNamespace(
        id="sustained",
        load=AsyncMock(),
        cache_script=Mock(),
        service=SimpleNamespace(process=process),
    )

    def acquire(*args: object, **kwargs: object) -> AsyncMock:
        """Create a context owning a real options snapshot but no native service.

        Args:
            *args: Offline acquisition selector inspected by the test.
            **kwargs: Explicit binary acquisition keyword inspected by the test.

        Returns:
            Context double closing the same independent profile ownership as production.
        """
        assert args == ("offline",) and kwargs == {"binary": "/unused/browser"}
        snapshot = driver.options.snapshot()
        context = AsyncMock()
        context._options = snapshot
        context.__aenter__.return_value = session

        async def close(*exit_args: object) -> bool:
            """Release the snapshot and optionally simulate a post-release teardown error.

            Args:
                *exit_args: Exception triple supplied by async context management.

            Returns:
                False so caller exceptions are never suppressed.

            Raises:
                RuntimeError: The requested teardown-failure scenario is active.
            """
            snapshot.close()
            process.status.return_value = soak_module.psutil.STATUS_ZOMBIE
            if cleanup_fails:
                raise RuntimeError("fixture teardown failure")
            return False

        context.__aexit__.side_effect = close
        return context

    monkeypatch.setattr(driver, "acquire", acquire)
    monkeypatch.setattr(soak_module, "Chrome", lambda **kwargs: driver)
    monkeypatch.setattr(soak_module, "mixed_iteration", AsyncMock())
    monkeypatch.setattr(
        soak_module,
        "long_resources",
        Mock(
            return_value={
                "rss_bytes": 100,
                "owned_rss_bytes": 200,
                "handles": 4,
                "owned_processes": 1,
            }
        ),
    )
    monkeypatch.setattr(soak_module.psutil, "Process", Mock(return_value=process))
    args = argparse.Namespace(
        browser="chrome",
        cache_dir=str(tmp_path),
        binary="/unused/browser",
        duration=0,
        interval=0,
        max_iterations=1,
        max_rss_growth_mib=1,
        max_browser_rss_growth_mib=1,
        max_handle_growth=1,
        max_process_growth=1,
    )
    result = await soak_module.soak_long_lived(args)
    assert result["status"] == ("failed" if cleanup_fails else "passed")
    assert result["iterations"] == 1
    assert result["session_profile_removed"] and result["template_profile_removed"]
    assert not result["remaining_observed_processes"]
    assert result["remaining_owned_tasks"] == 0
    if cleanup_fails:
        assert result["failure_type"] == "RuntimeError"
