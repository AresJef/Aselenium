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

from aselenium import Proxy, Timeouts
from aselenium._wait import T, poll
from aselenium.manager.version import Version

ROOT = Path(__file__).resolve().parents[1]


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
