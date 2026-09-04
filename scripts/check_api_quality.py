"""Audit documentation, signature coverage, and function-local imports without importing code.

Run ``python scripts/check_api_quality.py`` from any directory. The checker scans
the checkout's package, demos, maintenance scripts, and tests. It prints a JSON
summary and exits nonzero on missing documentation, missing annotations, or a
function-local import. Conditional module-level OS and TYPE_CHECKING imports are
allowed. Coverage is a structural check, not proof that every annotation is correct.
"""

from __future__ import annotations

import ast
import doctest
import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Audit:
    """Accumulate structural source-quality metrics and actionable violations.

    Attributes:
        files: Number of Python source files inspected.
        functions: Number of function and method definitions, including nested ones.
        classes: Number of class definitions.
        examples: Number of definitions containing an Example section.
        issues: File-and-line diagnostics that should fail the quality gate.
    """

    files: int = 0
    functions: int = 0
    classes: int = 0
    examples: int = 0
    issues: list[str] = field(default_factory=list)


def python_files(root: Path) -> Iterator[Path]:
    """Yield the maintained Python sources, excluding environments and build output.

    Args:
        root: Repository root containing src, scripts, and tests.

    Yields:
        Python source paths in deterministic order.
    """
    for directory in ("src", "scripts", "tests"):
        yield from sorted((root / directory).rglob("*.py"))


def inspect_file(path: Path, root: Path, result: Audit) -> None:
    """Inspect one source file using its AST without executing imports or examples.

    Args:
        path: Python source file to inspect.
        root: Repository root used to produce relative diagnostics.
        result: Mutable aggregate receiving counts and violations.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    relative = path.relative_to(root)
    result.files += 1
    if not ast.get_docstring(tree):
        result.issues.append(f"{relative}:1: missing module docstring")
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, (*functions, ast.ClassDef)):
            doc = ast.get_docstring(node)
            result.examples += bool(doc and re.search(r"(?m)^Example:$", doc))
            if doc:
                check_examples(doc, f"{relative}:{node.lineno}:{node.name}", result)
            if not doc:
                result.issues.append(
                    f"{relative}:{node.lineno}: {node.name}: missing docstring"
                )
            if isinstance(node, ast.ClassDef):
                result.classes += 1
                continue
            result.functions += 1
            if node.returns is None:
                result.issues.append(
                    f"{relative}:{node.lineno}: {node.name}: missing return annotation"
                )
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            arguments += [
                arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None
            ]
            for argument in arguments:
                implicit_receiver = isinstance(
                    parents[node], ast.ClassDef
                ) and argument.arg in {"self", "cls"}
                if argument.annotation is None and not implicit_receiver:
                    result.issues.append(
                        f"{relative}:{argument.lineno}: {node.name}: untyped {argument.arg}"
                    )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            parent = parents.get(node)
            while parent is not None:
                if isinstance(parent, functions):
                    result.issues.append(
                        f"{relative}:{node.lineno}: function-local import in {parent.name}"
                    )
                    break
                parent = parents.get(parent)


def check_examples(doc: str, label: str, result: Audit) -> None:
    """Validate prompted Python examples without executing browser operations.

    Args:
        doc: Cleaned docstring containing prose and optional prompted examples.
        label: File, line, and definition name used in diagnostics.
        result: Aggregate receiving malformed-header, prompt, or syntax violations.
    """
    if re.search(r"(?m)^Examples:$", doc) or ".. code-block:: python" in doc:
        result.issues.append(f"{label}: use Example: with >>> and ... prompts")
    try:
        examples = doctest.DocTestParser().get_examples(doc)
        if re.search(r"(?m)^Example:$", doc) and not examples:
            result.issues.append(f"{label}: Example section has no prompted Python")
        for example in examples:
            compile(example.source, label, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            if any(
                isinstance(node, ast.Constant) and node.value is Ellipsis
                for node in ast.walk(ast.parse(example.source))
            ):
                result.issues.append(
                    f"{label}: replace literal ellipsis with meaningful example code"
                )
    except (ValueError, SyntaxError) as cause:
        result.issues.append(f"{label}: invalid prompted example: {cause}")


def audit(root: Path, paths: Sequence[Path] | None = None) -> Audit:
    """Audit selected files or every maintained Python source in the checkout.

    Args:
        root: Repository root used for discovery and relative diagnostics.
        paths: Explicit source paths, or None to inspect all maintained sources.

    Returns:
        Counts and diagnostics without executing the inspected files.
    """
    result = Audit()
    for path in python_files(root) if paths is None else paths:
        inspect_file(path, root, result)
    return result


def main() -> int:
    """Print the checkout audit as JSON and return a process exit status.

    Returns:
        Zero when every structural check passes; one if violations were found.
    """
    result = audit(Path(__file__).resolve().parents[1])
    print(json.dumps(asdict(result), indent=2))
    return int(bool(result.issues))


if __name__ == "__main__":
    raise SystemExit(main())
