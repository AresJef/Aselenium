# Production-readiness hardening review

Subsequent testing: the [feature-testing expansion](feature-testing.md) supersedes
this report's test counts and public-feature coverage assessment. It also records
newly discovered unresolved defects. The observations below remain the historical
hardening-pass results, not a claim that those later defects are fixed.

Date: **2026-09-04**. Scope: the current local Aselenium source candidate,
Python 3.10+ API, driver management first, then lifecycle, protocol, public APIs,
security, documentation, testing, performance, and release validation.

## Decision

**This is a substantially better-validated candidate, not an unconditional
production-ready certification.** Confirmed defects were fixed, documentation
examples now use the requested prompted format, and new checks prevent several
classes of regression. The passing local boundary is Python 3.11/3.13 with native
Chrome and Edge on macOS ARM64. Broader release acceptance remains open below.

The version remains **1.0.5**. Existing user changes were preserved; nothing was
committed, pushed, or published. Temporary test environments were created without
updating the checkout's `.venv`. No personal browser profile, Safari permission,
or external publishing configuration was changed.

## Twelve workstreams and results

This table tracks the production-readiness pass in driver-first execution order;
it does not renumber the [historical modernization plan](original-12-step-second-pass.md).

| Workstream | Work performed | Acceptance status |
| --- | --- | --- |
| 1. Driver management | Rechecked cache identities, exact/compatible/offline selection, locks, publication, archive containment, compatibility resources, and cancellation. Reject invalid lock budgets before touching a lock file. Include download admission/client creation in the total deadline. Reject reuse of consumed archive content. | Deterministic suite and cached Chrome/Edge provisioning pass. Separate CfT bundle and other vendor/platform runs remain unverified. |
| 2. Session lifecycle | Revalidated startup/failed-start/quit ownership, cancellation, independent acquisition, and teardown. Removed reference-nulling-only finalizers from non-resource value objects. Element construction now reports an unstarted session as a package error. | Local lifecycle tests, demos, and 40 total browser cycles pass. Long-duration and other-OS behavior remain open. |
| 3. Async behavior and deadlines | Rechecked wait/transport queue budgets, owned workers, cancellation propagation, and transaction isolation. First-match waits now preserve falsey, non-None matches. | Offline regressions and live concurrency/cancellation stages pass. Explicit-profile acquisition still copies synchronously. |
| 4. Protocol and errors | Rechecked W3C envelopes, route encoding, redirects, and error mapping. Session, element, and shadow-root plural lookups now reject malformed lists and null/invalid element references consistently. | Targeted fault cases and full offline suite pass; not every public command's failure envelope is exercised. |
| 5. Public feature contracts | Fixed rectangle copy subtype preservation, keyboard-constant annotations, action queue typing, and misleading browser-version annotations. Execute the requested action example and check its actual wire payload. | Native Chrome/Edge feature tours pass. Browser-specific Firefox/Safari runtime gaps remain. |
| 6. Security and privacy | Raised vulnerable dependency floors; audited revised minima and the resolved development environment. Firefox certificate errors now require explicit opt-in. Redacted cookies, scripts, CDP payloads, and queued action data from diagnostic representations. | Audits and targeted regressions pass. A clean advisory scan is not proof of no vulnerabilities; browser sandbox and cache trust boundaries still apply. |
| 7. Imports, typing, docstrings | Rechecked all maintained Python files structurally; converted examples to singular `Example:` with `>>>`/`...`. Corrected API names, arguments, units, ownership, absence behavior, and literal ellipsis placeholders. Added AST contract checks. Expanded the passing mypy scope to 19 modules. | Structural/style/example gates pass. Whole-package typing and individual live execution of every browser example are not complete. |
| 8. Test effectiveness | Added failure-path regressions, deterministic generated-input tests, example execution, coverage reporting, and four targeted mutation probes in disposable copies. | All four deliberately reintroduced defects cause their tests to fail; unmodified controls pass. Coverage remains uneven. |
| 9. Compatibility/dependencies | Ran the suite on Python 3.11 and 3.13, plus exact runtime minima on 3.11. Verified dependency consistency and a fresh wheel import outside the checkout. | Local combinations pass. Python 3.10/3.12/3.14 and Windows/Linux runtime matrix need actual runners. |
| 10. Performance/stability | Re-ran import/cache and generated-download benchmarks; added a reusable bounded browser-soak script. Ran 20 sessions per browser at concurrency two, using fresh profiles and the docstring action example. | Local measurements recorded; no causal speedup percentage or long-duration leak-free claim. |
| 11. Packaging/release/CI | Built wheel/sdist, checked strict metadata validation, and exercised sdist rebuild/resource/import tests. Added coverage, dependency audit, and example checks to CI configuration. Existing publication opt-in guards remain. | Local artifacts pass. Remote CI, release version selection, credentials/publisher identity, and approval policy remain release gates. |
| 12. Documentation/handoff | Updated README and the API-quality guide; recorded fixes, compatibility changes, scope, benchmarks, source inventory, and remaining work. | Evidence is retained in a new validation record; older historical records are not rewritten as current results. |

## Important behavior changes

- **Firefox no longer accepts insecure certificates by default.** Set
  `driver.options.accept_insecure_certs = True` explicitly only for a trusted
  environment that requires it. This deliberately changes the previous default.
- Vendor downloads can time out while waiting for admission or client creation;
  the timeout is not deferred until network activity starts. Owned cleanup may
  make wall-clock return time longer than the request budget.
- Invalid artifact-lock budgets fail immediately, rather than causing a broken
  or indefinite contention wait.
- Invalid plural element responses raise `InvalidResponseError` instead of
  returning lists containing None or leaking a Python parsing error.
- Element handles require a started session with a connection and command URL.
- `Rectangle.copy()` preserves subclasses such as `ElementRect` and `WindowRect`.
- Diagnostic representations omit sensitive payload data. Inspect explicit
  properties only where disclosure is intended; do not log cookie values or
  JavaScript/CDP arguments indiscriminately.
- Runtime requirements are now **aiohttp >=3.14.3**, **orjson >=3.11.6**, and
  **psutil >=5.8.0**. Development pytest requires >=9.0.3. Consumers using locked
  environments must resolve/install the revised requirements before testing.

The aiohttp floor excludes a reported client response-parser denial-of-service
issue affecting versions through 3.14.2. See the
[maintainer advisory](https://github.com/aio-libs/aiohttp/security/advisories/GHSA-cq5v-8q36-5273).
The orjson floor includes the deeply nested serialization crash fix documented
in the [3.11.6 changelog](https://github.com/ijl/orjson/blob/master/CHANGELOG.md#3116---2026-01-29).
The previous minimum-version audit contained multiple advisory entries, including
aliases and server-specific issues; that is not a count of distinct exploitable
Aselenium vulnerabilities.

## Documentation verification

All **94 maintained Python files**, **1,561 function/method definitions**, and
**238 classes** pass the structural documentation/import/annotation checks.
There are **178 definitions with prompted `Example:` sections**. Every prompted
statement is parsed and compiled; known package method names and argument binding
are also checked. The formatter and documentation lint pass.

The requested action example is shown in the [API-quality guide](api-quality.md).
It runs against a recording protocol fixture and verbatim in all 40 browser-soak
sessions. Three pure constructor examples execute as doctests. Examples requiring
other real browser state, existing files, or permissions are not all executed
individually. Correct formatting is not a guarantee that an arbitrary page has
the illustrated selectors, and static checks are not a proof that every English
description or dynamic annotation is semantically complete.

## Test and compatibility evidence

The [machine-readable record](baselines/production-readiness-validation.json)
contains exact final test counts, runtime versions, artifact hashes, coverage,
benchmark samples, mutation results, and native-demo reports. The suite includes
generated cases, fault injection, distribution construction/rebuild checks, and
example compilation; its test count should not be read as a public-feature count.

| Validation | Result and limits |
| --- | --- |
| Offline regression suite | Passes on Python 3.11.15 and 3.13.12 with asyncio debugging. Exact runtime minima also pass on Python 3.11.15. |
| Native Chrome | Chrome 152.0.7977.76 / driver 152.0.7977.82: all 15 local-demo stages pass. |
| Native Edge | Edge 151.0.4129.93 / driver 151.0.4129.107: all 15 local-demo stages pass. |
| Bounded lifecycle soak | 20 sessions each, concurrency two. No remaining observed child processes or newly owned tasks; handles plateau at eight after warm-up from six. RSS samples are recorded, not asserted leak-free. |
| Security audits | Revised direct minimum versions and the refreshed Python 3.13 development environment report no known vulnerabilities at this date. |
| Configured typing | Passes for 19 modules. Whole-package run still reports 282 diagnostics in 18 files. |
| Coverage | Approximately 63% combined statement/branch coverage in the offline suite. Actions 65%, element 35%, session 32%, Firefox session 23%; several manager infrastructure modules are 85–93%. Live demos are separate evidence, not included in this percentage. |
| Packaging | Wheel/sdist and strict metadata checks pass; installed-wheel import and compatibility resource checks pass outside the checkout. |
| Unverified native combinations | Firefox, Safari, standalone Chromium, separate CfT bundles, beta/dev channels, Windows, Linux, and Python runtimes other than 3.11/3.13. |
| External services | No new live Google run or fresh vendor download in this pass. No remote CI job or package publication. |

## Performance interpretation

The benchmark records fresh-interpreter import latency/RSS and synthetic cache
queries at 10 and 1,000 entries, including executable checksum validation. It
does not measure website speed or live installation throughput. Generated 8,
64, and 128 MiB downloads used roughly 0.5–0.6 MiB of peak traced Python allocations;
that excludes native allocations and OS caches and is not an RSS measurement.

Chrome's 20-cycle median was about 1.02 seconds and Edge's about 1.00 seconds per
cycle at concurrency two on this machine. These include acquisition, fixture work,
and teardown. Concurrent system activity and filesystem caching affect the
measurements; no like-for-like speedup against an earlier release is claimed.

## Remaining release gates

These are genuine remaining work, not checks silently counted as passed:

1. **Finish whole-package type contracts.** Resolve lifecycle optionality,
   descriptor/subclass types, and selector narrowing; validate representative
   consumer programs against the installed typed wheel. Do not silence the
   remaining 282 diagnostics with blanket Any or ignores.
2. **Deepen public API failure coverage.** Add deterministic response/exception
   contracts for remaining session, element, alert, and Firefox operations.
   Use mutation checks for high-risk ownership and protocol behavior. Set useful
   per-component coverage gates after establishing representative tests, not an
   arbitrary percentage that can be satisfied by shallow cases.
3. **Run native support targets.** Execute the configured Python/OS matrix and
   browser-specific Firefox/Safari/CfT tests on actual compatible runners.
   Safari permission changes and browser installation require explicit setup.
4. **Extend stability and resource bounds.** Run hour-scale and interrupted
   workloads, disk-full/permission/AV interference, and platform-specific process
   cleanup. Version-probe runtime is bounded, but captured stdout is still not
   byte-capped. Explicit-profile acquisition remains synchronous. Private local
   caches—not hostile shared/NFS/SMB caches—are the supported trust assumption.
5. **Complete external release acceptance.** Select a new release version,
   obtain successful remote CI evidence, and verify repository environment
   reviewers plus publishing credentials or Trusted Publisher identity. The
   local workflow's opt-in guard is not an external approval policy.

The next coding priorities are gates 1 and 2, plus bounded probe-output handling
from gate 4. These do not require publication or account changes. A universal
production-readiness claim should wait for the appropriate native and release
acceptance evidence, not merely a green local test count.

## Reproduce local checks

Use the commands in the [API-quality guide](api-quality.md#reproduce-the-checks).
For an already populated, private driver cache, the opt-in soak is:

```bash
python scripts/soak_browser.py --browser chrome --binary /absolute/path/to/chrome --cache-dir /absolute/cache/parent --cycles 20 --concurrency 2
```

It uses a local data URL, does not download drivers, and runs the actual prompted
action example. Replace the browser and executable for Edge. Full local demo
instructions remain in the [local demo guide](demo-local.md). A temporary
before-review backup exists at
`/private/tmp/aselenium-production-review.FGj6sT/before-review.tar.gz`; system
temporary storage is not a permanent archive.
