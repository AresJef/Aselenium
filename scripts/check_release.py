"""Validate release metadata without uploading or contacting a package index."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def check_tag(tag: str, version: str) -> None:
    """Require the release tag to match the package version exactly.

    Args:
        tag: Release tag, optionally prefixed with v.
        version: Version object or version selector for this operation.
    """
    if tag not in {version, "v" + version}:
        raise ValueError(
            "Release tag must exactly match the package version (optional v prefix)"
        )


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with path.open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    check_tag(os.environ.get("RELEASE_TAG", ""), version)
    print("Release tag matches package version")
