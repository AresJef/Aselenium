# Import, documentation, and typing guide

The current quality gate scans every maintained Python file in the package,
demos, maintenance scripts, and tests. It requires every module, class, function,
method, fixture, and nested helper to be documented and every callable signature
to be annotated. The command prints live file/definition/example counts so this
guide does not turn a changing source-tree total into a stale promise. Structural
checks do not, by themselves, prove that every semantic contract is correct.

See the README's validation section for the current commands and evidence
boundaries. The [production-readiness report](production-readiness.md) and earlier
[API-quality record](baselines/api-quality-validation.json) are dated historical
snapshots; their original counts are intentionally not rolling status badges.

## Imports

Ordinary imports belong at module scope. Ruff checks import ordering and unused
imports; the structural audit rejects imports inside functions, methods, and
nested callbacks. Explicit public exports remain intact.

Use `TYPE_CHECKING` and postponed annotations for annotation-only dependencies
where runtime imports would create cycles. Code resolving annotations with
`typing.get_type_hints()` may need the defining type namespace. OS-specific
locking backends and the Python 3.10 TOML fallback remain conditional module-level
imports. Moving imports is not evidence of a measurable automation speedup.

## Filesystem-path architecture

Public and high-level filesystem parameters use the shared `PathInput` alias,
which accepts `str`, `pathlib.Path`, and compatible string-valued
`os.PathLike[str]` objects. Core entry points call the canonical parser once.
Retained fields, internal handoffs, and path-valued results then remain
host-native `Path` objects; they are not erased to text and parsed again.

The structural gate rejects missing or `Any` public path annotations, textual
retained-path fields/results, and direct or assigned stringify-then-reparse
workflows. It recognizes quoted annotations as well as evaluated syntax. `str`
remains valid where an external interface requires text—for example a subprocess
argument, WebDriver JSON field, URL, SQLite/JSON record, or cache key. Portable
archive-member metadata uses `PurePosixPath`; native filesystem work does not.

## Docstring structure

Use a concise summary and Google-style `Args:`, `Returns:` or `Yields:`, and
`Raises:` sections when applicable. Describe units, ownership, absence behavior,
side effects, and failure conditions. Do not merely repeat the annotation.

- Use **`Example:`**, singular, for usage examples.
- Start each independent Python statement with `>>>`.
- Use `...` for continuation lines of the same statement, including action chains,
  `try/finally`, `async with`, and function definitions.
- Do not use reStructuredText `.. code-block:: python` in docstring examples.
- Do not pass a literal `...` as a placeholder argument. It is a real Python
  object and often makes the example fail at runtime.
- Put expected output on unprompted lines only when it is deterministic.
- Use lowercase `from`; put `await` around the completed asynchronous operation,
  not its synchronous action builder.

The action example is written this way:

```text
Example:
    >>> from aselenium import KeyboardKeys
    >>> inputbox = await session.find_element("#inputbox")
    >>> if inputbox is None:
    ...     raise LookupError("The input field is missing")
    >>> await (
    ...     session.actions()
    ...     .move_to(inputbox)
    ...     .click()
    ...     .send_keys("Hello world!")
    ...     .send_keys(KeyboardKeys.ENTER)
    ...     .perform()
    ... )
```

Browser examples assume the named `session`, `element`, `options`, or `driver`
already exists unless the example creates it. Run asynchronous examples inside
an async function or a console supporting top-level await. Selectors, files,
browser installations, and permissions must match the environment. Prompt
formatting alone does not make browser examples ordinary synchronous doctests.

Void methods do not need a redundant `Returns: None`. Context-manager generators
document the yielded resource. Add examples where they clarify meaningful public
usage; do not fabricate examples for every setter, exception, or test helper.

## Example verification

The audit counts every definition with an `Example:` section. All prompted
statements are parsed and compiled, including top-level await. A separate AST
checker resolves known package classes, inheritance, method names, and argument
binding. It catches an unsupported `timeout` on `find_element`, a nonexistent
CSS-property method, and a misspelled package import.

This pass corrected inaccurate cache paths, CfT selector descriptions, timeout
semantics, screenshot and network method examples, shadow-only CSS arguments,
profile ownership, and browser-version return descriptions. Options/session
browser versions are strings or None, not parsed Version objects.

Three pure constructor examples execute as doctests. The action example above
executes against a recording protocol fixture and, verbatim, in **20 Chrome and
20 Edge sessions** using a local input. Other examples needing browser state are
not all executed individually. Static resolution leaves unknown application
objects unresolved; it is not a semantic proof.

## Type annotations

Keep generic callback/result types for waits and owned worker helpers. Distinguish
awaitable callbacks from already-created awaitables, generator yields from coroutine
returns, and nullable lifecycle state from always-present resources.

The configured mypy gate covers all maintained runtime and operational Python in
`src/` and `scripts/`, rather than a hand-picked module subset. Rectangle copies
preserve their concrete type; browser facades preserve their specific
session/manager/options types; filesystem inputs accept the public `PathInput`
union while retained and returned locations remain `Path`; and Firefox add-on
installation returns `list[FirefoxAddon]`. `Any` remains appropriate for
heterogeneous JavaScript/WebDriver protocol values and deliberately duck-typed
test/benchmark protocol values, not as a shortcut for unresolved ownership or
path contracts. Installed-wheel consumer typing is checked separately so an
editable checkout cannot hide missing annotations or `py.typed` metadata.

## Reproduce the checks

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python scripts/check_api_quality.py
python scripts/check_example_contracts.py
python -m mypy
python -m coverage run --branch --source=aselenium -m pytest --asyncio-debug
python -m coverage report
python -m pip check
python -m pip_audit --skip-editable
```

`python -m mypy` checks the complete configured `src/` and `scripts/` scope.
`python -m mypy src/aselenium` remains a useful package-only diagnostic but does
not replace the configured gate. CI also runs the structural/path/example checks,
lint, formatting, coverage, installed-wheel typing, and a dependency advisory
audit. Hosted execution and real browser behavior still require the platform
matrix; a local static pass is not a substitute for that evidence.
