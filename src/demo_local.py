"""Local HTML feature tour of the modernized Aselenium package (headless by default).

    python src/demo_local.py list
    python src/demo_local.py install --browser chrome --allow-download
    python src/demo_local.py run --browser chrome

No arguments prints help. Only `install`/`run` probe executables; vendor requests
require --allow-download. Browser pages and uploads stay on a loopback fixture.
See docs/demo-local.md for policies, browser prerequisites, and feature boundaries.
For a real-world website and a visible browser, use src/demo_google.py instead.
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
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from _demo_support import BROWSERS, CHROMIUM, acquire_offline, make_driver, provision
from aselenium import Element, Proxy, Session, WebDriver

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
    """A feature did not produce the expected result."""


class DemoSkipped(Exception):
    """A documented browser limitation, not a successful check."""


def check(condition: object, message: str) -> None:
    """Unlike assert, demo checks remain enabled under `python -O`.

    Args:
        condition: Asynchronous no-argument predicate whose truthy result completes the wait.
        message: Diagnostic message explaining the failed condition.
    """
    if not condition:
        raise DemoFailure(message)


def fixture_response(target: str) -> tuple[int, bytes]:
    """Serve only an explicit allowlist, never a directory or user-supplied path.

    Args:
        target: Target used by this operation.

    Returns:
        Serve only an explicit allowlist, never a directory or user-supplied path.
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
        The resource managed by this context; cleanup runs when the context exits.
    """

    class Handler(BaseHTTPRequestHandler):
        """Serve only the allowlisted local HTML demonstration fixtures."""

        def do_GET(self) -> None:
            """Write the allowlisted fixture response for the incoming GET request."""
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
                format: Format used by this operation.
                *args: Validated command-line options for the selected browser workflow.
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
        value: A finite positive command-line duration in seconds supplied for validation.

    Returns:
        A finite positive command-line duration in seconds.
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
        And validate the command line without launching a browser.
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
    """Configure.

    Args:
        driver: Driver object or downloaded driver artifact required by this operation.
        args: Validated command-line options for the selected browser workflow.
        profile_source: Empty demonstration profile to clone, or None for a fresh profile.

    Returns:
        A mapping containing the configure data.
    """
    options = driver.options
    options.session_timeout = 30
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
        if args.browser in CHROMIUM:
            (profile_source / "Default").mkdir()
            options.set_profile(str(profile_source), "Default")
        else:
            options.set_profile(str(profile_source))
    return {
        "implicit_wait_seconds": 0,
        "session_timeout_seconds": 30,
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
        session: Active session that owns the browser or HTTP operation.
        url: URL used for the request or browser navigation.
        output: Directory for this run's report and captures.
        browser: Browser captured for this operation.
        headed: Headed captured for this operation.
    """

    session: Session
    url: str
    output: Path
    browser: str
    headed: bool

    async def element(self, selector: str) -> Element:
        """Element.

        Args:
            selector: Selector used by this operation.

        Returns:
            The Element value produced by this operation.
        """
        element = await self.session.find_element(selector)
        check(element is not None, "Missing fixture element: " + selector)
        return element


async def navigation(tour: Tour) -> dict[str, Any]:
    """Navigation.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the navigation data.
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
    """Elements.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the elements data.
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
    await (await tour.element("#upload")).upload(str(ASSETS / "upload.txt"))
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
    check(shadow is not None, "open shadow root")
    child = await shadow.find_element("#shadow-text")
    check(
        child is not None and await child.text == "Inside shadow DOM", "shadow lookup"
    )
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
    """Waits.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the waits data.
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
    """Cookies.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the cookies data.
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
    """Windows.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the windows data.
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
    """Frames.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the frames data.
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
    """Alerts.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the alerts data.
    """
    s = tour.session
    # Schedule the prompt after this script returns so the WebDriver call can finish.
    await s.execute_script(
        "setTimeout(() => {document.querySelector('#prompt-result').textContent = prompt('Local demo prompt', '') || 'dismissed'}, 100)"
    )
    alert = await s.get_alert(timeout=3)
    check(alert is not None, "prompt appeared")
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
    """Scripts.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the scripts data.
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
    """Actions.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the actions data.
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
    """Artifacts.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the artifacts data.
    """
    s = tour.session
    capture = tour.output / "page.png"
    check(await s.save_screenshot(str(capture)), "PNG save returned false")
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
        check(await s.save_page(str(pdf)), "PDF save returned false")
        check(
            (await asyncio.to_thread(pdf.read_bytes)).startswith(b"%PDF"),
            "PDF signature",
        )
        files.append(pdf.name)
    if tour.browser == "firefox":
        full = tour.output / "full-page.png"
        check(await s.save_full_screenshot(str(full)), "Firefox full-page screenshot")
        check(
            (await asyncio.to_thread(full.read_bytes)).startswith(b"\x89PNG"),
            "full-page PNG signature",
        )
        files.append(full.name)
    return {"files": files, "notes": notes}


async def vendor(tour: Tour) -> dict[str, Any]:
    """Vendor.

    Args:
        tour: Active local-demo session and its fixture/output context.

    Returns:
        A mapping containing the vendor data.
    """
    s = tour.session
    if tour.browser in CHROMIUM:
        command = s.cache_cdp_cmd("demo-version", "Browser.getVersion")
        version = await s.execute_cdp_cmd(command)
        check(
            isinstance(version, dict) and "product" in version, "CDP Browser.getVersion"
        )
        original = await s.get_permission("geolocation")
        check(original is not None, "geolocation permission query")
        try:
            permission = await s.set_permission("geolocation", "denied")
            check(
                permission is not None and permission.state == "denied",
                "permission readback",
            )
        finally:
            await s.set_permission("geolocation", original.state)
        try:
            conditions = await s.set_network(
                offline=False, latency=10, download_throughput=1024 * 1024
            )
            check(conditions.latency == 10, "network emulation readback")
        finally:
            await s.reset_network()
        log_types = await s.log_types
        counts = {
            kind: len(await s.get_logs(kind)) for kind in log_types if kind == "browser"
        }
        return {
            "cdp_product": version["product"],
            "network_reset": True,
            "permission_restored": True,
            "log_counts": counts,
            "casting": "not invoked; requires explicit device selection",
        }
    if tour.browser == "firefox":
        check(await s.context == "content", "Firefox content context")
        addons = await s.install_addons(str(ASSETS / "firefox-addon"), temporary=True)
        try:
            check(len(addons) == 1, "temporary add-on installation")
            await s.refresh()

            async def addon_marker() -> Any:
                """Addon marker.

                Returns:
                    The Any value produced by this operation.
                """
                return await s.execute_script(
                    "return document.documentElement.dataset.aseleniumAddon === 'ready'"
                )

            check(
                await s.wait_for(addon_marker, timeout=3), "local add-on content script"
            )
        finally:
            for addon in addons:
                await s.uninstall_addon(addon)
        return {
            "content_context": True,
            "temporary_addons_removed": len(addons),
            "privileged_chrome_context": "not entered",
        }
    return {
        "safari_permissions": await s.permissions,
        "note": "Read-only Safari permission inspection; automation settings are never changed",
    }


async def drain_tasks(tasks: Sequence[asyncio.Task[Any]]) -> list[Any | BaseException]:
    """Own every task on Python 3.10 too; repeated cancellation cannot orphan cleanup.

    Args:
        tasks: Tasks owned by this operation and drained during teardown.

    Returns:
        The drain tasks values in order.
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
    """Concurrency.

    Args:
        driver: Driver object or downloaded driver artifact required by this operation.
        args: Validated command-line options for the selected browser workflow.
        url: URL used for the request or browser navigation.

    Returns:
        A mapping containing the concurrency data.
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

    async def worker(context: SessionContext, expected: int) -> tuple[str, str | None]:
        """Run one owned worker operation for the enclosing workflow.

        Args:
            context: Context used by this operation.
            expected: Expected result or configuration value used by the assertion.

        Returns:
            Run one owned worker operation for the enclosing workflow. None indicates that no value is available.
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
    """Cancellation.

    Args:
        driver: Driver object or downloaded driver artifact required by this operation.
        args: Validated command-line options for the selected browser workflow.
        url: URL used for the request or browser navigation.

    Returns:
        A mapping containing the cancellation data.
    """
    context = acquire_offline(driver, args)
    ready = asyncio.Event()

    async def worker() -> None:
        """Run one owned worker operation for the enclosing workflow."""
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
        report: Mutable run report updated with outcomes and diagnostic artifacts.
        name: Name identifying the requested item.
        operation: Operation performed by this helper; its result or failure is propagated.
    """
    started = perf_counter()
    entry = {"section": name}
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
    """Provision the browser and run the selected local HTML demo sections.

    Args:
        args: Validated command-line options for the selected browser workflow.
        url: URL used for the request or browser navigation.
        output: Directory for this run's report and captures.
        profile_source: Empty demonstration profile to clone, or None for a fresh profile.
        report: Mutable run report updated with outcomes and diagnostic artifacts.
    """
    driver = make_driver(args)
    try:

        async def manager_demo() -> dict[str, Any]:
            """Manager demo.

            Returns:
                A mapping containing the manager demo data.
            """
            result = await provision(driver, args)
            return asdict(result)

        await record(report, "driver-management", manager_demo())

        async def options_demo() -> dict[str, Any]:
            """Options demo.

            Returns:
                A mapping containing the options demo data.
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
                                # Each chapter can be selected independently and starts fresh.
                                """Chapter.

                                Args:
                                    name: Name identifying the requested item.

                                Returns:
                                    A mapping containing the chapter data.
                                """
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
    """Parse command-line arguments and run the requested program workflow.

    Args:
        argv: Command-line arguments; None reads the current process arguments.

    Returns:
        Process exit code; zero indicates the requested workflow completed successfully.
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
            """Install only.

            Returns:
                The InstallationResult value produced by this operation.
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
        print(json.dumps(asdict(result), indent=2))
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
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        print("Report: " + str(path))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
