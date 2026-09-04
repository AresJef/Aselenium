"""Check resolvable API names and call signatures in prompted docstring examples.

This complements compilation; it does not execute browsers or prove selector,
network, or application behavior. Unknown user-supplied objects are left unresolved.
"""

from __future__ import annotations

import ast
import doctest
import inspect
import json
from pathlib import Path


class Contracts:
    """Index package classes and resolve inherited method signatures without imports."""

    def __init__(self, root: Path) -> None:
        """Read the package ASTs and index named class definitions.

        Args:
            root: Checkout root containing src/aselenium.
        """
        self.trees = {
            path: ast.parse(path.read_text(encoding="utf-8"))
            for path in sorted((root / "src/aselenium").rglob("*.py"))
        }
        self.classes = {
            node.name: node
            for tree in self.trees.values()
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        }

    def method(
        self, owner: str, name: str
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        """Resolve a method or property through the statically named base classes.

        Args:
            owner: Class name in the source index.
            name: Attribute to look up on the class and its bases.

        Returns:
            The defining function, or None if this index cannot resolve it.
        """
        cls = self.classes.get(owner)
        if cls is None:
            return None
        for member in cls.body:
            if (
                isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name == name
            ):
                return member
        for base in cls.bases:
            found = self.method(ast.unparse(base).split("[")[0].split(".")[-1], name)
            if found is not None:
                return found
        return None

    def return_type(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef | None
    ) -> str | None:
        """Resolve an annotated package-class return type, ignoring optionality.

        Args:
            function: Method whose annotation should be inspected.

        Returns:
            The first named package class in the annotation, or None.
        """
        if function is not None and function.returns is not None:
            return next(
                (
                    node.id
                    for node in ast.walk(function.returns)
                    if isinstance(node, ast.Name) and node.id in self.classes
                ),
                None,
            )
        return None

    def signature(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> inspect.Signature:
        """Build a binding-only signature from Python parameter declarations.

        Args:
            function: Method or constructor whose call contract should be checked.

        Returns:
            Signature with a bound receiver omitted and defaults represented by None.
        """
        arguments = function.args
        positional = [*arguments.posonlyargs, *arguments.args]
        defaults_at = len(positional) - len(arguments.defaults)
        parameters = []
        for index, argument in enumerate(positional):
            if index == 0 and argument.arg in {"self", "cls"}:
                continue
            kind = (
                inspect.Parameter.POSITIONAL_ONLY
                if index < len(arguments.posonlyargs)
                else inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
            default = None if index >= defaults_at else inspect.Parameter.empty
            parameters.append(inspect.Parameter(argument.arg, kind, default=default))
        if arguments.vararg:
            parameters.append(
                inspect.Parameter(
                    arguments.vararg.arg, inspect.Parameter.VAR_POSITIONAL
                )
            )
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            parameters.append(
                inspect.Parameter(
                    argument.arg,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None if default is not None else inspect.Parameter.empty,
                )
            )
        if arguments.kwarg:
            parameters.append(
                inspect.Parameter(arguments.kwarg.arg, inspect.Parameter.VAR_KEYWORD)
            )
        return inspect.Signature(parameters)


class ExampleVisitor(ast.NodeVisitor):
    """Resolve familiar example objects and report invalid package method calls."""

    def __init__(self, index: Contracts, owner: str, label: str) -> None:
        """Initialize inferred objects for a single documented definition.

        Args:
            index: Package class and method index.
            owner: Class containing the documented method, if any.
            label: Source location attached to every diagnostic.
        """
        self.index = index
        self.label = label
        self.issues: list[str] = []
        self.types = {
            "session": owner if owner.endswith("Session") else "Session",
            "element": "Element",
            "inputbox": "Element",
            "shadow": "Shadow",
            "driver": "Chrome",
            "connection": "Connection",
            "alert": "Alert",
            "options": owner if owner.endswith("Options") else "ChromeOptions",
        }

    def infer(self, node: ast.AST) -> str | None:
        """Infer package classes for a limited set of example expressions.

        Args:
            node: Expression whose receiver or result type should be inferred.

        Returns:
            A known class name, or None for unresolved dynamic expressions.
        """
        if isinstance(node, ast.Name):
            return self.types.get(
                node.id, node.id if node.id in self.index.classes else None
            )
        if isinstance(node, ast.Await):
            return self.infer(node.value)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return self.infer(node.func)
            return self.infer(node.func)
        if isinstance(node, ast.Attribute):
            owner = self.infer(node.value)
            return (
                self.index.return_type(self.index.method(owner, node.attr))
                if owner
                else None
            )
        return None

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track package-class return values assigned to example variables.

        Args:
            node: Assignment statement being inspected.
        """
        self.generic_visit(node)
        result = self.infer(node.value)
        if result:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.types[target.id] = result

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        """Infer the session returned by an acquisition context.

        Args:
            node: Asynchronous context statement being inspected.
        """
        for item in node.items:
            owner = self.infer(item.context_expr)
            if owner and isinstance(item.optional_vars, ast.Name):
                result = self.index.return_type(self.index.method(owner, "__aenter__"))
                if result:
                    self.types[item.optional_vars.id] = result
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check the package spelling and track explicitly imported class aliases.

        Args:
            node: From-import statement in an example.
        """
        if node.module == "aslenium":
            self.issues.append(f"{self.label}: misspelled package import aslenium")
        for alias in node.names:
            if alias.name in self.index.classes:
                self.types[alias.asname or alias.name] = alias.name

    def visit_Call(self, node: ast.Call) -> None:
        """Check known method names and argument binding without evaluating arguments.

        Args:
            node: Call expression in the example source.
        """
        self.generic_visit(node)
        function = None
        if isinstance(node.func, ast.Attribute):
            owner = self.infer(node.func.value)
            if owner is not None:
                function = self.index.method(owner, node.func.attr)
                if function is None:
                    self.issues.append(
                        f"{self.label}: unknown {owner}.{node.func.attr}()"
                    )
        elif isinstance(node.func, ast.Name) and node.func.id in self.index.classes:
            function = self.index.method(node.func.id, "__init__")
        if (
            function is not None
            and not any(isinstance(arg, ast.Starred) for arg in node.args)
            and all(keyword.arg for keyword in node.keywords)
        ):
            try:
                self.index.signature(function).bind(
                    *[None for _ in node.args],
                    **{keyword.arg: None for keyword in node.keywords},
                )
            except TypeError as cause:
                self.issues.append(
                    f"{self.label}: invalid {function.name} call: {cause}"
                )


def audit(root: Path) -> list[str]:
    """Check all prompted package examples for statically resolvable API mistakes.

    Args:
        root: Checkout root containing the package source.

    Returns:
        Diagnostics for known-name and signature mistakes; unresolved objects are not certified.
    """
    index = Contracts(root)
    issues = []
    for path, tree in index.trees.items():
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            examples = doctest.DocTestParser().get_examples(
                ast.get_docstring(node) or ""
            )
            parent = parents.get(node)
            owner = (
                node.name
                if isinstance(node, ast.ClassDef)
                else parent.name
                if isinstance(parent, ast.ClassDef)
                else ""
            )
            visitor = ExampleVisitor(
                index, owner, f"{path.relative_to(root)}:{node.lineno}:{node.name}"
            )
            for example in examples:
                visitor.visit(ast.parse(example.source))
            issues.extend(visitor.issues)
    return issues


def main() -> int:
    """Print contract diagnostics and return a nonzero status on a confirmed mistake.

    Returns:
        Zero when no resolvable example contract errors are found; otherwise one.
    """
    issues = audit(Path(__file__).resolve().parents[1])
    print(json.dumps({"issues": issues}, indent=2))
    return bool(issues)


if __name__ == "__main__":
    raise SystemExit(main())
