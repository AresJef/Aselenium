"""Public exports for the aselenium.manager package."""

from aselenium.manager._installation import InstallationRequest, InstallationResult
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
    # Installation
    "InstallationRequest",
    "InstallationResult",
    # Version
    "ChromiumVersion",
    "FirefoxVersion",
    "GeckoVersion",
    "SafariVersion",
]
