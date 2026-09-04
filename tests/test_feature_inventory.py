"""Ensure feature reporting cannot confuse imported definitions with executed bodies."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def reporter() -> ModuleType:
    """Load the source-only reporting helper without importing a browser.

    Returns:
        Standalone inventory module under test.
    """
    path = Path(__file__).resolve().parents[1] / "scripts/report_feature_coverage.py"
    spec = importlib.util.spec_from_file_location("feature_report_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_selects_public_bodies_and_distinct_properties(
    reporter: ModuleType,
) -> None:
    """Keep constructors and getter/setters while excluding private implementation names.

    Args:
        reporter: Loaded coverage inventory helper.
    """
    tree = ast.parse(
        "class Public:\n"
        "    def __init__(self):\n"
        '        """Constructor."""\n'
        "        self._value = 0\n"
        "    @property\n"
        "    def value(self):\n"
        '        """Getter."""\n'
        "        return self._value\n"
        "    @value.setter\n"
        "    def value(self, value):\n"
        "        self._value = value\n"
        "    def _private(self):\n"
        "        return 1\n"
        "class _Private:\n"
        "    def visible(self):\n"
        "        return 1\n"
    )
    definitions = dict(reporter.public_definitions(tree))
    assert list(definitions) == [
        "Public.__init__",
        "Public.value.get",
        "Public.value.setter",
    ]
    assert reporter.body_lines(definitions["Public.__init__"]) == {4}
    assert reporter.body_lines(definitions["Public.value.get"]) == {8}
    assert reporter.body_lines(definitions["Public.value.setter"]) == {11}


def test_inventory_excludes_import_only_execution(
    tmp_path: Path, reporter: ModuleType
) -> None:
    """Report a definition as unexercised unless executable body lines were measured.

    Args:
        tmp_path: Temporary synthetic checkout containing one module.
        reporter: Loaded coverage inventory helper.
    """
    relative = "src/aselenium/example.py"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        "def imported():\n"
        '    """Uncalled public function."""\n'
        "    return 1\n"
        "def exercised():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    report = reporter.build_inventory(
        tmp_path,
        {
            "files": {
                relative: {
                    "executed_lines": [1, 4, 5],
                    "missing_lines": [3],
                    "contexts": {"1": [""], "5": ["test_example.test_contract"]},
                }
            }
        },
    )
    assert report["summary"] == {
        "callables": 2,
        "body_exercised": 1,
        "with_named_test_context": 1,
        "not_exercised": [relative + ":imported"],
    }
    assert report["callables"][0]["missing_body_lines"] == [3]
    assert report["callables"][1]["test_contexts"] == ["test_example.test_contract"]


def test_nested_helper_documentation_is_not_execution(reporter: ModuleType) -> None:
    """Exclude nested helper headers/docstrings but retain their enclosing behavior.

    Args:
        reporter: Loaded coverage inventory helper.
    """
    tree = ast.parse(
        "def outer():\n"
        '    """Public wrapper."""\n'
        "    def helper():\n"
        '        """Nested implementation."""\n'
        "        return 1\n"
        "    return helper()\n"
    )
    node = dict(reporter.public_definitions(tree))["outer"]
    assert reporter.body_lines(node) == {5, 6}
