"""Real-world Google website demo (a visible browser by default).

    .venv/bin/python src/demo_google.py run --allow-download
    .venv/bin/python src/demo_google.py run --query "Aselenium Python"
    .venv/bin/python src/demo_google.py run --headless --hold-seconds 0

Unlike demo_local.py, this demo requires Internet access to Google. No arguments
prints help without launching anything. Driver downloads require --allow-download;
that flag does not control website access. See docs/demo-google.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlsplit

from _demo_support import BROWSERS, CHROMIUM, acquire_offline, make_driver, provision
from aselenium import Element, KeyboardKeys, Session, WebDriver

ROOT = Path(__file__).resolve().parents[1]
GOOGLE_URL = "https://www.google.com/"
SEARCH_BOX = "textarea[name='q'], input[name='q']"
RESULT_HEADING = "a h3"
GOOGLE_HOSTS = {"google.com", "www.google.com"}


class GoogleNeedsAttention(RuntimeError):
    """The remote page needs attention, not an automated bypass or blind retry."""

    def __init__(self, reason: str, message: str) -> None:
        """Initialize the instance with the supplied configuration.

        Args:
            reason: Stable reason code recorded in the attention report.
            message: Diagnostic message explaining the failed condition.
        """
        super().__init__(message)
        self.reason = reason


def positive_seconds(value: str) -> float:
    """Parse a finite positive command-line duration in seconds.

    Args:
        value: A finite positive command-line duration in seconds supplied for validation.

    Returns:
        A finite positive command-line duration in seconds.
    """
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def hold_seconds(value: str) -> float:
    """Parse a browser hold duration between zero and sixty seconds.

    Args:
        value: A browser hold duration between zero and sixty seconds supplied for validation.

    Returns:
        A browser hold duration between zero and sixty seconds.
    """
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 60:
        raise argparse.ArgumentTypeError("must be between 0 and 60 seconds")
    return number


def query_text(value: str) -> str:
    """Validate and trim a search query containing one to 512 characters.

    Args:
        value: And trim a search query containing one to 512 characters supplied for validation.

    Returns:
        And trim a search query containing one to 512 characters.
    """
    value = value.strip()
    if not value or len(value) > 512:
        raise argparse.ArgumentTypeError("query must contain 1 to 512 characters")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and validate the command line without launching a browser.

    Args:
        argv: Command-line arguments; None reads the current process arguments.

    Returns:
        And validate the command line without launching a browser.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command")
    run = commands.add_parser(
        "run", help="open Google and optionally submit one search"
    )
    run.add_argument("--browser", choices=BROWSERS, default="chrome")
    run.add_argument(
        "--binary", help="browser executable; omit for automatic discovery"
    )
    run.add_argument("--channel", choices=("stable", "beta", "dev"), default="stable")
    run.add_argument(
        "--query",
        type=query_text,
        help="submit this text to Google once; omit to only open the homepage",
    )
    run.add_argument(
        "--headless",
        action="store_true",
        help="hide the browser window (not supported by Safari)",
    )
    run.add_argument(
        "--hold-seconds",
        type=hold_seconds,
        default=5,
        help="keep the final page visible before cleanup, 0 to 60 seconds; default 5",
    )
    run.add_argument(
        "--wait-timeout",
        type=positive_seconds,
        default=20,
        help="seconds to wait for page elements; choose consent manually if displayed",
    )
    run.add_argument(
        "--timeout",
        type=positive_seconds,
        default=180,
        help="overall work budget in seconds; owned cleanup may take longer",
    )
    run.add_argument(
        "--allow-download",
        action="store_true",
        help="allow driver vendor metadata/downloads; Google access is always online",
    )
    run.add_argument(
        "--cache-dir",
        type=Path,
        default=ROOT / ".demo-cache",
        help="demo cache parent, shared with demo_local.py",
    )
    run.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".demo-output",
        help="parent for a unique google-<browser>-... report/screenshot directory",
    )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return args
    if args.browser in {"firefox", "chromium"} and args.channel != "stable":
        parser.error("Firefox/Chromium use --binary, not release-channel selection")
    if args.browser == "safari" and (args.headless or args.channel == "beta"):
        parser.error("Safari is always headed and supports only stable/dev channels")
    return args


def configure(driver: WebDriver, args: argparse.Namespace) -> None:
    """Configure.

    Args:
        driver: Driver object or downloaded driver artifact required by this operation.
        args: Validated command-line options for the selected browser workflow.
    """
    options = driver.options
    options.set_timeouts(implicit=0, pageLoad=30, script=5)
    options.session_timeout = 40
    options.accept_insecure_certs = False
    options.page_load_strategy = "normal"
    if args.browser in CHROMIUM:
        options.add_arguments(
            "--window-size=1200,900",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-sync",
        )
        if args.headless:
            options.add_arguments("--headless=new")
    elif args.browser == "firefox" and args.headless:
        options.add_arguments("-headless")
    # No personal profile, proxy, account, user-agent spoofing, or stealth flags.


async def page_state(session: Session) -> tuple[str, str]:
    """Check the current page before interacting; never automate challenge solving.

    Args:
        session: Active session that owns the browser or HTTP operation.

    Returns:
        Check the current page before interacting; never automate challenge solving.
    """
    url = await session.url
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host == "consent.google.com":
        return url, "consent"
    if parsed.scheme != "https" or host not in GOOGLE_HOSTS:
        raise GoogleNeedsAttention(
            "unexpected-redirect",
            "Google redirected to a different origin; inspect the saved page before proceeding.",
        )
    if parsed.path.rstrip("/") == "/sorry" or parsed.path.startswith("/sorry/"):
        raise GoogleNeedsAttention(
            "challenge",
            "Google displayed a traffic/CAPTCHA challenge. The demo will not solve or bypass it.",
        )
    markers = await session.execute_script("""
        const shown = selector => Array.from(document.querySelectorAll(selector))
            .some(node => node.getClientRects().length > 0);
        return {
            challenge: shown('#captcha-form, form[action*="/sorry/"], iframe[title*="recaptcha challenge"]'),
            consent: shown('form[action*="consent.google"], [role="dialog"]')
        };
    """)
    if not isinstance(markers, dict):
        raise RuntimeError("Unexpected response while inspecting Google's page")
    if markers.get("challenge"):
        raise GoogleNeedsAttention(
            "challenge",
            "Google displayed a CAPTCHA/challenge. No automated bypass will be attempted.",
        )
    return url, "dialog" if markers.get("consent") else "page"


async def wait_for_search_box(session: Session, timeout: float) -> Element:
    """Wait for an enabled, unobscured Google search field without bypassing challenges.

    Args:
        session: Active session that owns the browser or HTTP operation.
        timeout: Total time budget in seconds; None follows the documented no-wait/default behavior.

    Returns:
        The Element value produced by this operation.
    """
    print(
        f"Waiting up to {timeout:g}s for Google's search box. If consent is shown, choose manually in the visible browser.",
        flush=True,
    )
    last_state = "page"

    async def ready() -> Element | None:
        """Return the ready result for the enclosing poll, or None.

        Returns:
            The ready result for the enclosing poll, or none.
        """
        nonlocal last_state
        _, last_state = await page_state(session)
        if last_state != "page":
            return None
        # Both desktop textarea and alternate input layouts are supported. Do not
        # assume the first matching node is visible or interactable.
        for field in await session.find_elements(SEARCH_BOX):
            if await field.enabled and await field.unobscured:
                return field
        return None

    field = await session.wait_for(ready, timeout=timeout)
    if field is None:
        reason = (
            "consent-or-dialog" if last_state != "page" else "search-box-unavailable"
        )
        raise GoogleNeedsAttention(
            reason,
            "Google's search box was not usable before the deadline. Inspect the screenshot for consent, a changed page layout, or a site restriction.",
        )
    return field


async def wait_for_results(
    session: Session, query: str, timeout: float
) -> dict[str, Any]:
    """Require navigation plus visible result headings, not a guessed page title.

    Args:
        session: Active session that owns the browser or HTTP operation.
        query: Search text submitted once to the real Google website.
        timeout: Total time budget in seconds; None follows the documented no-wait/default behavior.

    Returns:
        A mapping containing the wait for results data.
    """

    async def ready() -> dict[str, Any] | None:
        """Return the ready result for the enclosing poll, or None.

        Returns:
            The ready result for the enclosing poll, or none.
        """
        url, state = await page_state(session)
        if state != "page":
            return None
        parsed = urlsplit(url)
        if parsed.path.rstrip("/") != "/search" or parse_qs(parsed.query).get("q") != [
            query
        ]:
            return None
        headings = []
        for heading in (await session.find_elements(RESULT_HEADING))[:10]:
            value = await heading.text
            if value and value.strip():
                headings.append(value.strip())
            if len(headings) == 5:
                break
        return {"url": url, "heading_samples": headings} if headings else None

    result = await session.wait_for(ready, timeout=timeout)
    if not result:
        raise GoogleNeedsAttention(
            "results-unavailable",
            "A normal search-results page with visible headings did not appear. Consent, a restriction, zero results, or a Google layout change may be responsible; no search will be retried automatically.",
        )
    return result


async def save_capture(session: Session, path: Path, report: dict[str, Any]) -> None:
    """Save a screenshot, validate its PNG header, and add it to the run report.

    Args:
        session: Active session that owns the browser or HTTP operation.
        path: Filesystem path to inspect or operate on.
        report: Mutable run report updated with outcomes and diagnostic artifacts.
    """
    if not await session.save_screenshot(path):
        raise RuntimeError("Screenshot was not saved: " + path.name)
    header = await asyncio.to_thread(lambda: path.read_bytes()[:8])
    if header != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("Screenshot is not a PNG: " + path.name)
    report["artifacts"].append(path.name)


async def browse_google(
    session: Session, args: argparse.Namespace, output: Path, report: dict[str, Any]
) -> None:
    """The actual website example, separated from CLI/provisioning/report plumbing.

    Args:
        session: Active session that owns the browser or HTTP operation.
        args: Validated command-line options for the selected browser workflow.
        output: Directory for this run's report and captures.
        report: Mutable run report updated with outcomes and diagnostic artifacts.
    """
    print("Opening " + GOOGLE_URL, flush=True)
    await session.load(GOOGLE_URL)
    field = await wait_for_search_box(session, args.wait_timeout)
    report["homepage"] = {
        "url": await session.url,
        "title": await session.title,
        "search_box_ready": True,
    }
    await save_capture(session, output / "google-home.png", report)

    if args.query is not None:
        print("Submitting one Google search...", flush=True)
        await field.clear()
        await field.send(args.query, KeyboardKeys.ENTER)
        report["search"] = await wait_for_results(
            session, args.query, args.wait_timeout
        )
        report["search"]["title"] = await session.title
        await save_capture(session, output / "google-results.png", report)
    # No result links, ads, account controls, or consent buttons are clicked.


async def run_demo(
    args: argparse.Namespace, output: Path, report: dict[str, Any]
) -> None:
    """Provision a browser, visit Google, and always finish owned resource cleanup.

    Args:
        args: Validated command-line options for the selected browser workflow.
        output: Directory for this run's report and captures.
        report: Mutable run report updated with outcomes and diagnostic artifacts.
    """
    driver = make_driver(args)
    context = None
    try:
        print("Resolving a compatible driver...", flush=True)
        report["installation"] = asdict(await provision(driver, args))
        configure(driver, args)
        context = acquire_offline(driver, args)
        async with context as session:
            report["session"] = {
                "browser_version": str(session.browser_version),
                "driver_version": str(session.driver_version),
                "driver_resolution": "offline",
                "profile": "fresh",
            }
            try:
                await browse_google(session, args, output, report)
            except Exception:
                # Preserve the original failure even if diagnostic capture fails.
                try:
                    await save_capture(session, output / "google-attention.png", report)
                except Exception as capture_error:
                    report["capture_error"] = type(capture_error).__name__
                if args.hold_seconds:
                    print(
                        f"Keeping the page open for {args.hold_seconds:g}s before cleanup.",
                        flush=True,
                    )
                    await asyncio.sleep(args.hold_seconds)
                raise
            if args.hold_seconds:
                print(
                    f"Keeping the final page open for {args.hold_seconds:g}s.",
                    flush=True,
                )
                await asyncio.sleep(args.hold_seconds)
    finally:
        try:
            if context is not None:
                await (
                    context.quit()
                )  # Idempotent; also surfaces incomplete earlier cleanup.
        finally:
            await asyncio.to_thread(driver.options.close)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and run the requested program workflow.

    Args:
        argv: Command-line arguments; None reads the current process arguments.

    Returns:
        Process exit code; zero indicates the requested workflow completed successfully.
    """
    args = parse_args(argv)
    if args.command is None:
        return 0
    parent = args.output_dir.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="google-" + args.browser + "-", dir=parent))
    report = {
        "demo": "google-real-world",
        "browser": args.browser,
        "headless": args.headless,
        "query": args.query,
        "allow_driver_download": args.allow_download,
        "target": GOOGLE_URL,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "status": "running",
        "output": str(output),
        "artifacts": [],
    }
    started = perf_counter()
    code = 0
    try:
        asyncio.run(
            asyncio.wait_for(run_demo(args, output, report), timeout=args.timeout)
        )
        report["status"] = "passed"
    except GoogleNeedsAttention as exc:
        report.update(status="needs-attention", reason=exc.reason, message=str(exc))
        code = 2
    except KeyboardInterrupt:
        report.update(status="cancelled", error="KeyboardInterrupt")
        code = 130
    except Exception as exc:
        report.update(
            status="failed", error=type(exc).__name__, message=str(exc)[:1000]
        )
        code = 1
    finally:
        report["seconds_including_cleanup"] = round(perf_counter() - started, 3)
        path = output / "report.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        print("Report: " + str(path))
    return code


if __name__ == "__main__":
    sys.exit(main())
