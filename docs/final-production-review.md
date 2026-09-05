# Final production review

This is the preceding review snapshot. The later
[pre-deployment review](pre-deployment-review.md) records additional fixes and
current-candidate results; the counts and artifact identities below remain
historical evidence.

Review date: **2026-09-05**. This is a bounded release-candidate review, following
the [release-acceptance expansion](release-acceptance.md). The current 2.0.0
follow-up results below supersede the earlier 2,823- and 2,652-test snapshots;
older records remain historical evidence rather than continuously updated badges.

**Outcome: the 2.0.0 candidate passes every currently executable local release
gate.** The earlier multi-environment and native-browser evidence remains useful,
but hosted Windows/Linux and final-tag publication behavior must still be proven
by the configured CI/release workflow.

The review covered driver management first, then process/session ownership,
connection scheduling, options and browser adapters, DOM/input/value handling,
documentation, typing, distribution contents, and the acceptance harnesses.
The package and rebuilt distributions are version 2.0.0. No release was published
and no commit, push, or tag was performed during this review. Existing unrelated
working-tree changes were preserved.

## Preceding 2.0.0 follow-up verification

- The unrestricted Python 3.13.12 suite passed **3,227 tests** with asyncio
  debugging; the sole platform-inapplicable case was the Windows drive-relative
  syntax check, skipped on macOS. This run included real disposable loopback
  HTTP/TCP/TLS servers and owned-process inspection.
- Coverage measured **92.41% statement coverage** (7,174/7,763) and **83.45%
  branch coverage** (1,836/2,200), or **90.43% combined**. Every configured
  component floor passed.
- Ruff lint and formatting pass across **136 files**. The structural API audit
  covers **135 files, 2,407 functions/methods, 294 classes, and 196 prompted
  examples** with no findings. The example-contract checker also reports none.
- The configured mypy gate now checks all maintained Python under `src/` and
  `scripts/`: **78 source files** pass. This includes the local/Google demos,
  quick start, browser smoke/soak programs, benchmarks, and release tooling—not
  only the importable package. Installed-wheel consumer typing remains a separate
  distribution gate.
- The 2.0.0 wheel and source distribution pass strict metadata and archive
  integrity checks. Both carry matching `LICENSE`, `NOTICE`, README metadata,
  `py.typed`, and GeckoDriver compatibility data; runtime sources in the wheel
  match the reviewed checkout.
- A clean, non-editable installation of that wheel passed the complete local
  fixture tour on current macOS Chrome (**15/15 stages**) and Firefox (**15/15
  stages**). Safari passed all **12 applicable stages**; frames, W3C action chains,
  and concurrent sessions are the same three explicit facade exclusions described
  below. The installed package reports version 2.0.0 and its public typing consumer
  plus all three negative controls pass.
- The refreshed dependency audit reports no known vulnerabilities in the resolved
  environment. The editable Aselenium entry is intentionally skipped, so that
  result is not a security proof for Aselenium itself.

This follow-up was run in the current macOS/Python environment. Chrome, Firefox,
and Safari therefore have fresh final-wheel evidence. The earlier Python 3.11,
minimum-dependency, Edge, and reliability runs below predate the last
path/response/demo cleanup and remain baseline evidence. The release workflow
must rerun its Python 3.10-3.14, Windows/Linux/macOS, minimum-dependency, Edge,
and native reliability matrix on the tagged commit.

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

## Earlier multi-environment verification baseline

At this earlier checkpoint, four regression files added **171 cases**, bringing
that snapshot to **2,823 tests**. Parameterized cases are not a count of distinct
defects. These numbers are retained for traceability and are not the current
test count.

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
their own acceptance. Mypy now covers all maintained Python in `src/` and
`scripts/`; it is not a strict, `Any`-free typing guarantee. A bounded soak does
not prove unlimited uptime or absence of leaks.

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
