"""Fail-closed regressions for secret-based publication of tested release files."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import prepare_pypi_promotion as promotion

ROOT = Path(__file__).resolve().parents[1]
TAG = "v2.0.0"
RUN_ID = "12345"
SLUG = "AresJef/Aselenium"
COMMIT = "a" * 40
WHEEL = "aselenium-2.0.0-py3-none-any.whl"
SDIST = "aselenium-2.0.0.tar.gz"


def successful_provenance() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build successful run evidence from the actual configured CI matrix.

    Returns:
        Independent run and complete job API response fixtures.
    """
    workflow = yaml.load(
        (ROOT / ".github/workflows/tests.yml").read_text(), Loader=yaml.BaseLoader
    )
    matrix = workflow["jobs"]["package-tests"]["strategy"]["matrix"]
    names = [
        "validate / Build canonical distributions",
        "Verify tagged release artifacts",
    ]
    names.extend(
        f"validate / Python {version} / ubuntu-latest / current"
        for version in matrix["python-version"]
    )
    names.extend(
        f"validate / Python {entry['python-version']} / {entry['os']} / {entry['dependencies']}"
        for entry in matrix["include"]
    )
    names.extend(
        f"validate / native-browsers ({entry['os']}, {entry['browser']})"
        for entry in workflow["jobs"]["native-browsers"]["strategy"]["matrix"][
            "include"
        ]
    )
    run = {
        "id": int(RUN_ID),
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "path": ".github/workflows/release.yml",
        "head_branch": TAG,
        "head_sha": COMMIT,
        "repository": {"full_name": SLUG},
        "head_repository": {"full_name": SLUG},
    }
    jobs = {
        "total_count": len(names),
        "jobs": [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in names
        ],
    }
    return run, jobs


def check_run(run: dict[str, Any], jobs: dict[str, Any]) -> None:
    """Validate a fixture against the fixed expected release identity.

    Args:
        run: Workflow run evidence under test.
        jobs: Required validation job evidence under test.
    """
    promotion.validate_run(run, jobs, tag=TAG, run_id=RUN_ID, slug=SLUG, commit=COMMIT)


@pytest.mark.parametrize(
    "tag,run_id,slug",
    [
        ("", RUN_ID, SLUG),
        ("main", RUN_ID, SLUG),
        ("v2.0.0\n", RUN_ID, SLUG),
        ("v2/../main", RUN_ID, SLUG),
        ("v$(id)", RUN_ID, SLUG),
        (TAG, "0", SLUG),
        (TAG, "-1", SLUG),
        (TAG, "1/jobs", SLUG),
        (TAG, RUN_ID, "https://github.com/AresJef/Aselenium"),
    ],
)
def test_promotion_rejects_unsafe_identifiers(tag: str, run_id: str, slug: str) -> None:
    """Reject identifiers that could select a different API or Git resource.

    Args:
        tag: Possibly malformed tag name.
        run_id: Possibly malformed workflow-run identifier.
        slug: Possibly malformed repository identifier.
    """
    with pytest.raises(ValueError):
        promotion.validate_inputs(tag, run_id, slug)


def test_promotion_accepts_complete_current_validation_matrix() -> None:
    """Accept the full configured package/browser matrix, with PyPI skipped."""
    promotion.validate_inputs(TAG, RUN_ID, SLUG)
    run, jobs = successful_provenance()
    jobs["jobs"].append(
        {"name": "Publish tested distributions to PyPI", "conclusion": "skipped"}
    )
    jobs["total_count"] += 1
    check_run(run, jobs)


@pytest.mark.parametrize(
    "key,value",
    [
        ("id", 67890),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("event", "pull_request"),
        ("path", ".github/workflows/tests.yml"),
        ("head_branch", "main"),
        ("head_sha", "b" * 40),
        ("repository", {"full_name": "outsider/Aselenium"}),
        ("head_repository", {"full_name": "outsider/Aselenium"}),
    ],
)
def test_promotion_rejects_wrong_run_identity(key: str, value: Any) -> None:
    """Reject even successful runs that do not prove this release was tested.

    Args:
        key: Run response field to corrupt.
        value: Replacement value that must invalidate the evidence.
    """
    run, jobs = successful_provenance()
    run[key] = value
    with pytest.raises(ValueError):
        check_run(run, jobs)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "incomplete",
        "failed",
        "skipped",
        "running",
        "extra-failed",
    ],
)
def test_promotion_requires_every_validation_job(defect: str) -> None:
    """Reject missing, skipped, failed or incomplete validation evidence.

    Args:
        defect: Negative-control mutation applied to the job evidence.
    """
    run, jobs = successful_provenance()
    if defect == "missing":
        jobs["jobs"].pop()
        jobs["total_count"] -= 1
    elif defect == "duplicate":
        jobs["jobs"].append(copy.deepcopy(jobs["jobs"][0]))
        jobs["total_count"] += 1
    elif defect == "incomplete":
        jobs["total_count"] += 1
    elif defect == "extra-failed":
        jobs["jobs"].append(
            {"name": "validate / additional test", "conclusion": "failure"}
        )
        jobs["total_count"] += 1
    elif defect == "running":
        jobs["jobs"][0]["status"] = "in_progress"
    else:
        jobs["jobs"][0]["conclusion"] = "failure" if defect == "failed" else "skipped"
    with pytest.raises(ValueError):
        check_run(run, jobs)


def release_files(directory: Path, *, published: bool) -> None:
    """Write deterministic stand-in release bytes and their checksum manifest.

    Args:
        directory: Temporary directory in which to create the fixture.
        published: Whether to include the public SHA256SUMS asset.
    """
    directory.mkdir(parents=True)
    manifest = []
    for name in (WHEEL, SDIST):
        payload = name.encode()
        (directory / name).write_bytes(payload)
        manifest.append(f"{hashlib.sha256(payload).hexdigest()}  dist/{name}")
    if published:
        (directory / "SHA256SUMS").write_text(
            "\n".join(manifest) + "\n", encoding="utf-8"
        )


def test_promotion_requires_byte_identical_files(tmp_path: Path) -> None:
    """Accept only matching public files, native-tested artifacts and hashes.

    Args:
        tmp_path: Disposable directory for stand-in distribution files.
    """
    candidate, published = tmp_path / "candidate", tmp_path / "published"
    release_files(candidate, published=False)
    release_files(published, published=True)
    promotion.verify_distributions(candidate, published, "2.0.0")
    (published / WHEEL).write_bytes(b"untested replacement")
    with pytest.raises(ValueError, match="differs from tested"):
        promotion.verify_distributions(candidate, published, "2.0.0")


@pytest.mark.parametrize(
    "defect", ["missing", "extra-candidate", "extra-published", "directory", "checksum"]
)
def test_promotion_rejects_bad_artifact_sets(tmp_path: Path, defect: str) -> None:
    """Reject incomplete or ambiguous artifacts and a false checksum manifest.

    Args:
        tmp_path: Disposable directory containing the artifact fixtures.
        defect: File-set or checksum mutation that must fail verification.
    """
    candidate, published = tmp_path / "candidate", tmp_path / "published"
    release_files(candidate, published=False)
    release_files(published, published=True)
    if defect == "missing":
        (candidate / WHEEL).unlink()
    elif defect == "extra-candidate":
        (candidate / "other.whl").touch()
    elif defect == "extra-published":
        (published / "other.whl").touch()
    elif defect == "directory":
        (candidate / WHEEL).unlink()
        (candidate / WHEEL).mkdir()
    else:
        (published / "SHA256SUMS").write_text("0" * 64 + "  dist/other.whl\n")
    with pytest.raises(ValueError):
        promotion.verify_distributions(candidate, published, "2.0.0")


@pytest.mark.parametrize("release_defect", [None, "draft", "tag", "unpublished"])
def test_promotion_main_recovers_without_rebuilding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_defect: str | None,
) -> None:
    """Exercise the complete read-only provenance and artifact recovery sequence.

    Args:
        tmp_path: Disposable checkout root for the promotion output.
        monkeypatch: Fixture replacing only the Git/GitHub command boundaries.
        release_defect: Optional invalid published-release metadata control.
    """
    run, jobs = successful_provenance()
    release = {"tag_name": TAG, "draft": False, "published_at": "2026-09-05T00:00:00Z"}
    if release_defect == "draft":
        release["draft"] = True
    elif release_defect == "tag":
        release["tag_name"] = "v2.0.1"
    elif release_defect == "unpublished":
        release["published_at"] = None
    calls = []

    def command(repository: Path, *arguments: str) -> str:
        """Return isolated evidence instead of invoking Git or GitHub.

        Args:
            repository: Expected disposable checkout root.
            *arguments: Read-only command arguments chosen by the promotion.

        Returns:
            Stand-in API or Git output for the expected operation.
        """
        assert repository == tmp_path
        calls.append(arguments)
        if arguments[:2] == ("git", "show"):
            return '[project]\nname = "aselenium"\nversion = "2.0.0"\n'
        if arguments[:2] == ("gh", "api"):
            if "/jobs?" in arguments[2]:
                return json.dumps(jobs)
            return json.dumps(release if "/releases/" in arguments[2] else run)
        assert arguments[:3] in {
            ("gh", "run", "download"),
            ("gh", "release", "download"),
        }
        destination = Path(arguments[arguments.index("--dir") + 1])
        release_files(destination, published=arguments[1] == "release")
        return ""

    monkeypatch.setattr(
        promotion, "__file__", str(tmp_path / "scripts/prepare_pypi_promotion.py")
    )
    monkeypatch.setattr(promotion, "run_command", command)
    monkeypatch.setattr(promotion, "resolve_commit", lambda *_: COMMIT)
    monkeypatch.setattr(promotion, "check_tag_ancestry", lambda *_: None)
    for key, value in {
        "RELEASE_TAG": TAG,
        "VALIDATION_RUN": RUN_ID,
        "GITHUB_REPOSITORY": SLUG,
    }.items():
        monkeypatch.setenv(key, value)
    if release_defect:
        with pytest.raises(ValueError, match="published GitHub Release"):
            promotion.main()
        assert not (tmp_path / "dist").exists()
        assert len(calls) == 4
    else:
        promotion.main()
        assert {path.name for path in (tmp_path / "dist").iterdir()} == {WHEEL, SDIST}
        assert (tmp_path / "dist" / WHEEL).read_bytes() == WHEEL.encode()
        with pytest.raises(FileExistsError):
            promotion.main()


def test_manual_promotion_is_isolated_main_only_and_token_authenticated() -> None:
    """Keep recovery manual, test-gated, isolated from builds and least privileged."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/promote-pypi.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert set(workflow["on"]["workflow_dispatch"]["inputs"]) == {
        "release_tag",
        "validation_run",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert (
        workflow["concurrency"]["group"]
        == "release-refs/tags/${{ inputs.release_tag }}"
    )
    verify, publish = workflow["jobs"]["verify-promotion"], workflow["jobs"]["pypi"]
    assert verify["if"] == "github.ref == 'refs/heads/main'"
    assert verify["permissions"] == {"contents": "read", "actions": "read"}
    commands = "\n".join(step.get("run", "") for step in verify["steps"])
    assert "python -m scripts.prepare_pypi_promotion" in commands
    assert "twine check --strict" in commands
    assert "python -m build" not in commands
    assert "PYPI_API_TOKEN" not in str(verify)
    assert publish["needs"] == "verify-promotion"
    assert "if" not in publish
    assert publish["permissions"] == {"contents": "read"}
    assert all("checkout" not in step.get("uses", "") for step in publish["steps"])
    action = next(
        step for step in publish["steps"] if step.get("uses", "").startswith("pypa/")
    )
    assert action["with"] == {
        "user": "__token__",
        "password": "${{ secrets.PYPI_API_TOKEN }}",
        "attestations": "false",
    }
