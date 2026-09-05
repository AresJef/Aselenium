"""Shared driver provisioning for the local HTML and Google website demos.

These helpers do not start a fixture server or a browser on import.
They use only the public Aselenium facade/manager APIs.
"""

from __future__ import annotations

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


def make_driver(args: argparse.Namespace) -> WebDriver:
    """Create the selected browser facade using the dedicated demo cache.

    Args:
        args: Validated command-line options for the selected browser workflow.

    Returns:
        The WebDriver value produced by this operation.
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
        # Preserve the Path value; FirefoxService owns parsing and validation.
        kwargs["profile_root"] = profile_root
    return BROWSERS[args.browser](
        **kwargs,
    )


def install_arguments(args: argparse.Namespace) -> dict[str, Any]:
    """Do not forward Chromium-only selectors to Firefox/Safari.

    Args:
        args: Validated command-line options for the selected browser workflow.

    Returns:
        A mapping containing the install arguments data.
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
    """Step one: retain the immutable per-call result, not mutable manager state.

    Args:
        driver: Driver object or downloaded driver artifact required by this operation.
        args: Validated command-line options for the selected browser workflow.

    Returns:
        The InstallationResult value produced by this operation.
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
    """Every browser launch reuses the provisioned cache without vendor requests.

    `run` resolves a compatible cached pair, not an exact numeric version. Exact
    driver installation/pinning is a separate `install` example.

    Args:
        driver: Driver object or downloaded driver artifact required by this operation.
        args: Validated command-line options for the selected browser workflow.

    Returns:
        The SessionContext value produced by this operation.
    """
    kwargs = install_arguments(args)
    if args.browser != "safari":
        kwargs["version"] = "offline"
    return driver.acquire(**kwargs)
