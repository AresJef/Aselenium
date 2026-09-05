"""Validate release metadata without uploading or contacting a package index."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def check_tag(tag: str, version: str) -> None:
    """Require the release tag to match the package version exactly.

    Args:
        tag: Release tag, optionally prefixed with v.
        version: Exact package version from ``pyproject.toml``.
    """
    if tag not in {version, "v" + version}:
        raise ValueError(
            "Release tag must exactly match the package version (optional v prefix)"
        )


def resolve_commit(repository: Path, reference: str) -> str:
    """Resolve a Git reference to the commit it ultimately identifies.

    Args:
        repository: Checkout containing the release tag and main branch history.
        reference: Full Git reference or commit identifier to resolve.

    Returns:
        The canonical hexadecimal commit identifier.

    Raises:
        ValueError: The reference is absent, ambiguous, or is not commit-like.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", reference + "^{commit}"],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    commit = result.stdout.strip()
    if result.returncode or not commit:
        diagnostic = result.stderr.strip() or "reference did not resolve"
        raise ValueError(
            f"Unable to resolve release reference {reference!r}: {diagnostic}"
        )
    return commit


def check_tag_ancestry(
    repository: Path,
    tag: str,
    release_commit: str,
    main_reference: str = "refs/remotes/origin/main",
) -> None:
    """Require the event commit to be the tagged commit and an ancestor of main.

    Args:
        repository: Complete release checkout containing branch and tag history.
        tag: Validated release tag name.
        release_commit: Commit identifier supplied by the release event.
        main_reference: Remote-tracking reference for the protected main branch.

    Raises:
        ValueError: A reference is missing, the event does not identify the tag,
            or the tagged commit is not contained in main's history.
    """
    tagged_commit = resolve_commit(repository, "refs/tags/" + tag)
    event_commit = resolve_commit(repository, release_commit)
    main_commit = resolve_commit(repository, main_reference)
    if tagged_commit != event_commit:
        raise ValueError("Release event commit does not match the release tag commit")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tagged_commit, main_commit],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if ancestry.returncode == 1:
        raise ValueError("Release tag commit is not contained in main branch history")
    if ancestry.returncode:
        diagnostic = ancestry.stderr.strip() or "Git ancestry check failed"
        raise ValueError(diagnostic)


if __name__ == "__main__":
    repository = Path(__file__).resolve().parents[1]
    path = repository / "pyproject.toml"
    with path.open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    tag = os.environ.get("RELEASE_TAG", "")
    check_tag(tag, version)
    check_tag_ancestry(repository, tag, os.environ.get("RELEASE_COMMIT", ""))
    print("Release tag matches package version and belongs to main branch history")
