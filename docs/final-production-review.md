# Final production review

Review date: **2026-09-05**. This is a bounded release-candidate review, following
the [release-acceptance expansion](release-acceptance.md). Its results supersede
the earlier 2,652-test snapshot for the code reviewed here; older records remain
historical evidence rather than continuously updated badges.

> **Version note:** the tested artifacts in this dated record were labeled
> 1.0.5. The same reviewed runtime was subsequently assigned the 2.0.0 candidate
> version; this record and its hashes intentionally retain the tested identity.

**Outcome: the reviewed code passed the local release-candidate gates**, including
three complete regression environments, four installed-browser tours and the
Chrome/Edge recovery, proxy and sustained-session checks described below.

The review covered driver management first, then process/session ownership,
connection scheduling, options and browser adapters, DOM/input/value handling,
documentation, typing, distribution contents, and the acceptance harnesses.
The package was still version 1.0.5 at the time of this review. No release was
published and no commit or push was performed during the review. Existing
unrelated working-tree changes were preserved.

## Corrections made

### 1. Driver selection and provider responses

- An exact Chrome-for-Testing request now requires a complete four-component
  version. A major/build selector can no longer silently select a different
  version, including through an existing cache entry. Complete exact requests
  retain their driver/browser pinning behavior.
- Malformed Chrome-for-Testing asset URLs and Gecko release metadata now produce
  classified driver-request errors instead of leaking incidental Python errors.
  Invalid metadata cannot silently become a fallback or update the recorded
  maximum Gecko version. Existing intentional fallback cases remain supported.
- Download, cache integrity, safe extraction and publication protections were
  retained. No unmeasured optimization weakened these checks.

Regression file: [manager final-review tests](../tests/manager/test_final_review.py)
— **22 cases**.

### 2. Temporary profiles and configuration validation

- Replacing or removing a profile now releases its owned clone deterministically,
  even if application code retains the old `Profile` object.
- Closing options invalidates cached capabilities and removes stale Chromium
  profile arguments. Firefox no longer retains a stale encoded profile capability.
- Replacement creates the new clone before releasing the previous configuration.
  Failed cleanup retains ownership for a later retry, including the case where
  both the old clone and the unused replacement fail cleanup. Independent session
  snapshots do not inherit pending-cleanup ownership.
- Boolean options require actual booleans: for example, the string `"false"`
  cannot inadvertently enable insecure certificates or another boolean flag.
- Invalid timeout units, excessively large timeout values and malformed enum
  inputs are rejected through the configuration-error contract before mutation.
  The millisecond upper bound follows the
  [WebDriver timeouts specification](https://www.w3.org/TR/webdriver2/#timeouts).
- Safari service arguments are forwarded without duplicate constructor bindings.
  Firefox respects an explicit `--websocket-port=...` and handles trailing
  directory separators correctly when preparing extension archives.

Regression file: [vendor/options final-review tests](../tests/test_final_vendor_review.py)
— **117 cases**, including adversarial inputs and cleanup failures. Independent
review found no additional defect in the new profile ownership/retry paths.
Original profile directories are never the cleanup target.

### 3. Session state, cancellation and protocol validation

- Related reads and updates now share the existing command-transaction boundary
  for timeouts, window rectangles, network conditions, window creation and window
  closure. Deterministic concurrent tests previously reproduced lost updates,
  closing the wrong window, and duplicate named windows overwriting cache entries.
- Timeout mutations invalidate the cached snapshot before dispatch. Cancellation
  after a possible remote update cannot leave stale state for the next mutation.
- Window-handle collections are validated completely before cache changes.
  Element `enabled` and `selected` observations reject non-boolean responses.
- A native `JavaScriptTimeoutError` is no longer swallowed when it arrives at
  the polling deadline.
- Public Element, Shadow and supported container subclasses serialize using
  their base contracts, including nested values, without changing the input.
  Exact-type dispatch remains the fast path.

Regression file: [session final-review tests](../tests/test_final_session_review.py)
— **27 cases**, each observed failing before its corresponding fix.

Transaction ownership follows inherited async context. User-created child tasks
inside an explicit transaction inherit that ownership, just as internal deadline
and polling helpers do. Await dependent operations sequentially there; do not
use `asyncio.gather` to imply serialization between such child tasks. This
existing mechanism was documented, not redesigned in this review.

### 4. Partial startup, diagnostics and responsiveness

- If process launch succeeds but process-identity capture fails, cleanup now
  escalates from termination to killing the authoritative child when necessary
  and reaps it. A failed cleanup keeps ownership available for a retry.
- Representing an unstarted service for logging no longer allocates a port or
  opens a socket.
- Canonical profile-path ownership checks run through the existing bounded
  worker helper, avoiding filesystem resolution on the event-loop thread.
  This does not make every options snapshot or profile-copy operation asynchronous.
- Nullable service/session properties and several public descriptions and
  annotations were corrected. Docstring examples retain singular `Example:`
  headings with Python `>>>` and continuation `...` prompts.

Regression file: [lifecycle final-review tests](../tests/test_final_lifecycle_review.py)
— **5 cases**.

## Final verification

The four new regression files add **171 cases**, bringing the full suite to
**2,823 tests**. Parameterized cases are not a count of distinct defects.

| Environment | Passed | Failures / errors / skips |
| --- | ---: | --- |
| Python 3.13.12, current resolved dependencies | 2,823 | 0 / 0 / 0 |
| Python 3.11.15, current resolved dependencies | 2,823 | 0 / 0 / 0 |
| Python 3.11.15, exact runtime minima | 2,823 | 0 / 0 / 0 |

Every run included asyncio debugging, local HTTP/TCP/TLS integration and
owned-process checks. Current dependencies were aiohttp 3.14.3, psutil 7.2.2 and
orjson 3.12.0. Exact minima were aiohttp 3.14.3, psutil 5.8.0 and orjson 3.11.6.

Python 3.13 measured **92.55% statement coverage** (6,756/7,300) and **83.25%
branch coverage** (1,590/1,910). All configured critical-component floors passed.
These are distinct coverage measures, not proof of every execution path.

Additional gates passed:

- Ruff lint and formatting; **126 Python files** already formatted.
- Structural API audit: **125 files, 2,141 functions/methods, 272 classes and
  181 prompted example sections**, with no reported issues.
- Example syntax/signature checks and the existing **38 distinct verbatim
  docstring examples** executed by the runtime suite.
- Configured mypy checks for **19 modules**, plus installed-wheel public typing:
  the valid consumer passed and both deliberate misuse cases were rejected.
- Dependency consistency and strict wheel/source-distribution metadata checks.
- A final **410-test** documentation/API/distribution recheck passed after the
  review report and README edits, including rebuilding a wheel from the sdist.
- Dependency vulnerability audit: **no known vulnerabilities** among the 67
  audited distributions. The editable Aselenium distribution was explicitly
  skipped; this result is not a vulnerability assessment of our own code.

### Installed-wheel native acceptance

A new, non-editable environment outside the checkout imported the built wheel.
Its **55 Python files plus two resources** matched the checkout byte-for-byte.
Browser tests used local fixtures, dedicated caches and disposable profiles,
without downloads or changes to personal profiles or Safari automation settings.

| Browser on macOS 26.6.2 ARM64 | Browser / driver | Passed stages | Explicit skips |
| --- | --- | ---: | ---: |
| Chrome | 152.0.7977.76 / 152.0.7977.82 | 15 | 0 |
| Edge | 152.0.4191.62 / 152.0.4191.62 | 15 | 0 |
| Firefox | 155.0.1 / 0.37.1 | 15 | 0 |
| Safari | 26.6.2 / 26.6.2 | 12 | 3 |

Safari explicitly excludes frames, action chains and concurrent sessions in the
current facade. Its artifact stage checks PNG output, not disabled PDF printing.

Chrome and Edge each passed all four reliability gates: browser/driver crash and
hang recovery, HTTP/HTTPS browser proxy routing, all six manager authenticated
CONNECT/routing cases, and a sustained mixed workload. No recovery scenario
needed emergency cleanup by the harness.

| Browser | Workload duration | Iterations | Native script timeouts recovered |
| --- | ---: | ---: | ---: |
| Chrome | 120.28 seconds | 267 | 27 |
| Edge | 120.05 seconds | 262 | 27 |

Both ended with no observed owned processes or tasks remaining and their session
and template profiles removed. Measured growth stayed within the explicit limits;
this is not a claim of zero memory growth. The browser HTTPS proxy fixture opts
into insecure certificates for its disposable session; the separate manager
CONNECT fixture verifies TLS trust and hostname checking.

## Compatibility and remaining release boundaries

The changes intentionally tighten invalid-input handling. Supply `True`/`False`,
not truthy strings or integers, for boolean settings; use a complete version with
the exact CfT policy. Reconfigure a profile after removing/closing it instead of
depending on stale launch arguments. A retained reference to a removed temporary
profile no longer keeps its directory alive.

This review establishes local release-candidate evidence, not universal production
certification. Before publication, run the configured remote CI and release gates
on the exact candidate. Windows/Linux native behavior, standalone Chromium/CfT
bundles, WebView2, casting hardware and untested browser channels still require
their own acceptance. Whole-package strict typing remains outside the configured
19-module gate. A bounded soak does not prove unlimited uptime or absence of leaks.

Profile cleanup is not a transactional filesystem rollback after partial deletion.
Options mutation is not claimed to be arbitrary-thread-safe. An authoritative
child-process fallback cannot discover descendants that escaped before ownership
was captured. Browser automation is not a security sandbox for untrusted sites.

See the [machine-readable validation record](baselines/final-production-review-validation.json)
for source hashes, exact environments, artifact identity and retained native
evidence. Raw temporary paths are local reproduction aids and may eventually be
removed by the operating system. The tested wheel predates this retrospective
report; rebuild the final distribution when publishing, preserving the validated
runtime contents. The [acceptance guide](release-acceptance.md) contains the
reproduction commands and CI boundaries.
