"""Fresh vendor/configuration regressions with independent positive controls."""

from __future__ import annotations

from base64 import b64decode
from collections.abc import Iterator
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from aselenium import (
    ChromeOptions,
    ChromiumOptions,
    EdgeOptions,
    FirefoxOptions,
    Proxy,
    Safari,
    SafariOptions,
    Timeouts,
    errors,
)
from aselenium import options as options_module
from aselenium.command import Command
from aselenium.firefox.service import FirefoxService
from aselenium.firefox.session import FirefoxSession
from aselenium.firefox.utils import encode_dir_to_firefox_wire_protocol
from aselenium.manager.version import GeckoVersion
from aselenium.options import BaseOptions, ChromiumBaseOptions, Profile
from aselenium.safari.session import SafariSession

OPTION_TYPES = (
    ChromeOptions,
    ChromiumOptions,
    EdgeOptions,
    FirefoxOptions,
    SafariOptions,
)
PROFILE_OPTION_TYPES = (ChromeOptions, ChromiumOptions, EdgeOptions, FirefoxOptions)


def configure_profile(options: BaseOptions, source: Path) -> Profile:
    """Configure a real temporary profile without launching a browser.

    Args:
        options: Chromium-family or Firefox options to configure.
        source: Existing profile data directory shared by the controlled fixtures.

    Returns:
        The newly owned profile clone.
    """
    if isinstance(options, ChromiumBaseOptions):
        return options.set_profile(str(source.parent), source.name)
    return options.set_profile(str(source))


@pytest.fixture(params=PROFILE_OPTION_TYPES)
def profile_options(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[tuple[BaseOptions, Profile, Path]]:
    """Supply actual cloned data and release every fixture-owned profile afterward.

    Args:
        request: Parametrized concrete options class supplied by pytest.
        tmp_path: Disposable profile source directory.

    Yields:
        Options, retained original profile handle, and original source directory.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "Preferences").write_text("original", encoding="utf-8")
    options = request.param()
    options.add_arguments("--fixture-preserved")
    profile = configure_profile(options, source)
    try:
        yield options, profile, source
    finally:
        options.close()
        profile._delete_temp_profile()


@pytest.mark.parametrize("operation", ["close", "rem_profile"])
def test_releasing_profile_removes_owned_data_and_capabilities(
    profile_options: tuple[BaseOptions, Profile, Path], operation: str
) -> None:
    """Invalidate cached wire data and remove only the owned profile's launch flags.

    Args:
        profile_options: Actual options and profile clone retained by the caller.
        operation: Public release operation being verified.
    """
    options, profile, source = profile_options
    clone = Path(profile._temp_directory)
    before = options.capabilities
    assert clone.exists()
    getattr(options, operation)()
    assert not clone.exists(), "A retained profile reference must not delay cleanup"
    assert options.profile is None
    after = options.capabilities
    assert after != before
    assert options.arguments == ["--fixture-preserved"]
    assert "profile" not in after[options.KEY]
    assert (source / "Preferences").read_text(encoding="utf-8") == "original"
    getattr(options, operation)()


def test_replacing_profile_releases_old_clone_but_preserves_snapshot(
    profile_options: tuple[BaseOptions, Profile, Path],
) -> None:
    """Deterministically release the old template without touching acquisition copies.

    Args:
        profile_options: Actual options and an old profile still referenced by the caller.
    """
    options, old, source = profile_options
    old_clone = Path(old._temp_directory)
    snapshot = options.snapshot()
    snapshot_clone = Path(snapshot.profile._temp_directory)
    try:
        replacement = configure_profile(options, source)
        assert replacement is options.profile and replacement is not old
        assert not old_clone.exists()
        assert snapshot_clone.exists()
        assert Path(replacement._temp_directory).exists()
        assert options.arguments.count("--fixture-preserved") == 1
    finally:
        snapshot.close()


def test_profile_replacement_cleanup_failure_preserves_old_configuration(
    profile_options: tuple[BaseOptions, Profile, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the previous configuration and discard the pending clone if release fails.

    Args:
        profile_options: Actual options and a retained original template clone.
        monkeypatch: Fixture restoring the temporary filesystem-failure boundary.
    """
    options, old, source = profile_options
    old_caps = options.capabilities
    created: list[Path] = []
    allocate = options_module.mkdtemp

    def record_directory(*args: Any, **kwargs: Any) -> str:
        """Allocate an actual clone directory and record its cleanup ownership.

        Args:
            *args: Arguments passed to tempfile.mkdtemp.
            **kwargs: Keyword arguments passed to tempfile.mkdtemp.

        Returns:
            Newly allocated temporary directory.
        """
        directory = allocate(*args, **kwargs)
        created.append(Path(directory))
        return directory

    def deny_cleanup() -> None:
        """Simulate failure to remove the old clone without deleting any data."""
        raise PermissionError("fixture denies old profile removal")

    with monkeypatch.context() as patch:
        patch.setattr(options_module, "mkdtemp", record_directory)
        patch.setattr(old, "_delete_temp_profile", deny_cleanup)
        with pytest.raises(PermissionError, match="fixture denies"):
            configure_profile(options, source)
        assert options.profile is old
        assert options.capabilities == old_caps
        assert len(created) == 1 and not created[0].exists()


def test_double_profile_cleanup_failure_retains_pending_clone_for_retry(
    profile_options: tuple[BaseOptions, Profile, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain both clones when old release and pending-replacement cleanup fail.

    Args:
        profile_options: Actual options and their caller-retained original clone.
        monkeypatch: Fixture restoring the controlled profile-removal failure.
    """
    options, old, source = profile_options
    old_path = Path(old._temp_directory)
    before = options.capabilities

    def deny_cleanup(profile: Profile) -> None:
        """Simulate a temporary filesystem error for either owned clone.

        Args:
            profile: Profile whose directory must remain untouched by this failure.
        """
        assert Path(profile._temp_directory).exists()
        raise PermissionError("fixture temporarily denies clone cleanup")

    with monkeypatch.context() as patch:
        patch.setattr(Profile, "_delete_temp_profile", deny_cleanup)
        with pytest.raises(PermissionError, match="temporarily denies"):
            configure_profile(options, source)
        assert options.profile is old
        assert options.capabilities == before
        assert len(options._pending_profile_cleanup) == 1
        pending_path = Path(options._pending_profile_cleanup[0]._temp_directory)
        assert old_path.exists() and pending_path.exists()
        snapshot = options.snapshot()
        assert snapshot._pending_profile_cleanup == []
    try:
        snapshot_path = Path(snapshot.profile._temp_directory)
        options.close()
        assert not old_path.exists() and not pending_path.exists()
        assert snapshot_path.exists()
        assert options._pending_profile_cleanup == []
    finally:
        snapshot.close()


def test_options_can_be_reconfigured_after_repeated_profile_close(
    profile_options: tuple[BaseOptions, Profile, Path],
) -> None:
    """Keep close idempotent and permit later reuse without stale clone arguments.

    Args:
        profile_options: Options containing an independently owned profile clone.
    """
    options, _, source = profile_options
    options.close()
    options.close()
    assert options.arguments == ["--fixture-preserved"]
    current = configure_profile(options, source)
    assert options.profile is current
    assert Path(current._temp_directory).exists()
    assert options.capabilities[options.KEY]
    options.close()
    assert options.profile is None
    assert options.arguments == ["--fixture-preserved"]
    assert (source / "Preferences").read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("options_type", OPTION_TYPES)
@pytest.mark.parametrize(
    "name", ["accept_insecure_certs", "strict_file_interactability"]
)
@pytest.mark.parametrize("invalid", ["false", 0, None])
def test_boolean_browser_options_reject_coercion_atomically(
    options_type: type[BaseOptions], name: str, invalid: Any
) -> None:
    """Do not turn malformed configuration, particularly string false, into opt-in.

    Args:
        options_type: Concrete browser options implementation.
        name: Boolean configuration property.
        invalid: Non-boolean input deliberately supplied to the setter.
    """
    options = options_type()
    setattr(options, name, False)
    before = options.capabilities
    with pytest.raises(errors.InvalidOptionsError):
        setattr(options, name, invalid)
    assert options.capabilities == before
    setattr(options, name, True)
    assert getattr(options, name) is True
    setattr(options, name, False)
    assert getattr(options, name) is False


@pytest.mark.parametrize(
    "name", ["automatic_inspection", "automatic_profiling", "technology_preview"]
)
@pytest.mark.parametrize("invalid", ["false", 0, None])
def test_safari_boolean_options_require_actual_bool(name: str, invalid: Any) -> None:
    """Keep Safari-specific boolean configuration strict and transactionally validated.

    Args:
        name: Safari-specific boolean property.
        invalid: Non-boolean value supplied deliberately.
    """
    options = SafariOptions()
    before = options.capabilities
    with pytest.raises(errors.InvalidOptionsError):
        setattr(options, name, invalid)
    assert options.capabilities == before
    setattr(options, name, True)
    assert getattr(options, name) is True
    setattr(options, name, False)
    assert getattr(options, name) is False


@pytest.mark.parametrize("invalid", ["false", 0, None, []])
def test_proxy_constructor_validates_falsey_autodetection(invalid: Any) -> None:
    """Apply the same strict bool contract in proxy construction and assignment.

    Args:
        invalid: Invalid truthy or falsey proxy auto-detection flag.
    """
    with pytest.raises(errors.InvalidProxyError):
        Proxy(auto_detect=invalid)
    assert Proxy(auto_detect=True).to_capabilities() == {"proxyType": "autodetect"}
    assert Proxy(auto_detect=False).proxy_type in {"SYSTEM", "DIRECT"}


@pytest.mark.parametrize("name", ["page_load_strategy", "unhandled_prompt_behavior"])
@pytest.mark.parametrize("invalid", [[], {}, 1])
def test_enum_options_reject_invalid_types_without_raw_typeerror(
    name: str, invalid: Any
) -> None:
    """Return a package configuration error rather than an unhashable-value error.

    Args:
        name: Enum-valued configuration property.
        invalid: Non-string input supplied deliberately.
    """
    options = ChromeOptions()
    before = options.capabilities
    with pytest.raises(errors.InvalidOptionsError):
        setattr(options, name, invalid)
    assert options.capabilities == before


@pytest.mark.parametrize("unit", ["minutes", "", None, [], 1])
def test_timeout_unit_must_be_seconds_or_milliseconds(unit: Any) -> None:
    """Reject unknown timeout units instead of interpreting them as seconds.

    Args:
        unit: Invalid unit supplied deliberately.
    """
    with pytest.raises(errors.InvalidOptionsError):
        Timeouts(script=1, unit=unit)
    assert Timeouts(script=1, unit="s").script_ms == 1000
    assert Timeouts(script=1, unit="ms").script_ms == 1


@pytest.mark.parametrize(
    "name",
    ["implicit", "pageLoad", "script", "implicit_ms", "pageLoad_ms", "script_ms"],
)
@pytest.mark.parametrize(
    "invalid", [1e308, 10**400, 2**53], ids=["finite-float", "huge-int", "unsafe-int"]
)
def test_timeout_setters_reject_overflow_without_mutating_state(
    name: str, invalid: int | float
) -> None:
    """Reject timeout values that cannot become valid W3C integer milliseconds.

    Args:
        name: Seconds-based or milliseconds-based timeout property.
        invalid: Oversized value, including huge integers and finite floats.
    """
    timeouts = Timeouts(implicit=1, pageLoad=2, script=3)
    before = timeouts.dict
    with pytest.raises(errors.InvalidOptionsError):
        setattr(timeouts, name, invalid)
    assert timeouts.dict == before


def test_timeout_safe_boundary_and_fractional_conversion_remain_valid() -> None:
    """Preserve the largest safe protocol integer and existing subsecond truncation."""
    maximum = 2**53 - 1
    assert Timeouts(script=maximum).script_ms == maximum
    assert Timeouts(script=1.2349, unit="s").script_ms == 1234
    assert Timeouts(script=1.999, unit="ms").script_ms == 1
    options = ChromeOptions()
    before = options.timeouts
    with pytest.raises(errors.InvalidOptionsError):
        options.set_timeouts(implicit=1, script=1e308)
    assert options.timeouts == before


@pytest.mark.parametrize("options_type", OPTION_TYPES)
def test_unrepresentable_session_deadline_is_rejected_atomically(
    options_type: type[BaseOptions],
) -> None:
    """Return a typed configuration error if a huge integer cannot be a deadline.

    Args:
        options_type: Concrete browser options implementation.
    """
    options = options_type()
    before = options.session_timeout
    with pytest.raises(errors.InvalidOptionsError):
        options.session_timeout = 10**400
    assert options.session_timeout == before


def test_safari_forwards_positional_service_arguments_without_duplicate_binding() -> (
    None
):
    """Forward documented native service arguments through Safari's facade constructor."""
    driver = Safari(7, "--diagnose", close_fds=False)
    try:
        assert driver._service_timeout == 7
        assert driver._service_args == ("--diagnose",)
        assert driver._service_kwargs == {"close_fds": False}
        assert driver.options.browser_name == "safari"
    finally:
        driver.options.close()


@pytest.mark.parametrize(
    "arguments", [("--websocket-port", "5678"), ("--websocket-port=5678",)]
)
def test_firefox_respects_both_explicit_websocket_port_spellings(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    """Avoid an additional allocated websocket port when the caller supplies one.

    Args:
        tmp_path: Disposable path for an inert geckodriver file.
        arguments: Split or equals-form explicit websocket port argument.
    """
    executable = tmp_path / "geckodriver"
    executable.touch()
    service = FirefoxService(GeckoVersion("0.37.0"), str(executable), 10, *arguments)
    service._port = 41001
    service._port_str = "41001"
    service._cdp_port = 41002
    service._cdp_port_str = "41002"
    assert service.port_args == ["--port=41001"]
    assert service._args == list(arguments)


@pytest.mark.parametrize("suffix", ["", "/"])
def test_firefox_archive_preserves_names_with_trailing_directory_separator(
    tmp_path: Path, suffix: str
) -> None:
    """Serialize identical archive paths regardless of a directory's trailing slash.

    Args:
        tmp_path: Disposable directory to encode without extraction or execution.
        suffix: Optional trailing path separator supplied by the caller.
    """
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    encoded = encode_dir_to_firefox_wire_protocol(str(tmp_path) + suffix)
    with ZipFile(BytesIO(b64decode(encoded))) as archive:
        assert archive.namelist() == ["manifest.json"]
        assert archive.read("manifest.json") == b"{}"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["false", 0, None])
async def test_safari_permission_validation_precedes_any_wire_request(
    invalid: Any,
) -> None:
    """Reject malformed permission states before reading or mutating browser state.

    Args:
        invalid: Non-boolean permission state supplied deliberately.
    """
    options = SafariOptions()
    session = SafariSession(options, SimpleNamespace())
    session._base_url = "/session/safari-permission-test"
    session._conn = SimpleNamespace(
        execute=AsyncMock(return_value={"value": {"permissions": {}}}),
        transaction=nullcontext,
    )
    with pytest.raises(errors.InvalidPermissionStateError):
        await session.set_permission("getUserMedia", invalid)
    session._conn.execute.assert_not_awaited()
    await session.set_permission("getUserMedia", False)
    assert (
        session._conn.execute.await_args_list[1].args[1]
        == Command.SAFARI_SET_PERMISSIONS
    )
    assert session._conn.execute.await_args_list[1].kwargs["body"] == {
        "permissions": {"getUserMedia": False}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", None, [], 1])
async def test_safari_permission_names_are_validated_before_reading_state(
    name: Any,
) -> None:
    """Reject malformed permission names without an incidental read or remote write.

    Args:
        name: Invalid permission name supplied deliberately.
    """
    session = SafariSession(SafariOptions(), SimpleNamespace())
    session._conn = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(errors.InvalidPermissionNameError):
        await session.set_permission(name, False)
    session._conn.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["false", 0, None])
async def test_firefox_temporary_addon_flag_is_validated_before_filesystem_access(
    invalid: Any,
) -> None:
    """Reject malformed temporary-install flags even when the add-on batch is empty.

    Args:
        invalid: Non-boolean temporary-install option supplied deliberately.
    """
    options = FirefoxOptions()
    session = FirefoxSession(options, SimpleNamespace())
    session._conn = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(errors.InvalidArgumentError):
        await session.install_addons(temporary=invalid)
    assert await session.install_addons(temporary=True) == []
    session._conn.execute.assert_not_awaited()
