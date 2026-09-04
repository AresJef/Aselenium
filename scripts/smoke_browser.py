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
from typing import Any
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


async def smoke(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Run the opt-in browser smoke checks against a local data-URL fixture.

    Args:
        args: Validated command-line options for the selected browser workflow.
        root: Anchored root directory of the managed filesystem operation.

    Returns:
        A mapping containing the smoke data.
    """
    facade = (Chrome if args.browser == "chrome" else Edge)(
        directory=str(root), download_timeout=60
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
            assert await session.title == "Aselenium local fixture"
            await session.set_timeouts(implicit=0)
            hidden = await session.find_element("#hidden")
            assert await hidden.dom_text == "hidden text"
            for selector_id in ("#hidden", "#zero", "#offscreen"):
                target = await session.find_element(selector_id)
                assert not await target.in_viewport
                assert not await target.unobscured
            covered = await session.find_element("#covered")
            assert await covered.in_viewport
            assert not await covered.unobscured
            host = await session.find_element("#host")
            shadow_target = await (await host.shadow).find_element("#shadow")
            assert await shadow_target.unobscured
            assert await session.save_screenshot(str(root / "capture.png"))
            assert (root / "capture.png").read_bytes().startswith(b"\x89PNG")
            assert await session.save_page(str(root / "page.pdf"))
            assert (root / "page.pdf").read_bytes().startswith(b"%PDF")
            element = await session.find_1st_element("#missing", "#input")
            assert element is not None
            await element.send("local fixture")
            await element.click()
            await session.actions().send_keys("-actions").perform()
            assert await element.get_property("value") == "local fixture-actions"
            button = await session.find_element("#button")
            await button.click()
            assert await button.text == "clicked"
            host = await session.find_element("#host")
            shadow = await host.shadow
            assert await (await shadow.find_element("#shadow")).text == "shadow"
            assert await session.switch_frame("#frame", timeout=2)
            assert await (await session.find_element("#inside")).text == "frame"
            assert await session.default_frame()
            assert (await session.take_screenshot()).startswith(b"\x89PNG")
            async with session.transaction():
                assert (
                    await session.wait_for(lambda: button.text, timeout=1) == "clicked"
                )
            original = await session.active_window
            await session.new_window("extra")
            await session.load("data:text/html,<title>Extra local window</title>")
            assert await session.title == "Extra local window"
            await session.close_window(switch_to=original)
            await session.switch_window(original)
            assert await session.title == "Aselenium local fixture"
            timings.append(
                dict(
                    mode=selector,
                    acquisition_seconds=provisioned - started,
                    work_seconds=time.monotonic() - provisioned,
                )
            )
        timings[-1]["including_teardown_seconds"] = time.monotonic() - started
    result = facade.manager.last_result
    identity = await asyncio.to_thread(
        facade.manager._read_from_cmd, [result.driver_location, "--version"]
    )
    assert result.driver_version in identity
    return dict(
        browser=args.browser,
        browser_version=result.browser_version,
        driver_version=result.driver_version,
        driver_identity=identity.strip(),
        driver_sha256=hashlib.sha256(
            Path(result.driver_location).read_bytes()
        ).hexdigest(),
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
