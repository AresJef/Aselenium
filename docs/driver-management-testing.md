# Driver management: Step 1 test foundation

> Historical audit: this records the implementation at its original checkpoint.
> Subsequent [compatibility removals](legacy-removal.md) supersede its old-feature
> and dependency guidance; historical measurements are not current support promises.

Historical Step 1 checkpoint. Steps 2 and 3 have since fixed packaging/discovery
and hardened manager filesystem operations; see
[the Step 3 handoff](driver-management-step-3.md) for current results and behavior notes.
The Step 1 measurements and defect inventory below are preserved as a baseline.

Completed 2026-09-04 against Aselenium 1.0.5, source revision
`b714594d4b6cc9f0eadba13af14f924cb3b26f4e`. This step adds tests, development
configuration, a test-only CI workflow and a performance baseline. It deliberately
does not fix production behavior. Driver-management packaging/discovery is the
next implementation step; session, DOM, options and other feature refactors are
still deferred.

## Run locally

From the repository root, create an isolated environment if needed and install
the package with its actual runtime dependencies and development tools:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Dependency installation needs a package index or prepopulated wheel cache. The
test command itself requires neither network access nor installed browsers.
On Windows use `.venv\Scripts\python.exe` for the equivalent commands.

Useful commands:

```sh
# Fast manager tests, excluding disposable distribution builds
.venv/bin/python -m pytest -m "not packaging"

# Tracked regression cases, with complete explanations
.venv/bin/python -m pytest -m regression -rx

# Expose the known defects as ordinary failures (exit code 1 is expected now)
.venv/bin/python -m pytest --runxfail --tb=short

# Check async execution with debug diagnostics enabled
.venv/bin/python -m pytest --asyncio-debug

# Reproduce the offline performance workload; JSON is printed to stdout
.venv/bin/python scripts/benchmark_manager.py
```

Use `xfail` only for a demonstrated defect or an explicitly documented
version-dependent case. Every current xfail has a defect ID and a narrow expected
exception type. They execute normally; they are not skipped. An unexpected pass
fails the normal suite, requiring the marker to be removed when its fix lands.
Build and import errors cannot be absorbed by the distribution-resource xfails.

## What the suite exercises

- Public manager/version exports and constructor, install and reset signatures.
- Actual package construction, source-resource loading and version value semantics.
- Mock browser probes and temporary browser-location layouts, including Safari.
- In-memory vendor metadata, redirects and download payloads, timeout/proxy
  forwarding, Unicode fallback, and existing error mappings. The 401/403 tests
  characterize the existing API; they do not endorse its future HTTP policy.
- Synthetic ZIP archives, gzip TAR and the existing bzip fallback, invalid files,
  missing executables, and executable selection.
- Real Feather metadata write/reload and Chrome, Edge, Firefox and Chrome browser
  cache round trips, cache matching, stale entries, retention and singleton scope.
- Installation cache hits, exact-version resolution, concurrent request isolation,
  sequential event loops, cancellation and failed CfT sibling ownership.
- Direct wheel and sdist builds, a wheel rebuilt from the sdist, archive integrity,
  and clean subprocess imports of both wheels. Import checks use `-S`, explicitly
  supplied dependency directories and verified wheel origins, preventing fallback
  to the editable source checkout. Resource loading is checked when present; its
  current absence is a separate failing contract.

## Safety and isolation

All cache and archive data are disposable. Autouse fixtures reset the file-manager
singleton registry, installation lock and Gecko table between tests. Package home
expansion is redirected to the test directory, and constructors normally receive
an explicit temporary directory.

Real aiohttp requests, socket connections and manager subprocess calls are blocked.
Tests that inspect process invocation replace the probe with a fake. Archive chmod
calls are simulated in-process with a temporary-root containment check. Future
async process launch APIs are also blocked by default. These are test guards, not
an operating-system sandbox; subprocess build/import checks are separately scoped
and do not install dependencies or contact vendors.

Persistent-I/O tests use a sentinel after three mocked OS errors, so current
infinite retry loops cannot hang the suite, including with `--runxfail`. Async
tests use deadlines and cancel/drain their owned tasks. Archive traversal can
escape the extraction subdirectory only into its own temporary fixture directory.
Foreign-folder deletion tests intercept `rmtree` and record attempts without
performing the deletion. Cache-retention tests delete only their synthetic data.

## Tracked regressions and fix order

The counts below are the observed expected failures on Python 3.11 and 3.13.

| Defect ID | Cases | Desired behavior | Planned step |
| --- | ---: | --- | ---: |
| `DRV-PACKAGE-RESOURCE` | 3 | Direct wheel, sdist and rebuilt wheel contain Gecko data | 2 |
| `DRV-SAFARI-PLIST` | 2 | Safari version/Info plist discovery works | 2 |
| `DRV-SHELL-PROBE` | 1 | Browser path is a literal argument, without a shell | 3 |
| `DRV-METADATA-READ-RETRY` | 1 | Persistent metadata read errors terminate | 3 |
| `DRV-METADATA-WRITE-RETRY` | 1 | Persistent metadata write errors terminate | 3 |
| `DRV-DOWNLOAD-WRITE-RETRY` | 1 | Persistent downloaded-file write errors terminate | 3 |
| `DRV-TAR-TRAVERSAL` | 1 | Archive members stay inside the extraction root | 3 |
| `DRV-EXECUTABLE-CONTAINMENT` | 1 | Untrusted member names cannot select foreign files | 3 |
| `DRV-METADATA-CONTAINMENT` | 2 | Removal/retention cannot delete outside the managed cache | 3 |
| `DRV-REQUEST-STATE` | 5 | Concurrent installs retain their own requested versions | 4 |
| `DRV-LOCK-LOOP` | 1 | Sequential event loops do not reuse a bound lock | 4 |
| `DRV-CFT-SIBLING` | 1 | Failed CfT installs finish cleanup before returning | 4 |
| `DRV-EXACT-PIN` | 4 | Chrome/Chromium/Edge/CfT cold caches preserve exact pins | 5 |
| `DRV-GECKO-RANGE` | 2 | Historical Gecko 0.33.0 Firefox bounds match Mozilla | 5 |

`DRV-PY310-TIMEOUT` additionally tracks eight conditional cases for asyncio/aiohttp
timeout handling. They pass on the tested Python 3.11/3.13 interpreters. Python
3.10 execution remains unverified locally: there, asyncio's timeout class differs
from the built-in class caught by the current manager. The marker is conditioned
on the actual exception-class relationship. Address it with manager HTTP error
handling in Step 7 without raising the package's Python floor.
[Python timeout exception documentation](https://docs.python.org/3/library/asyncio-exceptions.html#asyncio.TimeoutError)

The TAR traversal xfail applies below Python 3.14; Python 3.14 changed the default
extraction filter. A safe default on one interpreter is not a package-level fix
across the retained Python range.
[Python extraction-filter documentation](https://docs.python.org/3/library/tarfile.html#extraction-filters)

The Gecko regression uses fixed historical facts: Mozilla lists Gecko 0.33.0 for
Firefox 102 ESR through 120. The checked-in table instead has minimum 113 and an
effectively unbounded maximum. Broader table refresh and compatibility-policy
validation remain Step 5 work; this test does not fetch current releases.
[Mozilla support table, checked 2026-09-04](https://firefox-source-docs.mozilla.org/testing/geckodriver/Support.html)

## Validation performed

On macOS 26.6.2, ARM64:

| Interpreter / command | Result |
| --- | --- |
| Python 3.13.12, normal suite | 95 passed, 26 xfailed |
| Python 3.13.12, `--asyncio-debug` | 95 passed, 26 xfailed |
| Python 3.13.12, `--runxfail --tb=short` | Exactly 26 known failures, 95 passed; exit 1 |
| Python 3.11.15, `--asyncio-debug` in a separate temporary venv | 95 passed, 26 xfailed |
| Dependency consistency, both venvs | `pip check` passed |
| Whitespace / patch validity | `git diff --check` passed |

No unexpected failures or skips occurred. Existing production warnings remain
visible: TAR filter deprecations on 3.13, and invalid string escapes on initial
source compilation. Async debug runs produced no leaked-task or unawaited-coroutine
warnings. Both test environments use pytest 8.4.2 and pytest-asyncio 1.4.0.

The new test-only GitHub Actions job is configured for Ubuntu and Python
3.10–3.14 with read-only repository permissions. It has not been dispatched or
observed remotely. Configuration is not evidence that those CI combinations pass.
The release/publishing workflow remains unchanged.

## Performance baseline

The recorded JSON is in `docs/baselines/driver-manager-step-1.json`. It contains
all seven samples per measurement, installed dependency versions, platform and
Python details, the source revision, and hashes of the package sources and
benchmark script. Development dependency ranges are not a lockfile; this JSON is
the exact observed environment, not a portable cross-platform dependency lock.

Recorded on Python 3.13.12 with aiohttp 3.14.3, pandas 3.0.5, pyarrow 25.0.1,
NumPy 2.5.2, psutil 7.2.2 and orjson 3.12.0:

| Workload | Median |
| --- | ---: |
| Fresh-interpreter `import aselenium` | 247.38 ms |
| Process RSS after import | 109.23 MiB |
| Exact cache hit, 10 / 100 / 1,000 entries | 0.498 / 0.501 / 0.506 ms |
| Exact cache miss, 10 / 100 / 1,000 entries | 0.475 / 0.475 / 0.482 ms |
| Feather reload, 10 / 100 / 1,000 entries | 0.385 / 0.406 / 0.457 ms |

Imports use fresh subprocesses but do not flush OS disk caches; interpreter
startup is excluded. RSS is total post-import process memory, not incremental
package allocation or peak download memory. Lookup values are medians of seven
batch averages, each containing 100 calls. Dataframe seeding, filesystem setup,
and warm-up are excluded. Metadata reloads read real synthetic Feather files
with warm OS caches. This is not a real driver/browser download, extraction,
startup or end-to-end provisioning benchmark, and does not demonstrate a speedup.

## Review checkpoint

Step 1 is ready for review. No production module, runtime dependency declaration,
compatibility resource or release workflow was changed. No real browser/driver
was downloaded or launched, and no personal browser profile/cache was used. No
commit, push or publication was performed.

Next: Step 2 fixes distribution-resource inclusion/loading and Safari/browser
discovery, adds the corresponding positive edge-case tests, and removes the
now-passing regression markers. Later steps must still add cross-process/crash
cache tests, architecture identity, cancellation under real I/O, live vendor
contract checks and real-browser smoke validation. This foundation is not a
complete package certification.
