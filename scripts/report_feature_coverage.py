"""Map source-defined public callables to measured body coverage and test contexts.

Generate coverage JSON with ``coverage json --show-contexts`` first. This report
distinguishes executing an implementation from verifying all of its behavior.
It includes public-named source definitions and constructors, not inherited
aliases, dynamically generated members, constants, or a promise of supported API.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def public_definitions(
    node: ast.Module | ast.ClassDef, prefix: str = ""
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield public-named definitions, preserving property getter/setter identities.

    Args:
        node: Parsed module or public class to traverse.
        prefix: Qualified name of the containing public class.

    Yields:
        Qualified callable name and its syntax-tree definition.
    """
    for child in node.body:
        if isinstance(child, ast.ClassDef) and not child.name.startswith("_"):
            yield from public_definitions(child, prefix + child.name + ".")
        elif isinstance(child, FUNCTIONS) and (
            not child.name.startswith("_") or child.name == "__init__"
        ):
            suffix = ""
            for decorator in child.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "property":
                    suffix = ".get"
                elif isinstance(decorator, ast.Attribute) and decorator.attr in (
                    "setter",
                    "deleter",
                ):
                    suffix = "." + decorator.attr
            yield prefix + child.name + suffix, child


def body_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    """Select body lines without counting definitions or docstrings as execution.

    Args:
        node: Function definition, including any nested helper implementations.

    Returns:
        Candidate body lines; callers intersect these with executable coverage lines.
        Nested helper bodies belong to their enclosing public implementation.
    """
    lines = set(range(node.body[0].lineno, (node.end_lineno or node.lineno) + 1))
    for child in ast.walk(node):
        if isinstance(child, (*FUNCTIONS, ast.ClassDef)):
            first = child.body[0]
            lines.difference_update(range(child.lineno, first.lineno))
            for decorator in child.decorator_list:
                lines.difference_update(
                    range(
                        decorator.lineno, (decorator.end_lineno or decorator.lineno) + 1
                    )
                )
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                lines.difference_update(
                    range(first.lineno, (first.end_lineno or first.lineno) + 1)
                )
    return lines


def build_inventory(root: Path, coverage: dict[str, Any]) -> dict[str, Any]:
    """Associate public callable bodies with line evidence from a coverage JSON file.

    Args:
        root: Checkout root containing src/aselenium.
        coverage: JSON output from coverage.py, preferably with dynamic test contexts.

    Returns:
        Portable inventory, aggregate counts, and explicit interpretation limits.
    """
    entries: list[dict[str, Any]] = []
    for relative, measured in sorted(coverage["files"].items()):
        path = Path(relative)
        path = path if path.is_absolute() else root / path
        path = path.resolve()
        try:
            package_path = path.relative_to(root / "src" / "aselenium")
        except ValueError:
            continue
        if any(
            part.startswith("_") and part != "__init__.py"
            for part in package_path.parts
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        executed = set(measured["executed_lines"])
        missing = set(measured["missing_lines"])
        contexts = measured.get("contexts", {})
        for name, node in public_definitions(tree):
            executable = body_lines(node) & (executed | missing)
            hit = executable & executed
            tests = sorted(
                {
                    context
                    for line in hit
                    for context in contexts.get(str(line), [])
                    if context
                }
            )
            entries.append(
                {
                    "file": path.relative_to(root).as_posix(),
                    "name": name,
                    "line": node.lineno,
                    "body_exercised": bool(hit),
                    "executed_body_lines": len(hit),
                    "executable_body_lines": len(executable),
                    "missing_body_lines": sorted(executable & missing),
                    "test_contexts": tests,
                }
            )
    return {
        "scope": "public-named source definitions and constructors in non-private package modules; inherited implementations counted once",
        "interpretation": "body execution is not behavioral correctness; expected-failure tests also contribute coverage; unnamed fixture/import/native-thread activity may have no test context; nested helper bodies are included",
        "summary": {
            "callables": len(entries),
            "body_exercised": sum(entry["body_exercised"] for entry in entries),
            "with_named_test_context": sum(
                bool(entry["test_contexts"]) for entry in entries
            ),
            "not_exercised": [
                entry["file"] + ":" + entry["name"]
                for entry in entries
                if not entry["body_exercised"]
            ],
        },
        "callables": entries,
    }


def main() -> int:
    """Write a reproducible feature inventory from a measured coverage report.

    Returns:
        Zero after successfully reading coverage and writing the inventory.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    inventory = build_inventory(
        root, json.loads(args.coverage_json.read_text(encoding="utf-8"))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(inventory["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
