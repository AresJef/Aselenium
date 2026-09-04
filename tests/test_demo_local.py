"""The local HTML tour's CLI, ownership, fixtures, and offline-by-default contract.

No test launches a browser or makes a network request. Native runs remain opt-in.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from aselenium import Cookie


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Demo.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    path = Path(__file__).resolve().parents[1] / "src" / "demo_local.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("aselenium_demo_under_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize(
    "argv", [[], ["list"], ["--help"], ["run", "--help"], ["install", "--help"]]
)
def test_discovery_never_probes_browsers_or_creates_files(
    demo: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: Any,
) -> None:
    """Verify discovery never probes browsers or creates files.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
        capsys: Pytest fixture capturing text written to standard output and error.
        argv: Fixture or parametrized argv input for this regression.
    """

    def forbidden(*args: Any, **kwargs: Any) -> None:
        """Forbidden.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        pytest.fail("Discovery must not allocate a driver or server")

    monkeypatch.setattr(demo, "make_driver", forbidden)
    monkeypatch.setattr(demo, "fixture_server", forbidden)
    if "--help" in argv:
        with pytest.raises(SystemExit) as exc:
            demo.main(argv)
        assert exc.value.code == 0
    else:
        assert demo.main(argv) == 0
    assert capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "arguments",
    [
        ["install", "--policy", "exact", "--allow-download"],
        ["install", "--policy", "latest-compatible"],
        ["install", "--version", "152.0"],
        [
            "install",
            "--version",
            "152.0.1.1",
            "--policy",
            "compatible-build",
            "--allow-download",
        ],
        ["install", "--browser", "firefox", "--version", "0.36"],
        [
            "install",
            "--browser",
            "firefox",
            "--policy",
            "compatible-build",
            "--allow-download",
        ],
        ["install", "--browser", "safari", "--pin"],
        ["install", "--browser", "safari", "--policy", "offline"],
        ["run", "--browser", "safari", "--profile-demo"],
        ["run", "--browser", "safari", "--channel", "beta"],
        ["run", "--browser", "edge", "--channel", "cft"],
        ["run", "--channel", "cft"],
        ["install", "--channel", "cft"],
        [
            "install",
            "--channel",
            "cft",
            "--version",
            "152.0.7977.82",
            "--binary",
            "/ignored",
        ],
        ["run", "--browser", "firefox", "--channel", "dev"],
        ["run", "--browser", "chromium", "--channel", "beta"],
        ["run", "--browser", "chrome", "--profile-root", "/shared/profiles"],
        ["run", "--sections", "unknown"],
        ["run", "--timeout", "nan"],
        ["run", "--timeout", "inf"],
        ["run", "--timeout", "0"],
        ["run", "--timeout", "-1"],
        ["run", "--session-timeout", "nan"],
        ["run", "--session-timeout", "0"],
    ],
)
def test_invalid_cli_is_rejected_before_side_effects(
    demo: Any, tmp_path: Path, arguments: Any
) -> None:
    """Verify invalid cli is rejected before side effects.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        arguments: Fixture or parametrized arguments input for this regression.
    """
    with pytest.raises(SystemExit) as exc:
        demo.parse_args(arguments)
    assert exc.value.code == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("browser", ["chrome", "chromium", "edge", "firefox", "safari"])
@pytest.mark.asyncio
async def test_all_provisioning_defaults_to_offline_and_correct_signatures(
    demo: Any, browser: Any
) -> None:
    """Verify all provisioning defaults to offline and correct signatures.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        browser: Fixture or parametrized browser input for this regression.
    """
    args = demo.parse_args(
        ["install", "--browser", browser, "--binary", "/fake/browser"]
    )
    manager = SimpleNamespace(install_result=AsyncMock(return_value=object()))
    result = await demo.provision(SimpleNamespace(manager=manager), args)
    assert result is manager.install_result.return_value
    keywords = manager.install_result.call_args.kwargs
    assert keywords["policy"] == "offline"
    assert keywords["validate_compatibility"] is True
    assert keywords["binary"] == "/fake/browser"
    assert ("version" in keywords) == (browser != "safari")
    assert ("channel" in keywords) == (browser in {"chrome", "edge", "safari"})


@pytest.mark.parametrize(
    "browser,extra,expected",
    [
        ("chrome", [], "compatible-build"),
        ("edge", [], "compatible-build"),
        ("firefox", [], "cached-compatible"),
        ("safari", [], "offline"),
        ("chrome", ["--version", "152.0.7977.82"], "exact"),
        ("firefox", ["--version", "0.36.0"], "exact"),
        ("chrome", ["--policy", "cached-compatible"], "cached-compatible"),
    ],
)
@pytest.mark.asyncio
async def test_explicit_download_opt_in_selects_expected_policy(
    demo: Any, browser: Any, extra: Any, expected: Any
) -> None:
    """Verify explicit download opt in selects expected policy.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        browser: Fixture or parametrized browser input for this regression.
        extra: Fixture or parametrized extra input for this regression.
        expected: Fixture or parametrized expected input for this regression.
    """
    args = demo.parse_args(
        ["install", "--browser", browser, "--allow-download", *extra]
    )
    manager = SimpleNamespace(install_result=AsyncMock())
    await demo.provision(SimpleNamespace(manager=manager), args)
    assert manager.install_result.call_args.kwargs["policy"] == expected


@pytest.mark.parametrize("pin,expected", [("--pin", True), ("--unpin", False)])
@pytest.mark.asyncio
async def test_pin_changes_only_the_resolved_driver_in_selected_cache(
    demo: Any, pin: Any, expected: Any
) -> None:
    """Verify pin changes only the resolved driver in selected cache.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        pin: Fixture or parametrized pin input for this regression.
        expected: Fixture or parametrized expected input for this regression.
    """
    args = demo.parse_args(["install", "--version", "152.0.7977.82", pin])
    manager = SimpleNamespace(
        install_result=AsyncMock(
            return_value=SimpleNamespace(driver_version="152.0.7977.82")
        ),
        pin=AsyncMock(),
    )
    await demo.provision(SimpleNamespace(manager=manager), args)
    assert manager.install_result.call_args.kwargs["policy"] == "offline"
    manager.pin.assert_awaited_once_with("152.0.7977.82", pinned=expected)


@pytest.mark.parametrize("browser", ["chrome", "chromium", "edge", "firefox", "safari"])
def test_browser_acquisition_is_offline_even_after_opted_in_provisioning(
    demo: Any, browser: Any
) -> None:
    """Verify browser acquisition is offline even after opted in provisioning.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        browser: Fixture or parametrized browser input for this regression.
    """
    args = demo.parse_args(["run", "--browser", browser, "--allow-download"])
    driver = SimpleNamespace(acquire=Mock())
    assert demo.acquire_offline(driver, args) is driver.acquire.return_value
    kwargs = driver.acquire.call_args.kwargs
    assert kwargs.get("version") == (None if browser == "safari" else "offline")
    assert ("channel" in kwargs) == (browser in {"chrome", "edge", "safari"})


@pytest.mark.parametrize("browser", ["chrome", "chromium", "edge", "firefox", "safari"])
def test_options_and_constructor_work_without_browser_probes(
    demo: Any, tmp_path: Path, browser: Any
) -> None:
    """Verify options and constructor work without browser probes.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        browser: Fixture or parametrized browser input for this regression.
    """
    args = demo.parse_args(["run", "--browser", browser])
    driver = demo.make_driver(args)
    source = tmp_path / "source"
    source.mkdir()
    try:
        details = demo.configure(driver, args, source)
        assert details["defensive_capabilities"] is True
        assert driver.options.timeouts.implicit == 0
        assert driver.options.session_timeout == 30
        assert details["session_timeout_seconds"] == 30
        assert driver.options.proxy is None  # Serialization-only proxy example.
        assert args.cache_dir.exists() == (browser != "safari")
    finally:
        driver.options.close()


def test_run_accepts_an_explicit_session_timeout(demo: Any, tmp_path: Path) -> None:
    """Apply a user-selected session deadline through the real options API.

    Args:
        demo: Imported local demonstration module.
        tmp_path: Empty profile source used without launching a browser.
    """
    args = demo.parse_args(["run", "--browser", "firefox", "--session-timeout", "75"])
    driver = demo.make_driver(args)
    source = tmp_path / "source"
    source.mkdir()
    try:
        details = demo.configure(driver, args, source)
        assert driver.options.session_timeout == 75
        assert details["session_timeout_seconds"] == 75
    finally:
        driver.options.close()


def test_firefox_profile_root_remains_a_path_until_service_start(
    demo: Any, tmp_path: Path
) -> None:
    """Forward the CLI Path without reparsing it in the demonstration layer.

    Args:
        demo: Imported local demonstration module.
        tmp_path: Existing shared profile root and dedicated demo cache parent.
    """
    profile_root = tmp_path / "shared-profiles"
    profile_root.mkdir()
    args = demo.parse_args(
        [
            "run",
            "--browser",
            "firefox",
            "--profile-root",
            str(profile_root),
        ]
    )
    driver = demo.make_driver(args)
    try:
        assert args.profile_root == profile_root
        assert isinstance(driver._service_kwargs["profile_root"], Path)
        assert driver._service_kwargs["profile_root"] is args.profile_root
    finally:
        driver.options.close()


@pytest.mark.parametrize("browser", ["chrome", "edge", "chromium", "firefox"])
def test_profile_demo_uses_empty_source_and_physically_independent_snapshots(
    demo: Any, tmp_path: Path, browser: Any
) -> None:
    """Verify profile demo uses empty source and physically independent snapshots.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        browser: Fixture or parametrized browser input for this regression.
    """
    args = demo.parse_args(["run", "--browser", browser, "--profile-demo"])
    driver = demo.make_driver(args)
    source = tmp_path / "empty-profile"
    source.mkdir()
    snapshots = []
    try:
        demo.configure(driver, args, source)
        snapshots = [driver.options.snapshot(), driver.options.snapshot()]
        paths = [
            Path(options.profile.directory_temp)
            for options in [driver.options, *snapshots]
        ]
        assert len(set(paths)) == 3
        assert all(path.is_dir() for path in paths)
        assert all(source not in path.parents for path in paths)
    finally:
        for options in snapshots:
            options.close()
        driver.options.close()
    assert all(not path.exists() for path in paths)
    assert source.is_dir()  # Original empty source remains untouched.


@pytest.mark.parametrize(
    "target", ["/", "/index.html", "/second.html", "/frame.html", "/?test=true"]
)
def test_loopback_fixture_routes(demo: Any, target: Any) -> None:
    """Verify loopback fixture routes.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        target: Fixture or parametrized target input for this regression.
    """
    status, content = demo.fixture_response(target)
    assert status == 200
    assert content.startswith(b"<!doctype html>")
    assert b"https://" not in content
    assert b"http://" not in content


@pytest.mark.parametrize(
    "target",
    [
        "/../../README.md",
        "/%2e%2e/README.md",
        "/etc/passwd",
        "/upload.txt",
        "/firefox-addon/manifest.json",
        "/missing",
    ],
)
def test_loopback_server_cannot_read_arbitrary_files(demo: Any, target: Any) -> None:
    """Verify loopback server cannot read arbitrary files.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        target: Fixture or parametrized target input for this regression.
    """
    assert demo.fixture_response(target) == (404, b"Not found")


def test_addon_is_local_only_and_not_privileged(demo: Any) -> None:
    """Verify addon is local only and not privileged.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    manifest = json.loads((demo.ASSETS / "firefox-addon" / "manifest.json").read_text())
    assert (
        manifest["browser_specific_settings"]["gecko"]["id"]
        == "local-demo@aselenium.invalid"
    )
    assert "permissions" not in manifest and "background" not in manifest
    assert manifest["content_scripts"][0]["matches"] == ["http://127.0.0.1/*"]


@pytest.mark.parametrize("outcome", ["pass", "skip", "fail", "cancel"])
@pytest.mark.asyncio
async def test_report_distinguishes_success_skip_failure_and_cancellation(
    demo: Any, outcome: Any
) -> None:
    """Verify report distinguishes success skip failure and cancellation.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        outcome: Fixture or parametrized outcome input for this regression.
    """
    report = {"sections": []}

    async def operation() -> Any:
        """Operation.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        if outcome == "skip":
            raise demo.DemoSkipped("unsupported browser")
        if outcome == "fail":
            raise demo.DemoFailure("bad result")
        if outcome == "cancel":
            raise asyncio.CancelledError
        return {"checked": True}

    if outcome in {"fail", "cancel"}:
        with pytest.raises(
            demo.DemoFailure if outcome == "fail" else asyncio.CancelledError
        ):
            await demo.record(report, "example", operation())
    else:
        await demo.record(report, "example", operation())
    assert (
        report["sections"][0]["status"]
        == {
            "pass": "passed",
            "skip": "skipped",
            "fail": "failed",
            "cancel": "cancelled",
        }[outcome]
    )


@pytest.mark.asyncio
async def test_drain_awaits_owned_cleanup_even_under_repeated_cancellation(
    demo: Any,
) -> None:
    """Verify drain awaits owned cleanup even under repeated cancellation.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    cleaned = asyncio.Event()

    async def worker() -> None:
        """Run one owned worker operation for the enclosing workflow."""
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await release.wait()
            cleaned.set()

    child = asyncio.create_task(worker())
    await started.wait()
    drain = asyncio.create_task(demo.drain_tasks([child]))
    await asyncio.sleep(0)
    drain.cancel()
    await asyncio.sleep(0)
    drain.cancel()
    release.set()
    await drain
    assert child.done() and cleaned.is_set()


@pytest.mark.parametrize("failed_index", [0, 1])
@pytest.mark.asyncio
async def test_concurrent_startup_failure_closes_every_context_and_restores_options(
    demo: Any, monkeypatch: pytest.MonkeyPatch, failed_index: Any
) -> None:
    """Verify concurrent startup failure closes every context and restores options.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        failed_index: Fixture or parametrized failed index input for this regression.
    """
    args = demo.parse_args(["run"])
    driver = SimpleNamespace(options=SimpleNamespace(session_timeout=30))
    contexts = []

    class Context:
        """Represent Context using the inherited implementation."""

        def __init__(self, index: Any, timeout: Any) -> None:
            """Initialize the instance with the supplied configuration.

            Args:
                index: Fixture or parametrized index input for this regression.
                timeout: Fixture or parametrized timeout input for this regression.
            """
            self.index = index
            self.quit = AsyncMock()
            self.session = SimpleNamespace(
                options=SimpleNamespace(session_timeout=timeout, profile=None),
                load=AsyncMock(),
                get_cookie=AsyncMock(return_value=None),
                add_cookie=AsyncMock(),
            )

        async def __aenter__(self) -> Context:
            """Start the owned asynchronous context and return its managed value.

            Returns:
                The stored session.
            """
            if self.index == failed_index:
                raise RuntimeError("startup failed")
            return self.session

        async def __aexit__(self, *exc: Any) -> None:
            """Await owned cleanup when leaving the asynchronous context.

            Args:
                *exc: Fixture or parametrized exc input for this regression.
            """
            await self.quit()

    def acquire(*_: Any) -> Any:
        """Acquire.

        Args:
            *_: Fixture or parametrized   input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        context = Context(len(contexts), driver.options.session_timeout)
        contexts.append(context)
        return context

    monkeypatch.setattr(demo, "acquire_offline", acquire)
    before = set(asyncio.all_tasks())
    with pytest.raises(RuntimeError, match="startup failed"):
        await asyncio.wait_for(
            demo.concurrency(driver, args, "http://127.0.0.1:1234"), 1
        )
    assert len(contexts) == 2
    assert all(context.quit.await_count >= 1 for context in contexts)
    assert driver.options.session_timeout == 30
    assert not (set(asyncio.all_tasks()) - before)


@pytest.mark.asyncio
async def test_cancellation_demo_preserves_startup_error_and_drains_readiness_waiter(
    demo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify cancellation demo preserves startup error and drains readiness waiter.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    args = demo.parse_args(["run"])

    class Context:
        """Represent Context using the inherited implementation."""

        quit = AsyncMock()

        async def __aenter__(self) -> None:
            """Start the owned asynchronous context and return its managed value."""
            raise RuntimeError("startup failed")

        async def __aexit__(self, *exc: Any) -> None:
            """Await owned cleanup when leaving the asynchronous context.

            Args:
                *exc: Fixture or parametrized exc input for this regression.
            """
            await self.quit()

    context = Context()
    monkeypatch.setattr(demo, "acquire_offline", lambda *_: context)
    before = set(asyncio.all_tasks())
    with pytest.raises(RuntimeError, match="startup failed"):
        await asyncio.wait_for(
            demo.cancellation(object(), args, "http://127.0.0.1:1234"), 1
        )
    context.quit.assert_awaited_once()
    assert not (set(asyncio.all_tasks()) - before)


@pytest.mark.asyncio
async def test_cookie_chapter_uses_real_cookie_mapping_api(
    demo: Any, tmp_path: Path
) -> None:
    """Verify cookie chapter uses real cookie mapping api.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    session = SimpleNamespace(
        add_cookie=AsyncMock(),
        delete_cookie=AsyncMock(),
        get_cookie=AsyncMock(
            side_effect=[Cookie(name="aselenium-demo", value="local-only"), None]
        ),
    )
    details = await demo.cookies(
        demo.Tour(session, "http://127.0.0.1:1234", tmp_path, "chrome", False)
    )
    assert details["cookie_deleted"] is True
    session.delete_cookie.assert_awaited_once_with("aselenium-demo")


@dataclass
class FakeResult:
    """Represent FakeResult using the inherited implementation.

    Attributes:
        driver_version: Resolved browser-driver version.
    """

    driver_version: str = "152.0.7977.82"


@pytest.mark.asyncio
async def test_selected_sections_run_in_order_after_management_and_clean_up(
    demo: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify selected sections run in order after management and clean up.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    args = demo.parse_args(["run", "--sections", "scripts", "navigation"])
    session = SimpleNamespace(
        browser_version="152.0.7977.76",
        driver_version="152.0.7977.82",
        load=AsyncMock(),
    )

    class Context:
        """Represent Context using the inherited implementation."""

        quit = AsyncMock()

        async def __aenter__(self) -> Context:
            """Start the owned asynchronous context and return its managed value.

            Returns:
                The Context value produced by this operation.
            """
            return session

        async def __aexit__(self, *exc: Any) -> None:
            """Await owned cleanup when leaving the asynchronous context.

            Args:
                *exc: Fixture or parametrized exc input for this regression.
            """
            await self.quit()

    context = Context()
    driver = SimpleNamespace(options=SimpleNamespace(close=Mock()))
    monkeypatch.setattr(demo, "make_driver", lambda _: driver)
    monkeypatch.setattr(demo, "provision", AsyncMock(return_value=FakeResult()))
    monkeypatch.setattr(demo, "configure", Mock(return_value={}))
    monkeypatch.setattr(demo, "acquire_offline", Mock(return_value=context))
    monkeypatch.setattr(demo, "navigation", AsyncMock(return_value={}))
    monkeypatch.setattr(demo, "scripts", AsyncMock(return_value={}))
    report = {"sections": []}
    await demo.run_tour(args, "http://127.0.0.1:1234", tmp_path, tmp_path, report)
    assert [entry["section"] for entry in report["sections"]] == [
        "driver-management",
        "options",
        "navigation",
        "scripts",
    ]
    assert all(entry["status"] == "passed" for entry in report["sections"])
    assert session.load.await_count == 2
    assert context.quit.await_count == 2
    driver.options.close.assert_called_once()


def test_failure_still_writes_unique_report_and_returns_nonzero(
    demo: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify failure still writes unique report and returns nonzero.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
        capsys: Pytest fixture capturing text written to standard output and error.
    """

    def fail_server() -> None:
        """Fail server."""
        raise OSError("loopback fixture unavailable")

    monkeypatch.setattr(demo, "fixture_server", fail_server)
    for _ in range(2):
        assert demo.main(["run", "--output-dir", str(tmp_path / "reports")]) == 1
    reports = list((tmp_path / "reports").glob("*/report.json"))
    assert len(reports) == 2
    for path in reports:
        report = json.loads(path.read_text())
        assert report["status"] == "failed" and report["error"] == "OSError"
        assert all(entry["status"] == "not-run" for entry in report["sections"])
        assert report["counts"]["not-run"] == len(demo.SECTIONS) + 2
    assert "Report:" in capsys.readouterr().out
