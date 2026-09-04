"""Baseline value semantics used by driver resolution and cache lookups."""

from __future__ import annotations

from typing import Any

import pytest

from aselenium import errors
from aselenium.manager import (
    ChromiumVersion,
    FirefoxVersion,
    GeckoVersion,
    SafariVersion,
)


@pytest.mark.parametrize(
    ("version_type", "probe_text", "expected"),
    [
        (ChromiumVersion, "Google Chrome 120.0.6099.71", "120.0.6099.71"),
        (ChromiumVersion, "Microsoft Edge 120.0.2210.91", "120.0.2210.91"),
        (FirefoxVersion, "Mozilla Firefox 120.0.1", "120.0.1"),
        (GeckoVersion, "geckodriver 0.33.0 (synthetic build)", "0.33.0"),
        (SafariVersion, "17.2", "17.2"),
    ],
)
def test_version_parses_browser_probe_output(
    version_type: Any, probe_text: Any, expected: Any
) -> None:
    # This tolerant probe parsing is separate from future strict user-pin parsing.
    """Verify version parses browser probe output.

    Args:
        version_type: Fixture or parametrized version type input for this regression.
        probe_text: Fixture or parametrized probe text input for this regression.
        expected: Fixture or parametrized expected input for this regression.
    """
    version = version_type(probe_text)
    assert str(version) == expected
    assert version_type(version) == version
    assert hash(version_type(version)) == hash(version)


@pytest.mark.parametrize(
    "version_type", [ChromiumVersion, FirefoxVersion, GeckoVersion, SafariVersion]
)
def test_version_comparison_is_numeric(version_type: Any) -> None:
    """Verify version comparison is numeric.

    Args:
        version_type: Fixture or parametrized version type input for this regression.
    """
    assert version_type("10.0.0") > version_type("9.0.0")
    assert version_type("10.0.0") == version_type("10")
    assert len({version_type("10"), version_type("10.0.0")}) == 1
    assert version_type("10.0.0") != version_type("11.0.0")


@pytest.mark.parametrize(
    "version_type", [ChromiumVersion, FirefoxVersion, GeckoVersion, SafariVersion]
)
@pytest.mark.parametrize("value", ["not-a-version", "", None])
def test_missing_numeric_version_is_rejected(version_type: Any, value: Any) -> None:
    """Verify missing numeric version is rejected.

    Args:
        version_type: Fixture or parametrized version type input for this regression.
        value: Fixture or parametrized value input for this regression.
    """
    with pytest.raises(errors.InvalidVersionError):
        version_type(value)


def test_chromium_version_components_used_by_cache_queries() -> None:
    """Verify chromium version components used by cache queries."""
    version = ChromiumVersion("120.0.6099.71")
    assert (version.major, version.build, version.patch) == (
        "120",
        "120.0.6099",
        "120.0.6099.71",
    )
    assert (
        version.major_num,
        version.minor_num,
        version.build_num,
        version.patch_num,
    ) == (120, 0, 6099, 71)
