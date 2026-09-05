"""Opt-in live Chrome/Edge smoke using only a disposable cache/profile and data URL.

No personal profile is configured. Vendor downloads occur only with the explicit
--allow-download flag; this script is not collected by the offline test suite.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import tempfile
import time
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote

from aselenium import Chrome, Edge

HTML = """<!doctype html><title>Aselenium local fixture</title>
<input id='input'><button id='button' onclick="this.textContent='clicked'">click</button>
<div id='host'></div><iframe id='frame' srcdoc="<p id='inside'>frame</p>"></iframe>
<div id='hidden' style='display:none'>hidden text</div>
<div id='zero' style='width:0;height:0;overflow:hidden'>zero</div>
<div id='offscreen' style='position:fixed;left:-1000px;top:0'>offscreen</div>
<div id='covered' style='position:fixed;left:400px;top:50px;width:100px;height:40px'>covered</div>
<div id='overlay' style='position:fixed;left:400px;top:50px;width:100px;height:40px;background:white'>overlay</div>
<script>document.querySelector('#host').attachShadow({mode:'open'}).innerHTML='<span id="shadow">shadow</span>';</script>"""
T = TypeVar("T")


def require(condition: bool, label: str) -> None:
    """Fail explicitly when an acceptance condition is false.

    Unlike an ``assert`` statement, this check remains active when Python runs
    with optimization enabled.

    Args:
        condition: Evaluated acceptance condition.
        label: Short description included in the failure.

    Raises:
        AssertionError: The condition is false.
    """
    if not condition:
        raise AssertionError(f"Smoke-test condition failed: {label}")


def require_value(value: T | None, label: str) -> T:
    """Return a required smoke-test value or fail with useful context.

    Args:
        value: Optional value returned by a public lookup API.
        label: Short description included in the assertion failure.

    Returns:
        The non-None value.

    Raises:
        AssertionError: The required value is None.
    """
    if value is None:
        raise AssertionError(f"Missing required smoke-test value: {label}")
    return value


async def smoke(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Run the opt-in browser smoke checks against a local data-URL fixture.

    Args:
        args: Validated command-line options for the selected browser workflow.
        root: Anchored root directory of the managed filesystem operation.

    Returns:
        A mapping containing the smoke data.
    """
    facade = (Chrome if args.browser == "chrome" else Edge)(
        directory=root, download_timeout=60
    )
    facade.options.add_arguments(
        "--headless=new",
        "--disable-background-networking",
        "--no-first-run",
        "--disable-default-apps",
        "--disable-sync",
    )
    timings = []
    for attempt in range(2):
        started = time.monotonic()
        selector = "build" if args.allow_download and attempt == 0 else "offline"
        async with facade.acquire(selector, binary=args.binary) as session:
            provisioned = time.monotonic()
            await session.load("data:text/html;charset=utf-8," + quote(HTML))
            require(await session.title == "Aselenium local fixture", "fixture title")
            await session.set_timeouts(implicit=0)
            hidden = require_value(await session.find_element("#hidden"), "#hidden")
            require(await hidden.dom_text == "hidden text", "hidden DOM text")
            for selector_id in ("#hidden", "#zero", "#offscreen"):
                target = require_value(
                    await session.find_element(selector_id), selector_id
                )
                require(not await target.in_viewport, selector_id + " viewport state")
                require(not await target.unobscured, selector_id + " hit-test state")
            covered = require_value(await session.find_element("#covered"), "#covered")
            require(await covered.in_viewport, "covered element viewport state")
            require(not await covered.unobscured, "covered element hit-test state")
            host = require_value(await session.find_element("#host"), "#host")
            shadow = require_value(await host.shadow, "#host shadow root")
            shadow_target = require_value(
                await shadow.find_element("#shadow"), "#shadow"
            )
            require(await shadow_target.unobscured, "shadow element hit-test state")
            require(
                await session.save_screenshot(root / "capture.png"),
                "screenshot save",
            )
            require(
                (root / "capture.png").read_bytes().startswith(b"\x89PNG"),
                "screenshot signature",
            )
            require(await session.save_page(root / "page.pdf"), "PDF save")
            require(
                (root / "page.pdf").read_bytes().startswith(b"%PDF"),
                "PDF signature",
            )
            element = require_value(
                await session.find_1st_element("#missing", "#input"), "#input"
            )
            await element.send("local fixture")
            await element.click()
            await session.actions().send_keys("-actions").perform()
            require(
                await element.get_property("value") == "local fixture-actions",
                "action input value",
            )
            button = require_value(await session.find_element("#button"), "#button")
            await button.click()
            require(await button.text == "clicked", "button click")
            host = require_value(await session.find_element("#host"), "#host")
            shadow = require_value(await host.shadow, "#host shadow root")
            shadow_target = require_value(
                await shadow.find_element("#shadow"), "#shadow"
            )
            require(await shadow_target.text == "shadow", "shadow text")
            require(await session.switch_frame("#frame", timeout=2), "frame switch")
            inside = require_value(await session.find_element("#inside"), "#inside")
            require(await inside.text == "frame", "frame text")
            require(await session.default_frame(), "default-frame restoration")
            require(
                (await session.take_screenshot()).startswith(b"\x89PNG"),
                "in-memory screenshot signature",
            )
            async with session.transaction():
                require(
                    await session.wait_for(lambda: button.text, timeout=1) == "clicked",
                    "transaction wait result",
                )
            original = require_value(await session.active_window, "active window")
            await session.new_window("extra")
            await session.load("data:text/html,<title>Extra local window</title>")
            require(await session.title == "Extra local window", "new-window title")
            await session.close_window(switch_to=original)
            await session.switch_window(original)
            require(
                await session.title == "Aselenium local fixture",
                "original-window title",
            )
            timings.append(
                dict(
                    mode=selector,
                    acquisition_seconds=provisioned - started,
                    work_seconds=time.monotonic() - provisioned,
                )
            )
        timings[-1]["including_teardown_seconds"] = time.monotonic() - started
    result = require_value(facade.manager.last_result, "installation result")
    driver_version = require_value(result.driver_version, "driver version")
    identity = await asyncio.to_thread(
        facade.manager._read_from_cmd, [str(result.driver_location), "--version"]
    )
    require(driver_version in identity, "driver executable identity")
    return dict(
        browser=args.browser,
        browser_version=result.browser_version,
        driver_version=driver_version,
        driver_identity=identity.strip(),
        driver_sha256=hashlib.sha256(result.driver_location.read_bytes()).hexdigest(),
        python=platform.python_version(),
        platform=platform.platform(),
        machine=platform.machine(),
        timings=timings,
        fixture="data URL only; private profiles; cache deleted on completion",
    )


def main() -> None:
    """Parse command-line arguments and run the requested program workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=("chrome", "edge"), default="chrome")
    parser.add_argument("--binary", required=True)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aselenium-live-smoke-") as directory:
        result = asyncio.run(
            asyncio.wait_for(smoke(args, Path(directory)), timeout=180)
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
