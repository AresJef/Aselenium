"""Regression gates for source documentation, imports, and typed helper contracts."""

from __future__ import annotations

import ast
import doctest
import importlib.util
import inspect
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, get_type_hints

import pytest

import aselenium
from aselenium import Proxy, Timeouts
from aselenium import firefox as firefox_package
from aselenium import manager as manager_package
from aselenium._wait import T, poll
from aselenium.manager.version import Version

ROOT = Path(__file__).resolve().parents[1]


def test_root_exports_are_unique_resolved_and_cover_facade_packages() -> None:
    """Keep the formatted root facade complete and free of stale export names."""
    exports = aselenium.__all__
    assert len(exports) == len(set(exports))
    assert all(
        not name.startswith("_") and hasattr(aselenium, name) for name in exports
    )
    for package in (firefox_package, manager_package):
        for name in package.__all__:
            assert getattr(aselenium, name) is getattr(package, name)
    assert {
        "AseleniumDirectoryNotFoundError",
        "AseleniumInvalidPathError",
        "FirefoxAddon",
        "InstallationRequest",
        "InstallationResult",
        "WindowNotFoundError",
    } <= set(exports)
    assert "WindowNotFountError" not in exports


def test_all_sources_meet_structural_api_quality_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require documented and annotated definitions with no function-local imports.

    Args:
        monkeypatch: Pytest fixture restoring the temporary module registration.
    """
    spec = importlib.util.spec_from_file_location(
        "api_quality_under_test", ROOT / "scripts/check_api_quality.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclass processing consults the module namespace during execution.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    result = module.audit(ROOT)
    assert result.files >= 80
    assert result.functions >= 1500
    assert result.examples >= 170
    assert result.issues == []


def doc_examples() -> list[tuple[str, str]]:
    """Collect prompted Python examples from all package docstrings without importing modules.

    Returns:
        Pairs of a source label and its browser-example code.
    """
    examples = []
    for path in sorted((ROOT / "src/aselenium").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            doc = ast.get_docstring(node) or ""
            for index, example in enumerate(doctest.DocTestParser().get_examples(doc)):
                examples.append(
                    (
                        f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}:{index}",
                        example.source,
                    )
                )
    return examples


@pytest.mark.parametrize("label,code", doc_examples())
def test_browser_docstring_examples_are_valid_python(label: str, code: str) -> None:
    """Compile browser examples with top-level await without performing their actions.

    Args:
        label: Source location identifying the example.
        code: Example body to syntax-check without execution.
    """
    compile(code, label, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


@pytest.mark.parametrize(
    "target", [Proxy.__init__, Timeouts.__init__, Version.__init__]
)
def test_pure_docstring_examples_execute_without_external_resources(
    target: Callable[..., Any],
) -> None:
    """Run the pure configuration/version examples as doctests.

    Args:
        target: Documented constructor with deterministic, side-effect-free examples.
    """
    test = doctest.DocTestParser().get_doctest(
        inspect.getdoc(target) or "", {}, target.__qualname__, "<docstring>", 0
    )
    runner = doctest.DocTestRunner()
    runner.run(test)
    result = runner.summarize()
    assert result.attempted > 0
    assert result.failed == 0


def test_poll_retains_the_predicate_result_type() -> None:
    """Keep predicate results generic instead of erasing every wait result to Any."""
    hints = get_type_hints(poll)
    assert hints["check"] == Callable[[], Awaitable[T]]
    assert hints["return"] == T | None


@pytest.mark.parametrize(
    "doc,valid",
    [
        ("Summary.\n\nExample:\n    >>> value = 1\n", True),
        ("Summary.\n\nExamples:\n    >>> value = 1\n", False),
        ("Summary.\n\nExample:\n    >>> options.add_arguments(...)\n", False),
        (
            "Summary.\n\nExample:\n    >>> await (\n    ...     session.actions().click().perform()\n    ... )\n",
            True,
        ),
    ],
)
def test_prompted_example_style_guard(
    doc: str, valid: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enforce the requested singular header and executable continuation format.

    Args:
        doc: Synthetic docstring with valid or deliberately invalid example syntax.
        valid: Whether the style checker should accept the docstring.
        monkeypatch: Fixture restoring the checker module after dataclass loading.
    """
    spec = importlib.util.spec_from_file_location(
        "example_style_check", ROOT / "scripts/check_api_quality.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    result = module.Audit()
    module.check_examples(doc, "fixture", result)
    assert (not result.issues) is valid


def path_architecture_issues(module: Any, code: str) -> list[str]:
    """Run only the package Path-semantics checks against synthetic source.

    Args:
        module: Loaded API-quality checker module.
        code: Python module source to inspect.

    Returns:
        Path-architecture diagnostics produced for the synthetic module.
    """
    tree = ast.parse(code)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    result = module.Audit()
    module.check_path_architecture(
        tree, Path("src/aselenium/fixture.py"), parents, result
    )
    return result.issues


@pytest.mark.parametrize(
    "code,expected",
    [
        (
            "def save(path: str) -> bool:\n    return True\n",
            "public path boundary must accept PathInput",
        ),
        (
            "def save(path: Any) -> bool:\n    return True\n",
            "path annotation must not use Any",
        ),
        (
            "def save(path) -> bool:\n    return True\n",
            "missing path annotation",
        ),
        (
            "class Session:\n"
            "    @property\n"
            "    def driver_location(self) -> str:\n"
            "        return '/tmp/driver'\n",
            "filesystem result must retain Path semantics",
        ),
        (
            "class Session:\n"
            "    @property\n"
            "    def driver_location(self):\n"
            "        return Path('/tmp/driver')\n",
            "filesystem result must retain Path semantics",
        ),
        (
            "class Session:\n"
            "    @property\n"
            "    def driver_location(self) -> PathInput:\n"
            "        return '/tmp/driver'\n",
            "filesystem result must retain Path semantics",
        ),
        (
            "class Snapshot:\n    driver_location: str\n",
            "retained path must use Path",
        ),
        (
            "class Snapshot:\n    driver_location: PathInput\n",
            "retained path must use Path",
        ),
        (
            "class Snapshot:\n"
            "    def __init__(self) -> None:\n"
            "        self.driver_location: str = '/tmp/driver'\n",
            "retained path must use Path",
        ),
        (
            "class Options:\n"
            "    @property\n"
            "    def browser_location(self) -> Path | None:\n"
            "        return None\n"
            "\n"
            "    @browser_location.setter\n"
            "    def browser_location(self, value: str | None) -> None:\n"
            "        pass\n",
            "public path boundary must accept PathInput",
        ),
        (
            "async def install(binary: PathInput | None = None) -> str:\n"
            "    return '/tmp/driver'\n",
            "filesystem result must retain Path semantics",
        ),
        (
            "def _core(path: Path) -> Path:\n    return parse_path(str(path))\n",
            "stringify/reparse path workflow",
        ),
        (
            "def _core(path: Path) -> Path:\n"
            "    encoded = str(path)\n"
            "    return parse_path(encoded)\n",
            "stringify/reparse path workflow",
        ),
    ],
)
def test_path_architecture_guard_rejects_semantic_regressions(
    code: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject API narrowing, type erasure, and duplicate path parsing.

    Args:
        code: Synthetic package source containing one deliberate regression.
        expected: Diagnostic fragment proving the intended guard fired.
        monkeypatch: Fixture restoring the checker module registration.
    """
    spec = importlib.util.spec_from_file_location(
        "path_architecture_check", ROOT / "scripts/check_api_quality.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert any(expected in issue for issue in path_architecture_issues(module, code))


def test_path_architecture_guard_accepts_boundary_and_core_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept PathInput at public boundaries and Path throughout parsed cores.

    Args:
        monkeypatch: Fixture restoring the checker module registration.
    """
    spec = importlib.util.spec_from_file_location(
        "valid_path_architecture_check", ROOT / "scripts/check_api_quality.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    code = (
        "class Snapshot:\n"
        "    driver_location: Path\n"
        "\n"
        "class Client:\n"
        "    def __init__(self, directory: PathInput) -> None:\n"
        "        self.directory = parse_path(directory)\n"
        "\n"
        "    @property\n"
        "    def driver_location(self) -> Path:\n"
        "        return self.directory\n"
        "\n"
        "    def save(self, path: PathInput) -> Path:\n"
        "        return parse_path(path)\n"
        "\n"
        "    def quoted(self, path: 'PathInput') -> 'Path':\n"
        "        return parse_path(path)\n"
        "\n"
        "def _core(path: Path) -> Path:\n"
        "    return path\n"
    )
    assert path_architecture_issues(module, code) == []


@pytest.mark.parametrize(
    "code,expected",
    [
        ('await element.get_css_property("color")', "unknown Element.get_css_property"),
        ('await session.find_element("#name", timeout=0)', "unexpected keyword"),
        ("from aslenium import KeyboardKeys", "misspelled package"),
        ('await session.load("https://example.com")', None),
    ],
)
def test_example_contract_checker_rejects_real_api_mistakes(
    code: str, expected: str | None
) -> None:
    """Exercise positive and negative cases for the static example contract checker.

    Args:
        code: Example statement containing either a real API call or a deliberate defect.
        expected: Required diagnostic fragment, or None for a valid call.
    """
    spec = importlib.util.spec_from_file_location(
        "example_contracts_under_test", ROOT / "scripts/check_example_contracts.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    visitor = module.ExampleVisitor(module.Contracts(ROOT), "Session", "fixture")
    visitor.visit(ast.parse(code))
    if expected is None:
        assert visitor.issues == []
    else:
        assert any(expected in issue for issue in visitor.issues)


def test_all_prompted_examples_match_resolvable_api_contracts() -> None:
    """Reject known method-name and argument-binding mistakes in package examples."""
    spec = importlib.util.spec_from_file_location(
        "example_contracts_under_test", ROOT / "scripts/check_example_contracts.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.audit(ROOT) == []


def test_unset_proxy_properties_are_annotated_as_optional() -> None:
    """Keep public proxy return annotations consistent with their unset values."""
    proxy = Proxy()
    for name in ("http_proxy", "https_proxy", "socks_proxy", "no_proxy"):
        getter = getattr(Proxy, name).fget
        assert get_type_hints(getter)["return"] == str | None
        assert getattr(proxy, name) is None
