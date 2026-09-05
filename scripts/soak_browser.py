"""Run opt-in fresh-session or sustained long-lived Chrome/Edge workloads.

Only a previously populated cache is used. Each acquisition owns a fresh profile;
no personal profile, external website, download, or system setting is requested.
Fresh-session mode runs the documented Actions.send_keys example in each session.
Long-lived mode keeps one session open while repeatedly exercising DOM, scripts,
actions, windows and timeout changes, with configurable resource-growth limits.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import doctest
import inspect
import json
import platform
import statistics
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from urllib.parse import quote

import psutil

from aselenium import Chrome, Edge, Session, errors
from aselenium.actions import Actions
from aselenium.options import ChromiumBaseOptions
from aselenium.service import BaseService

HTML = "<title>Aselenium soak</title><input id='inputbox'>"
EXAMPLES = doctest.DocTestParser().get_examples(inspect.getdoc(Actions.send_keys) or "")
LONG_HTML = "<title>Aselenium sustained fixture</title><input id='inputbox'><main id='markers'></main>"
MIB = 1024 * 1024


def resources() -> dict[str, int]:
    """Measure resources owned by this Python process, without inspecting others.

    Returns:
        RSS bytes and an OS-specific open-handle count at the observation point.
    """
    process = psutil.Process()
    handles = (
        process.num_handles() if hasattr(process, "num_handles") else process.num_fds()
    )
    return {"rss_bytes": process.memory_info().rss, "handles": handles}


async def execute_example(session: Session) -> None:
    """Run the package's prompted action example against a live local input field.

    Args:
        session: Started session displaying the local soak fixture.
    """
    namespace = {"session": session}
    for example in EXAMPLES:
        code = compile(
            example.source,
            "Actions.send_keys:Example",
            "exec",
            ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
        result = eval(code, namespace)
        if inspect.isawaitable(result):
            await result
    field = await session.find_element("#inputbox")
    if field is None or await field.get_property("value") != "Hello world!":
        raise AssertionError(
            "The prompted example did not populate the input correctly"
        )


async def mixed_iteration(session: Session, iteration: int) -> None:
    """Exercise stateful public APIs without replacing the long-lived session.

    Args:
        session: Started session on the controlled local data URL.
        iteration: Sequence number used to detect stale DOM or cached-script results.
    """
    await session.set_timeouts(implicit=0, pageLoad=10, script=5)
    if iteration % 10 == 0:
        await exercise_script_timeout(session)
    field = await session.find_element("#inputbox")
    if field is None:
        raise AssertionError("Long-lived session lost its local input")
    await field.clear()
    value = f"iteration-{iteration}"
    await session.actions().move_to(field).click().send_keys(value).perform()
    if await field.get_property("value") != value:
        raise AssertionError("Action chain produced an incorrect input value")
    if await session.execute_script("soak-identity", iteration) != iteration:
        raise AssertionError("Cached script did not retain the iteration argument")
    if (
        await session.execute_async_script(
            "arguments[arguments.length - 1](arguments[0]);", iteration
        )
        != iteration
    ):
        raise AssertionError("Asynchronous script returned a stale iteration value")
    await session.execute_script(
        "const n=document.createElement('span');n.id='marker';n.textContent=arguments[0];document.querySelector('#markers').appendChild(n);",
        value,
    )
    marker = await session.find_element("#marker")
    if marker is None or await marker.text != value:
        raise AssertionError("DOM insertion returned an incorrect marker")
    await session.execute_script("document.querySelector('#marker').remove();")
    original = await session.active_window
    if original is None:
        raise AssertionError("The original session window disappeared")
    try:
        await session.new_window(f"iteration-{iteration}")
        await session.load("data:text/html,<title>Aselenium temporary tab</title>")
        if await session.title != "Aselenium temporary tab":
            raise AssertionError("The temporary tab did not navigate to its local page")
    finally:
        active = await session.active_window
        if active is not None and active.handle != original.handle:
            await session.close_window(switch_to=original)
    if len(await session.windows) != 1:
        raise AssertionError("An iteration left an extra browser window")
    if await session.title != "Aselenium sustained fixture":
        raise AssertionError("The iteration did not restore its original window")


async def exercise_script_timeout(session: Session) -> None:
    """Require a controlled native script timeout and restore the normal budget.

    Args:
        session: Long-lived session on the controlled local page.

    Raises:
        AssertionError: An async script that never invokes its callback succeeds.
        errors.WebDriverError: A different driver error occurs or restoring timeouts fails.
    """
    try:
        await session.set_timeouts(script=0.05)
        try:
            await session.execute_async_script("void 0;")
        except errors.JavaScriptTimeoutError:
            pass
        else:
            raise AssertionError("Async script without a callback did not time out")
    finally:
        await session.set_timeouts(script=5)


def long_resources(service: BaseService) -> dict[str, int]:
    """Measure Python resources and only this session's owned browser process tree.

    Args:
        service: Running service belonging to the long-lived acquisition.

    Returns:
        Python RSS/handle counts and aggregate owned-process RSS/process count.
    """
    sample = resources()
    process = service.process
    if process is None:
        raise RuntimeError("The long-lived session lost its owned service process")
    sample["owned_rss_bytes"] = 0
    sample["owned_processes"] = 0
    for child in (process, *process.children(recursive=True)):
        try:
            if child.status() != psutil.STATUS_ZOMBIE:
                sample["owned_rss_bytes"] += child.memory_info().rss
                sample["owned_processes"] += 1
        except psutil.NoSuchProcess:
            continue
    return sample


def enforce_resource_bounds(
    baseline: dict[str, int], current: dict[str, int], args: argparse.Namespace
) -> None:
    """Enforce declared post-warmup growth budgets without claiming leak freedom.

    Args:
        baseline: Resource observation after the first full mixed iteration.
        current: Latest resource observation in the same session.
        args: Configured Python/browser memory, handle and process growth budgets.

    Raises:
        AssertionError: Any configured growth budget is exceeded.
    """
    limits = {
        "rss_bytes": args.max_rss_growth_mib * MIB,
        "owned_rss_bytes": args.max_browser_rss_growth_mib * MIB,
        "handles": args.max_handle_growth,
        "owned_processes": args.max_process_growth,
    }
    for key, limit in limits.items():
        growth = current[key] - baseline[key]
        if growth > limit:
            raise AssertionError(
                f"Resource growth exceeded {key} budget: {growth} > {limit}"
            )


async def soak_long_lived(args: argparse.Namespace) -> dict[str, Any]:
    """Keep one session alive for a configurable sustained mixed workload.

    Args:
        args: Browser/binary/cache, duration, pacing and explicit growth budgets.

    Returns:
        Version metadata, iteration count, sampled resource growth and cleanup evidence.
        The observed duration and budgets are acceptance bounds, not proof of no leaks.
    """
    initial_tasks = set(asyncio.all_tasks())
    owned_processes: set[tuple[int, float]] = set()
    samples: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "status": "failed",
        "mode": "long-lived",
        "browser": args.browser,
    }
    with TemporaryDirectory(prefix="aselenium-sustained-template-") as template:
        (Path(template) / "Default").mkdir()
        driver = (Chrome if args.browser == "chrome" else Edge)(
            directory=args.cache_dir
        )
        driver.options.add_arguments(
            "--headless=new",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--no-first-run",
        )
        driver.options.set_profile(template, "Default")
        driver.options.set_timeouts(implicit=0, pageLoad=10, script=5)
        driver.options.session_timeout = 20
        configured_profile = driver.options.profile
        if configured_profile is None or configured_profile.directory_temp is None:
            raise AssertionError("Chromium profile template was not configured")
        template_profile = configured_profile.directory_temp
        context = driver.acquire("offline", binary=args.binary)
        context_options = cast(ChromiumBaseOptions, context._options)
        context_profile = context_options.profile
        if context_profile is None or context_profile.directory_temp is None:
            raise AssertionError("Acquisition profile snapshot was not created")
        profile = context_profile.directory_temp
        iterations = 0
        elapsed = 0.0
        try:
            async with context as session:
                result["session_id"] = session.id
                await session.load("data:text/html;charset=utf-8," + quote(LONG_HTML))
                session.cache_script("soak-identity", "return arguments[0];")
                started = time.monotonic()
                baseline: dict[str, int] | None = None
                while iterations == 0 or time.monotonic() - started < args.duration:
                    if iterations >= args.max_iterations:
                        raise AssertionError(
                            "Configured iteration limit reached before requested duration"
                        )
                    await asyncio.wait_for(
                        mixed_iteration(session, iterations), timeout=30
                    )
                    iterations += 1
                    service_process = session.service.process
                    if service_process is None:
                        raise AssertionError("WebDriver service process disappeared")
                    for process in (
                        service_process,
                        *service_process.children(recursive=True),
                    ):
                        try:
                            owned_processes.add((process.pid, process.create_time()))
                        except psutil.NoSuchProcess:
                            pass
                    sample = long_resources(session.service)
                    if baseline is None:
                        baseline = sample.copy()
                    enforce_resource_bounds(baseline, sample, args)
                    elapsed = time.monotonic() - started
                    # Cap evidence growth while retaining the first, periodic and
                    # latest observations even during hour-long opt-in runs.
                    observation = {
                        "iteration": iterations,
                        "elapsed_seconds": elapsed,
                        **sample,
                    }
                    if iterations == 1 or iterations % 10 == 0:
                        samples.append(observation)
                    result["last_sample"] = observation
                    if args.interval:
                        await asyncio.sleep(args.interval)
                elapsed = time.monotonic() - started
                result["baseline"] = baseline
                result["status"] = "passed"
        except Exception as cause:
            result["status"] = "failed"
            result["failure_type"] = type(cause).__name__
            result["failure"] = str(cause)
        finally:
            driver.options.close()
        alive = []
        for pid, created in sorted(owned_processes):
            try:
                process = psutil.Process(pid)
                if (
                    process.create_time() == created
                    and process.status() != psutil.STATUS_ZOMBIE
                ):
                    alive.append(pid)
            except psutil.NoSuchProcess:
                pass
        pending = [
            task for task in asyncio.all_tasks() - initial_tasks if not task.done()
        ]
        installation = driver.manager.last_result
        result.update(
            {
                "browser_version": installation.browser_version
                if installation
                else None,
                "driver_version": installation.driver_version if installation else None,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "iterations": iterations,
                "controlled_native_script_timeouts": (iterations + 9) // 10,
                "requested_duration_seconds": args.duration,
                "workload_elapsed_seconds": elapsed,
                "resource_samples": samples,
                "growth_limits": {
                    "python_rss_mib": args.max_rss_growth_mib,
                    "browser_tree_rss_mib": args.max_browser_rss_growth_mib,
                    "handles": args.max_handle_growth,
                    "processes": args.max_process_growth,
                },
                "session_profile_removed": not profile.exists(),
                "template_profile_removed": not template_profile.exists(),
                "remaining_observed_processes": alive,
                "remaining_owned_tasks": len(pending),
                "scope": "one sustained session; controlled data URLs; DOM/scripts/actions/windows/native-timeout recovery; post-warmup growth bounds; not unlimited stability certification",
            }
        )
        if alive or pending or profile.exists() or template_profile.exists():
            result["status"] = "failed"
    return result


async def soak(args: argparse.Namespace) -> dict[str, Any]:
    """Repeat independent session lifecycles and check owned process/task cleanup.

    Args:
        args: Browser, binary, populated cache, batch size, and cycle count.

    Returns:
        Version metadata, latency distribution, resource samples, and cleanup status.
        RSS samples are observations, not a proof of leak freedom.
    """
    driver = (Chrome if args.browser == "chrome" else Edge)(directory=args.cache_dir)
    driver.options.add_arguments(
        "--headless=new",
        "--disable-background-networking",
        "--disable-sync",
        "--no-first-run",
    )
    driver.options.set_timeouts(implicit=0, pageLoad=10, script=5)
    driver.options.session_timeout = 20
    initial_tasks = set(asyncio.all_tasks())
    owned_processes: set[tuple[int, float]] = set()
    samples = [resources()]
    durations: list[float] = []

    async def cycle() -> None:
        """Acquire one fresh session, execute the example, and await full teardown."""
        started = time.monotonic()
        async with driver.acquire("offline", binary=args.binary) as session:
            for process in psutil.Process().children(recursive=True):
                try:
                    owned_processes.add((process.pid, process.create_time()))
                except psutil.NoSuchProcess:
                    pass
            await session.load("data:text/html;charset=utf-8," + quote(HTML))
            if await session.title != "Aselenium soak":
                raise AssertionError("Fresh session did not load its local fixture")
            await execute_example(session)
        durations.append(time.monotonic() - started)

    try:
        for start in range(0, args.cycles, args.concurrency):
            # Await every sibling even if one fails; no browser task is abandoned.
            results = await asyncio.gather(
                *(cycle() for _ in range(min(args.concurrency, args.cycles - start))),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            samples.append(resources())
        await asyncio.sleep(0.1)
        alive = []
        for pid, created in sorted(owned_processes):
            try:
                process = psutil.Process(pid)
                if (
                    process.create_time() == created
                    and process.is_running()
                    and process.status() != psutil.STATUS_ZOMBIE
                ):
                    alive.append(pid)
            except psutil.NoSuchProcess:
                pass
        pending = [
            task for task in asyncio.all_tasks() - initial_tasks if not task.done()
        ]
        installation = driver.manager.last_result
        ordered = sorted(durations)
        return {
            "status": "passed" if not alive and not pending else "failed",
            "mode": "fresh",
            "browser": args.browser,
            "browser_version": installation.browser_version if installation else None,
            "driver_version": installation.driver_version if installation else None,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cycles": len(durations),
            "concurrency": args.concurrency,
            "median_cycle_seconds": statistics.median(durations),
            "p95_cycle_seconds": ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)],
            "resource_samples": samples,
            "observed_child_processes": len(owned_processes),
            "remaining_observed_processes": alive,
            "remaining_owned_tasks": len(pending),
            "scope": "bounded local-data-URL soak; offline cache; fresh profiles; not a long-duration stability certification",
        }
    finally:
        driver.options.close()


def main() -> int:
    """Run the explicitly requested browser soak and print its JSON evidence.

    Returns:
        Zero after a clean soak, or one if observed resources remain alive.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=("chrome", "edge"), required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--mode", choices=("fresh", "long-lived"), default="fresh")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--interval", type=float, default=0.05)
    parser.add_argument("--max-iterations", type=int, default=10000)
    parser.add_argument("--max-rss-growth-mib", type=float, default=128)
    parser.add_argument("--max-browser-rss-growth-mib", type=float, default=512)
    parser.add_argument("--max-handle-growth", type=int, default=32)
    parser.add_argument("--max-process-growth", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100 or not 1 <= args.concurrency <= 4:
        parser.error("cycles must be 1..100 and concurrency must be 1..4")
    if not 1 <= args.duration <= 3600 or not 0 <= args.interval <= 5:
        parser.error(
            "duration must be 1..3600 seconds and interval must be 0..5 seconds"
        )
    if not 1 <= args.max_iterations <= 100000:
        parser.error("max-iterations must be 1..100000")
    if (
        not 0 <= args.max_rss_growth_mib <= 4096
        or not 0 <= args.max_browser_rss_growth_mib <= 8192
    ):
        parser.error("RSS growth budgets must be finite nonnegative bounded MiB values")
    if (
        not 0 <= args.max_handle_growth <= 4096
        or not 0 <= args.max_process_growth <= 128
    ):
        parser.error("handle/process growth budgets are out of range")
    operation = soak_long_lived(args) if args.mode == "long-lived" else soak(args)
    result = asyncio.run(
        asyncio.wait_for(
            operation, timeout=args.duration + 60 if args.mode == "long-lived" else 300
        )
    )
    serialized = json.dumps(result, indent=2)
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
