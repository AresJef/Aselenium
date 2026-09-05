"""Minimal real-world Aselenium example using Google and managed ChromeDriver.

The example needs Chrome and Internet access. Driver metadata or artifacts may
be downloaded during provisioning; the acquired browser session then resolves
from the populated cache without another vendor request.
"""

from __future__ import annotations

import asyncio

from aselenium import Chrome


async def main() -> None:
    """Provision ChromeDriver, visit Google, and release all owned resources.

    The browser remains open for five seconds after printing the current URL and
    title. The options-owned temporary data is closed even when provisioning,
    session creation, navigation, or inspection fails.

    Example:
        Run the complete real-world example from an asynchronous program:

        >>> await main()  # doctest: +SKIP
    """
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
