# Import, documentation, and typing guide

The current production-readiness pass scans **94 maintained Python files**:
package source, demos, maintenance scripts, and tests. Every one of the **1,561
function/method definitions** and **238 classes** has a docstring; every function
signature is annotated. These counts include fixtures and nested helpers, not
only public APIs. Structural checks do not prove every semantic contract correct.

See the [production-readiness report](production-readiness.md) for current
results, compatibility changes, remaining risks, and release gates. The earlier
[API-quality record](baselines/api-quality-validation.json) is historical.

## Imports

Ordinary imports belong at module scope. Ruff checks import ordering and unused
imports; the structural audit rejects imports inside functions, methods, and
nested callbacks. Explicit public exports remain intact.

Use `TYPE_CHECKING` and postponed annotations for annotation-only dependencies
where runtime imports would create cycles. Code resolving annotations with
`typing.get_type_hints()` may need the defining type namespace. OS-specific
locking backends and the Python 3.10 TOML fallback remain conditional module-level
imports. Moving imports is not evidence of a measurable automation speedup.

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

The audit identifies **178 definitions with `Example:` sections**. All prompted
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

The passing mypy gate covers **19 modules**, up from 14. This pass added actions,
alerts, utility value objects, archive files, and elements. Rectangle copies
preserve their concrete type; action dictionaries describe empty queues; numeric
version strings are accepted by annotations that previously excluded them.
`Any` remains appropriate for heterogeneous JavaScript/WebDriver payloads and
test doubles, not as a shortcut for unresolved ownership contracts.

A separate whole-package run still reports **282 diagnostics in 18 files** under
the existing mypy configuration. It is not a strict run, and the whole package is
not type-clean even at that setting. Remaining work includes nullable lifecycle
state, browser-subclass contracts, and shadow-selector narrowing. No blanket
suppression was added to misrepresent this as complete.

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

For the broader diagnostic inventory, run `python -m mypy src/aselenium`; it
currently exits nonzero. Keep the passing gate and that open-work inventory
distinct. CI runs the structural/example checks, lint, formatting, configured
typing gate, coverage, and a dependency audit. Remote execution needs verification.
