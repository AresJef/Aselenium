"""Shared driver provisioning for the local HTML and Google website demos.

These helpers do not start a fixture server or a browser on import.
They use only the public Aselenium facade/manager APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from aselenium import (
    Chrome,
    Chromium,
    Edge,
    Firefox,
    Safari,
    WebDriver,
)

if TYPE_CHECKING:
    import argparse

    from aselenium.manager._installation import InstallationResult
    from aselenium.webdriver import SessionContext

BROWSERS = {
    "chrome": Chrome,
    "chromium": Chromium,
    "edge": Edge,
    "firefox": Firefox,
    "safari": Safari,
}
CHROMIUM = {"chrome", "chromium", "edge"}


def json_default(value: object) -> str:
    """Convert a retained path only when it reaches a JSON boundary.

    Args:
        value: Object rejected by JSON's built-in encoders.

    Returns:
        Native filesystem text when ``value`` is a :class:`pathlib.Path`.

    Raises:
        TypeError: ``value`` is not a :class:`pathlib.Path`.

    Example:
        >>> json_default(Path("report.json"))
        'report.json'
    """
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def make_driver(args: argparse.Namespace) -> WebDriver:
    """Create the browser facade selected by parsed demo arguments.

    Non-Safari facades receive the dedicated demo cache and conservative
    provisioning timeouts. Safari uses its system-managed driver and therefore
    receives only the service-start timeout. The Firefox facade normalizes a
    supplied profile root once and retains the resulting path for acquisitions.

    Args:
        args: Parsed demo arguments. The namespace must provide ``browser`` and,
            except for Safari, ``cache_dir``. ``session_timeout`` and
            ``profile_root`` are honored when present.

    Returns:
        A new browser-specific :class:`~aselenium.webdriver.WebDriver` facade.

    Raises:
        KeyError: The browser name is not present in :data:`BROWSERS`.
        OSError: The dedicated cache directory cannot be created.
    """
    # The local tour exposes one explicit session-start budget. Apply it to
    # both service readiness and WebDriver session creation so a cold native
    # service cannot fail at the facade's shorter default first. The install
    # command and Google demo have no such setting and retain the package
    # default.
    service_timeout = getattr(args, "session_timeout", 10)
    if args.browser == "safari":
        # Safari has no download/cache constructor parameters.
        return Safari(service_timeout=service_timeout)
    cache = args.cache_dir.expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "directory": cache,
        "max_cache_size": None,
        "request_timeout": 20,
        "download_timeout": 90,
        "service_timeout": service_timeout,
    }
    profile_root = getattr(args, "profile_root", None)
    if args.browser == "firefox" and profile_root is not None:
        # Preserve the Path value; Firefox normalizes it once at its facade boundary.
        kwargs["profile_root"] = profile_root
    return BROWSERS[args.browser](
        **kwargs,
    )


def install_arguments(args: argparse.Namespace) -> dict[str, Any]:
    """Build browser-appropriate driver installation arguments.

    The result always carries the optional browser executable. Chrome, Edge,
    and Safari also receive their selected release channel. Non-Safari browsers
    receive either the explicitly requested version or the demo's browser-
    appropriate compatibility selector.

    Args:
        args: Parsed demo arguments containing ``browser``, ``binary``, and any
            supported ``channel`` or ``version`` values.

    Returns:
        Keyword arguments suitable for ``install_result()`` or ``acquire()``.
    """
    kwargs = {"binary": args.binary}
    if args.browser in {"chrome", "edge", "safari"}:
        kwargs["channel"] = args.channel
    if args.browser != "safari":
        kwargs["version"] = getattr(args, "version", None) or (
            "auto" if args.browser == "firefox" else "build"
        )
    return kwargs


async def provision(driver: WebDriver, args: argparse.Namespace) -> InstallationResult:
    """Resolve a compatible driver and optionally change its cache pin.

    Offline resolution is the default. When downloads are allowed, Chromium
    browsers use compatible-build resolution and Firefox uses its cached-
    compatible policy; an explicit version plus download permission switches to
    exact resolution. Safari always performs system-only discovery.
    Compatibility validation is enabled for every browser.

    Args:
        driver: Browser facade whose manager performs installation or discovery.
        args: Parsed demo arguments controlling browser selection, download
            permission, policy, version, and optional pinning.

    Returns:
        The immutable installation result for this provisioning call.
    """
    policy = getattr(args, "policy", None)
    if policy is None:
        policy = (
            ("cached-compatible" if args.browser == "firefox" else "compatible-build")
            if args.allow_download
            else "offline"
        )
        if args.allow_download and getattr(args, "version", None):
            policy = "exact"
    if args.browser == "safari":
        policy = "offline"  # System lookup only; Safari never downloads an executable.
    result = await driver.manager.install_result(
        **install_arguments(args), policy=policy, validate_compatibility=True
    )
    if args.browser != "safari" and (
        getattr(args, "pin", False) or getattr(args, "unpin", False)
    ):
        await driver.manager.pin(result.driver_version, pinned=not args.unpin)
    return result


def acquire_offline(driver: WebDriver, args: argparse.Namespace) -> SessionContext:
    """Create a session context that performs no vendor download requests.

    Non-Safari browsers receive the ``offline`` version selector. Safari uses
    system discovery and receives only its browser/channel arguments. Entering
    the returned context, rather than this function, launches the browser.

    Args:
        driver: Browser facade used to acquire the session.
        args: Parsed demo arguments containing browser, binary, and channel data.

    Returns:
        A single-use asynchronous context for an offline-resolved session.
    """
    kwargs = install_arguments(args)
    if args.browser != "safari":
        kwargs["version"] = "offline"
    return driver.acquire(**kwargs)
