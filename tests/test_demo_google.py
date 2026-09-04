"""Real-website demo guardrails and workflow contracts, with zero real network use."""

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
from urllib.parse import urlencode

import pytest

from aselenium import KeyboardKeys


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Demo.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    path = Path(__file__).resolve().parents[1] / "src" / "demo_google.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("google_demo_under_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize("argv", [[], ["--help"], ["run", "--help"]])
def test_google_help_never_creates_cache_or_starts_browser(
    demo: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: Any,
) -> None:
    """Verify google help never creates cache or starts browser.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
        capsys: Pytest fixture capturing text written to standard output and error.
        argv: Fixture or parametrized argv input for this regression.
    """
    monkeypatch.setattr(
        demo, "make_driver", Mock(side_effect=AssertionError("unexpected browser"))
    )
    if "--help" in argv:
        with pytest.raises(SystemExit) as exc:
            demo.main(argv)
        assert exc.value.code == 0
    else:
        assert demo.main(argv) == 0
    assert "run" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_google_defaults_are_headed_homepage_only_and_offline_provisioning(
    demo: Any,
) -> None:
    """Verify google defaults are headed homepage only and offline provisioning.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    args = demo.parse_args(["run"])
    assert args.browser == "chrome"
    assert args.query is None
    assert not args.headless and not args.allow_download
    assert args.hold_seconds == 5
    assert args.cache_dir == demo.ROOT / ".demo-cache"


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--hold-seconds", "-1"],
        ["run", "--hold-seconds", "61"],
        ["run", "--hold-seconds", "nan"],
        ["run", "--wait-timeout", "0"],
        ["run", "--wait-timeout", "inf"],
        ["run", "--timeout", "nan"],
        ["run", "--query", "   "],
        ["run", "--query", "x" * 513],
        ["run", "--browser", "safari", "--headless"],
        ["run", "--browser", "safari", "--channel", "beta"],
        ["run", "--browser", "firefox", "--channel", "dev"],
        ["run", "--browser", "chromium", "--channel", "beta"],
        ["run", "--channel", "cft"],
    ],
)
def test_invalid_arguments_fail_before_any_browser_operation(
    demo: Any, argv: Any, tmp_path: Path
) -> None:
    """Verify invalid arguments fail before any browser operation.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        argv: Fixture or parametrized argv input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    with pytest.raises(SystemExit) as exc:
        demo.parse_args(argv)
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "browser,headless",
    [
        (browser, headless)
        for browser in ("chrome", "edge", "chromium", "firefox", "safari")
        for headless in (False, True)
        if not (browser == "safari" and headless)
    ],
)
def test_display_options_match_the_selected_browser(
    demo: Any, browser: Any, headless: Any, tmp_path: Path
) -> None:
    """Verify display options match the selected browser.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        browser: Fixture or parametrized browser input for this regression.
        headless: Fixture or parametrized headless input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    args = demo.parse_args(
        ["run", "--browser", browser, *(["--headless"] if headless else [])]
    )
    driver = demo.make_driver(args)
    try:
        demo.configure(driver, args)
        arguments = driver.options.arguments
        if browser in demo.CHROMIUM:
            assert ("--headless=new" in arguments) == headless
        elif browser == "firefox":
            assert ("-headless" in arguments) == headless
        assert driver.options.accept_insecure_certs is False
        assert driver.options.timeouts.implicit == 0
        assert not any(
            "user-data-dir" in argument or "user-agent" in argument
            for argument in arguments
        )
    finally:
        driver.options.close()


class FakeField:
    """Represent FakeField using the inherited implementation."""

    def __init__(
        self, *, enabled: bool = True, unobscured: bool = True, text: str = "Result"
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            enabled: Fixture or parametrized enabled input for this regression.
            unobscured: Fixture or parametrized unobscured input for this regression.
            text: Fixture or parametrized text input for this regression.
        """
        self.is_enabled = enabled
        self.is_unobscured = unobscured
        self.content = text
        self.clear = AsyncMock()
        self.send = AsyncMock()

    @property
    async def enabled(self) -> Any:
        """Enabled.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return self.is_enabled

    @property
    async def unobscured(self) -> Any:
        """Unobscured.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return self.is_unobscured

    @property
    async def text(self) -> Any:
        """Text.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return self.content


class FakeSession:
    """Represent FakeSession using the inherited implementation."""

    def __init__(
        self, url: str = "https://www.google.com/", markers: Any = None
    ) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            url: Fixture or parametrized url input for this regression.
            markers: Fixture or parametrized markers input for this regression.
        """
        self.current_url = url
        self.load = AsyncMock()
        self.execute_script = AsyncMock(
            return_value=markers or {"challenge": False, "consent": False}
        )
        self.find_elements = AsyncMock(return_value=[])
        self.saved_paths = []
        self.browser_version = "152.0.7977.76"
        self.driver_version = "152.0.7977.82"

    @property
    async def url(self) -> Any:
        """Url.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return self.current_url

    @property
    async def title(self) -> Any:
        """Title.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        return "Google"

    async def wait_for(self, predicate: Any, timeout: Any) -> Any:
        """Wait for.

        Args:
            predicate: Fixture or parametrized predicate input for this regression.
            timeout: Fixture or parametrized timeout input for this regression.

        Returns:
            The first truthy predicate result, or a falsey result/None when the deadline expires.
        """
        return await predicate()

    async def save_screenshot(self, path: Any) -> Any:
        """Save screenshot.

        Args:
            path: Fixture or parametrized path input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        self.saved_paths.append(path)
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        return True


@pytest.mark.parametrize(
    "url,reason",
    [
        ("https://www.google.com/sorry/index", "challenge"),
        ("https://www.google.com/sorry", "challenge"),
        ("https://google.com.evil.invalid/", "unexpected-redirect"),
        ("https://accounts.google.com/", "unexpected-redirect"),
        ("http://www.google.com/", "unexpected-redirect"),
    ],
)
@pytest.mark.asyncio
async def test_challenge_and_unexpected_origins_stop_before_interaction(
    demo: Any, url: Any, reason: Any
) -> None:
    """Verify challenge and unexpected origins stop before interaction.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        url: Fixture or parametrized url input for this regression.
        reason: Fixture or parametrized reason input for this regression.
    """
    session = FakeSession(url)
    with pytest.raises(demo.GoogleNeedsAttention) as exc:
        await demo.wait_for_search_box(session, 1)
    assert exc.value.reason == reason
    session.find_elements.assert_not_awaited()


@pytest.mark.asyncio
async def test_dom_challenge_stops_without_solving_or_retrying(demo: Any) -> None:
    """Verify dom challenge stops without solving or retrying.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    session = FakeSession(markers={"challenge": True, "consent": False})
    with pytest.raises(demo.GoogleNeedsAttention, match="bypass"):
        await demo.page_state(session)
    session.execute_script.assert_awaited_once()
    session.find_elements.assert_not_awaited()


@pytest.mark.parametrize("consent_url", [True, False])
@pytest.mark.asyncio
async def test_consent_or_dialog_needs_manual_attention(
    demo: Any, consent_url: Any
) -> None:
    """Verify consent or dialog needs manual attention.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        consent_url: Fixture or parametrized consent url input for this regression.
    """
    session = FakeSession(
        "https://consent.google.com/" if consent_url else "https://www.google.com/",
        {"challenge": False, "consent": True},
    )
    with pytest.raises(demo.GoogleNeedsAttention) as exc:
        await demo.wait_for_search_box(session, 1)
    assert exc.value.reason == "consent-or-dialog"
    session.find_elements.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_dismissed_consent_can_continue_within_the_wait(demo: Any) -> None:
    """Verify user dismissed consent can continue within the wait.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    session = FakeSession("https://consent.google.com/")
    field = FakeField()
    session.find_elements.return_value = [field]

    async def two_observations(predicate: Any, timeout: Any) -> Any:
        """Two observations.

        Args:
            predicate: Fixture or parametrized predicate input for this regression.
            timeout: Fixture or parametrized timeout input for this regression.

        Returns:
            Fixture value or simulated response used by the regression.
        """
        assert await predicate() is None
        session.current_url = (
            "https://www.google.com/"  # User, not automation, changed the page.
        )
        return await predicate()

    session.wait_for = two_observations
    assert await demo.wait_for_search_box(session, 1) is field
    field.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_box_skips_hidden_or_disabled_matches(demo: Any) -> None:
    """Verify search box skips hidden or disabled matches.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    session = FakeSession()
    usable = FakeField()
    session.find_elements.return_value = [
        FakeField(enabled=False),
        FakeField(unobscured=False),
        usable,
    ]
    assert await demo.wait_for_search_box(session, 1) is usable


@pytest.mark.asyncio
async def test_missing_search_box_is_not_reported_as_success(demo: Any) -> None:
    """Verify missing search box is not reported as success.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    with pytest.raises(demo.GoogleNeedsAttention) as exc:
        await demo.wait_for_search_box(FakeSession(), 1)
    assert exc.value.reason == "search-box-unavailable"


@pytest.mark.parametrize(
    "path,query,headings",
    [
        ("/", "Aselenium Python", [FakeField()]),
        ("/search", "another query", [FakeField()]),
        ("/search", "Aselenium Python", []),
        ("/search", "Aselenium Python", [FakeField(text=" ")]),
    ],
)
@pytest.mark.asyncio
async def test_results_require_matching_navigation_and_visible_headings(
    demo: Any, path: Any, query: Any, headings: Any
) -> None:
    """Verify results require matching navigation and visible headings.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        path: Fixture or parametrized path input for this regression.
        query: Fixture or parametrized query input for this regression.
        headings: Fixture or parametrized headings input for this regression.
    """
    session = FakeSession(
        "https://www.google.com" + path + "?" + urlencode({"q": query})
    )
    session.find_elements.return_value = headings
    with pytest.raises(demo.GoogleNeedsAttention) as exc:
        await demo.wait_for_results(session, "Aselenium Python", 1)
    assert exc.value.reason == "results-unavailable"


@pytest.mark.asyncio
async def test_result_sampling_is_bounded_and_does_not_follow_links(demo: Any) -> None:
    """Verify result sampling is bounded and does not follow links.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    session = FakeSession(
        "https://www.google.com/search?" + urlencode({"q": "Aselenium Python"})
    )
    session.find_elements.return_value = [
        FakeField(text=f"Result {index}") for index in range(20)
    ]
    result = await demo.wait_for_results(session, "Aselenium Python", 1)
    assert result["heading_samples"] == [f"Result {index}" for index in range(5)]
    session.load.assert_not_awaited()


@pytest.mark.asyncio
async def test_homepage_demo_does_not_submit_a_search(
    demo: Any, tmp_path: Path
) -> None:
    """Verify homepage demo does not submit a search.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    args = demo.parse_args(["run", "--hold-seconds", "0"])
    session = FakeSession()
    field = FakeField()
    session.find_elements.return_value = [field]
    report = {"artifacts": []}
    await demo.browse_google(session, args, tmp_path, report)
    session.load.assert_awaited_once_with(demo.GOOGLE_URL)
    field.send.assert_not_awaited()
    assert "search" not in report
    assert report["homepage"]["search_box_ready"] is True
    assert report["artifacts"] == ["google-home.png"]


@pytest.mark.asyncio
async def test_optional_query_submits_once_and_captures_home_and_results(
    demo: Any, tmp_path: Path
) -> None:
    """Verify optional query submits once and captures home and results.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    args = demo.parse_args(
        ["run", "--query", "  Aselenium Python  ", "--hold-seconds", "0"]
    )
    session = FakeSession()
    field = FakeField()

    async def send(*keys: Any) -> None:
        """Send.

        Args:
            *keys: Fixture or parametrized keys input for this regression.
        """
        assert keys == ("Aselenium Python", KeyboardKeys.ENTER)
        session.current_url = "https://www.google.com/search?" + urlencode(
            {"q": args.query}
        )

    field.send.side_effect = send
    session.find_elements.side_effect = [[field], [FakeField(text="Aselenium project")]]
    report = {"artifacts": []}
    await demo.browse_google(session, args, tmp_path, report)
    field.clear.assert_awaited_once()
    field.send.assert_awaited_once_with(args.query, KeyboardKeys.ENTER)
    assert report["artifacts"] == ["google-home.png", "google-results.png"]
    assert report["search"]["heading_samples"] == ["Aselenium project"]


@dataclass(frozen=True)
class FakeInstallation:
    """Represent FakeInstallation using the inherited implementation.

    Attributes:
        driver_version: Resolved browser-driver version.
    """

    driver_version: str = "152.0.7977.82"


class FakeContext:
    """Represent FakeContext using the inherited implementation."""

    def __init__(self, session: Any) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            session: Fixture or parametrized session input for this regression.
        """
        self.session = session
        self.quit = AsyncMock()

    async def __aenter__(self) -> FakeContext:
        """Start the owned asynchronous context and return its managed value.

        Returns:
            The stored session.
        """
        return self.session

    async def __aexit__(self, *exc: Any) -> None:
        """Await owned cleanup when leaving the asynchronous context.

        Args:
            *exc: Fixture or parametrized exc input for this regression.
        """
        await self.quit()


@pytest.mark.parametrize("outcome", ["success", "attention", "failure", "cancel"])
@pytest.mark.asyncio
async def test_run_owns_cleanup_and_never_disguises_original_error(
    demo: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outcome: Any
) -> None:
    """Verify run owns cleanup and never disguises original error.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
        outcome: Fixture or parametrized outcome input for this regression.
    """
    args = demo.parse_args(["run", "--hold-seconds", "0", "--allow-download"])
    session = FakeSession()
    context = FakeContext(session)
    manager = SimpleNamespace(install_result=AsyncMock(return_value=FakeInstallation()))
    driver = SimpleNamespace(
        manager=manager,
        options=SimpleNamespace(close=Mock()),
        acquire=Mock(return_value=context),
    )
    monkeypatch.setattr(demo, "make_driver", lambda _: driver)
    monkeypatch.setattr(demo, "configure", Mock())
    errors = {
        "attention": demo.GoogleNeedsAttention("challenge", "stop here"),
        "failure": RuntimeError("website unavailable"),
        "cancel": asyncio.CancelledError(),
    }
    error = errors.get(outcome)
    monkeypatch.setattr(demo, "browse_google", AsyncMock(side_effect=error))
    report = {"artifacts": []}
    if error is None:
        await demo.run_demo(args, tmp_path, report)
    else:
        with pytest.raises(type(error)) as raised:
            await demo.run_demo(args, tmp_path, report)
        assert raised.value is error
    assert manager.install_result.call_args.kwargs["policy"] == "compatible-build"
    driver.acquire.assert_called_once_with(
        binary=None, channel="stable", version="offline"
    )
    assert context.quit.await_count == 2
    driver.options.close.assert_called_once()
    assert ("google-attention.png" in report["artifacts"]) == (
        outcome in {"attention", "failure"}
    )


@pytest.mark.parametrize(
    "outcome,code,status",
    [
        ("ok", 0, "passed"),
        ("attention", 2, "needs-attention"),
        ("failed", 1, "failed"),
        ("interrupt", 130, "cancelled"),
    ],
)
def test_cli_always_writes_a_report_with_honest_exit_status(
    demo: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcome: Any,
    code: Any,
    status: Any,
) -> None:
    """Verify cli always writes a report with honest exit status.

    Args:
        demo: Fixture or parametrized demo input for this regression.
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
        outcome: Fixture or parametrized outcome input for this regression.
        code: Fixture or parametrized code input for this regression.
        status: Fixture or parametrized status input for this regression.
    """

    async def fake_run(args: Any, output: Any, report: Any) -> None:
        """Fake run.

        Args:
            args: Fixture or parametrized args input for this regression.
            output: Fixture or parametrized output input for this regression.
            report: Fixture or parametrized report input for this regression.
        """
        if outcome == "attention":
            raise demo.GoogleNeedsAttention("challenge", "Google requires attention")
        if outcome == "failed":
            raise RuntimeError("network failed")

    if outcome == "interrupt":
        # Raising KeyboardInterrupt inside asyncio.run has special loop behavior;
        # patch the synchronous runner and explicitly close its coroutine instead.
        def interrupt(coroutine: Any) -> None:
            """Interrupt.

            Args:
                coroutine: Fixture or parametrized coroutine input for this regression.
            """
            coroutine.close()
            raise KeyboardInterrupt

        monkeypatch.setattr(demo.asyncio, "run", interrupt)
        monkeypatch.setattr(
            demo.asyncio, "wait_for", lambda operation, timeout: operation
        )
    monkeypatch.setattr(demo, "run_demo", fake_run)
    assert demo.main(["run", "--output-dir", str(tmp_path / "reports")]) == code
    paths = list((tmp_path / "reports").glob("google-chrome-*/report.json"))
    assert len(paths) == 1
    report = json.loads(paths[0].read_text())
    assert report["status"] == status
    assert report["demo"] == "google-real-world"
    assert report["query"] is None


def test_google_import_does_not_import_local_tour_or_its_http_server(demo: Any) -> None:
    """Verify google import does not import local tour or its http server.

    Args:
        demo: Fixture or parametrized demo input for this regression.
    """
    assert "fixture_server" not in demo.__dict__
    assert "demo_local" not in demo.__dict__
    assert demo.make_driver.__module__ == "_demo_support"
