"""Minimal real-world Aselenium navigation example."""

from __future__ import annotations

import asyncio

from aselenium import Chrome


async def main() -> None:
    """Provision Chrome, open Google for five seconds, and clean up."""
    driver = Chrome()
    driver.options.set_timeouts(implicit=0, pageLoad=20, script=5)
    driver.options.session_timeout = 30

    try:
        result = await driver.manager.install_result(
            version="build",
            policy="compatible-build",
            validate_compatibility=True,
        )
        print("Driver:", result.driver_version)
        print("Browser:", result.browser_version)

        async with driver.acquire(version="offline") as session:
            await session.load("https://www.google.com/")
            print("URL:", await session.url)
            print("Title:", await session.title)
            await asyncio.sleep(5)
    finally:
        driver.options.close()


if __name__ == "__main__":
    asyncio.run(main())
