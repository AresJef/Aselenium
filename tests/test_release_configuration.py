"""Offline release metadata and workflow guardrails, not a remote CI run."""

from __future__ import annotations

import re
import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def run_git(repository: Path, *arguments: str) -> str:
    """Run one local Git command for a disposable release-history fixture.

    Args:
        repository: Temporary repository in which to run the command.
        *arguments: Git subcommand and arguments.

    Returns:
        Stripped standard output from the successful command.
    """
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("tag", ["2.0.0", "v2.0.0"])
def test_release_tag_matches_version(tag: Any) -> None:
    """Verify release tag matches version.

    Args:
        tag: Fixture or parametrized tag input for this regression.
    """
    check = runpy.run_path(str(ROOT / "scripts/check_release.py"))["check_tag"]
    check(tag, "2.0.0")


@pytest.mark.parametrize(
    "tag", ["", "v2.0.1", "release-2.0.0", "v2.0.0\n", "$(untrusted)"]
)
def test_release_tag_mismatch_fails_closed(tag: Any) -> None:
    """Verify release tag mismatch fails closed.

    Args:
        tag: Fixture or parametrized tag input for this regression.
    """
    check = runpy.run_path(str(ROOT / "scripts/check_release.py"))["check_tag"]
    with pytest.raises(ValueError):
        check(tag, "2.0.0")


def test_release_workflow_gates_publication_on_the_tested_tag_artifacts() -> None:
    """Require a tagged, tested artifact before PyPI or GitHub publication."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"] == {"push": {"tags": ["v*"]}}
    jobs = workflow["jobs"]
    assert jobs["validate"]["uses"] == "./.github/workflows/tests.yml"
    assert jobs["validate"]["with"]["reliability_duration"] == "600"
    assert jobs["verify-release"]["needs"] == "validate"
    verify_steps = jobs["verify-release"]["steps"]
    checkout = next(
        step
        for step in verify_steps
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"] == {
        "fetch-depth": "0",
        "fetch-tags": "true",
        "persist-credentials": "false",
    }
    tag_check = next(
        step
        for step in verify_steps
        if step.get("run") == "python scripts/check_release.py"
    )
    assert tag_check["env"] == {
        "RELEASE_COMMIT": "${{ github.sha }}",
        "RELEASE_TAG": "${{ github.ref_name }}",
    }
    verify_commands = "\n".join(step.get("run", "") for step in verify_steps)
    assert "readme-renderer[md]>=46,<47" in verify_commands
    assert "markdown.render" in verify_commands
    assert jobs["pypi"]["needs"] == "verify-release"
    assert "if" not in jobs["pypi"]
    assert jobs["pypi"]["environment"]["name"] == "pypi"
    assert jobs["pypi"]["permissions"] == {"contents": "read"}
    assert all("checkout" not in step.get("uses", "") for step in jobs["pypi"]["steps"])
    publish_step = next(
        step
        for step in jobs["pypi"]["steps"]
        if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@")
    )
    assert publish_step["with"] == {
        "user": "__token__",
        "password": "${{ secrets.PYPI_API_TOKEN }}",
        "attestations": "false",
    }
    secret_check = next(step for step in jobs["pypi"]["steps"] if "env" in step)
    assert secret_check["env"] == {"PYPI_API_TOKEN": "${{ secrets.PYPI_API_TOKEN }}"}
    assert 'if [ -z "$PYPI_API_TOKEN" ]; then' in secret_check["run"]
    assert "exit 1" in secret_check["run"]

    github_release = jobs["github-release"]
    assert set(github_release["needs"]) == {"verify-release", "pypi"}
    assert github_release["permissions"] == {"contents": "write"}
    assert "needs.pypi.result == 'success'" in github_release["if"]
    assert "skipped" not in github_release["if"]
    release_commands = "\n".join(
        step.get("run", "") for step in github_release["steps"]
    )
    assert "gh release create" in release_commands
    assert "--notes-file" in release_commands
    assert "--verify-tag" in release_commands
    assert "dist/*.whl dist/*.tar.gz SHA256SUMS" in release_commands


def test_release_tag_commit_must_belong_to_main_history(tmp_path: Path) -> None:
    """Reject a correctly named tag created only on an unmerged feature branch.

    Args:
        tmp_path: Disposable Git repository used to model divergent history.
    """
    checks = runpy.run_path(str(ROOT / "scripts/check_release.py"))
    repository = tmp_path / "repository"
    repository.mkdir()
    run_git(repository, "init", "--initial-branch=main")
    run_git(repository, "config", "user.name", "Release Test")
    run_git(repository, "config", "user.email", "release@example.invalid")
    tracked = repository / "tracked.txt"
    tracked.write_text("main\n", encoding="utf-8")
    run_git(repository, "add", "tracked.txt")
    run_git(repository, "commit", "-m", "main release")
    main_commit = run_git(repository, "rev-parse", "HEAD")
    run_git(repository, "tag", "v2.0.0")
    checks["check_tag_ancestry"](repository, "v2.0.0", main_commit, "refs/heads/main")

    run_git(repository, "switch", "--create", "feature-release")
    tracked.write_text("feature\n", encoding="utf-8")
    run_git(repository, "commit", "--all", "-m", "unmerged release")
    feature_commit = run_git(repository, "rev-parse", "HEAD")
    run_git(repository, "tag", "v2.0.1")
    with pytest.raises(ValueError, match="not contained in main"):
        checks["check_tag_ancestry"](
            repository, "v2.0.1", feature_commit, "refs/heads/main"
        )
    with pytest.raises(ValueError, match="does not match"):
        checks["check_tag_ancestry"](
            repository, "v2.0.0", feature_commit, "refs/heads/main"
        )


def test_ci_covers_current_package_without_removed_migration_job() -> None:
    """Verify ci covers current package without removed migration job."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/tests.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert "workflow_call" in workflow["on"]
    assert set(workflow["jobs"]) == {
        "build-distributions",
        "package-tests",
        "native-browsers",
    }
    assert workflow["on"]["push"] == {"branches": ["**"]}
    call_input = workflow["on"]["workflow_call"]["inputs"]["reliability_duration"]
    assert call_input == {
        "description": "Chrome and Edge sustained-session duration in seconds",
        "required": "false",
        "type": "number",
        "default": "30",
    }
    matrix = workflow["jobs"]["package-tests"]["strategy"]["matrix"]
    assert matrix["python-version"] == ["3.10", "3.11", "3.12", "3.13", "3.14"]
    commands = "\n".join(
        step.get("run", "") for step in workflow["jobs"]["package-tests"]["steps"]
    )
    assert "coverage run --branch --source=aselenium" in commands
    assert "--junitxml=pytest-results.xml" in commands
    assert "report_pytest_failures.py pytest-results.xml" in commands
    assert "pip_audit --skip-editable" in commands
    assert "check_example_contracts.py" in commands
    assert "check_coverage.py" in commands
    assert any(item.get("dependencies") == "minimum" for item in matrix["include"])
    diagnostic_step = next(
        step
        for step in workflow["jobs"]["package-tests"]["steps"]
        if step.get("name") == "Report failing tests in annotations"
    )
    assert diagnostic_step["if"] == "failure()"


def test_configured_mypy_gate_covers_runtime_demos_and_maintenance_scripts() -> None:
    """Prevent the default typing gate from silently shrinking to package-only code."""
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert configuration["tool"]["mypy"]["files"] == ["src", "scripts"]
    assert "ASYNC" in configuration["tool"]["ruff"]["lint"]["select"]


def test_native_ci_requires_installed_wheel_and_all_browser_stages() -> None:
    """Keep real browser acceptance mandatory with explicit installed-package checks."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/tests.yml").read_text(), Loader=yaml.BaseLoader
    )
    job = workflow["jobs"]["native-browsers"]
    assert set(job["needs"]) == {"build-distributions", "package-tests"}
    assert int(job["timeout-minutes"]) >= 40
    assert "continue-on-error" not in job
    combinations = {
        (entry["os"], entry["browser"])
        for entry in job["strategy"]["matrix"]["include"]
    }
    assert {
        ("ubuntu-24.04", "chrome"),
        ("ubuntu-24.04", "firefox"),
        ("windows-2025", "edge"),
        ("macos-15", "safari"),
    } <= combinations
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "pip install dist/*.whl" in commands
    assert "test_installed_browser.py" in commands
    assert "check_public_typing.py" in commands
    assert "run_reliability.py" in commands
    assert '--duration "$RELIABILITY_DURATION"' in commands
    assert "--allow-download" in commands
    assert all("continue-on-error" not in step for step in job["steps"])

    downloads = [
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    ]
    assert len(downloads) == 1
    assert downloads[0]["with"] == {
        "name": "candidate-distributions",
        "path": "dist",
    }
    native_upload = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert native_upload["if"] == "always()"
    assert native_upload["with"]["include-hidden-files"] == "true"
    assert not any("python -m build" in step.get("run", "") for step in job["steps"])


def test_ci_builds_one_canonical_distribution_for_native_and_release_use() -> None:
    """Keep one immutable distribution artifact as the acceptance boundary."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/tests.yml").read_text(), Loader=yaml.BaseLoader
    )
    build_job = workflow["jobs"]["build-distributions"]
    commands = "\n".join(step.get("run", "") for step in build_job["steps"])
    assert commands.count("python -m build") == 1
    assert "twine check --strict dist/*.whl dist/*.tar.gz" in commands
    upload = next(
        step
        for step in build_job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["name"] == "candidate-distributions"

    release = yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader
    )
    for job_name in ("verify-release", "pypi", "github-release"):
        download = next(
            step
            for step in release["jobs"][job_name]["steps"]
            if step.get("uses", "").startswith("actions/download-artifact@")
        )
        assert download["with"]["name"] == "candidate-distributions"


def test_release_notes_exist_for_the_package_version() -> None:
    """Require curated GitHub release notes for the declared package version."""
    metadata = (ROOT / "pyproject.toml").read_text()
    version = re.search(r'^version = "([^"]+)"$', metadata, re.MULTILINE)
    assert version is not None
    notes = ROOT / "docs" / "releases" / f"{version[1]}.md"
    assert notes.is_file()
    assert notes.read_text().startswith(f"# Aselenium {version[1]}\n")


def test_minimum_constraints_match_declared_runtime_dependencies() -> None:
    """Prevent the minimum-version matrix from drifting away from package metadata."""
    metadata = (ROOT / "pyproject.toml").read_text()
    dependencies = re.search(r"^dependencies = \[(.*?)\]$", metadata, re.MULTILINE)
    assert dependencies is not None
    minima = dict(re.findall(r'"([a-zA-Z0-9_-]+)>=([0-9.]+)"', dependencies[1]))
    constraints = dict(
        re.findall(
            r"^([a-zA-Z0-9_-]+)==([0-9.]+)$",
            (ROOT / "requirements-minimum.txt").read_text(),
            re.MULTILINE,
        )
    )
    assert constraints == minima


def test_runtime_requirements_match_declared_dependencies_exactly() -> None:
    """Prevent installer requirements from drifting from package metadata."""
    with (ROOT / "pyproject.toml").open("rb") as stream:
        declared = tuple(tomllib.load(stream)["project"]["dependencies"])
    requirements = tuple(
        line
        for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    )
    assert requirements == declared


@pytest.mark.parametrize("name", ["tests.yml", "release.yml", "promote-pypi.yml"])
def test_external_workflow_actions_are_pinned_to_full_commits(name: Any) -> None:
    """Verify external workflow actions are pinned to full commits.

    Args:
        name: Fixture or parametrized name input for this regression.
    """
    workflow = yaml.load(
        (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
    )
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
