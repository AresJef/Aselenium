"""Build and inspect real distribution artifacts without changing the checkout.

Build tools and runtime dependencies must already exist in the test interpreter.
No isolated build environment, dependency installation, or vendor request is used.
Resource presence and clean-wheel manager construction are mandatory contracts.
Only locally built wheels are target-installed, with --no-deps and --no-index.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import textwrap
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from readme_renderer import markdown

pytestmark = pytest.mark.packaging


REPOSITORY = Path(__file__).resolve().parents[1]
WHEEL_RESOURCE = "aselenium/manager/geckodriver/compatibility.json"
SOURCE_RESOURCE = "src/" + WHEEL_RESOURCE
ARTIFACT_KINDS = ("source-wheel", "sdist", "sdist-wheel")


def test_pypi_readme_renders_without_repository_relative_links() -> None:
    """Require renderable metadata links that also work outside GitHub."""
    readme = (REPOSITORY / "README.md").read_text()
    assert markdown.render(readme) is not None
    relative_links = re.findall(
        r"\]\((?!#|https?://|mailto:)([^)]+)\)",
        readme,
    )
    assert relative_links == []


REMOVED_MODULES = (
    "aselenium/manager/migration.py",
    "aselenium/javascript/get_attribute.py",
    "aselenium/javascript/is_viewable.py",
)


def subprocess_environment() -> Any:
    """Subprocess environment.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        PIP_NO_INDEX="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
    )
    return environment


def run_checked(command: Any, *, cwd: Any, environment: Any) -> Any:
    """Run checked.

    Args:
        command: Fixture or parametrized command input for this regression.
        cwd: Fixture or parametrized cwd input for this regression.
        environment: Fixture or parametrized environment input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        pytest.fail(
            f"Command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            pytrace=False,
        )
    return result


def single_artifact(directory: Any, pattern: Any) -> Any:
    """Single artifact.

    Args:
        directory: Fixture or parametrized directory input for this regression.
        pattern: Fixture or parametrized pattern input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    matches = list(directory.glob(pattern))
    if len(matches) != 1:
        pytest.fail(f"Expected one {pattern} in {directory}, found {matches}")
    return matches[0]


def unpack_source_archive(archive_path: Any, destination: Any) -> Any:
    """Unpack our generated sdist without relying on version-specific filters.

    Args:
        archive_path: Fixture or parametrized archive path input for this regression.
        destination: Fixture or parametrized destination input for this regression.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    destination.mkdir()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                pytest.fail(f"Unsafe sdist member: {member.name!r}")
            if not member.isdir() and not member.isfile():
                pytest.fail(f"Unexpected non-file sdist member: {member.name!r}")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    pytest.fail(f"Cannot read sdist member: {member.name!r}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        pytest.fail(f"Expected a single sdist project directory, found {roots}")
    return roots[0]


@pytest.fixture(scope="module")
def built_distributions(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Built distributions.

    Args:
        tmp_path_factory: Pytest factory for temporary directories shared by fixture scopes.

    Returns:
        Fixture value or simulated response used by the regression.
    """
    workspace = tmp_path_factory.mktemp("distribution-build")
    source = workspace / "source"
    shutil.copytree(
        REPOSITORY,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "venv",
            ".tox",
            ".nox",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            "*.egg-info",
            "build",
            "dist",
            ".demo-cache",
            ".demo-output",
        ),
    )
    environment = subprocess_environment()
    direct_output = workspace / "direct-dist"
    run_checked(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--sdist",
            "--outdir",
            str(direct_output),
        ],
        cwd=source,
        environment=environment,
    )
    source_wheel = single_artifact(direct_output, "*.whl")
    sdist = single_artifact(direct_output, "*.tar.gz")
    restored_source = unpack_source_archive(sdist, workspace / "restored-sdist")
    rebuilt_output = workspace / "rebuilt-dist"
    run_checked(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--outdir",
            str(rebuilt_output),
        ],
        cwd=restored_source,
        environment=environment,
    )
    return {
        "source-wheel": source_wheel,
        "sdist": sdist,
        "sdist-wheel": single_artifact(rebuilt_output, "*.whl"),
    }


def test_sdist_contains_repeatable_acceptance_fixtures(
    built_distributions: dict[str, Path],
) -> None:
    """Keep TLS, typing and minimum-version fixtures in the runnable source archive.

    Args:
        built_distributions: Locally built source and wheel artifacts.
    """
    required = {
        "requirements.txt",
        "requirements-minimum.txt",
        "src/quick_start.py",
        "docs/release-acceptance.md",
        "docs/baselines/release-acceptance-validation.json",
        "tests/fixtures/tls/loopback-cert.pem",
        "tests/fixtures/tls/loopback-key.pem",
        "tests/fixtures/tls/README.md",
        "tests/typing/public_api.py",
        "scripts/test_installed_browser.py",
        "scripts/run_reliability.py",
        "scripts/_owned_subprocess.py",
        "scripts/check_public_typing.py",
        "scripts/check_coverage.py",
    }
    with tarfile.open(built_distributions["sdist"], "r:gz") as archive:
        members = {
            str(
                PurePosixPath(member.name).relative_to(
                    PurePosixPath(member.name).parts[0]
                )
            ): member
            for member in archive.getmembers()
            if member.isfile()
        }
        assert required <= members.keys()
        for name in required:
            source = archive.extractfile(members[name])
            assert source is not None
            with source:
                assert source.read() == (REPOSITORY / name).read_bytes()


@pytest.mark.parametrize("kind", ARTIFACT_KINDS)
def test_distribution_archives_are_readable(
    built_distributions: Any, kind: Any
) -> None:
    """Verify distribution archives are readable.

    Args:
        built_distributions: Fixture or parametrized built distributions input for this regression.
        kind: Fixture or parametrized kind input for this regression.
    """
    path = built_distributions[kind]
    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            assert members
            forbidden = ("src/demo.py", *("src/" + name for name in REMOVED_MODULES))
            assert not any(
                member.name.endswith("/" + name)
                for member in members
                for name in forbidden
            )
            assert not any("/src/test_files/" in member.name for member in members)
            # Setuptools generates a tiny egg_info-only setup.cfg inside an sdist.
            # It is not the removed project configuration or compatibility code.
            generated = next(
                member for member in members if member.name.endswith("/setup.cfg")
            )
            config = configparser.ConfigParser()
            config.read_string(archive.extractfile(generated).read().decode("utf-8"))
            assert config.sections() == ["egg_info"]
            assert set(config["egg_info"]) <= {
                "tag_build",
                "tag_date",
                "tag_svn_revision",
            }
            assert any(member.name.endswith("/pyproject.toml") for member in members)
            assert any(
                member.name.endswith("/.github/workflows/tests.yml")
                for member in members
            )
            assert any(
                member.name.endswith("/.github/workflows/release.yml")
                for member in members
            )
            assert any(
                member.name.endswith("/src/aselenium/__init__.py") for member in members
            )
            for asset in (
                "src/quick_start.py",
                "src/demo_local.py",
                "src/demo_google.py",
                "src/_demo_support.py",
                "docs/demo.md",
                "docs/demo-local.md",
                "docs/demo-google.md",
                "src/demo_assets/index.html",
                "src/demo_assets/frame.html",
                "src/demo_assets/second.html",
                "src/demo_assets/upload.txt",
                "src/demo_assets/firefox-addon/manifest.json",
                "src/demo_assets/firefox-addon/marker.js",
            ):
                assert any(member.name.endswith("/" + asset) for member in members)
    else:
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert "aselenium/__init__.py" in archive.namelist()
            assert any(
                name.endswith(".dist-info/METADATA") for name in archive.namelist()
            )
            assert not any(
                name.startswith("demo_assets/") for name in archive.namelist()
            )
            assert not {
                "demo.py",
                "demo_local.py",
                "demo_google.py",
                "_demo_support.py",
            }.intersection(archive.namelist())
            assert not set(REMOVED_MODULES).intersection(archive.namelist())
            assert not any(
                name.startswith("test_files/") for name in archive.namelist()
            )


@pytest.mark.parametrize("kind", ("source-wheel", "sdist-wheel"))
def test_wheel_metadata_preserves_runtime_contract(
    built_distributions: Any, kind: Any
) -> None:
    """Verify wheel metadata preserves runtime contract.

    Args:
        built_distributions: Fixture or parametrized built distributions input for this regression.
        kind: Fixture or parametrized kind input for this regression.
    """
    with zipfile.ZipFile(built_distributions[kind]) as archive:
        name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(name))
    assert metadata["Name"] == "aselenium"
    assert metadata["Version"] == "2.0.0"
    assert metadata["Requires-Python"] == ">=3.10"
    assert metadata["License-Expression"] == "Apache-2.0"
    dependencies = metadata.get_all("Requires-Dist")
    core = [value for value in dependencies if ";" not in value]
    assert set(core) == {"aiohttp>=3.14.3", "psutil>=5.8.0", "orjson>=3.11.6"}
    assert not any("pandas" in value or "pyarrow" in value for value in dependencies)
    assert "legacy-cache" not in metadata.get_all("Provides-Extra", [])


@pytest.mark.parametrize("kind", ARTIFACT_KINDS)
@pytest.mark.regression
def test_distribution_includes_gecko_compatibility_resource(
    built_distributions: Any, kind: Any
) -> None:
    """DRV-PACKAGE-RESOURCE: ship identical data through both build paths.

    Args:
        built_distributions: Fixture or parametrized built distributions input for this regression.
        kind: Fixture or parametrized kind input for this regression.
    """
    path = built_distributions[kind]
    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.endswith("/" + SOURCE_RESOURCE)
            ]
            assert len(members) == 1, f"{kind} must contain one {SOURCE_RESOURCE}"
            with archive.extractfile(members[0]) as resource:
                content = resource.read()
    else:
        with zipfile.ZipFile(path) as archive:
            assert archive.namelist().count(WHEEL_RESOURCE) == 1
            content = archive.read(WHEEL_RESOURCE)
            assert "aselenium/py.typed" in archive.namelist()
    assert content == (REPOSITORY / SOURCE_RESOURCE).read_bytes()
    assert isinstance(json.loads(content), dict)


@pytest.mark.parametrize("kind", ("source-wheel", "sdist-wheel"))
def test_wheel_imports_without_source_checkout(
    built_distributions: Any, kind: Any, tmp_path: Path
) -> None:
    """Verify wheel imports without source checkout.

    Args:
        built_distributions: Fixture or parametrized built distributions input for this regression.
        kind: Fixture or parametrized kind input for this regression.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    installed = tmp_path / "installed-wheel"
    working_directory = tmp_path / "outside-checkout"
    working_directory.mkdir()
    environment = subprocess_environment()
    run_checked(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--no-cache-dir",
            "--target",
            str(installed),
            str(built_distributions[kind]),
        ],
        cwd=working_directory,
        environment=environment,
    )
    environment["PYTHONPATH"] = str(installed)
    script = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path
        import sys

        wheel_root = Path(sys.argv[1]).resolve()
        repository = Path(sys.argv[2]).resolve()
        dependency_paths = json.loads(sys.argv[3])
        cache_root = Path(sys.argv[4]).resolve()
        # -S bypasses .pth files and sitecustomize. Add dependency directories
        # explicitly, without processing their editable-install hooks.
        sys.path.extend(entry for entry in dependency_paths if entry not in sys.path)
        excluded = {repository, repository / "src"}
        sys.path[:] = [entry for entry in sys.path
                       if entry and Path(entry).resolve() not in excluded]

        def isolated_expanduser(path):
            value = os.fspath(path)
            text = os.fsdecode(value)
            if text == "~" or text.startswith(("~/", "~\\\\")):
                replacement = str(cache_root) + text[1:]
                return os.fsencode(replacement) if isinstance(value, bytes) else replacement
            if text.startswith("~"):
                raise RuntimeError("User-specific home lookup is not permitted in this test")
            return value

        # Protect the real user's cache even if an import-time regression starts
        # creating a default manager; that side effect will then fail safely.
        os.path.expanduser = isolated_expanduser
        import builtins
        original_import = builtins.__import__
        def without_legacy(name, *args, **kwargs):
            if name.split(".")[0] in {"pandas", "pyarrow"}:
                raise AssertionError("Core imports a legacy migration dependency")
            return original_import(name, *args, **kwargs)
        builtins.__import__ = without_legacy
        import aselenium
        import importlib.util
        for removed_module in ("aselenium.manager.migration", "aselenium.javascript.get_attribute", "aselenium.javascript.is_viewable"):
            assert importlib.util.find_spec(removed_module) is None
        assert not hasattr(aselenium.Element, "visible")
        assert not hasattr(aselenium.Element, "viewable")
        assert not hasattr(aselenium.Element, "get_attribute")
        from aselenium import manager
        from aselenium import options as options_module
        from aselenium import service as service_module
        from aselenium.manager import driver as driver_module
        from importlib import resources
        import aiohttp
        import asyncio
        import socket

        class UnexpectedConstructionSideEffect(BaseException):
            pass

        def forbidden(*args, **kwargs):
            raise UnexpectedConstructionSideEffect(
                "Construction must not launch processes, use the network, or create profiles"
            )

        async def forbidden_async(*args, **kwargs):
            forbidden()

        driver_module.Popen = forbidden
        service_module.Popen = forbidden
        options_module.mkdtemp = forbidden
        socket.socket.connect = forbidden
        socket.socket.connect_ex = forbidden
        socket.create_connection = forbidden
        aiohttp.ClientSession._request = forbidden_async
        asyncio.create_subprocess_exec = forbidden_async
        asyncio.create_subprocess_shell = forbidden_async

        assert Path(aselenium.__file__).resolve().is_relative_to(wheel_root)
        assert Path(manager.__file__).resolve().is_relative_to(wheel_root)
        for name in manager.__all__:
            assert getattr(aselenium, name) is getattr(manager, name)
        resource = resources.files("aselenium.manager").joinpath(
            "geckodriver"
        ).joinpath("compatibility.json")
        assert resource.is_file()
        data = json.loads(resource.read_text(encoding="utf-8"))
        manager.FirefoxDriverManager.load_driver_compatibility_table()
        loaded = {
            str(version): {key: str(value) for key, value in bounds.items()}
            for version, bounds in manager.FirefoxDriverManager._GECKODRIVER_TABLE.items()
        }
        assert loaded == data
        # Neither importing nor the class-level loader creates a default cache.
        assert not (cache_root / ".aselenium").exists()
        explicit_cache = cache_root.parent / "explicit-manager-cache"
        explicit_cache.mkdir()
        instance = manager.FirefoxDriverManager(directory=str(explicit_cache))
        assert instance._GECKODRIVER_TABLE is manager.FirefoxDriverManager._GECKODRIVER_TABLE
        assert (explicit_cache / ".aselenium").is_dir()

        facades = []
        for name in ("Chrome", "Chromium", "Edge", "Firefox", "Safari"):
            facade_class = getattr(aselenium, name)
            if name == "Safari":
                facade = facade_class()
                assert facade.manager._file_manager is None
            else:
                facade_cache = cache_root.parent / ("facade-cache-" + name)
                facade_cache.mkdir()
                facade = facade_class(directory=str(facade_cache))
                assert (facade_cache / ".aselenium").is_dir()
            assert isinstance(facade.manager, getattr(manager, name + "DriverManager"))
            assert isinstance(facade.options, getattr(aselenium, name + "Options"))
            assert getattr(facade.options, "_profile", None) is None
            for field in ("_driver_location", "_driver_version",
                          "_browser_location", "_browser_version"):
                assert getattr(facade.manager, field) is None
            facades.append(name)
        assert not (cache_root / ".aselenium").exists()
        print(json.dumps({"exports": manager.__all__, "resource": data, "facades": facades}))
        """
    )
    cache_root = tmp_path / "default-cache"
    cache_root.mkdir()
    dependency_paths = sorted(
        {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}
    )
    result = run_checked(
        [
            sys.executable,
            "-B",
            "-S",
            "-c",
            script,
            str(installed),
            str(REPOSITORY),
            json.dumps(dependency_paths),
            str(cache_root),
        ],
        cwd=working_directory,
        environment=environment,
    )
    payload = json.loads(result.stdout)
    assert "FirefoxDriverManager" in payload["exports"]
    assert payload["facades"] == ["Chrome", "Chromium", "Edge", "Firefox", "Safari"]
    expected = json.loads((REPOSITORY / SOURCE_RESOURCE).read_text(encoding="utf-8"))
    assert payload["resource"] == expected
