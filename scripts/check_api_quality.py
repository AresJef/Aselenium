"""Audit documentation, signature coverage, and function-local imports without importing code.

Run ``python scripts/check_api_quality.py`` from any directory. The checker scans
the checkout's package, demos, maintenance scripts, and tests. It prints a JSON
summary and exits nonzero on missing documentation, missing annotations, or a
function-local import. It also protects the package's public ``PathInput``
boundaries and parsed ``Path`` workflows. Conditional module-level OS and
TYPE_CHECKING imports are allowed. Other annotation coverage remains structural.
"""

from __future__ import annotations

import ast
import doctest
import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

_PATH_ARGUMENT_NAMES = {
    "base_dir",
    "binary",
    "destination",
    "directory",
    "driver",
    "executable",
    "file",
    "files",
    "location",
    "output_file",
    "path",
    "paths",
    "plist_file",
    "profile_root",
    "root",
}
_PATH_NAME_SUFFIXES = ("_dir", "_directory", "_location", "_path", "_paths", "_root")
_PATH_BOUNDARY_HELPERS = {
    "directory_path",
    "file_path",
    "parse_path",
    "save_file_path",
}
_PATH_REPARSERS = {"Path", "PurePath", *_PATH_BOUNDARY_HELPERS}
_PATH_OBJECT_TYPES = {
    "Path",
    "PosixPath",
    "PurePath",
    "PurePosixPath",
    "PureWindowsPath",
    "WindowsPath",
}
_PATH_RESULT_FUNCTIONS = {
    "browser_location",
    "directory",
    "driver_location",
    "install",
    "unpack",
}
_STRING_PATH_RESULTS = {"encode_addon_path", "lease_path"}
_STRINGIFY_CALLS = {"__str__", "as_posix", "fspath", "str"}
_PUBLIC_PATH_CLASSES = {"ChromiumProfile"}


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


def annotation_symbols(annotation: ast.expr | None) -> set[str]:
    """Return every simple or qualified symbol used by an annotation.

    Args:
        annotation: Parsed annotation expression, or None when it is absent.

    Returns:
        Identifier components such as ``PathInput``, ``Path``, or ``Any``.
    """
    if annotation is None:
        return set()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return set()
    return {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(annotation)
        if isinstance(node, (ast.Name, ast.Attribute))
    }


def path_name(name: str) -> bool:
    """Return whether an identifier denotes a filesystem path in this package.

    Args:
        name: Parameter, field, property, or helper name from the package AST.

    Returns:
        True for the package's path-bearing naming conventions.
    """
    normalized = name.lstrip("_")
    return (
        normalized in _PATH_ARGUMENT_NAMES
        or normalized in {"target_binary", "target_driver"}
        or normalized.endswith(_PATH_NAME_SUFFIXES)
    )


def public_path_boundary(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    relative: Path,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    """Return whether a callable receives raw paths from a high-level API.

    Args:
        node: Function or method definition being classified.
        relative: Source path relative to the repository root.
        parents: Direct AST parent mapping for the source file.

    Returns:
        True for public package callables and the canonical parsing helpers.
    """
    if node.name in _PATH_BOUNDARY_HELPERS:
        return True
    if node.name.startswith("_") and node.name != "__init__":
        return False
    parent = parents.get(node)
    if relative.name.startswith("_"):
        return isinstance(parent, ast.ClassDef) and parent.name in _PUBLIC_PATH_CLASSES
    return not isinstance(parent, ast.ClassDef) or not parent.name.startswith("_")


def call_name(node: ast.Call) -> str | None:
    """Return the terminal identifier for a direct function or constructor call.

    Args:
        node: Parsed call expression.

    Returns:
        The simple function name, qualified attribute name, or None.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def path_result_name(name: str) -> bool:
    """Return whether a callable name promises a retained filesystem path.

    Args:
        name: Function or property name.

    Returns:
        True when the result belongs to the package's Path-valued API surface.
    """
    normalized = name.lstrip("_")
    if normalized.startswith("set_"):
        return False
    return normalized not in _STRING_PATH_RESULTS and (
        normalized in _PATH_RESULT_FUNCTIONS
        or normalized.endswith(("_directory", "_location", "_path"))
    )


def path_result_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a callable, rather than a property setter, returns a path.

    Args:
        node: Function or method whose result contract is being classified.

    Returns:
        True when the callable name denotes a path result and it is not a setter.
    """
    return path_result_name(node.name) and not any(
        isinstance(decorator, ast.Attribute) and decorator.attr == "setter"
        for decorator in node.decorator_list
    )


def expression_key(node: ast.expr) -> str | None:
    """Return a stable identifier for a simple variable or attribute expression.

    Args:
        node: Expression used as an assignment target or parser input.

    Returns:
        A dotted identifier, or None for expressions that cannot be tracked safely.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = expression_key(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    return None


def assignment_keys(node: ast.expr) -> set[str]:
    """Return simple names written by one assignment target.

    Args:
        node: Name, attribute, or destructuring assignment target.

    Returns:
        Trackable identifiers written by the target.
    """
    if isinstance(node, (ast.Tuple, ast.List)):
        return {key for item in node.elts for key in assignment_keys(item)}
    key = expression_key(node)
    return {key} if key else set()


def scoped_nodes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[ast.AST]:
    """Yield nodes in one callable without entering nested definitions.

    Args:
        node: Function whose local path data flow is being inspected.

    Yields:
        Descendants belonging to the callable's own lexical scope.
    """
    pending: list[ast.AST] = list(reversed(node.body))
    while pending:
        child = pending.pop()
        yield child
        if isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(child))))


def contains_stringification(node: ast.AST) -> bool:
    """Return whether an expression explicitly converts a value to path text.

    Args:
        node: Expression or statement subtree to inspect.

    Returns:
        True when the subtree calls a supported stringification primitive.
    """
    return any(
        isinstance(child, ast.Call) and call_name(child) in _STRINGIFY_CALLS
        for child in ast.walk(node)
    )


def check_indirect_path_reparse(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    relative: Path,
    result: Audit,
) -> None:
    """Reject locally stringified values that are later passed to a path parser.

    Args:
        node: Callable whose local assignments and parser calls are inspected.
        relative: Source path relative to the repository root.
        result: Mutable aggregate receiving path-architecture violations.
    """
    if node.name == "parse_path":
        # This is the one boundary that must convert a raw os.PathLike payload
        # before constructing the package's canonical Path object.
        return
    local_nodes = list(scoped_nodes(node))
    stringified: set[str] = set()
    for child in local_nodes:
        if isinstance(child, ast.Assign) and contains_stringification(child.value):
            for target in child.targets:
                stringified.update(assignment_keys(target))
        elif isinstance(child, ast.AnnAssign) and child.value is not None:
            if contains_stringification(child.value):
                stringified.update(assignment_keys(child.target))
        elif isinstance(child, ast.NamedExpr) and contains_stringification(child.value):
            stringified.update(assignment_keys(child.target))
    if not stringified:
        return
    for child in local_nodes:
        if not isinstance(child, ast.Call) or call_name(child) not in _PATH_REPARSERS:
            continue
        values = [*child.args, *(keyword.value for keyword in child.keywords)]
        if any(contains_stringification(value) for value in values):
            continue
        references = {
            key
            for value in values
            for descendant in ast.walk(value)
            if isinstance(descendant, (ast.Name, ast.Attribute))
            if (key := expression_key(descendant)) is not None
        }
        if references.intersection(stringified):
            result.issues.append(
                f"{relative}:{child.lineno}: stringify/reparse path workflow"
            )


def check_path_architecture(
    tree: ast.Module,
    relative: Path,
    parents: dict[ast.AST, ast.AST],
    result: Audit,
) -> None:
    """Enforce one-parse Path workflows for the production package.

    Public filesystem boundaries accept ``PathInput``. Once parsed, retained
    locations and internal handoffs stay as ``Path`` objects; they must not be
    erased to ``str``/``Any`` and then passed through a parser again.

    Args:
        tree: Parsed source module.
        relative: Source path relative to the repository root.
        parents: Direct AST parent mapping for the source file.
        result: Mutable aggregate receiving path-architecture violations.
    """
    if relative.parts[:2] != ("src", "aselenium"):
        return
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, functions):
            check_indirect_path_reparse(node, relative, result)
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            arguments += [
                argument
                for argument in (node.args.vararg, node.args.kwarg)
                if argument is not None
            ]
            for argument in arguments:
                if not path_name(argument.arg) and not (
                    argument.arg == "value" and path_result_name(node.name)
                ):
                    continue
                symbols = annotation_symbols(argument.annotation)
                label = f"{relative}:{argument.lineno}: {node.name}: {argument.arg}"
                if not symbols:
                    result.issues.append(f"{label}: missing path annotation")
                elif "Any" in symbols:
                    result.issues.append(f"{label}: path annotation must not use Any")
                if (
                    public_path_boundary(node, relative, parents)
                    and "PathInput" not in symbols
                ):
                    result.issues.append(
                        f"{label}: public path boundary must accept PathInput"
                    )
            if path_result_function(node):
                symbols = annotation_symbols(node.returns)
                if (
                    not symbols
                    or symbols.intersection({"Any", "PathInput", "str"})
                    or not symbols.intersection(_PATH_OBJECT_TYPES)
                ):
                    result.issues.append(
                        f"{relative}:{node.lineno}: {node.name}: "
                        "filesystem result must retain Path semantics"
                    )
        elif isinstance(node, ast.AnnAssign):
            target = (
                node.target.id
                if isinstance(node.target, ast.Name)
                else node.target.attr
                if isinstance(node.target, ast.Attribute)
                else ""
            )
            retained = isinstance(node.target, ast.Attribute) or isinstance(
                parents.get(node), ast.ClassDef
            )
            if (
                retained
                and path_name(target)
                and (
                    not (symbols := annotation_symbols(node.annotation))
                    or symbols.intersection({"Any", "PathInput", "str"})
                    or not symbols.intersection(_PATH_OBJECT_TYPES)
                )
            ):
                result.issues.append(
                    f"{relative}:{node.lineno}: {target}: retained path must use Path"
                )
        elif isinstance(node, ast.Call) and call_name(node) in _PATH_REPARSERS:
            values = [*node.args, *(keyword.value for keyword in node.keywords)]
            if any(
                isinstance(child, ast.Call) and call_name(child) in _STRINGIFY_CALLS
                for value in values
                for child in ast.walk(value)
            ):
                owner = parents.get(node)
                while owner is not None and not isinstance(owner, functions):
                    owner = parents.get(owner)
                if isinstance(owner, functions) and owner.name == "parse_path":
                    continue
                result.issues.append(
                    f"{relative}:{node.lineno}: stringify/reparse path workflow"
                )


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
    check_path_architecture(tree, relative, parents, result)
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
