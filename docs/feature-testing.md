# Feature-testing expansion

**Follow-up, 2026-09-05:** all 10 issue families documented below have now been
fixed. The current suite has **2,277 passing tests with no expected failures or
skips**. See [known-issue fixes](known-issue-fixes.md) for current behavior and
verification. This page retains the testing pass's historical counts and findings.

Date: **2026-09-04**. This testing pass follows the
[production-readiness review](production-readiness.md). It adds tests and test
tooling; it does **not** fix the newly discovered runtime defects or certify the
package as production-ready.

## Result and interpretation

Added **763 test cases across nine new test files**: 740 passing cases and 23
strict expected failures. The complete suite has **2,072 passed, 23 expected
failures, zero unexpected failures and zero skipped tests** in each available
environment: Python **3.13.12**, Python **3.11.15**, and Python 3.11.15 with exact
runtime dependency minima. The latter uses aiohttp 3.14.3, orjson 3.11.6 and
psutil 5.8.0; the development tools are not all pinned to their minimum versions.

| Coverage measure | Before this pass | After this pass |
| --- | ---: | ---: |
| Executable statements | 66.50% | **90.97%** |
| Branches | 49.34% | **80.18%** |
| Combined statements/branches | 63.01% | **88.78%** |

Both measurements use the same production source denominator: 7,155 statements
and 1,826 branches. The new measurement includes 28 real-loopback transport
tests, but excludes native browser runs. Per-module combined coverage is now
98.60% for elements, 96.81% for shadow roots, 94.02% for actions, 95.74% for
alerts, 87.97% for sessions, 96.50% for Firefox sessions and 100% for the small
Safari session wrapper. These percentages include known-failure execution and
do not establish native Firefox/Safari correctness.

Chrome and Edge each passed **15/15 local feature-tour stages**, including
physical profile cloning, and a real local HTTP proxy-routing check. Each also
passed **100 lifecycle sessions at concurrency four**, with no remaining
observed owned processes or tasks. Handles stabilized at eight after warm-up
from six; Python RSS grew from approximately 49 MB to 56 MB. These short,
bounded observations are not proof of long-duration leak freedom or a measured
performance improvement.

Ruff, formatting, structural import/docstring/annotation checks, all 178 prompted
example sections' syntax and resolvable API contracts, and the configured
19-module mypy gate pass. The structural audit now covers 105 Python files,
1,829 function/method definitions and 252 classes. Whole-package strict typing
remains outside that passing gate.

The source inventory now measures execution inside **all 550 public-named
callables and constructors** defined in non-private package modules. Property
getters and setters are separate entries; inherited implementations are counted
once. Constants, private helpers, generated members, and aliases are not separate
callables. The report excludes definition/decorator/docstring lines so merely
importing a method cannot make it count as exercised.

**This is implementation-body coverage, not 100% behavioral correctness.** A test
can exercise one path while other branches remain untested. Strict expected
failures also contribute to code coverage. Native browser behavior is a separate
layer from passing Python protocol tests.

The [validation record](baselines/feature-testing-validation.json) retains exact
test counts, environments, coverage, known defects, native-browser observations,
and unavailable checks. The [callable inventory](baselines/feature-api-inventory.json)
maps each measured definition to source lines, missing body lines, and named
test contexts. Contexts identify exercising tests, not necessarily direct
assertions on every line or branch.

## What is tested

| Feature family | Automated evidence | Native evidence and limits |
| --- | --- | --- |
| Driver management | Existing `tests/manager/` suites cover discovery, version policies, offline/exact/compatible results, archive containment, cache integrity, SQLite recovery, locks, concurrent installation, cancellation and synthetic I/O failures. New lifecycle tests exercise public pin/unpin against actual disposable cache artifacts. | Cached Chrome/Edge resolution and compatibility checks pass. No fresh vendor downloads, separate CfT bundle or other-platform execution in this pass. |
| Service and lifecycle | `test_lifecycle_features.py` plus existing runtime/readiness tests cover service state, bounded port selection, startup/handshake errors, idempotent concurrent starts, cleanup, failed restart and cancellation. | Chrome/Edge tours exercise independent sessions, physical profile clones, cancellation and fresh acquisition after teardown. A separate bounded soak checks owned processes and tasks. |
| HTTP and commands | `test_transport_loopback.py` uses **real aiohttp and TCP**, not a mocked HTTP response, for Unicode JSON, routes, W3C errors, malformed responses, redirects, connection aborts, deadlines and cancellation. | Only the fixture's exact `127.0.0.1` address and ephemeral port are allowed. Other hosts, alternate local ports and external redirects remain blocked. |
| Session APIs | `test_session_features.py` covers navigation/retries, URL/title waits, screenshots/PDF, timeouts, cookies, windows, frame switching, scrolling, root lookups/waits, scripts, CDP, permissions, network conditions, casting and logs. | Chrome/Edge local tours verify representative actual renderer/driver behavior. Casting tests verify command payloads and errors only; no device is contacted. |
| Elements and shadow roots | `test_dom_features.py` directly tests every public declared method/property, including attributes, CSS/DOM values, accessibility, geometry, uploads, screenshots, submit, scoped search and all wait conditions, stale/missing handles and malformed responses. | Local browser fixtures additionally exercise rendered visibility, covered/offscreen/zero-size elements, forms, uploads and shadow roots. Offline tests alone do not validate JavaScript rendering. |
| Actions and alerts | `test_input_features.py` covers mouse/pen/touch command construction, five mouse buttons, drag/drop, keyboard/Unicode/modifiers, wheel payloads, aligned device ticks, dispatch/reset, failures and cancellation; alert text, accept/dismiss, typing and pauses. | Chrome/Edge execute representative action chains; the prompted `Actions.send_keys` example executes verbatim during the soak. Not every gesture/device combination is native-tested. |
| Firefox | `test_browser_features.py` covers context, full screenshots, packed/unpacked add-ons, archive payloads, metadata, returned IDs, uninstall, profiles, options, failure/cancellation and cleanup. | Native Firefox is unavailable on this host. These are real Python wrapper/profile tests against controlled responses, not native Firefox passes. |
| Safari | `test_browser_features.py` covers permission merging, malformed responses, vendor commands, documented unsupported operations, flags and Technology Preview configuration. | Native Safari automation permission was not established or changed. No Safari runtime pass is claimed. |
| Options, profiles and proxies | Browser/value suites cover defensive capabilities, validation, snapshots, extensions, preferences, binary paths, timeout units, proxy modes, credentials and bypass serialization. | The opt-in `scripts/test_browser_proxy.py` separately checks real Chrome/Edge HTTP proxy routing. It does not test SOCKS, HTTPS CONNECT, proxy authentication, PAC execution or WPAD. |
| Value objects and metadata | `test_value_features.py` covers geometry, copy isolation, versions, mappings, path validation, JSON/plist parsing and base/vendor metadata getters. | Pure/local behavior; no native browser required. |
| Documentation and release artifacts | Existing example/API/distribution/release tests remain in the complete suite. New `test_feature_inventory.py` checks the report's selection and execution-counting logic; `test_proxy_harness.py` checks proxy safety boundaries. | All prompted examples compile and known API calls bind statically. Selected examples execute; not all browser-dependent examples are individually run. No publication or remote CI execution. |

## Known failures: tested, but not fixed in this pass

There are **23 strict expected-failure cases across 10 issue families**. Every
expected failure is limited to the observed exception category; an unexpected
pass fails the test run, prompting removal of the marker after a fix. They are
not skipped checks and must not be counted as working features. They are included
in coverage because the buggy code actually executes.

| Issue | Cases | Reproduction and required correction |
| --- | ---: | --- |
| Empty screenshot path | 1 | `Element.save_screenshot("")` accepts an empty path and could choose a sibling of the current directory. The regression aborts at transport before writing anything. Reject an empty output target before requesting data; audit other callers of the shared path helper. |
| Stale Edge WebView capabilities | 1 | Read `options.capabilities`, then change `use_webview`: cached `browserName` remains stale. Invalidate cached capabilities when this option changes. |
| Negative navigation retry | 2 | `load(..., retry=-1)` and `refresh(retry=-1)` silently do nothing. Reject invalid retry budgets before navigation. |
| Invalid cookie collection | 1 | A `{"value": None}` cookie response leaks `TypeError`. Validate the collection and raise `InvalidResponseError`. |
| Invalid Firefox context | 5 | Arbitrary response values are returned instead of enforcing the documented `content`/`chrome` union. Validate the returned context. |
| Invalid Firefox add-on ID | 4 | Missing/empty/non-string IDs are accepted, or an unhashable value leaks `TypeError`. Validate before modifying the add-on cache. |
| Invalid Safari permissions | 4 | Wrong response shapes/non-boolean values are accepted or leak `TypeError`. Validate the nested `dict[str, bool]` contract. |
| Uncached JavaScript object | 2 | A standalone `JavaScript` can reach transport as a non-serializable object. The documented API promises cached objects: either reject an uncached object with a typed error or convert it into a valid payload. No new standalone-object feature is required by the regression. |
| Uncached CDP object | 1 | The analogous `DevToolsCMD` case sends a non-serializable command object. Reject or normalize before transport. |
| Relative path documentation mismatch | 2 | `validate_file`/`validate_dir` promise absolute paths but preserve relative inputs. Resolve the contract mismatch in behavior or documentation. |

The first nine families concern runtime robustness; the last is a documentation
contract mismatch. Fixing these and retaining the now-passing regression tests
is the next coding task. A successful pytest exit with acknowledged expected
failures is **not** a clean release acceptance result.

## What remains unverified

These checks are not silently replaced by mocks or counted as native passes:

- **Missing native targets:** Firefox, standalone Chromium, separate Chrome for
  Testing bundles, beta/dev channels and Windows WebView2. Install/provision the
  appropriate isolated runner before testing them.
- **Safari and permissions:** establish explicit Remote Automation setup on a
  suitable host; permission-dependent camera/microphone/device behavior needs
  controlled grants and appropriate fixtures. No system setting was changed.
- **Other OS/runtime combinations:** Windows/Linux and Python 3.10/3.12/3.14
  require their actual runners. The configured CI matrix is not evidence of a
  successful remote run.
- **Physical/external systems:** real cast receivers, authenticated proxies,
  SOCKS/HTTPS CONNECT, PAC/WPAD, live vendor downloads, corporate TLS interception
  and uncontrolled third-party sites require dedicated integration environments.
  Google search can stop at CAPTCHA; it is not a deterministic package test.
- **Long-duration/platform interference:** bounded soak results do not establish
  hour/day stability, absence of every leak, hardware power-loss durability,
  network-share safety or antivirus-specific behavior. Synthetic disk-full,
  permissions and interruption tests do exist, but are not physical platform
  certification.
- **Remaining path/input combinations:** all measured public bodies are touched,
  not every malformed scalar, window recovery sequence, scroll trajectory,
  cross-feature ordering, or example/browser permutation. Consult missing lines
  and branch counts rather than interpreting the inventory as exhaustive proof.

## Reproduce

Use an isolated development environment with `requirements-dev.txt` installed.
The default complete suite does not launch installed browsers or access external
sites, but **does require permission to bind disposable loopback servers**:

```bash
python -m pytest --asyncio-debug
python -m coverage run --branch --source=aselenium -m pytest --asyncio-debug
python -m coverage report
python -m coverage json -o coverage.json
python scripts/report_feature_coverage.py coverage.json feature-coverage.json
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python scripts/check_api_quality.py
python scripts/check_example_contracts.py
python -m mypy
```

If an execution sandbox forbids **all** local socket binding, an explicitly
reduced run is possible; its 28 loopback cases are **deselected, not passed**:

```bash
python -m pytest --asyncio-debug -m "not loopback"
```

Run the native tour against a populated private driver cache; downloads remain
disabled. The profile example uses a new empty template, not personal profiles:

```bash
python src/demo_local.py run --browser chrome --binary /absolute/path/to/chrome --cache-dir /absolute/cache/parent --profile-demo --output-dir /absolute/test-output
python scripts/test_browser_proxy.py --browser chrome --binary /absolute/path/to/chrome --cache-dir /absolute/cache/parent
python scripts/soak_browser.py --browser chrome --binary /absolute/path/to/chrome --cache-dir /absolute/cache/parent --cycles 100 --concurrency 4
```

Repeat with `--browser edge` and its actual binary. Native tests require process
launch and local networking permissions. Proxy proof requires both browser-visible
content and an origin request containing a proxy-only proof header; direct
loopback bypass cannot accidentally pass. The proxy never forwards a request to
an external host and refuses CONNECT.

### Optional per-test context inventory

The saved inventory includes dynamic test contexts. For reproduction, create a
temporary coverage configuration with `[run]`, `branch = true`,
`source = aselenium`, and `dynamic_context = test_function`. Run the suite except
`tests/manager/test_files.py` using that configuration, then append that file with
dynamic contexts disabled:

```bash
python -m coverage run --rcfile=/absolute/context-coverage.ini -m pytest --asyncio-debug --ignore=tests/manager/test_files.py
python -m coverage run --append --branch --source=aselenium -m pytest --asyncio-debug tests/manager/test_files.py
python -m coverage json --show-contexts -o coverage-contexts.json
python scripts/report_feature_coverage.py coverage-contexts.json feature-api-inventory.json
```

Use the same coverage data file in both invocations. The split is necessary
because one cache fault-injection test temporarily replaces `sqlite3.connect`;
dynamic-context switching writes coverage's own SQLite database while that fault
is active. The split avoids a measurement-tool conflict **without removing that
test from the measured suite**. The normal complete test run needs no split.

## Change boundary

Production package code, version, runtime dependencies and the user's `.venv`
were not changed in this pass. No browser installation, personal-profile access,
Safari permission change, commit, push or publication was performed. Historical
validation records retain their earlier counts and scope; this report supersedes
their public-feature coverage assessment, not their dated observations.
