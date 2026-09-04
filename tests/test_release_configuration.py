"""Offline release metadata and workflow guardrails, not a remote CI run."""

from __future__ import annotations

import re
import runpy
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


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
    verify_commands = "\n".join(
        step.get("run", "") for step in jobs["verify-release"]["steps"]
    )
    assert "readme-renderer[md]>=46,<47" in verify_commands
    assert "markdown.render" in verify_commands
    assert jobs["pypi"]["needs"] == "verify-release"
    assert "vars.ASELENIUM_PUBLISH_ENABLED == 'true'" in jobs["pypi"]["if"]
    assert jobs["pypi"]["environment"]["name"] == "pypi"
    assert jobs["pypi"]["permissions"] == {"id-token": "write"}
    assert all("checkout" not in step.get("uses", "") for step in jobs["pypi"]["steps"])
    publish_step = next(
        step
        for step in jobs["pypi"]["steps"]
        if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@")
    )
    assert "with" not in publish_step

    github_release = jobs["github-release"]
    assert set(github_release["needs"]) == {"verify-release", "pypi"}
    assert github_release["permissions"] == {"contents": "write"}
    release_commands = "\n".join(
        step.get("run", "") for step in github_release["steps"]
    )
    assert "gh release create" in release_commands
    assert "--notes-file" in release_commands
    assert "--verify-tag" in release_commands
    assert "dist/*.whl dist/*.tar.gz SHA256SUMS" in release_commands


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


@pytest.mark.parametrize("name", ["tests.yml", "release.yml"])
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
