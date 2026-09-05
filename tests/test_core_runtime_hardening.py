"""Regressions for path retention, identity equality, and strict value validation."""

from __future__ import annotations

from contextlib import nullcontext
from inspect import signature
from pathlib import Path
from plistlib import dumps as plist_dumps
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

import aselenium
from aselenium import _paths as paths_module
from aselenium import errors
from aselenium import service as service_module
from aselenium.alert import Alert
from aselenium.chrome.session import ChromeSession
from aselenium.chromium.session import ChromiumSession
from aselenium.connection import Connection
from aselenium.edge.session import EdgeSession
from aselenium.element import Element
from aselenium.firefox.options import FirefoxOptions
from aselenium.firefox.utils import encode_dir_to_firefox_wire_protocol
from aselenium.manager.file import File
from aselenium.manager.version import ChromiumVersion
from aselenium.options import Profile
from aselenium.safari.session import SafariSession
from aselenium.service import BaseService, ChromiumBaseService
from aselenium.session import DevToolsCMD, JavaScript, Network, Session, Window
from aselenium.utils import load_plist_file


class SingleUsePath:
    """Expose a filesystem path exactly once to detect accidental reparsing."""

    def __init__(self, value: Path) -> None:
        """Store the filesystem value without converting it to text.

        Args:
            value: Existing path returned by the first protocol access.
        """
        self.value = value
        self.calls = 0

    def __fspath__(self) -> str:
        """Return path text once and reject a second protocol access.

        Returns:
            Native path text on the first call.

        Raises:
            AssertionError: The workflow asks to parse the input again.
        """
        self.calls += 1
        if self.calls != 1:
            raise AssertionError("path-like input was parsed more than once")
        return str(self.value)


def test_firefox_profile_retains_path_after_public_boundary(tmp_path: Path) -> None:
    """Avoid reparsing a profile path while scanning and encoding its clone.

    Args:
        tmp_path: Isolated directory used as a minimal Firefox profile.
    """
    source = tmp_path / "profile"
    source.mkdir()
    (source / "prefs.js").write_text("// fixture", encoding="utf-8")
    supplied = SingleUsePath(source)
    options = FirefoxOptions()
    try:
        profile = options.set_profile(supplied)
        assert profile.directory == source
        assert profile.encode
        assert supplied.calls == 1
    finally:
        options.close()


def test_plist_public_boundary_parses_pathlike_once(tmp_path: Path) -> None:
    """Parse a public plist path once before retaining its ``Path`` internally.

    Args:
        tmp_path: Isolated directory containing valid property-list metadata.
    """
    path = tmp_path / "Info.plist"
    path.write_bytes(plist_dumps({"CFBundleShortVersionString": "17.4"}))
    supplied = SingleUsePath(path)

    assert load_plist_file(supplied)["CFBundleShortVersionString"] == "17.4"
    assert supplied.calls == 1


@pytest.mark.parametrize(
    "values",
    [
        {"offline": 1},
        {"latency": True},
        {"upload_throughput": False},
        {"download_throughput": True},
    ],
)
def test_network_rejects_boolean_numeric_substitutes(values: dict[str, object]) -> None:
    """Do not accept booleans in integer fields or coerce integers to bool.

    Args:
        values: One invalid network-emulation constructor argument.
    """
    with pytest.raises(errors.InvalidArgumentError):
        Network(**values)


@pytest.mark.parametrize(
    "duration", [True, False, float("nan"), float("inf"), float("-inf")]
)
def test_scroll_pause_rejects_boolean_and_nonfinite_durations(
    duration: object,
) -> None:
    """Reject values that cannot form a finite positive scrolling delay.

    Args:
        duration: Invalid boolean or nonfinite numeric pause value.
    """
    session = object.__new__(Session)
    with pytest.raises(errors.InvalidArgumentError):
        session._validate_pause(duration)


class CollidingConnection(Connection):
    """Force distinct connections to share a hash for equality regression testing."""

    def __hash__(self) -> int:
        """Return a deliberately colliding hash.

        Returns:
            The fixed collision value.
        """
        return 1


class CollidingService(BaseService):
    """Force distinct services to share a hash for equality regression testing."""

    def __hash__(self) -> int:
        """Return a deliberately colliding hash.

        Returns:
            The fixed collision value.
        """
        return 1


class CollidingSession(Session):
    """Force distinct sessions to share a hash for equality regression testing."""

    def __hash__(self) -> int:
        """Return a deliberately colliding hash.

        Returns:
            The fixed collision value.
        """
        return 1


class CollidingProfile(Profile):
    """Force distinct profile owners to share a hash for equality regression testing."""

    def __hash__(self) -> int:
        """Return a deliberately colliding hash.

        Returns:
            The fixed collision value.
        """
        return 1


def test_identity_objects_do_not_compare_by_hash_collision() -> None:
    """Keep mutable resource owners distinct even when their hashes collide."""
    classes = (
        CollidingConnection,
        CollidingService,
        CollidingSession,
        CollidingProfile,
    )
    for class_ in classes:
        left = object.__new__(class_)
        right = object.__new__(class_)
        assert hash(left) == hash(right)
        assert left != right


class CollidingAlert(Alert):
    """Force alert hashes to collide across different sessions."""

    def __hash__(self) -> int:
        """Return a deliberately colliding hash.

        Returns:
            The fixed collision value.
        """
        return 1


class CollidingElement(Element):
    """Force element hashes to collide across different sessions."""

    def __hash__(self) -> int:
        """Return a deliberately colliding hash.

        Returns:
            The fixed collision value.
        """
        return 1


def test_browser_handles_compare_structural_identity_not_hashes() -> None:
    """Require the same owning session even when alert or element hashes collide."""
    first_session = object.__new__(Session)
    second_session = object.__new__(Session)

    first_alert = object.__new__(CollidingAlert)
    first_alert._session = first_session
    second_alert = object.__new__(CollidingAlert)
    second_alert._session = second_session
    assert first_alert != second_alert

    first_element = object.__new__(CollidingElement)
    first_element._session = first_session
    first_element._id = "same-id"
    second_element = object.__new__(CollidingElement)
    second_element._session = second_session
    second_element._id = "same-id"
    assert first_element != second_element

    same_element = object.__new__(CollidingElement)
    same_element._session = first_session
    same_element._id = "same-id"
    assert first_element == same_element


def test_cached_value_equality_is_transitive_and_includes_payload() -> None:
    """Keep cached value objects distinct from names and unequal definitions."""
    command = DevToolsCMD("fixture", "Runtime.evaluate", expression="1")
    assert command == command.copy()
    assert hash(command) == hash(command.copy())
    assert command != DevToolsCMD("fixture", "Runtime.evaluate", expression="2")
    assert command != "fixture"

    script = JavaScript("fixture", "return arguments[0]", 1)
    assert script == script.copy()
    assert script != JavaScript("fixture", "return arguments[0]", 2)
    assert script != "fixture"

    window = Window("handle", "fixture")
    assert window == window.copy()
    assert window != Window("different", "fixture")
    assert window != "fixture"


def test_public_not_found_error_uses_consistent_webdriver_capitalization() -> None:
    """Expose only the clean 2.0 spellings of WebDriver exception names."""
    assert aselenium.WebDriverNotFoundError is errors.WebDriverNotFoundError
    assert aselenium.IncompatibleWebDriverError is errors.IncompatibleWebDriverError
    assert not hasattr(aselenium, "WebdriverNotFoundError")
    assert not hasattr(aselenium, "IncompatibleWebdriverError")


def test_incompatible_session_message_maps_to_clean_public_error() -> None:
    """Map a recognized driver/browser mismatch to the renamed exception."""
    response = {
        "value": {
            "error": "session not created",
            "message": (
                "session not created: This version of ChromeDriver only supports "
                "Chrome version 120"
            ),
        }
    }
    with pytest.raises(errors.IncompatibleWebDriverError):
        errors.webdriver_error_handler(response, http_status=500)


@pytest.mark.parametrize(
    "code,error_type",
    [
        ("unknown method", errors.UnknownMethodError),
        ("unknown method exception", errors.UnknownMethodError),
        ("detached shadow root", errors.DetachedShadowRootError),
    ],
)
def test_standard_and_vendor_error_codes_map_to_specific_errors(
    code: str, error_type: type[errors.WebDriverError]
) -> None:
    """Map current W3C and retained vendor spellings to public exception types.

    Args:
        code: Remote WebDriver error code.
        error_type: Expected package exception class.
    """
    with pytest.raises(error_type):
        errors.webdriver_error_handler(
            {"value": {"error": code, "message": "fixture"}}, http_status=500
        )


def test_detached_shadow_root_error_is_public() -> None:
    """Export the W3C detached-shadow-root classification at package level."""
    assert aselenium.DetachedShadowRootError is errors.DetachedShadowRootError


def test_unexpected_alert_string_separates_diagnostics() -> None:
    """Format alert text and the driver message on distinct readable lines."""
    error = errors.UnexpectedAlertFoundError("dialog", alert_text="Hi")
    assert str(error) == "Alert Text: Hi\ndialog"
    assert str(errors.UnexpectedAlertFoundError("dialog")) == "dialog"


def test_unexpected_alert_error_rejects_non_string_remote_text() -> None:
    """Reject malformed alert metadata instead of violating exception typing."""
    response = {
        "value": {
            "error": "unexpected alert open",
            "message": "blocked",
            "data": {"text": 7},
        }
    }

    with pytest.raises(errors.InvalidResponseError, match="alert text"):
        errors.webdriver_error_handler(response, http_status=500)


def test_file_unpack_does_not_expose_internal_publication_hooks() -> None:
    """Keep cache ownership hooks private to the Path-only unpacking core."""
    parameters = signature(File.unpack).parameters
    assert tuple(parameters) == ("self", "directory")


def test_file_rejects_unpacked_executable_downloads() -> None:
    """Reject raw executables because publication supports archives only."""
    artifact = File("driver", "win", "https://example.invalid/driver.exe", b"")

    with pytest.raises(errors.InvalidDownloadFileError):
        _ = artifact.filetype


class ReparseEntry:
    """Simulate a Windows directory junction returned by ``os.scandir``."""

    name = "junction"

    def stat(self, *, follow_symlinks: bool = True) -> Any:
        """Return non-following status containing the Windows reparse bit.

        Args:
            follow_symlinks: Whether the caller requested link following.

        Returns:
            Directory-like status carrying the Windows reparse attribute.
        """
        assert follow_symlinks is False
        return SimpleNamespace(st_mode=0o40755, st_file_attributes=0x400)


def test_firefox_profile_and_encoder_reject_child_reparse_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never follow a Windows junction while cloning or packing a Firefox tree.

    Args:
        tmp_path: Isolated existing directory used as the tree root.
        monkeypatch: Fixture replacing the platform directory scanner.
    """
    (tmp_path / "prefs.js").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(
        paths_module,
        "scandir",
        lambda directory: nullcontext((ReparseEntry(),)),
    )
    options = FirefoxOptions()
    try:
        with pytest.raises(errors.InvalidProfileError, match="reparse point"):
            options.set_profile(tmp_path)
        with pytest.raises(errors.InvalidExtensionError, match="reparse point"):
            encode_dir_to_firefox_wire_protocol(tmp_path)
    finally:
        options.close()


def test_firefox_profile_skips_extension_with_missing_manifest(
    tmp_path: Path,
) -> None:
    """Ignore corrupt pre-existing add-ons without aborting profile construction.

    Args:
        tmp_path: Isolated Firefox source profile.
    """
    extensions = tmp_path / "extensions"
    extensions.mkdir()
    with ZipFile(extensions / "missing-manifest.xpi", "w") as archive:
        archive.writestr("content.txt", "fixture")
    options = FirefoxOptions()
    try:
        profile = options.set_profile(tmp_path)
        assert profile.extensions == {}
    finally:
        options.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [True, -1, float("nan"), float("inf"), "1"])
async def test_command_pause_helpers_require_finite_nonnegative_numbers(
    duration: object,
) -> None:
    """Reject ambiguous or unbounded delays consistently across command owners.

    Args:
        duration: Invalid delay supplied to every public pause helper.
    """
    session = object.__new__(Session)
    element = object.__new__(Element)
    element._session = session
    for owner in (session, Alert(session), element):
        with pytest.raises(errors.InvalidArgumentError):
            await owner.pause(duration)  # type: ignore[arg-type]


class StatusResponse:
    """Provide one asynchronous service-status response."""

    def __init__(self, status: int, payload: object) -> None:
        """Store the HTTP status and asynchronous JSON result.

        Args:
            status: Synthetic HTTP status.
            payload: Value returned by ``json()`` or exception to raise.
        """
        self.status = status
        self.json = AsyncMock(
            side_effect=payload if isinstance(payload, BaseException) else None,
            return_value=None if isinstance(payload, BaseException) else payload,
        )

    async def __aenter__(self) -> StatusResponse:
        """Return this response from the asynchronous context.

        Returns:
            This response.
        """
        return self

    async def __aexit__(self, *args: object) -> None:
        """Leave the response context without additional cleanup.

        Args:
            *args: Context-manager exception details.
        """


@pytest.mark.asyncio
async def test_service_start_retries_non_json_unavailable_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Treat a transient non-JSON 503 as not-ready instead of aborting startup.

    Args:
        tmp_path: Isolated inert driver executable.
        monkeypatch: Fixture replacing process, HTTP, and sleep boundaries.
    """
    executable = tmp_path / "driver"
    executable.touch()
    service = ChromiumBaseService(ChromiumVersion("120.0.1.1"), executable, timeout=1)
    unavailable = StatusResponse(503, AssertionError("503 body must not be parsed"))
    ready = StatusResponse(200, {"value": {"ready": True}})
    responses = iter((unavailable, ready))
    client = SimpleNamespace(
        closed=False,
        get=lambda *args, **kwargs: next(responses),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_start_process",
        lambda: setattr(
            service,
            "_process",
            SimpleNamespace(is_running=lambda: True, children=lambda recursive: []),
        ),
    )
    monkeypatch.setattr(
        service, "_start_session", lambda: setattr(service, "_session", client)
    )
    monkeypatch.setattr(service_module, "sleep", AsyncMock())

    await service.start()

    unavailable.json.assert_not_awaited()
    ready.json.assert_awaited_once_with()
    service._session = None
    service._process = None


def test_released_typed_sessions_do_not_return_none_as_live_resources() -> None:
    """Preserve base lifecycle checks through browser-specific typed accessors."""
    for session_type in (ChromeSession, ChromiumSession, EdgeSession, SafariSession):
        session = object.__new__(session_type)
        session._options = None
        session._service = None
        with pytest.raises(errors.InvalidSessionError):
            _ = session.options
        with pytest.raises(errors.InvalidSessionError):
            _ = session.service
