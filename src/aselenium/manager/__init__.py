# -*- coding: UTF-8 -*-
"""Public exports for the aselenium.manager package."""

from aselenium.manager.driver import (
    ChromeDriverManager,
    ChromiumDriverManager,
    EdgeDriverManager,
    FirefoxDriverManager,
    SafariDriverManager,
)
from aselenium.manager.version import (
    ChromiumVersion,
    FirefoxVersion,
    GeckoVersion,
    SafariVersion,
)

__all__ = [
    # Driver Manager
    "EdgeDriverManager",
    "ChromeDriverManager",
    "ChromiumDriverManager",
    "FirefoxDriverManager",
    "SafariDriverManager",
    # Version
    "ChromiumVersion",
    "FirefoxVersion",
    "GeckoVersion",
    "SafariVersion",
]
