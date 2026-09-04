"""Positive consumer contracts, checked against the installed typed distribution."""

from __future__ import annotations

from typing import Literal

from typing_extensions import assert_type

from aselenium import (
    Actions,
    Chrome,
    ChromeSession,
    Cookie,
    Edge,
    EdgeOptions,
    Element,
    Firefox,
    FirefoxSession,
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
