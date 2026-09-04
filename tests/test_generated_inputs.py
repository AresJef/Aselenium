"""Generated-input contracts for version ordering, timeout units, and archive paths."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aselenium import Timeouts
from aselenium.manager._filesystem import member_path
from aselenium.manager.version import ChromiumVersion


@settings(max_examples=200, derandomize=True, deadline=None)
@given(st.tuples(*(st.integers(min_value=0, max_value=9999) for _ in range(4))))
def test_version_roundtrip_preserves_components(
    parts: tuple[int, int, int, int],
) -> None:
    """Round-trip generated complete Chromium versions without changing components.

    Args:
        parts: Nonnegative major, minor, build, and patch components.
    """
    text = ".".join(map(str, parts))
    assert str(ChromiumVersion(text)) == text


@settings(max_examples=200, derandomize=True, deadline=None)
@given(st.integers(min_value=0, max_value=1_000_000))
def test_timeout_milliseconds_roundtrip(milliseconds: int) -> None:
    """Preserve an integral wire timeout through millisecond setters and copy.

    Args:
        milliseconds: Finite nonnegative protocol timeout in milliseconds.
    """
    value = Timeouts()
    value.implicit_ms = milliseconds
    assert value.implicit_ms == milliseconds
    assert value.copy().implicit_ms == milliseconds
    assert value.implicit == milliseconds / 1000


@settings(max_examples=200, derandomize=True, deadline=None)
@given(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=40)
)
def test_archive_parent_traversal_is_always_rejected(name: str) -> None:
    """Reject a generated otherwise-portable name when it contains parent traversal.

    Args:
        name: Safe basename used to isolate traversal as the rejected property.
    """
    assert member_path(name) == PurePosixPath(name)
    with pytest.raises(ValueError):
        member_path(name + "/../escape")
