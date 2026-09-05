"""Run a guarded real-world Google demo in a visible browser by default.

Unlike :mod:`demo_local`, this demo requires Internet access to Google. Running
without a subcommand prints help and launches nothing. ``--allow-download``
controls driver provisioning only; it does not disable website access. The demo
never tries to bypass consent screens, traffic challenges, or CAPTCHAs.

Example:
    Parse a headless invocation without provisioning a driver or browser:

    >>> options = parse_args(["run", "--headless", "--hold-seconds", "0"])
    >>> (options.command, options.browser, options.headless)
    ('run', 'chrome', True)
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

from _demo_support import (
    BROWSERS,
    CHROMIUM,
    acquire_offline,
    json_default,
    make_driver,
    provision,
)
from aselenium import Element, KeyboardKeys, Session, WebDriver

ROOT = Path(__file__).resolve().parents[1]
GOOGLE_URL = "https://www.google.com/"
SEARCH_BOX = "textarea[name='q'], input[name='q']"
RESULT_HEADING = "a h3"
GOOGLE_HOSTS = {"google.com", "www.google.com"}


class GoogleNeedsAttention(RuntimeError):
    """Signal that the Google page requires manual review.

    Attributes:
        reason: Stable machine-readable reason recorded in the JSON report.
    """

    def __init__(self, reason: str, message: str) -> None:
        """Create an attention error with a stable reason and readable message.

        Args:
            reason: Stable reason code recorded in the attention report.
            message: Human-readable explanation exposed by :class:`RuntimeError`.
        """
        super().__init__(message)
        self.reason = reason


def positive_seconds(value: str) -> float:
    """Parse a finite positive command-line duration in seconds.

    Args:
        value: Command-line text representing a duration in seconds.

    Returns:
        The parsed finite value, which is strictly greater than zero.

    Raises:
        ValueError: ``value`` is not numeric.
        argparse.ArgumentTypeError: The numeric value is non-finite or not positive.

    Example:
        >>> positive_seconds("2.5")
        2.5
    """
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def hold_seconds(value: str) -> float:
    """Parse a browser hold duration between zero and sixty seconds.

    Args:
        value: Command-line text representing a browser hold duration.

    Returns:
        The parsed finite value in the inclusive range from zero to sixty.

    Raises:
        ValueError: ``value`` is not numeric.
        argparse.ArgumentTypeError: The value is non-finite or outside the allowed range.

    Example:
        >>> hold_seconds("0")
        0.0
    """
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 60:
        raise argparse.ArgumentTypeError("must be between 0 and 60 seconds")
    return number


def query_text(value: str) -> str:
    """Validate and trim a search query containing one to 512 characters.

    Args:
        value: Search-query text from the command line.

    Returns:
        The stripped query, containing between one and 512 characters.

    Raises:
        argparse.ArgumentTypeError: The stripped query is empty or exceeds 512 characters.

    Example:
        >>> query_text("  Aselenium Python  ")
        'Aselenium Python'
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
        The parsed namespace. Its ``command`` is ``None`` when no subcommand was
        supplied and help was printed.

    Raises:
        SystemExit: Argument parsing or cross-option validation fails.

    Example:
        >>> options = parse_args(["run", "--query", "Aselenium"])
        >>> (options.command, options.query)
        ('run', 'Aselenium')
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
        "--profile-root",
        type=Path,
        help="existing shared writable Firefox profile root (Snap/Flatpak workaround)",
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
    if args.profile_root is not None and args.browser != "firefox":
        parser.error("--profile-root is only available for Firefox")
    if args.browser == "safari" and (args.headless or args.channel == "beta"):
        parser.error("Safari is always headed and supports only stable/dev channels")
    return args


def configure(driver: WebDriver, args: argparse.Namespace) -> None:
    """Apply conservative browser options for the Google demonstration.

    Every browser receives explicit WebDriver timeouts, normal page loading, and
    certificate verification. Chromium-based browsers also receive deterministic
    window and first-run flags; Chrome, Chromium, Edge, and Firefox receive their
    supported headless flag only when requested. Safari remains headed.

    Args:
        driver: Browser facade whose mutable options are configured before acquisition.
        args: Parsed demo arguments containing ``browser`` and ``headless``.
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
        session: Active browser session displaying a Google-owned page.

    Returns:
        A pair of the current URL and one of ``"page"``, ``"consent"``, or
        ``"dialog"``. ``"dialog"`` denotes visible consent-like page UI.

    Raises:
        GoogleNeedsAttention: The page is a challenge or has left the expected
            HTTPS Google origins.
        RuntimeError: The page-inspection script returns an unexpected payload.
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
        session: Active session displaying the Google homepage.
        timeout: Maximum number of seconds to wait for a usable search field.

    Returns:
        The first enabled and unobscured Google search field.

    Raises:
        GoogleNeedsAttention: A challenge is detected, Google redirects away, or
            no usable search field appears before the deadline.
    """
    print(
        f"Waiting up to {timeout:g}s for Google's search box. If consent is shown, choose manually in the visible browser.",
        flush=True,
    )
    last_state = "page"

    async def ready() -> Element | None:
        """Inspect one poll iteration for an interactable search field.

        Returns:
            A usable search field, or ``None`` while the page is not ready.
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
        session: Active session after the query has been submitted.
        query: Search text submitted once to the real Google website.
        timeout: Maximum number of seconds to wait for a normal result page.

    Returns:
        The verified result URL and up to five non-empty visible heading samples.

    Raises:
        GoogleNeedsAttention: A challenge is detected, Google redirects away, or
            matching visible results do not appear before the deadline.
    """

    async def ready() -> dict[str, Any] | None:
        """Inspect one poll iteration for the submitted query and result headings.

        Returns:
            Result metadata when the page is ready, otherwise ``None``.
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
        session: Active browser session to capture.
        path: Destination for the PNG screenshot.
        report: Mutable run report whose ``artifacts`` list receives the filename.

    Raises:
        RuntimeError: WebDriver reports failure or the saved file lacks a PNG signature.
        OSError: The screenshot cannot be read after it is saved.
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
    """Visit Google, capture the homepage, and optionally submit one query.

    The function records verified homepage and search metadata and saves a PNG
    after each completed stage. It does not click results, ads, account controls,
    consent controls, or challenge UI.

    Args:
        session: Active browser session used for the website interaction.
        args: Parsed arguments containing the optional query and wait timeout.
        output: Existing run directory that receives screenshots.
        report: Mutable run report receiving page metadata and artifact names.

    Raises:
        GoogleNeedsAttention: Google requires manual attention or expected UI does
            not appear.
        RuntimeError: A diagnostic screenshot cannot be created or validated.
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
    """Provision a browser, visit Google, and release all owned resources.

    Installation and session versions are added to the report. On an interaction
    failure, the function attempts one diagnostic screenshot without masking the
    original exception. Session cleanup and options cleanup run on every exit.

    Args:
        args: Parsed browser, provisioning, interaction, and hold options.
        output: Existing run directory that receives screenshots.
        report: Mutable run report receiving installation and session details.
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
    """Run the Google demo and write a JSON report in a unique directory.

    Args:
        argv: Command-line arguments; None reads the current process arguments.

    Returns:
        ``0`` after help or a successful run, ``2`` when Google needs manual
        attention, ``130`` after keyboard interruption, or ``1`` for another
        handled run failure.

    Raises:
        SystemExit: Command-line parsing or validation fails.
        OSError: The output directory or final report cannot be created.
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
        path.write_text(
            json.dumps(report, indent=2, default=json_default) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2, default=json_default))
        print("Report: " + str(path))
    return code


if __name__ == "__main__":
    sys.exit(main())
