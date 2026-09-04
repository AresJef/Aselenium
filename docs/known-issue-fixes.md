# Known-issue fixes and regression verification

> Historical validation record: the source was version 1.0.5 at this checkpoint.
> Later release-candidate reviews and the 2.0.0 release supersede its current-state
> wording while preserving the measured results below.

Date: **2026-09-05**. Scope: the **10 issue families** found by the
[feature-testing expansion](feature-testing.md), previously represented by
23 strict expected-failure cases.

## Result

**All 10 targeted issues are fixed.** The expected-failure markers have been
removed, their regressions now pass, and adjacent boundary cases have been added.
The complete suite reports **2,277 passed, zero failed, zero expected failures,
and zero skipped** in each of these existing isolated environments:

| Environment | Runtime dependency versions | Result |
| --- | --- | --- |
| Python 3.13.12 | aiohttp 3.14.3, orjson 3.12.0, psutil 7.2.2 | 2,277 passed |
| Python 3.11.15 | aiohttp 3.14.3, orjson 3.12.0, psutil 7.2.2 | 2,277 passed |
| Python 3.11.15, exact runtime minima | aiohttp 3.14.3, orjson 3.11.6, psutil 5.8.0 | 2,277 passed |

All runs enable asyncio debugging and include the 28 real-loopback transport
tests. The case count increased by 182 from the prior 2,095 collected cases;
the earlier 23 expected-failure cases are no longer excluded from passing results.

The [validation record](baselines/known-issue-fixes-validation.json) contains
counts, runtime versions, source fingerprints, coverage, native-demo reports and
verification limits. The [updated callable inventory](baselines/known-issue-fixes-api-inventory.json)
records the current source locations and exercising test contexts. Older JSON
records remain unchanged as dated evidence of the pre-fix state.

## Fixed behavior

| Issue | Fix | Compatibility and safety |
| --- | --- | --- |
| Empty screenshot destination | The shared output-path validator rejects empty strings, empty pathlike objects, null-containing/non-text inputs and directory destinations before a browser request. | Applies to element screenshots, session screenshots, PDFs and Firefox full-page screenshots. Valid relative/pathlike filenames, Unicode and whitespace are preserved. |
| Relative-path documentation mismatch | File/directory validators return absolute paths as documented. | `Path.absolute()` preserves symbolic-link names and symlink-sensitive `..` traversal. Resolving links or collapsing those components could otherwise select a different file. |
| Stale Edge WebView capabilities | Changing `use_webview` invalidates cached capabilities. | Regular Edge/WebView2 toggles refresh `browserName`; existing snapshots stay isolated. Invalid values do not change state. |
| Negative navigation retries | `load` and `refresh` validate the retry budget before dispatch. | `None` and `0` still mean one attempt. Other accepted values are nonnegative integers; booleans, negatives, floats and other types raise `InvalidArgumentError`. Only native page-load timeouts are retried; cancellation propagates. |
| Malformed cookie collection | Cookie responses must contain a list, and members must be constructible cookie objects. Invalid data raises `InvalidResponseError`. | Empty lists, ordering and existing constructor conventions are preserved. Parsing errors no longer include cookie payloads or expose constructor messages through chained tracebacks. This is not a new exhaustive cookie schema. |
| Invalid Firefox context response | Returned contexts must be exactly `"content"` or `"chrome"`. | Invalid envelopes/values raise `InvalidResponseError` without echoing raw data. |
| Invalid Firefox add-on IDs | Returned IDs must be non-blank strings before entering the local add-on cache. | Valid IDs are preserved verbatim. Earlier confirmed installations remain cached if a later batch item fails; uncertain remote writes are not replayed. |
| Invalid Safari permissions | The response must contain a nested mapping with string keys and actual boolean values. | Empty mappings remain valid. Missing `get_permission` results still return `None`; its annotation now reflects that behavior. |
| Uncached JavaScript object | Sync/async script execution raises `JavaScriptNotFoundError` before transport if an object has no matching cached name. | Raw strings, cached names, original objects, copies and equivalent same-name keys retain their established behavior. Explicit falsey arguments override defaults correctly. Wrong input types raise `InvalidArgumentError`. |
| Uncached CDP object | CDP execution raises `DevToolsCMDNotFoundError` before transport if an object has no matching cached name. | Raw command strings, name-based lookup and explicit parameter overrides remain supported. Wrong input types raise `InvalidArgumentError`. |

The JavaScript/CDP choice follows the existing documented **cached-instance**
contract. It does not introduce execution of arbitrary standalone value objects.
For example:

```python
script = session.cache_script("identity", "return arguments[0]", "default")
result = await session.execute_script(script, 0)
assert result == 0
```

After removal or renaming, the old instance's name is no longer cached and the
corresponding typed not-found error is raised. Lookup remains name-based rather
than object-identity-based; an existing cached entry with the same name wins.

## Verification

- **Targeted regressions:** malformed envelopes and IDs, early rejection before
  dispatch, cache invalidation and snapshot isolation, confirmed partial add-on
  batches, removed/renamed handles, falsey overrides, no-retry budgets,
  cancellation during backoff, cookie traceback redaction, safe output and
  symlink-parent path behavior.
- **Real Chrome/Edge:** each passed all **15 local-demo stages** using existing
  cached drivers and fresh clones of an empty profile. This includes navigation,
  cookies, scripts/CDP, screenshots/PDF, independent sessions and cancellation.
  Chrome was 152.0.7977.76 with driver 152.0.7977.82; Edge was 151.0.4129.93 with
  driver 151.0.4129.107 on macOS ARM64.
- **Quality gates:** Ruff, formatting, structural import/docstring/annotation
  checks, prompted-example syntax and resolvable API contracts, and the configured
  19-module mypy gate pass. There are now 106 maintained Python files, 1,862
  function/method definitions, 253 classes and 180 prompted example sections.
- **Independent review:** a separate reviewer checked the changed implementation
  and tests against the pre-fix snapshot, found no actionable regression, and
  independently reran the affected session/browser/output suites.
- **Regression effectiveness:** 98 selected current regression cases were also
  run against an isolated copy of the archived pre-fix package. They produced
  88 intentional failures and 10 passes, with at least one failure in each of
  the 10 defect families and no setup/collection errors. Those same cases are
  included in the passing current-source suite. The negative control confirms
  that the tests detect the old bugs; its intentional failures are not failures
  of the repaired package.

Measured full-suite coverage is **91.09% of executable statements**, **80.54% of
branches**, and **88.92% combined**. Unlike the previous coverage observation,
there are no expected-failure executions in this run. The source denominator has
changed, so the percentage delta is not a performance or correctness metric.

## Remaining boundaries

This completes the 10 identified fixes, not a guarantee that no other defects
exist. Native Firefox/Safari/WebView2 and other unavailable browser/platform
combinations remain unverified. Whole-package strict typing, physical-device
behavior, external proxy/vendor integrations, long-duration stability and remote
release acceptance remain separate work.

The preceding pass's 100-session soaks and real HTTP proxy checks are historical
evidence, not newly rerun results for this patch. This pass reran the full local
Chrome/Edge feature tours and all deterministic/loopback tests. No dependency
upgrade, user `.venv` change, browser installation, personal-profile access,
Safari permission change, commit, push or publication was performed. The package
version at this checkpoint remained **1.0.5**.

## Reproduce

Use an existing isolated development environment with the declared test tools:

```bash
python -m pytest --asyncio-debug
python -m coverage run --branch --source=aselenium -m pytest --asyncio-debug
python -m coverage report
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python scripts/check_api_quality.py
python scripts/check_example_contracts.py
python -m mypy
```

The full suite needs permission to bind local TCP servers but prohibits external
requests and installed-browser launches. See the
[feature-testing guide](feature-testing.md#reproduce) for native tours and
per-test coverage inventory reproduction. A restricted run excluding `loopback`
does not establish the 28 deselected transport cases.
