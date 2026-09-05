"""Exercise modern Aselenium features against local HTML fixtures.

The tour is headless by default. Running without a subcommand prints help, and
``list`` reports available sections without probing any executable. ``install``
and ``run`` may inspect installed browsers; vendor requests occur only with
``--allow-download``. Browser navigation and the upload demonstration remain on
an ephemeral loopback server. Use :mod:`demo_google` for a real-world website.

Example:
    Inspect the section-list command without launching a browser:

    >>> options = parse_args(["list"])
    >>> options.command
    'list'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import re
import sys
import tempfile
from collections.abc import Awaitable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from _demo_support import (
    BROWSERS,
    CHROMIUM,
    acquire_offline,
    json_default,
    make_driver,
    provision,
)
from aselenium import (
    ChromeSession,
    ChromiumSession,
    EdgeSession,
    Element,
    FirefoxSession,
    Proxy,
    SafariSession,
    Session,
    WebDriver,
)

if TYPE_CHECKING:
    from aselenium.manager._installation import InstallationResult
    from aselenium.webdriver import SessionContext

ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).resolve().with_name("demo_assets")
POLICIES = (
    "exact",
    "compatible-build",
    "compatible-major",
    "latest-compatible",
    "cached-compatible",
    "offline",
)
SECTIONS = {
    "navigation": "Navigation, page information, and runtime timeouts",
    "elements": "Forms, uploads, DOM text, visibility, scrolling, and shadow DOM",
    "waits": "Explicit deadlines, immediate lookup, and shared-session transactions",
    "cookies": "Local-origin cookie creation, retrieval, and deletion",
    "windows": "Named tabs and deterministic focus restoration",
    "frames": "Frame entry and guaranteed return to the top-level document",
    "alerts": "Prompt text, input, and acceptance",
    "scripts": "Reusable JavaScript, element arguments, and asynchronous callbacks",
    "actions": "Pointer/keyboard actions, chain reuse, and input-state reset",
    "artifacts": "Atomic PNG/PDF output and browser-specific screenshots",
    "vendor": "Chromium CDP/network/permissions/logs or Firefox temporary add-ons",
    "concurrency": "Two independent sessions with acquisition-time option snapshots",
    "cancellation": "Cancel owned work, await cleanup, and reuse the facade",
}


class DemoFailure(RuntimeError):
    """Signal that a demonstrated feature violated an expected invariant."""


class DemoSkipped(Exception):
    """Signal that a demo section is unsupported by the selected browser."""


def check(condition: object, message: str) -> None:
    """Raise a demo failure when an observed condition is false.

    Unlike an ``assert`` statement, this validation remains active under
    ``python -O``.

    Args:
        condition: Observed value whose truthiness determines success.
        message: Diagnostic text attached to a failed check.

    Raises:
        DemoFailure: ``condition`` is false.

    Example:
        >>> check(2 + 2 == 4, "arithmetic changed")
    """
    if not condition:
        raise DemoFailure(message)


def fixture_response(target: str) -> tuple[int, bytes]:
    """Serve only an explicit allowlist, never a directory or user-supplied path.

    Args:
        target: Request target or URL. Only its parsed path is considered.

    Returns:
        A pair containing the HTTP status and response body. Unknown paths return
        ``404`` and the favicon path returns an empty ``204`` response.

    Raises:
        OSError: An allowlisted fixture file cannot be read.

    Example:
        >>> fixture_response("/favicon.ico")
        (204, b'')
    """
    path = urlsplit(target).path
    pages = {
        "/": "index.html",
        "/index.html": "index.html",
        "/second.html": "second.html",
        "/frame.html": "frame.html",
    }
    if path == "/favicon.ico":
        return 204, b""
    if path not in pages:
        return 404, b"Not found"
    return 200, (ASSETS / pages[path]).read_bytes()


@contextmanager
def fixture_server() -> Iterator[str]:
    """An ephemeral loopback server with no external assets or upload endpoint.

    Yields:
        The HTTP origin of a server bound to an ephemeral IPv4 loopback port.

    Raises:
        OSError: The loopback server cannot bind or close cleanly.
    """

    class Handler(BaseHTTPRequestHandler):
        """Serve only the allowlisted local HTML demonstration fixtures."""

        def do_GET(self) -> None:
            """Write the allowlisted response for the current HTTP GET request."""
            status, content = fixture_response(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: Any) -> None:
            """Suppress request logging for the local demonstration server.

            Args:
                format: ``printf``-style message supplied by the base handler.
                *args: Values that the base handler would interpolate into ``format``.
            """
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(
        target=server.serve_forever, name="aselenium-demo-http", daemon=True
    )
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


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
        >>> positive_seconds("30")
        30.0
    """
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite, positive number")
    return number


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
        >>> options = parse_args(["run", "--sections", "navigation", "cookies"])
        >>> (options.browser, options.sections)
        ('chrome', ['navigation', 'cookies'])
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("list", help="list the tour without opening a browser")
    install = commands.add_parser(
        "install", help="resolve/cache a driver without launching a browser"
    )
    run = commands.add_parser("run", help="run the local feature tour")
    for command in (install, run):
        command.add_argument("--browser", choices=BROWSERS, default="chrome")
        command.add_argument(
            "--binary", help="browser executable, not the .app directory"
        )
        command.add_argument(
            "--channel", choices=("stable", "beta", "dev", "cft"), default="stable"
        )
        command.add_argument(
            "--cache-dir",
            type=Path,
            default=ROOT / ".demo-cache",
            help="dedicated demo cache parent; never defaults to your personal cache",
        )
        command.add_argument(
            "--allow-download",
            action="store_true",
            help="allow vendor metadata/driver downloads (and browser download for CfT)",
        )
        command.add_argument(
            "--timeout",
            type=positive_seconds,
            default=240,
            help="overall work budget in seconds; owned cleanup may take longer",
        )
    install.add_argument(
        "--version", help="full numeric driver version; required for exact policy"
    )
    install.add_argument(
        "--policy",
        choices=POLICIES,
        help="default: offline; with --allow-download: build (Chromium) / cached (Firefox)",
    )
    pins = install.add_mutually_exclusive_group()
    pins.add_argument(
        "--pin",
        action="store_true",
        help="protect the resolved driver from cache eviction",
    )
    pins.add_argument(
        "--unpin",
        action="store_true",
        help="remove eviction protection from the resolved driver",
    )
    run.add_argument(
        "--sections", nargs="+", choices=("all", *SECTIONS), default=["all"]
    )
    run.add_argument(
        "--session-timeout",
        type=positive_seconds,
        default=30,
        help="per-command and session-start deadline in seconds; default 30",
    )
    run.add_argument(
        "--headed",
        action="store_true",
        help="show browser UI (Safari is always headed)",
    )
    run.add_argument(
        "--profile-demo",
        action="store_true",
        help="clone a new, empty demo profile; never reads a personal profile",
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
        help="parent for a unique run directory containing the JSON report and artifacts",
    )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return args
    if args.command == "list":
        return args
    if args.browser in {"chromium", "firefox"} and args.channel != "stable":
        parser.error(
            "Chromium/Firefox select their executable with --binary, not --channel"
        )
    if args.browser == "edge" and args.channel == "cft":
        parser.error("--channel cft is only available for Chrome")
    if (
        args.command == "run"
        and args.profile_root is not None
        and args.browser != "firefox"
    ):
        parser.error("--profile-root is only available for Firefox")
    if args.channel == "cft":
        if args.command == "run":
            parser.error(
                "Provision CfT with install --channel cft --version FULL, then run --binary PATH using its browser_location and the stable channel"
            )
        if not args.version:
            parser.error(
                "Chrome for Testing requires --version with a complete numeric version"
            )
        if args.binary:
            parser.error("CfT provisions its own browser; --binary would be ignored")
    if args.browser == "safari":
        if args.channel not in {"stable", "dev"}:
            parser.error("Safari channels are stable and dev (Technology Preview)")
        if args.command == "install" and (
            args.version or args.policy or args.pin or args.unpin
        ):
            parser.error(
                "Safari uses Apple's installed driver; version policies and cache pins do not apply"
            )
        if args.command == "run" and args.profile_demo:
            parser.error("Safari does not support the cloned-profile demo")
    if args.command == "install":
        if args.version:
            segments = 3 if args.browser == "firefox" else 4
            if not re.fullmatch(
                r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){%d}" % (segments - 1),
                args.version,
            ):
                parser.error(
                    "--version requires a full %d-component numeric version" % segments
                )
            if args.policy not in {None, "exact", "offline"}:
                parser.error(
                    "--version pairs with --policy exact or offline, not a compatibility selector"
                )
        if args.browser == "firefox" and args.policy in {
            "compatible-build",
            "compatible-major",
        }:
            parser.error(
                "Firefox policies are exact, latest-compatible, cached-compatible, and offline"
            )
        if args.policy == "exact" and not args.version:
            parser.error(
                "--policy exact requires --version with the complete driver version"
            )
        if args.policy not in {None, "offline"} and not args.allow_download:
            parser.error(
                "online-capable policies require --allow-download; use --policy offline otherwise"
            )
    return args


def configure(
    driver: WebDriver, args: argparse.Namespace, profile_source: Path | None
) -> dict[str, Any]:
    """Configure options and return the options-section report details.

    The function applies deterministic timeouts and browser-specific arguments,
    verifies that capabilities are defensive copies, and demonstrates proxy
    serialization without enabling the proxy. When ``profile_demo`` is selected,
    it configures an empty source profile for cloning during each acquisition.

    Args:
        driver: Browser facade whose mutable options are configured before acquisition.
        args: Parsed local-demo browser, timeout, display, and profile options.
        profile_source: Empty directory used as the clone source. It must be a
            path when ``args.profile_demo`` is true; otherwise it is ignored.

    Returns:
        Report fields describing timeouts, defensive capabilities, the serialized
        proxy example, and the selected profile mode.

    Raises:
        DemoFailure: A configuration invariant fails or profile demonstration
            was requested without its source directory.
        OSError: The empty Chromium profile directory cannot be prepared.
    """
    options = driver.options
    options.session_timeout = args.session_timeout
    options.set_timeouts(
        implicit=0, pageLoad=20, script=5
    )  # Public setters use seconds.
    options.page_load_strategy = "normal"
    options.unhandled_prompt_behavior = (
        "ignore"  # The alerts chapter handles its own prompt.
    )
    options.accept_insecure_certs = False
    if args.browser in CHROMIUM:
        options.add_arguments(
            "--disable-background-networking",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-sync",
            "--window-size=1200,900",
        )
        if not args.headed:
            options.add_arguments("--headless=new")
        options.set_preferences(
            **{
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
            }
        )
        options.add_experimental_options(excludeSwitches=["enable-logging"])
    elif args.browser == "firefox":
        if not args.headed:
            options.add_arguments("-headless")
        options.set_preferences(**{"browser.shell.checkDefaultBrowser": False})

    # Accessors return defensive copies. Change configuration through setters.
    detached = options.capabilities
    detached["pageLoadStrategy"] = "none"
    check(
        options.capabilities["pageLoadStrategy"] == "normal",
        "capabilities leaked a mutable reference",
    )

    # Serialization-only example: this proxy is NEVER assigned to the live browser.
    proxy = Proxy(
        http_proxy="http://127.0.0.1:8080", no_proxy=["localhost", "127.0.0.1"]
    )
    check(
        proxy.to_capabilities()["noProxy"] == ["localhost", "127.0.0.1"],
        "proxy bypass serialization",
    )
    if args.profile_demo:
        if profile_source is None:
            raise DemoFailure("Profile demonstration requires a source directory")
        if args.browser in CHROMIUM:
            (profile_source / "Default").mkdir()
            options.set_profile(profile_source, "Default")
        else:
            options.set_profile(profile_source)
    return {
        "implicit_wait_seconds": 0,
        "session_timeout_seconds": args.session_timeout,
        "defensive_capabilities": True,
        "proxy": "serialization only; not enabled",
        "profile": "empty template cloned per acquisition"
        if args.profile_demo
        else "fresh browser profile",
    }


@dataclass
class Tour:
    """Session, local fixture URL, and artifact context for one browser tour.

    Attributes:
        session: Active browser session for the current ordinary demo sections.
        url: Base URL of the ephemeral loopback fixture server.
        output: Run-specific directory for screenshots and PDFs.
        browser: Normalized browser name selected on the command line.
        headed: Whether the demo requested a visible browser window.
    """

    session: Session
    url: str
    output: Path
    browser: str
    headed: bool

    async def element(self, selector: str) -> Element:
        """Find one required fixture element by CSS selector.

        Args:
            selector: CSS selector evaluated in the current browsing context.

        Returns:
            The matching element.

        Raises:
            DemoFailure: No element matches ``selector``.
        """
        element = await self.session.find_element(selector)
        if element is None:
            raise DemoFailure("Missing fixture element: " + selector)
        return element


async def navigation(tour: Tour) -> dict[str, Any]:
    """Demonstrate navigation, page metadata, and runtime timeouts.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Observed page dimensions, source length, and reset timeout values.

    Raises:
        DemoFailure: A navigation, title, URL, or timeout check fails.
    """
    s = tour.session
    check(await s.title == "Aselenium local demo", "initial title")
    await s.load(tour.url + "/second.html")
    check(
        await s.wait_until_url("endswith", "/second.html", timeout=2), "navigation URL"
    )
    await s.backward()
    check(
        await s.wait_until_title("equals", "Aselenium local demo", timeout=2),
        "back navigation",
    )
    await s.forward()
    check(await s.title == "Second local page", "forward navigation")
    await s.refresh()
    await s.set_timeouts(implicit=0, pageLoad=15, script=3)
    check((await s.timeouts).script == 3, "runtime timeout setter uses seconds")
    await s.reset_timeouts()
    return {
        "page_width": await s.page_width,
        "page_height": await s.page_height,
        "source_characters": len(await s.page_source),
        "timeouts_ms": (await s.timeouts).dict,
    }


async def elements(tour: Tour) -> dict[str, Any]:
    """Demonstrate forms, upload selection, visibility, and shadow DOM.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Report details confirming local form submission, local file selection,
        and the visibility cases that were checked.

    Raises:
        DemoFailure: Any element behavior differs from the fixture contract.
    """
    s = tour.session
    field = await tour.element("#name")
    check(
        await field.get_attribute_dom("id") == "name", "explicit DOM attribute lookup"
    )
    await field.send("Aselenium")  # Element.send(), not Selenium's send_keys().
    check(await field.get_property("value") == "Aselenium", "input value")
    await field.clear()
    await field.send("modern package")
    checkbox = await tour.element("#subscribe")
    await checkbox.click()
    check(await checkbox.selected, "checkbox selection")
    await (await tour.element("#upload")).upload(ASSETS / "upload.txt")
    check(
        await s.execute_script("return document.querySelector('#upload').files.length")
        == 1,
        "local file input",
    )
    await (
        field.submit()
    )  # The fixture intercepts submission; no upload is sent anywhere.
    check(
        await (await tour.element("#submitted")).text == "Submitted: modern package",
        "form submit",
    )
    check(len(await s.find_elements(".item")) == 3, "multiple-element lookup")
    check(
        await (await tour.element("#hidden")).dom_text == "Hidden DOM text",
        "DOM text ignores rendering",
    )
    for selector in ("#hidden", "#zero", "#offscreen"):
        element = await tour.element(selector)
        check(
            not await element.in_viewport and not await element.unobscured,
            selector + " should not be interactable",
        )
    covered = await tour.element("#covered")
    check(
        await covered.in_viewport and not await covered.unobscured, "covered hit-test"
    )
    shadow = await (await tour.element("#host")).shadow
    if shadow is None:
        raise DemoFailure("open shadow root")
    child = await shadow.find_element("#shadow-text")
    if child is None:
        raise DemoFailure("shadow lookup")
    check(await child.text == "Inside shadow DOM", "shadow lookup")
    check(await child.unobscured, "shadow-root-aware hit-test")
    check(await child.wait_until("unobscured", timeout=2), "element hit-test wait")
    check(
        await shadow.wait_until_element("unobscured", "#shadow-text", timeout=2),
        "shadow hit-test wait",
    )
    check(await s.scroll_into_view("#bottom", timeout=2), "scroll into view")
    await s.scroll_to_top()
    return {
        "form": "submitted locally",
        "upload": "one fixture file selected; no network upload",
        "visibility": "hidden, zero-size, offscreen, covered, and shadow cases checked",
    }


async def waits(tour: Tour) -> dict[str, Any]:
    """Demonstrate explicit waits and a shared-session transaction.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Report details for truthy-result, zero-timeout, viewport, and hit-test waits.

    Raises:
        DemoFailure: A wait result violates the demonstrated deadline semantics.
    """
    s = tour.session
    check(
        await s.wait_until_element("in_viewport", "#name", timeout=2), "viewport wait"
    )
    check(await s.wait_until_element("unobscured", "#name", timeout=2), "hit-test wait")
    check(
        await s.find_1st_element("#absent", "#name") is not None,
        "all fallback selectors must be checked",
    )
    await s.execute_script(
        "setTimeout(() => {const p=document.createElement('p'); p.id='ready'; p.textContent='Ready'; document.body.append(p)}, 100)"
    )
    async with s.transaction():
        # The transaction keeps related stateful operations together on this session.
        ready = await s.wait_for(lambda: s.find_element("#ready"), timeout=2)
        check(ready is not None and await ready.text == "Ready", "deadline-aware wait")
    check(
        not await s.wait_for(lambda: s.find_element("#absent"), timeout=0),
        "zero timeout performs one observation",
    )
    return {
        "explicit_wait": "truthy result returned; zero-timeout missing lookup is falsey",
        "current_conditions": ["in_viewport", "unobscured"],
    }


async def cookies(tour: Tour) -> dict[str, Any]:
    """Create, retrieve, and delete a cookie on the loopback origin.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        The cookie origin and confirmation that the temporary cookie was deleted.

    Raises:
        DemoFailure: Cookie retrieval or deletion does not match the expected value.
    """
    s = tour.session
    await s.add_cookie(
        {
            "name": "aselenium-demo",
            "value": "local-only",
            "path": "/",
            "sameSite": "Lax",
        }
    )
    try:
        cookie = await s.get_cookie("aselenium-demo")
        check(cookie is not None and cookie["value"] == "local-only", "cookie readback")
    finally:
        await s.delete_cookie("aselenium-demo")
    check(await s.get_cookie("aselenium-demo") is None, "cookie deletion")
    return {"origin": tour.url, "cookie_deleted": True}


async def windows(tour: Tour) -> dict[str, Any]:
    """Open a named tab, close it, and restore the original browsing context.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Confirmation that the temporary tab was closed.

    Raises:
        DemoFailure: Tab count, title, or focus restoration is incorrect.
    """
    s = tour.session
    original = await s.active_window
    async with s.transaction():
        await s.new_window("demo-extra", win_type="tab")
        try:
            await s.load(tour.url + "/second.html")
            check(await s.title == "Second local page", "new tab")
            check(len(await s.windows) == 2, "two tabs")
        finally:
            await s.close_window(switch_to=original)
        check(await s.title == "Aselenium local demo", "restored original tab")
    return {"temporary_tab_closed": True}


async def frames(tour: Tour) -> dict[str, Any]:
    """Enter the local iframe and restore the top-level document.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Confirmation that the default frame was restored.

    Raises:
        DemoSkipped: Safari is selected because its facade disables frame switching.
        DemoFailure: Frame entry, content, or top-level restoration fails.
    """
    if tour.browser == "safari":
        raise DemoSkipped("The current Safari facade disables frame switching")
    s = tour.session
    try:
        check(await s.switch_frame("#frame", timeout=2), "frame entry")
        check(
            await (await tour.element("#frame-text")).text == "Inside a local frame",
            "frame content",
        )
    finally:
        check(await s.default_frame(), "return to top-level document")
    return {"default_frame_restored": True}


async def alerts(tour: Tour) -> dict[str, Any]:
    """Inspect a local prompt, send text, and accept it safely.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Confirmation that prompt text was submitted and accepted.

    Raises:
        DemoFailure: The prompt, its text, or submitted result is incorrect.
    """
    s = tour.session
    # Schedule the prompt after this script returns so the WebDriver call can finish.
    await s.execute_script(
        "setTimeout(() => {document.querySelector('#prompt-result').textContent = prompt('Local demo prompt', '') || 'dismissed'}, 100)"
    )
    alert = await s.get_alert(timeout=3)
    if alert is None:
        raise DemoFailure("prompt appeared")
    try:
        check(await alert.text == "Local demo prompt", "prompt text")
        await alert.send("accepted locally")
    finally:
        await alert.accept()
    check(
        await (await tour.element("#prompt-result")).text == "accepted locally",
        "prompt input",
    )
    return {"prompt_accepted": True}


async def scripts(tour: Tour) -> dict[str, Any]:
    """Demonstrate cached, synchronous, and asynchronous JavaScript execution.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Report details confirming script-cache lifecycle and preservation of an
        application payload that resembles a WebDriver error.

    Raises:
        DemoFailure: Script results or cache removal differ from expectations.
    """
    s = tour.session
    cached = s.cache_script("demo-sum", "return arguments[0] + arguments[1]", 2, 3)
    check(await s.execute_script(cached) == 5, "cached JavaScript")
    field = await tour.element("#name")
    check(
        await s.execute_script("return arguments[0].id", field) == "name",
        "element wire argument",
    )
    result = await s.execute_async_script(
        "const done=arguments[arguments.length-1]; setTimeout(() => done({ready:true}), 25)"
    )
    check(result == {"ready": True}, "async JavaScript callback")
    payload = await s.execute_script(
        "return {error:'application-data', message:'not a WebDriver error'}"
    )
    check(
        payload["error"] == "application-data",
        "application error-shaped data was preserved",
    )
    check(s.remove_script("demo-sum"), "script cache removal")
    return {
        "script_cache": "created, executed, removed",
        "application_payload_preserved": True,
    }


async def actions(tour: Tour) -> dict[str, Any]:
    """Demonstrate a reusable action chain and remote input-state reset.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Confirmation that performed actions were not replayed and input state was reset.

    Raises:
        DemoSkipped: Safari is selected because its facade disables W3C actions.
        DemoFailure: Reusing the chain produces an unexpected input value.
    """
    if tour.browser == "safari":
        raise DemoSkipped("The current Safari facade disables W3C action chains")
    field = await tour.element("#name")
    chain = tour.session.actions()
    try:
        await chain.move_to(field).click().send_keys("first").perform()
        await chain.send_keys(
            "-second"
        ).perform()  # No replay of already-performed actions.
        check(await field.get_property("value") == "first-second", "action chain reuse")
    finally:
        await (
            chain.reset()
        )  # Releases remote input state as well as local queued actions.
    return {"reusable_chain": True, "remote_input_state_reset": True}


async def artifacts(tour: Tour) -> dict[str, Any]:
    """Save and validate browser-supported PNG and PDF artifacts.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Saved artifact filenames and notes explaining any intentional PDF skip.

    Raises:
        DemoFailure: Saving fails or an artifact has the wrong file signature.
        OSError: A saved artifact cannot be read for validation.
    """
    s = tour.session
    capture = tour.output / "page.png"
    check(await s.save_screenshot(capture), "PNG save returned false")
    check(
        (await asyncio.to_thread(capture.read_bytes)).startswith(b"\x89PNG\r\n\x1a\n"),
        "PNG signature",
    )
    files = [capture.name]
    notes = []
    if tour.browser == "safari" or (tour.browser in CHROMIUM and tour.headed):
        notes.append(
            "PDF skipped: Safari facade disables printing; Chromium demo prints in headless mode only"
        )
    else:
        pdf = tour.output / "page.pdf"
        check(await s.save_page(pdf), "PDF save returned false")
        check(
            (await asyncio.to_thread(pdf.read_bytes)).startswith(b"%PDF"),
            "PDF signature",
        )
        files.append(pdf.name)
    if tour.browser == "firefox":
        firefox = cast(FirefoxSession, s)
        full = tour.output / "full-page.png"
        check(await firefox.save_full_screenshot(full), "Firefox full-page screenshot")
        check(
            (await asyncio.to_thread(full.read_bytes)).startswith(b"\x89PNG"),
            "full-page PNG signature",
        )
        files.append(full.name)
    return {"files": files, "notes": notes}


async def vendor(tour: Tour) -> dict[str, Any]:
    """Demonstrate browser-specific extension APIs without persistent changes.

    Chromium browsers exercise CDP, permissions, network emulation, and browser
    logs while restoring the original permission and network state. Firefox
    installs a local add-on temporarily and removes it in ``finally``. Safari
    performs read-only permission inspection.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        Browser-specific results describing the exercised APIs and restored state.

    Raises:
        DemoFailure: A vendor API result or cleanup invariant is incorrect.
    """
    s = tour.session
    if tour.browser in CHROMIUM:
        chromium = cast(ChromeSession | ChromiumSession | EdgeSession, s)
        command = chromium.cache_cdp_cmd("demo-version", "Browser.getVersion")
        version = await chromium.execute_cdp_cmd(command)
        check(
            isinstance(version, dict) and "product" in version, "CDP Browser.getVersion"
        )
        original = await chromium.get_permission("geolocation")
        if original is None:
            raise DemoFailure("geolocation permission query")
        try:
            permission = await chromium.set_permission("geolocation", "denied")
            check(
                permission is not None and permission.state == "denied",
                "permission readback",
            )
        finally:
            await chromium.set_permission("geolocation", original.state)
        try:
            conditions = await chromium.set_network(
                offline=False, latency=10, download_throughput=1024 * 1024
            )
            check(conditions.latency == 10, "network emulation readback")
        finally:
            await chromium.reset_network()
        log_types = await chromium.log_types
        counts = {
            kind: len(await chromium.get_logs(kind))
            for kind in log_types
            if kind == "browser"
        }
        return {
            "cdp_product": version["product"],
            "network_reset": True,
            "permission_restored": True,
            "log_counts": counts,
            "casting": "not invoked; requires explicit device selection",
        }
    if tour.browser == "firefox":
        firefox = cast(FirefoxSession, s)
        check(await firefox.context == "content", "Firefox content context")
        addons = await firefox.install_addons(ASSETS / "firefox-addon", temporary=True)
        try:
            check(len(addons) == 1, "temporary add-on installation")
            await firefox.refresh()

            async def addon_marker() -> Any:
                """Read whether the temporary add-on marked the fixture document.

                Returns:
                    The script result, expected to be truthy after the content script runs.
                """
                return await firefox.execute_script(
                    "return document.documentElement.dataset.aseleniumAddon === 'ready'"
                )

            check(
                await s.wait_for(addon_marker, timeout=3), "local add-on content script"
            )
        finally:
            for addon in addons:
                await firefox.uninstall_addon(addon)
        return {
            "content_context": True,
            "temporary_addons_removed": len(addons),
            "privileged_chrome_context": "not entered",
        }
    safari = cast(SafariSession, s)
    return {
        "safari_permissions": await safari.permissions,
        "note": "Read-only Safari permission inspection; automation settings are never changed",
    }


async def drain_tasks(tasks: Sequence[asyncio.Task[Any]]) -> list[Any | BaseException]:
    """Own every task on Python 3.10 too; repeated cancellation cannot orphan cleanup.

    Args:
        tasks: Owned tasks to cancel if unfinished and await to completion.

    Returns:
        Each task's result or raised exception, in input order.
    """
    for task in tasks:
        if not task.done():
            task.cancel()
    drain = asyncio.gather(*tasks, return_exceptions=True)
    while not drain.done():
        try:
            await asyncio.shield(drain)
        except asyncio.CancelledError:
            continue
    return drain.result()


async def concurrency(
    driver: WebDriver, args: argparse.Namespace, url: str
) -> dict[str, Any]:
    """Run two isolated sessions with acquisition-time option snapshots.

    Each worker receives a distinct session timeout, profile, session ID, and
    cookie store. All created tasks and contexts are drained before returning or
    propagating a failure, and the facade's original timeout is restored.

    Args:
        driver: Configured browser facade reused for both acquisitions.
        args: Parsed browser arguments used for offline session acquisition.
        url: Base URL of the loopback fixture server.

    Returns:
        Confirmation of session, timeout, cookie, and optional profile isolation.

    Raises:
        DemoSkipped: Safari is selected because its automation service is single-session.
        DemoFailure: Session IDs, option snapshots, cookies, or profiles are not isolated.
    """
    if args.browser == "safari":
        raise DemoSkipped(
            "Safari's automation service is single-session; no concurrent tour"
        )
    contexts = []
    tasks = []
    original = driver.options.session_timeout
    both_written = asyncio.Event()
    writes = 0

    async def worker(context: SessionContext, expected: int) -> tuple[str, Path | None]:
        """Exercise one isolated context and return its session/profile identity.

        Args:
            context: Single-use context whose option snapshot is under test.
            expected: Expected session timeout and private cookie value.

        Returns:
            The session ID and temporary profile directory, if a profile exists.

        Raises:
            DemoFailure: The option snapshot or cookie store is not isolated.
        """
        nonlocal writes
        async with context as session:
            check(
                session.options.session_timeout == expected,
                "acquisition snapshot changed",
            )
            await session.load(url)
            # A private cookie proves isolation even if the other worker runs first.
            check(
                await session.get_cookie("worker") is None,
                "browser profiles shared cookies",
            )
            await session.add_cookie({"name": "worker", "value": str(expected)})
            writes += 1
            if writes == 2:
                both_written.set()
            await both_written.wait()
            check(
                (await session.get_cookie("worker"))["value"] == str(expected),
                "worker cookie isolation",
            )
            profile = session.options.profile
            return session.id, profile.directory_temp if profile is not None else None

    try:
        for timeout in (11, 17):
            driver.options.session_timeout = timeout
            context = acquire_offline(
                driver, args
            )  # Snapshot is taken NOW, before awaiting.
            contexts.append(context)
            tasks.append(asyncio.create_task(worker(context, timeout)))
        driver.options.session_timeout = 23
        results = await asyncio.gather(*tasks)
        check(len({result[0] for result in results}) == 2, "independent session IDs")
        if args.profile_demo:
            check(
                len({result[1] for result in results}) == 2,
                "physical profile clone isolation",
            )
        return {
            "independent_sessions": 2,
            "captured_timeouts_seconds": [11, 17],
            "cookies_isolated": True,
            "physical_clones_checked": args.profile_demo,
        }
    finally:
        await drain_tasks(tasks)
        cleanup_errors = []
        for context in contexts:
            try:
                await context.quit()  # Idempotent; surfaces a failed earlier teardown.
            except BaseException as exc:
                cleanup_errors.append(exc)
        driver.options.session_timeout = original
        if cleanup_errors:
            raise cleanup_errors[0]


async def cancellation(
    driver: WebDriver, args: argparse.Namespace, url: str
) -> dict[str, Any]:
    """Cancel an owned session task, drain cleanup, and reuse the facade.

    A deliberately idle worker is cancelled only after its first page is ready.
    The closed context is not reused; a fresh acquisition verifies that the
    browser facade remains usable after cancellation.

    Args:
        driver: Configured browser facade used for both acquisitions.
        args: Parsed browser arguments used for offline session acquisition.
        url: Base URL of the loopback fixture server.

    Returns:
        Confirmation that cancellation was awaited and a fresh acquisition succeeded.

    Raises:
        DemoFailure: The worker does not start, propagate cancellation, or permit
            a successful fresh acquisition.
    """
    context = acquire_offline(driver, args)
    ready = asyncio.Event()

    async def worker() -> None:
        """Load the fixture, signal readiness, and wait indefinitely for cancellation."""
        async with context as session:
            await session.load(url)
            ready.set()
            await (
                asyncio.Event().wait()
            )  # Deliberately idle until its owner cancels it.

    task = asyncio.create_task(worker())
    waiter = asyncio.create_task(ready.wait())
    try:
        done, _ = await asyncio.wait(
            {task, waiter}, timeout=45, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            await (
                task
            )  # Preserve startup failures instead of disguising them as a timeout.
        check(ready.is_set(), "cancellation worker did not become ready")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise DemoFailure("worker did not propagate cancellation")
    finally:
        await drain_tasks([task, waiter])
        await context.quit()
    # A closed context is single-use. Reuse the facade with a NEW acquisition.
    async with acquire_offline(driver, args) as session:
        await session.load(url)
        check(
            await session.title == "Aselenium local demo",
            "new session after cancellation",
        )
    return {"cancelled_task_awaited": True, "fresh_acquisition_succeeded": True}


async def record(report: dict[str, Any], name: str, operation: Awaitable[Any]) -> None:
    """Record the outcome and duration of one awaited demo section.

    Args:
        report: Mutable run report whose ``sections`` list receives one entry.
        name: Stable section name displayed and stored in the report.
        operation: Awaitable implementing the section.

    Raises:
        BaseException: Any section failure other than :class:`DemoSkipped` is
            recorded with duration and then propagated unchanged.
    """
    started = perf_counter()
    entry: dict[str, Any] = {"section": name}
    report["sections"].append(entry)
    print("Running " + name + "...", flush=True)
    try:
        entry["details"] = await operation
        entry["status"] = "passed"
    except DemoSkipped as exc:
        entry.update(status="skipped", reason=str(exc))
    except BaseException as exc:
        entry.update(
            status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
            error=type(exc).__name__,
            message=str(exc)[:1000],
        )
        raise
    finally:
        entry["seconds"] = round(perf_counter() - started, 3)


async def run_tour(
    args: argparse.Namespace,
    url: str,
    output: Path,
    profile_source: Path | None,
    report: dict[str, Any],
) -> None:
    """Provision the browser and run the selected local HTML tour sections.

    Driver management and option configuration always run first. Ordinary
    sections share one session and reload the fixture before each chapter;
    concurrency and cancellation own separate acquisitions. Browser options are
    closed regardless of success, failure, or cancellation.

    Args:
        args: Parsed browser, provisioning, section, and session options.
        url: Base URL of the loopback fixture server.
        output: Run-specific directory for screenshots and PDFs.
        profile_source: Empty demonstration profile to clone, or ``None`` when
            profile cloning is unavailable.
        report: Mutable run report receiving section and session results.
    """
    driver = make_driver(args)
    try:

        async def manager_demo() -> dict[str, Any]:
            """Provision the selected driver and convert its result to a report mapping.

            Returns:
                Dataclass fields from the completed installation result.
            """
            result = await provision(driver, args)
            return asdict(result)

        await record(report, "driver-management", manager_demo())

        async def options_demo() -> dict[str, Any]:
            """Configure the facade and return its options report details.

            Returns:
                The summary produced by :func:`configure`.
            """
            return configure(driver, args, profile_source)

        await record(report, "options", options_demo())
        selected = set(SECTIONS) if "all" in args.sections else set(args.sections)
        ordinary = selected - {"concurrency", "cancellation"}
        if ordinary:
            context = acquire_offline(driver, args)
            try:
                async with context as session:
                    report["session"] = {
                        "browser_version": str(session.browser_version),
                        "driver_version": str(session.driver_version),
                        "acquisition": "offline",
                    }
                    tour = Tour(session, url, output, args.browser, args.headed)
                    for name in SECTIONS:
                        if name in ordinary:

                            async def chapter(name: str = name) -> dict[str, Any]:
                                """Reload the fixture and run one selected ordinary section.

                                Args:
                                    name: Section name used to resolve its coroutine.

                                Returns:
                                    Browser observations reported by the section.

                                Raises:
                                    KeyError: ``name`` does not identify a registered section.
                                """
                                # Each chapter can be selected independently and starts fresh.
                                await session.load(url)
                                return await globals()[name](tour)

                            await record(report, name, chapter())
            finally:
                await context.quit()
        if "concurrency" in selected:
            await record(report, "concurrency", concurrency(driver, args, url))
        if "cancellation" in selected:
            await record(report, "cancellation", cancellation(driver, args, url))
    finally:
        # Release the facade's cloned template, independently of session snapshots.
        await asyncio.to_thread(driver.options.close)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested local-demo command and emit its report or listing.

    ``list`` prints section names, ``install`` prints one installation result,
    and ``run`` creates a unique artifact directory with ``report.json``. A run
    report includes not-run entries for sections skipped after an earlier failure.

    Args:
        argv: Command-line arguments; None reads the current process arguments.

    Returns:
        ``0`` after help, listing, installation, or a successful tour; ``130``
        after keyboard interruption; otherwise ``1`` for a handled failure.

    Raises:
        SystemExit: Command-line parsing or validation fails.
        OSError: A fixture, output directory, or final report cannot be created.
    """
    args = parse_args(argv)
    if args.command is None:
        return 0
    if args.command == "list":
        print("Always first: driver-management, options")
        for name, description in SECTIONS.items():
            print(f"  {name:14} {description}")
        return 0
    if args.command == "install":

        async def install_only() -> InstallationResult:
            """Provision one driver while guaranteeing options cleanup.

            Returns:
                The completed immutable installation result.
            """
            driver = make_driver(args)
            try:
                return await provision(driver, args)
            finally:
                driver.options.close()

        try:
            result = asyncio.run(asyncio.wait_for(install_only(), args.timeout))
        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            print(f"Installation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(asdict(result), indent=2, default=json_default))
        return 0

    args.output_dir = args.output_dir.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(
        tempfile.mkdtemp(prefix="local-" + args.browser + "-", dir=args.output_dir)
    )
    report = {
        "demo": "local-html",
        "browser": args.browser,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "allow_download": args.allow_download,
        "selected_sections": args.sections,
        "output": str(output),
        "sections": [],
        "status": "running",
        "scope": "loopback pages; fresh or empty-template profiles; no casting",
    }
    code = 0
    try:
        with (
            fixture_server() as url,
            tempfile.TemporaryDirectory(prefix="aselenium-demo-profile-") as source,
        ):
            asyncio.run(
                asyncio.wait_for(
                    run_tour(args, url, output, Path(source), report), args.timeout
                )
            )
        report["status"] = "passed"
    except KeyboardInterrupt:
        report.update(status="cancelled", error="KeyboardInterrupt")
        code = 130
    except Exception as exc:
        report.update(
            status="failed", error=type(exc).__name__, message=str(exc)[:1000]
        )
        code = 1
    finally:
        # A unique directory prevents overwriting an earlier run, even on failure.
        expected = [
            "driver-management",
            "options",
            *[
                name
                for name in SECTIONS
                if "all" in args.sections or name in args.sections
            ],
        ]
        recorded = {entry["section"] for entry in report["sections"]}
        for name in expected:
            if name not in recorded:
                report["sections"].append(
                    {
                        "section": name,
                        "status": "not-run",
                        "reason": "an earlier setup or section failed",
                    }
                )
        report["counts"] = {
            status: sum(entry["status"] == status for entry in report["sections"])
            for status in ("passed", "skipped", "failed", "cancelled", "not-run")
        }
        path = output / "report.json"
        path.write_text(
            json.dumps(report, indent=2, default=json_default) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2, default=json_default))
        print("Report: " + str(path))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
