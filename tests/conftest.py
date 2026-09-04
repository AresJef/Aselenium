"""Offline, disposable isolation for the driver-management test suite.

The guards raise BaseException rather than Exception because several existing
manager helpers swallow arbitrary Exception subclasses. An accidental real
request/process must fail loudly, even while testing a known failure.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from aselenium import service as service_module
from aselenium.manager import _cache as cache_module
from aselenium.manager import driver as driver_module


class UnexpectedExternalOperation(BaseException):
    """A test attempted unmocked network access or an executable probe."""


@pytest.fixture(autouse=True)
def isolated_manager_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Use disposable caches and reset lazily loaded compatibility data.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    monkeypatch.setattr(cache_module, "expanduser", lambda path: str(tmp_path))
    monkeypatch.setattr(driver_module.FirefoxDriverManager, "_GECKODRIVER_TABLE", None)
    monkeypatch.setattr(
        driver_module.FirefoxDriverManager, "_GECKODRIVER_MAX_VERSION", None
    )
    monkeypatch.setattr(
        driver_module.FirefoxDriverManager, "_GECKODRIVER_TABLE_MAX_VERSION", None
    )


@pytest.fixture(autouse=True)
def forbid_external_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default tests may neither use the network nor launch installed browsers.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """

    def blocked(*args: Any, **kwargs: Any) -> None:
        """Blocked.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        raise UnexpectedExternalOperation(
            "Mock network/process operations in manager tests"
        )

    async def blocked_request(*args: Any, **kwargs: Any) -> None:
        """Blocked request.

        Args:
            *args: Fixture or parametrized args input for this regression.
            **kwargs: Fixture or parametrized kwargs input for this regression.
        """
        blocked()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", blocked_request)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(driver_module, "Popen", blocked)
    monkeypatch.setattr(service_module, "Popen", blocked)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", blocked_request)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", blocked_request)
