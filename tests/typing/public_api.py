"""Positive consumer contracts, checked against the installed typed distribution."""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Literal

from typing_extensions import assert_type

from aselenium import (
    Actions,
    Chrome,
    ChromeDriverManager,
    ChromeSession,
    ChromiumProfile,
    Cookie,
    Edge,
    EdgeOptions,
    Element,
    Firefox,
    FirefoxAddon,
    FirefoxProfile,
    FirefoxSession,
    InstallationResult,
    Safari,
    SafariSession,
    Session,
)


async def common_usage(session: Session) -> None:
    """Check asynchronous lookups, collections, transactions and output types.

    Args:
        session: Session supplied by the application.
    """
    assert_type(await session.find_element("#input"), Element | None)
    assert_type(await session.find_elements("input"), list[Element])
    assert_type(await session.find_1st_element("#missing", "#input"), Element | None)
    assert_type(await session.cookies, list[Cookie])
    assert_type(await session.title, str)
    assert_type(session.actions(), Actions)
    async with session.transaction():
        element = await session.find_element("#input")
        if element is not None:
            assert_type(element, Element)
            await element.send("typed consumer")
    assert_type(await session.take_screenshot(), bytes)


async def path_usage(
    session: Session, element: Element, path: str | PathLike[str]
) -> None:
    """Keep public filesystem inputs broad and retained locations Path-valued.

    Args:
        session: Session exposing page output and retained executable locations.
        element: Element exposing upload and screenshot filesystem boundaries.
        path: Text or string-valued path-like input supplied by a consumer.
    """
    assert_type(await session.save_screenshot(path), bool)
    assert_type(await session.save_page(path), bool)
    assert_type(await element.save_screenshot(path), bool)
    await element.upload(path)
    assert_type(session.driver_location, Path)
    assert_type(session.browser_location, Path | None)
    if isinstance(session, FirefoxSession):
        assert_type(await session.save_full_screenshot(path), bool)
        assert_type(await session.install_addons(path), list[FirefoxAddon])


async def manager_path_usage(
    manager: ChromeDriverManager, path: str | PathLike[str]
) -> None:
    """Preserve Path inputs and outputs across installed manager annotations.

    Args:
        manager: Concrete manager whose binary override is statically typed.
        path: Text or string-valued path-like browser executable override.
    """
    assert_type(await manager.install(binary=path), Path)
    assert_type(await manager.install_result(binary=path), InstallationResult)
    assert_type(manager.last_result, InstallationResult | None)


def path_configuration_usage(path: str | PathLike[str]) -> None:
    """Check profile, option, and manager path contracts from an installed wheel.

    Args:
        path: Existing consumer-controlled directory or executable location.
    """
    profile = ChromiumProfile(path, "Default")
    assert_type(profile.directory, Path)
    firefox_profile = FirefoxProfile(path)
    assert_type(firefox_profile.directory, Path)
    manager = ChromeDriverManager(directory=path)
    assert_type(manager.driver_location, Path)
    assert_type(manager.browser_location, Path)
    edge = Edge(directory=path)
    edge.options.browser_location = path
    assert_type(edge.options.browser_location, Path | None)


async def vendor_usage() -> None:
    """Preserve concrete browser session types through acquisition contexts."""
    chrome = Chrome()
    try:
        async with chrome.acquire() as session:
            assert_type(session, ChromeSession)
            await common_usage(session)
    finally:
        chrome.options.close()
    firefox = Firefox()
    try:
        async with firefox.acquire() as firefox_session:
            assert_type(firefox_session, FirefoxSession)
            assert_type(await firefox_session.context, Literal["content", "chrome"])
    finally:
        firefox.options.close()
    safari = Safari()
    try:
        async with safari.acquire() as safari_session:
            assert_type(safari_session, SafariSession)
            assert_type(await safari_session.permissions, dict[str, bool])
            assert_type(
                await safari_session.get_permission("getUserMedia"), bool | None
            )
    finally:
        safari.options.close()
    edge = Edge()
    try:
        assert_type(edge.options, EdgeOptions)
        edge.options.use_webview = False
    finally:
        edge.options.close()


def firefox_profile_root_usage(profile_root: str | PathLike[str]) -> None:
    """Accept standard text/path-like profile roots through the public facade.

    Args:
        profile_root: Existing directory visible to Firefox and GeckoDriver.
    """
    first = Firefox(profile_root=profile_root)
    second = Firefox(profile_root=Path("shared-firefox-profiles"))
    first.options.close()
    second.options.close()
