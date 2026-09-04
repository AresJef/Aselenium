"""Offline, disposable isolation for the driver-management test suite.

The guards raise BaseException rather than Exception because several existing
manager helpers swallow arbitrary Exception subclasses. An accidental real
request/process must fail loudly, even while testing a known failure.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from aselenium import service as service_module
from aselenium.manager import driver as driver_module

_SOCKET_CONNECT = socket.socket.connect
_SOCKET_CONNECT_EX = socket.socket.connect_ex


class UnexpectedExternalOperation(BaseException):
    """A test attempted unmocked network access or an executable probe."""


@pytest.fixture(autouse=True)
def isolated_manager_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Use disposable caches and reset lazily loaded compatibility data.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(driver_module.FirefoxDriverManager, "_GECKODRIVER_TABLE", None)
    monkeypatch.setattr(
        driver_module.FirefoxDriverManager, "_GECKODRIVER_MAX_VERSION", None
    )
    monkeypatch.setattr(
        driver_module.FirefoxDriverManager, "_GECKODRIVER_TABLE_MAX_VERSION", None
    )


@pytest.fixture(autouse=True)
def forbid_external_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default tests may neither use external networks nor launch browsers.

    Windows' default asyncio event loop implements ``socketpair()`` with a
    private IPv4 loopback connection. Permit loopback at the lowest socket layer
    on Windows so pytest-asyncio can create its own control sockets; higher-level
    HTTP and connection helpers remain blocked unless a test replaces them with
    an exact fixture allowlist.

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

    def guarded_connect(sock: socket.socket, target: Any) -> Any:
        """Permit only the loopback connect required by Windows event loops.

        Args:
            sock: Socket attempting the connection.
            target: Address passed to ``socket.connect``.

        Returns:
            The original socket result for an allowed Windows loopback target.
        """
        if (
            sys.platform == "win32"
            and isinstance(target, tuple)
            and target
            and target[0] in {"127.0.0.1", "::1", "localhost"}
        ):
            return _SOCKET_CONNECT(sock, target)
        blocked()

    def guarded_connect_ex(sock: socket.socket, target: Any) -> int:
        """Permit only Windows event-loop loopback ``connect_ex`` calls.

        Args:
            sock: Socket attempting the connection.
            target: Address passed to ``socket.connect_ex``.

        Returns:
            The original socket status for an allowed Windows loopback target.
        """
        if (
            sys.platform == "win32"
            and isinstance(target, tuple)
            and target
            and target[0] in {"127.0.0.1", "::1", "localhost"}
        ):
            return _SOCKET_CONNECT_EX(sock, target)
        blocked()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", blocked_request)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(driver_module, "Popen", blocked)
    monkeypatch.setattr(service_module, "Popen", blocked)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", blocked_request)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", blocked_request)
