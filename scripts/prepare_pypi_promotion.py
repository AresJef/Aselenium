"""Recover an existing release for PyPI only after verifying its tested provenance.

Run ``python -m scripts.prepare_pypi_promotion`` from the repository root in
GitHub Actions. RELEASE_TAG, VALIDATION_RUN, GITHUB_REPOSITORY and GH_TOKEN must
be set. The token needs read access only; this script never publishes a package.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from scripts.check_release import check_tag, check_tag_ancestry, resolve_commit

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def run_command(repository: Path, *arguments: str) -> str:
    """Execute a bounded read/download command without invoking a shell.

    Args:
        repository: Checkout in which to execute the command.
        *arguments: Executable and separate command-line arguments.

    Returns:
        Standard output from the successful command.

    Raises:
        subprocess.CalledProcessError: The command fails.
        subprocess.TimeoutExpired: The command exceeds two minutes.
    """
    return subprocess.run(
        arguments,
        cwd=repository,
        text=True,
        capture_output=True,
        timeout=120,
        check=True,
    ).stdout


def validate_inputs(tag: str, run_id: str, slug: str) -> None:
    """Reject malformed identifiers before using them in GitHub or Git commands.

    Args:
        tag: Existing version tag, including its v prefix.
        run_id: Positive decimal GitHub Actions run identifier.
        slug: GitHub repository in owner/name form.

    Raises:
        ValueError: An identifier is empty or contains unexpected characters.
    """
    if not re.fullmatch(r"v[0-9][A-Za-z0-9.!+_-]*", tag):
        raise ValueError("A version tag beginning with v and a digit is required")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("A positive decimal validation run ID is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", slug):
        raise ValueError("A GitHub owner/repository identifier is required")


def validate_run(
    run: dict[str, Any],
    jobs: dict[str, Any],
    *,
    tag: str,
    run_id: str,
    slug: str,
    commit: str,
) -> None:
    """Require a successful tagged release run with all its validation jobs.

    Args:
        run: GitHub workflow-run API response.
        jobs: First jobs page, requested with a page size of 100.
        tag: Exact release tag being promoted.
        run_id: Expected workflow-run identifier.
        slug: Expected source and workflow repository.
        commit: Commit resolved from the immutable release tag.

    Raises:
        ValueError: Run identity, completeness or a required result is invalid.
    """
    expected = {
        "id": int(run_id),
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "path": ".github/workflows/release.yml",
        "head_branch": tag,
        "head_sha": commit,
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise ValueError("Validation must be a successful release.yml run for this tag")
    for key in ("repository", "head_repository"):
        if run.get(key, {}).get("full_name") != slug:
            raise ValueError("Validation run must belong to the same repository")

    entries = jobs.get("jobs", [])
    if jobs.get("total_count") != len(entries):
        raise ValueError("Validation jobs response is incomplete")
    by_name = {job["name"]: job for job in entries}
    required = {
        "validate / Build canonical distributions",
        "Verify tagged release artifacts",
        *(
            f"validate / Python 3.{minor} / ubuntu-latest / current"
            for minor in range(10, 15)
        ),
        "validate / Python 3.13 / windows-latest / current",
        "validate / Python 3.13 / macos-latest / current",
        "validate / Python 3.11 / ubuntu-latest / minimum",
        *(
            f"validate / native-browsers ({system}, {browser})"
            for system, browser in (
                ("ubuntu-24.04", "chrome"),
                ("ubuntu-24.04", "firefox"),
                ("windows-2025", "edge"),
                ("macos-15", "chrome"),
                ("macos-15", "firefox"),
                ("macos-15", "safari"),
            )
        ),
    }
    if len(by_name) != len(entries) or not required <= by_name.keys():
        raise ValueError("Validation is missing required package or browser jobs")
    for name, job in by_name.items():
        if name in required or name.startswith("validate / "):
            if job.get("status") != "completed" or job.get("conclusion") != "success":
                raise ValueError(f"Required validation job did not succeed: {name}")


def verify_distributions(candidate: Path, published: Path, version: str) -> None:
    """Require the public files, test artifacts and release checksums to agree.

    Args:
        candidate: Directory containing the canonical, native-tested files.
        published: Directory containing downloaded GitHub Release assets.
        version: Exact version declared by the tagged package metadata.

    Raises:
        ValueError: A file is missing, unexpected, symlinked or has changed bytes.
    """
    names = {f"aselenium-{version}-py3-none-any.whl", f"aselenium-{version}.tar.gz"}
    if {path.name for path in candidate.iterdir()} != names:
        raise ValueError("Test artifact must contain exactly the wheel and sdist")
    if {path.name for path in published.iterdir()} != names | {"SHA256SUMS"}:
        raise ValueError("Published assets must contain the wheel, sdist and checksums")
    paths = [*candidate.iterdir(), *published.iterdir()]
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("Distribution artifacts must be regular files")
    checksums = set((published / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
    expected = set()
    for name in names:
        tested_digest = hashlib.sha256((candidate / name).read_bytes()).hexdigest()
        released_digest = hashlib.sha256((published / name).read_bytes()).hexdigest()
        if tested_digest != released_digest:
            raise ValueError(
                f"Published distribution differs from tested artifact: {name}"
            )
        expected.add(f"{tested_digest}  dist/{name}")
    if checksums != expected:
        raise ValueError("Published SHA256SUMS does not match the tested distributions")


def main() -> None:
    """Validate provenance and copy only the verified public distributions to dist.

    Raises:
        ValueError: Release identity, test results or artifact hashes do not match.
        FileExistsError: The output directory already exists.
        subprocess.CalledProcessError: Git or GitHub cannot retrieve evidence.
    """
    repository = Path(__file__).resolve().parents[1]
    tag = os.environ.get("RELEASE_TAG", "")
    run_id = os.environ.get("VALIDATION_RUN", "")
    slug = os.environ.get("GITHUB_REPOSITORY", "")
    validate_inputs(tag, run_id, slug)
    commit = resolve_commit(repository, "refs/tags/" + tag)
    check_tag_ancestry(repository, tag, commit)
    metadata = tomllib.loads(
        run_command(repository, "git", "show", f"{commit}:pyproject.toml")
    )
    version = metadata["project"]["version"]
    if metadata["project"]["name"] != "aselenium":
        raise ValueError("Only Aselenium distributions may be promoted")
    check_tag(tag, version)
    run = json.loads(
        run_command(repository, "gh", "api", f"repos/{slug}/actions/runs/{run_id}")
    )
    jobs = json.loads(
        run_command(
            repository,
            "gh",
            "api",
            f"repos/{slug}/actions/runs/{run_id}/jobs?per_page=100",
        )
    )
    validate_run(run, jobs, tag=tag, run_id=run_id, slug=slug, commit=commit)
    release = json.loads(
        run_command(repository, "gh", "api", f"repos/{slug}/releases/tags/{tag}")
    )
    if (
        release.get("tag_name") != tag
        or release.get("draft") is not False
        or not release.get("published_at")
    ):
        raise ValueError("The tag must already have a published GitHub Release")

    output = repository / "dist"
    if output.exists():
        raise FileExistsError(
            "Refusing to mix promotion files with an existing dist directory"
        )
    with tempfile.TemporaryDirectory(prefix="aselenium-pypi-promotion-") as temporary:
        work = Path(temporary)
        candidate = work / "candidate"
        published = work / "published"
        run_command(
            repository,
            "gh",
            "run",
            "download",
            run_id,
            "--repo",
            slug,
            "--name",
            "candidate-distributions",
            "--dir",
            str(candidate),
        )
        run_command(
            repository,
            "gh",
            "release",
            "download",
            tag,
            "--repo",
            slug,
            "--pattern",
            f"aselenium-{version}-py3-none-any.whl",
            "--pattern",
            f"aselenium-{version}.tar.gz",
            "--pattern",
            "SHA256SUMS",
            "--dir",
            str(published),
        )
        verify_distributions(candidate, published, version)
        output.mkdir()
        for path in published.iterdir():
            if path.name != "SHA256SUMS":
                (output / path.name).write_bytes(path.read_bytes())
    print(
        f"Verified {tag}: successful release run {run_id}, matching public and tested files"
    )


if __name__ == "__main__":
    main()
