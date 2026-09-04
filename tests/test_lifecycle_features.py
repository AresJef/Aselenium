"""Remaining offline service, facade, installation, and session-start contracts."""

from __future__ import annotations

import asyncio
from io import BytesIO
from json import dumps, loads
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import pytest

from aselenium import errors
from aselenium.chrome.options import ChromeOptions
from aselenium.chrome.service import ChromeService
from aselenium.chrome.webdriver import ChromeSessionContext
from aselenium.manager.driver import (
    ChromeDriverManager,
    DriverManager,
    FirefoxDriverManager,
)
from aselenium.manager.file import ChromeBinaryFile, ChromeDriverFile, File
from aselenium.manager.version import ChromiumVersion, FirefoxVersion
from aselenium.service import BaseService, ChromiumBaseService
from aselenium.session import Session
from aselenium.webdriver import ChromiumBaseWebDriver, WebDriver


@pytest.fixture
def executable(tmp_path: Path) -> Path:
    """Create an inert executable-path fixture that must never be launched.

    Args:
        tmp_path: Disposable directory supplied by pytest.

    Returns:
        Existing file used solely for constructor path validation.
    """
    path = tmp_path / "inert-driver"
    path.write_bytes(b"inert driver fixture; never execute")
    return path


def test_base_service_public_state_and_abstract_port_arguments(
    executable: Path,
) -> None:
    """Read initial service state and its explicit abstract port-argument contract.

    Args:
        executable: Existing inert driver-path fixture.
    """
    version = ChromiumVersion("120.0.1.2")
    service = BaseService(version, str(executable), timeout=2.5)
    assert service.driver_version is version
    assert service.driver_location == str(executable)
    assert service.timeout == 2.5
    assert service.process is None
    assert service.session is None
    assert service.process_running is False
    assert service.session_connectable is False
    assert service.port_connectable is False
    assert service.running is False
    with pytest.raises(NotImplementedError, match="port_args"):
        service.port_args
    service.timeout = 1
    assert service.timeout == 1


@pytest.mark.parametrize(
    "timeout", [0, -1, True, None, "1", float("inf"), float("nan")]
)
def test_service_timeout_invalid_update_preserves_current_value(
    executable: Path, timeout: Any
) -> None:
    """Reject invalid service deadlines without overwriting the existing budget.

    Args:
        executable: Existing inert driver-path fixture.
        timeout: Invalid timeout value.
    """
    service = BaseService(ChromiumVersion("120.0.1.2"), str(executable), timeout=2)
    with pytest.raises(errors.InvalidArgumentError):
        service.timeout = timeout
    assert service.timeout == 2


def test_service_port_allocation_skips_busy_and_reserved_ports(
    executable: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry occupied and already-reserved candidates, then retain one free port.

    Args:
        executable: Existing inert driver-path fixture.
        monkeypatch: Reversible patch fixture for socket-probing boundaries.
    """
    service = BaseService(ChromiumVersion("120.0.1.2"), str(executable))
    reserved = {41002}
    monkeypatch.setattr(BaseService, "_BaseService__PORTS", reserved)
    candidates = Mock(side_effect=[41001, 41002, 41003])
    probes = Mock(side_effect=[True, False, False])
    monkeypatch.setattr(service, "_free_port", candidates)
    monkeypatch.setattr(service, "_ping_port", probes)
    assert service.get_free_port() == 41003
    assert reserved == {41002, 41003}
    assert candidates.call_count == 3
    assert [call.args[0] for call in probes.call_args_list] == [41001, 41002, 41003]
    service._remove_port(41003)
    assert reserved == {41002}


def test_service_port_allocation_has_a_finite_retry_limit(
    executable: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop after one hundred occupied-port probes instead of looping forever.

    Args:
        executable: Existing inert driver-path fixture.
        monkeypatch: Reversible patch fixture for socket-probing boundaries.
    """
    service = BaseService(ChromiumVersion("120.0.1.2"), str(executable))
    monkeypatch.setattr(BaseService, "_BaseService__PORTS", set())
    candidates = Mock(return_value=41001)
    probes = Mock(return_value=True)
    monkeypatch.setattr(service, "_free_port", candidates)
    monkeypatch.setattr(service, "_ping_port", probes)
    with pytest.raises(errors.ServiceSocketError, match="Unable to allocate"):
        service.get_free_port()
    assert candidates.call_count == probes.call_count == 100
    assert BaseService._BaseService__PORTS == set()


def test_service_lazy_port_url_and_chromium_version(
    executable: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allocate one lazy port and keep URL, string, and Chromium metadata aligned.

    Args:
        executable: Existing inert driver-path fixture.
        monkeypatch: Reversible patch fixture for socket-probing boundaries.
    """
    version = ChromiumVersion("120.0.1.2")
    service = ChromiumBaseService(version, str(executable))
    monkeypatch.setattr(BaseService, "_BaseService__PORTS", set())
    candidates = Mock(return_value=41004)
    monkeypatch.setattr(service, "_free_port", candidates)
    monkeypatch.setattr(service, "_ping_port", Mock(return_value=False))
    assert service.url == "http://localhost:41004"
    assert service.port == 41004
    assert service.port_str == "41004"
    assert service.port_args == ["--port=41004"]
    assert service.driver_version is version
    assert service.url == "http://localhost:41004"
    candidates.assert_called_once_with()
    service._reset_port()
    assert BaseService._BaseService__PORTS == set()


@pytest.mark.parametrize(
    "process_alive,port_alive,client_closed,expected",
    [
        (True, True, False, True),
        (False, True, False, False),
        (True, False, False, False),
        (True, True, True, False),
    ],
)
def test_service_running_requires_process_socket_and_http_client(
    executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    process_alive: bool,
    port_alive: bool,
    client_closed: bool,
    expected: bool,
) -> None:
    """Require all three independently observable service-health components.

    Args:
        executable: Existing inert driver-path fixture.
        monkeypatch: Reversible patch fixture for the socket-probing boundary.
        process_alive: Simulated process liveness.
        port_alive: Simulated socket reachability.
        client_closed: Simulated HTTP-client closed state.
        expected: Expected aggregate service-health state.
    """
    service = BaseService(ChromiumVersion("120.0.1.2"), str(executable))
    process = SimpleNamespace(is_running=Mock(return_value=process_alive))
    client = SimpleNamespace(closed=client_closed)
    service._process = process
    service._session = client
    service._port = 41005
    monkeypatch.setattr(service, "_ping_port", Mock(return_value=port_alive))
    assert service.process is process
    assert service.session is client
    assert service.running is expected
    service._process = None
    service._session = None


class LifecycleResponse:
    """Supply one wire response or transport exception to a real Connection."""

    def __init__(self, payload: Any) -> None:
        """Store independently specified WebDriver response data.

        Args:
            payload: JSON-compatible response or exception to raise on entry.
        """
        self.payload = payload
        self.status = 200
        self.headers = {"Content-Type": "application/json"}

    async def __aenter__(self) -> LifecycleResponse:
        """Open the fake response or propagate its simulated transport failure.

        Returns:
            This response object.

        Raises:
            BaseException: If the supplied payload is a simulated exception.
        """
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the fake response without suppressing failures.

        Args:
            exc_type: Propagating exception type, if any.
            exc: Propagating exception instance, if any.
            traceback: Associated exception traceback, if any.
        """

    async def read(self) -> bytes:
        """Serialize the fixture as JSON bytes for the real protocol decoder.

        Returns:
            UTF-8 JSON response bytes.
        """
        return dumps(self.payload).encode("utf-8")


class LifecycleClient:
    """Record HTTP requests while serving an ordered in-memory response queue."""

    def __init__(self, responses: list[Any]) -> None:
        """Store responses and initialize an independent request log.

        Args:
            responses: Ordered response payloads or transport exceptions.
        """
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> LifecycleResponse:
        """Record the wire request and return the next queued fake response.

        Args:
            method: HTTP method requested by Connection.
            url: Driver URL or relative endpoint path.
            **kwargs: JSON body, headers, timeout, and redirect options.

        Returns:
            The next independently specified HTTP response.
        """
        self.calls.append((method, url, kwargs))
        return LifecycleResponse(self.responses.pop(0))


@pytest.mark.asyncio
async def test_session_start_is_idempotent_and_registers_default_window() -> None:
    """Exercise actual session creation, window caching, repeated starts, and quit."""
    client = LifecycleClient(
        [
            {"value": {"sessionId": "fixture/id", "capabilities": {}}},
            {"value": "window-1"},
            {"value": "window-1"},
            {"value": None},
        ]
    )
    service = SimpleNamespace(
        start=AsyncMock(), stop=AsyncMock(), session=client, running=True
    )
    session = Session(ChromeOptions(), service)
    first, second = await asyncio.gather(session.start(), session.start())
    try:
        assert first is second
        assert first.handle == "window-1"
        assert first.name == "default"
        assert session.id == "fixture/id"
        assert session.base_url == "/session/fixture%2Fid"
        service.start.assert_awaited_once_with()
        assert [(method, url) for method, url, _ in client.calls] == [
            ("POST", "/session"),
            ("GET", "/session/fixture%2Fid/window"),
            ("GET", "/session/fixture%2Fid/window"),
        ]
        payload = loads(client.calls[0][2]["data"])
        assert payload["capabilities"]["alwaysMatch"]["browserName"] == "chrome"
    finally:
        await session.quit()
    service.stop.assert_awaited_once_with()
    with pytest.raises(errors.InvalidSessionError, match="closed"):
        await session.start()


@pytest.mark.parametrize(
    "failure",
    [errors.ServiceStartError("fixture startup failure"), asyncio.CancelledError()],
)
@pytest.mark.asyncio
async def test_session_start_service_failure_or_cancellation_cleans_up(
    failure: BaseException,
) -> None:
    """Await service cleanup and preserve startup failures, including cancellation.

    Args:
        failure: Simulated service-start exception.
    """
    service = SimpleNamespace(start=AsyncMock(side_effect=failure), stop=AsyncMock())
    session = Session(ChromeOptions(), service)
    with pytest.raises(type(failure)) as captured:
        await session.start()
    assert captured.value is failure
    service.stop.assert_awaited_once_with()
    assert session._conn is None
    with pytest.raises(errors.InvalidSessionError, match="closed"):
        await session.start()


@pytest.mark.parametrize(
    "response,exception",
    [
        ({"value": {}}, errors.InvalidSessionError),
        (asyncio.CancelledError(), asyncio.CancelledError),
    ],
)
@pytest.mark.asyncio
async def test_session_start_handshake_failure_stops_owned_service(
    response: Any, exception: type[BaseException]
) -> None:
    """Tear down the service when the new-session handshake fails or is cancelled.

    Args:
        response: Invalid handshake payload or simulated transport cancellation.
        exception: Expected public failure type.
    """
    client = LifecycleClient([response])
    service = SimpleNamespace(
        start=AsyncMock(), stop=AsyncMock(), session=client, running=True
    )
    session = Session(ChromeOptions(), service)
    with pytest.raises(exception):
        await session.start()
    service.start.assert_awaited_once_with()
    service.stop.assert_awaited_once_with()
    assert len(client.calls) == 1
    assert session._conn is None


@pytest.mark.parametrize("facade_class", [WebDriver, ChromiumBaseWebDriver])
def test_base_facade_getters_return_constructor_owned_dependencies(
    facade_class: type[WebDriver], tmp_path: Path
) -> None:
    """Exercise base facade getters using concrete local browser dependencies.

    Args:
        facade_class: Base or Chromium-family facade implementation.
        tmp_path: Disposable manager cache directory.
    """
    driver = facade_class(
        ChromeDriverManager,
        ChromeService,
        ChromeOptions,
        ChromeSessionContext,
        directory=str(tmp_path),
    )
    try:
        assert driver.manager is driver._manager
        assert isinstance(driver.manager, ChromeDriverManager)
        assert driver.options is driver._options
        assert isinstance(driver.options, ChromeOptions)
    finally:
        driver.options.close()


@pytest.mark.asyncio
async def test_base_driver_manager_install_is_explicitly_abstract() -> None:
    """Require concrete managers to implement the installation operation."""
    manager = DriverManager("fixture", None, None, None)
    with pytest.raises(NotImplementedError, match="install"):
        await manager.install("fixture", option=True)


@pytest.mark.parametrize(
    "manager_class,version",
    [
        (ChromeDriverManager, ChromiumVersion("120.0.1.2")),
        (FirefoxDriverManager, FirefoxVersion("130.0.1")),
    ],
)
def test_manager_channel_and_browser_version_require_completed_state(
    manager_class: type[DriverManager], version: Any, tmp_path: Path
) -> None:
    """Reject premature result reads and return stored typed metadata afterward.

    Args:
        manager_class: Concrete browser driver-manager implementation.
        version: Expected browser-version value object.
        tmp_path: Disposable manager cache directory.
    """
    manager = manager_class(directory=str(tmp_path))
    with pytest.raises(errors.DriverInstallationError):
        manager.channel
    with pytest.raises(errors.DriverInstallationError):
        manager.browser_version
    manager._channel = "stable"
    manager._browser_version = version
    assert manager.channel == "stable"
    assert manager.browser_version is version
    manager.reset()
    with pytest.raises(errors.DriverInstallationError):
        manager.channel
    with pytest.raises(errors.DriverInstallationError):
        manager.browser_version


@pytest.mark.parametrize("artifact", ["driver", "binary"])
@pytest.mark.asyncio
async def test_public_manager_pin_protects_real_indexed_artifacts(
    artifact: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protect and unprotect real cache entries through DriverManager.pin.

    Args:
        artifact: Driver or browser-binary cache partition under test.
        tmp_path: Disposable manager cache directory.
        monkeypatch: Reversible platform-identity patch fixture.
    """
    manager = ChromeDriverManager(directory=str(tmp_path))
    monkeypatch.setattr(manager, "_DriverManager__os_name", "linux")
    monkeypatch.setattr(manager, "_DriverManager__os_arch", "64")
    monkeypatch.setattr(manager, "_DriverManager__os_is_arm", False)
    cache = manager._cache_view
    locations: list[Path] = []
    for version in ("120.0.1.2", "121.0.1.2"):
        data = BytesIO()
        name = "chromedriver" if artifact == "driver" else "chrome"
        with ZipFile(data, "w") as archive:
            archive.writestr(name, b"inert cached fixture")
        archive_class = ChromeDriverFile if artifact == "driver" else ChromeBinaryFile
        payload = archive_class(
            "linux", "https://example.invalid/archive.zip", data.getvalue()
        )
        cache_operation = (
            cache.cache_driver if artifact == "driver" else cache.cache_binary
        )
        result = cache_operation(ChromiumVersion(version), payload)
        locations.append(Path(result["location"]))
    await manager.pin("120.0.1.2", artifact=artifact)
    cache.prune(kind=artifact, limit=1)
    assert locations[0].is_file()
    assert locations[1].is_file()
    await manager.pin("120.0.1.2", artifact=artifact, pinned=False)
    with cache._db() as database:
        row = database.execute(
            "SELECT pinned FROM artifacts WHERE version=?", ("120.0.1.2",)
        ).fetchone()
    assert row[0] == 0
    cache.prune(kind=artifact, limit=1)
    assert not locations[0].exists()
    assert locations[1].is_file()


@pytest.mark.parametrize("artifact", ["unknown", "", None])
@pytest.mark.asyncio
async def test_public_manager_pin_rejects_unknown_artifacts(
    artifact: Any, tmp_path: Path
) -> None:
    """Reject unknown artifact kinds before changing the cache index.

    Args:
        artifact: Unsupported artifact selector.
        tmp_path: Disposable manager cache directory.
    """
    manager = ChromeDriverManager(directory=str(tmp_path))
    with pytest.raises(
        errors.InvalidArgumentError, match="Unsupported cached artifact"
    ):
        await manager.pin("120.0.1.2", artifact=artifact)


@pytest.mark.asyncio
async def test_public_manager_pin_rejects_managers_without_cache() -> None:
    """Reject pinning on system-managed driver configurations with no cache."""
    manager = DriverManager("fixture", None, None, None)
    with pytest.raises(
        errors.InvalidArgumentError, match="Unsupported cached artifact"
    ):
        await manager.pin("120.0.1.2")


@pytest.mark.parametrize("name", ["driver", "browser", "fixture-名字"])
def test_downloaded_file_name_preserves_the_supplied_label(name: str) -> None:
    """Return archive identity labels without consuming the downloaded payload.

    Args:
        name: Caller-supplied archive identity label.
    """
    file = File(name, "linux", "https://example.invalid/archive.zip", b"fixture")
    assert file.name == name
    assert file._content == b"fixture"
