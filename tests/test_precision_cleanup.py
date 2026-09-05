"""Regressions for final dead-code, path-retention, and helper hardening."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from aselenium import _profiles as profile_registry
from aselenium import errors, javascript
from aselenium.command import COMMANDS, Command
from aselenium.firefox.utils import (
    FirefoxAddon,
    encode_dir_to_firefox_wire_protocol,
)
from aselenium.options import BaseOptions


def test_command_registry_contains_only_implemented_routes() -> None:
    """Exclude command constants that have no package-level operation or caller."""
    removed = {
        "ADD_CREDENTIAL",
        "ADD_VIRTUAL_AUTHENTICATOR",
        "FIND_CHILD_ELEMENT",
        "FIND_CHILD_ELEMENTS",
        "FIND_ELEMENT_FROM_SHADOW_ROOT",
        "FIND_ELEMENTS_FROM_SHADOW_ROOT",
        "GET_CREDENTIALS",
        "REMOVE_ALL_CREDENTIALS",
        "REMOVE_CREDENTIAL",
        "REMOVE_VIRTUAL_AUTHENTICATOR",
        "SAFARI_ATTACH_DEBUGGER",
        "SET_USER_VERIFIED",
        "UPLOAD_FILE",
    }
    assert not removed.intersection(vars(Command))
    assert set(COMMANDS).issubset(
        {value for value in vars(Command).values() if isinstance(value, str)}
    )


def test_form_submission_rejects_a_non_form_ancestor_chain() -> None:
    """Check the terminal DOM node before invoking the native form submit method."""
    assert 'if (form.nodeName !== "FORM")' in javascript.ELEMENT_SUBMIT_FORM
    assert "if (!form)" not in javascript.ELEMENT_SUBMIT_FORM


@pytest.mark.parametrize(
    "details",
    [
        {"id": "", "name": "Example", "version": "1.0"},
        {"id": None, "name": "", "version": "1.0"},
        {"id": None, "name": "Example", "version": ""},
        {"id": 1, "name": "Example", "version": "1.0"},
    ],
)
def test_firefox_addon_rejects_invalid_identity_fields(
    details: dict[str, Any],
) -> None:
    """Reject add-on metadata that could later fail through a typed property.

    Args:
        details: Deliberately malformed constructor fields.
    """
    with pytest.raises(errors.InvalidExtensionError):
        FirefoxAddon(**details)


def test_firefox_directory_encoder_rejects_symbolic_links(tmp_path: Path) -> None:
    """Prevent an add-on archive from reading a file outside its selected root.

    Args:
        tmp_path: Isolated add-on and external-file parent.
    """
    addon = tmp_path / "addon"
    addon.mkdir()
    external = tmp_path / "secret.txt"
    external.write_text("not extension data", encoding="utf-8")
    link = addon / "linked.txt"
    try:
        link.symlink_to(external)
    except OSError as cause:
        pytest.skip(f"Symbolic links are unavailable on this host: {cause}")
    with pytest.raises(errors.InvalidExtensionError):
        encode_dir_to_firefox_wire_protocol(addon)


def test_managed_profile_path_is_not_converted_back_and_reparsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a managed profile clone as ``Path`` through ownership registration.

    Args:
        tmp_path: Existing path standing in for a managed profile clone.
        monkeypatch: Fixture replacing the raw-text parser with a failure sentinel.
    """
    options = SimpleNamespace(
        _profile=SimpleNamespace(_temp_directory=tmp_path),
        arguments=[f"--user-data-dir={tmp_path}"],
    )
    owner = object()

    def unexpected_parse(_: object) -> Path:
        """Fail if managed typed state re-enters the raw path parser.

        Args:
            _: Unexpected raw value.

        Raises:
            AssertionError: Always; this path should remain typed.
        """
        raise AssertionError("managed Path was reparsed")

    monkeypatch.setattr(profile_registry, "parse_path", unexpected_parse)
    try:
        profile_registry.claim_profile(cast(BaseOptions, options), owner)
    finally:
        profile_registry.release_profile(owner)
