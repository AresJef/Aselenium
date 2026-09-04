"""Exercise package-resource loading without changing bundled compatibility data."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from aselenium import errors
from aselenium.manager import FirefoxDriverManager, FirefoxVersion, GeckoVersion
from aselenium.manager import driver as driver_module

VALID_TABLE = {
    "9.8.1": {"min_firefox_version": "200.0.0", "max_firefox_version": "201.0.0"},
    "9.9.0": {"min_firefox_version": "202.0.0", "max_firefox_version": "203.0.0"},
}


def assert_unloaded() -> None:
    """Assert unloaded."""
    assert FirefoxDriverManager._GECKODRIVER_TABLE is None
    assert FirefoxDriverManager._GECKODRIVER_TABLE_MAX_VERSION is None
    assert FirefoxDriverManager._GECKODRIVER_MAX_VERSION is None


def assert_loaded(expected: Any = VALID_TABLE) -> None:
    """Assert loaded.

    Args:
        expected: Fixture or parametrized expected input for this regression.
    """
    table = FirefoxDriverManager._GECKODRIVER_TABLE
    assert isinstance(table, dict)
    assert all(isinstance(version, GeckoVersion) for version in table)
    assert all(
        isinstance(value, FirefoxVersion)
        for bounds in table.values()
        for value in bounds.values()
    )
    assert {
        str(version): {key: str(value) for key, value in bounds.items()}
        for version, bounds in table.items()
    } == expected
    maximum = max(GeckoVersion(version) for version in expected)
    assert FirefoxDriverManager._GECKODRIVER_TABLE_MAX_VERSION == maximum
    assert FirefoxDriverManager._GECKODRIVER_MAX_VERSION == maximum


@pytest.fixture
def resource_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Resource file.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    root = tmp_path / "resource-package"
    resource = root / "geckodriver" / "compatibility.json"
    resource.parent.mkdir(parents=True)
    provider = Mock(return_value=root)
    monkeypatch.setattr(driver_module.resources, "files", provider)
    return resource, provider


def test_loads_typed_table_and_reuses_successful_class_cache(
    resource_file: Any,
) -> None:
    """Verify loads typed table and reuses successful class cache.

    Args:
        resource_file: Fixture or parametrized resource file input for this regression.
    """
    resource, provider = resource_file
    resource.write_text(json.dumps(VALID_TABLE), encoding="utf-8")
    assert_unloaded()
    FirefoxDriverManager.load_driver_compatibility_table()
    assert_loaded()
    original = FirefoxDriverManager._GECKODRIVER_TABLE
    provider.assert_called_once_with("aselenium.manager")

    provider.side_effect = AssertionError("A cached table must not reread resources")
    FirefoxDriverManager.load_driver_compatibility_table()
    assert FirefoxDriverManager._GECKODRIVER_TABLE is original
    assert provider.call_count == 1
    assert_loaded()


def test_reads_zip_backed_traversable_without_filesystem_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify reads zip backed traversable without filesystem fallback.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    archive_path = tmp_path / "resource-package.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "aselenium/manager/geckodriver/compatibility.json",
            json.dumps(VALID_TABLE),
        )
    with zipfile.ZipFile(archive_path) as archive:
        root = zipfile.Path(archive, at="aselenium/manager/")
        provider = Mock(return_value=root)
        monkeypatch.setattr(driver_module.resources, "files", provider)
        FirefoxDriverManager.load_driver_compatibility_table()
    provider.assert_called_once_with("aselenium.manager")
    # These synthetic versions are not in the real bundled resource, so passing
    # proves the loader did not silently fall back to a path beside __file__.
    assert_loaded()


def test_missing_resource_preserves_cause_and_can_be_retried(
    resource_file: Any,
) -> None:
    """Verify missing resource preserves cause and can be retried.

    Args:
        resource_file: Fixture or parametrized resource file input for this regression.
    """
    resource, provider = resource_file
    with pytest.raises(errors.DriverManagerError, match="compatibility.json") as caught:
        FirefoxDriverManager.load_driver_compatibility_table()
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert_unloaded()

    resource.write_text(json.dumps(VALID_TABLE), encoding="utf-8")
    FirefoxDriverManager.load_driver_compatibility_table()
    assert provider.call_count == 2
    assert_loaded()


def test_unreadable_resource_preserves_original_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify unreadable resource preserves original os error.

    Args:
        monkeypatch: Pytest fixture for reversible environment, attribute, and path patches.
    """
    original_error = PermissionError("Synthetic resource access failure")
    root = Mock()
    root.joinpath.return_value.joinpath.return_value.read_text.side_effect = (
        original_error
    )
    monkeypatch.setattr(driver_module.resources, "files", Mock(return_value=root))
    with pytest.raises(errors.DriverManagerError, match="compatibility.json") as caught:
        FirefoxDriverManager.load_driver_compatibility_table()
    assert caught.value.__cause__ is original_error
    assert_unloaded()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"\xff", id="invalid-utf8"),
        pytest.param(b"{broken", id="invalid-json"),
        pytest.param(b"null", id="null-table"),
        pytest.param(b"[]", id="array-table"),
        pytest.param(b"{}", id="empty-table"),
        pytest.param(b'{"9.9.0": null}', id="null-bounds"),
        pytest.param(b'{"9.9.0": []}', id="array-bounds"),
        pytest.param(
            b'{"9.9.0": {"min_firefox_version": "200.0.0"}}',
            id="missing-maximum",
        ),
        pytest.param(
            json.dumps(
                {"9.9.0": {**VALID_TABLE["9.9.0"], "unexpected": "value"}}
            ).encode(),
            id="unknown-bound-key",
        ),
        pytest.param(
            json.dumps({"not-a-version": VALID_TABLE["9.9.0"]}).encode(),
            id="invalid-gecko-version",
        ),
        pytest.param(
            json.dumps({"geckodriver 9.9.0": VALID_TABLE["9.9.0"]}).encode(),
            id="decorated-gecko-version",
        ),
        pytest.param(
            json.dumps({"9.9.0.1": VALID_TABLE["9.9.0"]}).encode(),
            id="truncated-gecko-version",
        ),
        pytest.param(
            json.dumps(
                {"9.9": VALID_TABLE["9.9.0"], "9.9.0": VALID_TABLE["9.9.0"]}
            ).encode(),
            id="duplicate-normalized-gecko-versions",
        ),
        pytest.param(
            b'{"9.9.0": {"min_firefox_version": 200, "max_firefox_version": "201.0.0"}}',
            id="non-string-firefox-version",
        ),
        pytest.param(
            b'{"9.9.0": {"min_firefox_version": "unknown", "max_firefox_version": "201.0.0"}}',
            id="invalid-firefox-version",
        ),
        pytest.param(
            b'{"9.9.0": {"min_firefox_version": "Firefox 200.0.0", "max_firefox_version": "201.0.0"}}',
            id="decorated-firefox-minimum",
        ),
        pytest.param(
            b'{"9.9.0": {"min_firefox_version": "200.0.0", "max_firefox_version": "201.0.0-beta"}}',
            id="decorated-firefox-maximum",
        ),
        pytest.param(
            b'{"9.9.0": {"min_firefox_version": "202.0.0", "max_firefox_version": "201.0.0"}}',
            id="inverted-bounds",
        ),
        pytest.param(
            json.dumps({"9.8.1": VALID_TABLE["9.8.1"], "9.9.0": {}}).encode(),
            id="invalid-later-entry-does-not-publish-partial-table",
        ),
    ],
)
def test_invalid_resources_never_publish_partial_class_state(
    resource_file: Any, content: Any
) -> None:
    """Verify invalid resources never publish partial class state.

    Args:
        resource_file: Fixture or parametrized resource file input for this regression.
        content: Fixture or parametrized content input for this regression.
    """
    resource, _ = resource_file
    resource.write_bytes(content)
    with pytest.raises(errors.DriverManagerError, match="compatibility.json") as caught:
        FirefoxDriverManager.load_driver_compatibility_table()
    assert caught.value.__cause__ is not None
    assert_unloaded()

    resource.write_text(json.dumps(VALID_TABLE), encoding="utf-8")
    FirefoxDriverManager.load_driver_compatibility_table()
    assert_loaded()
