# Modernization completion and release-candidate report

> Historical audit: this records the implementation at its original checkpoint.
> Subsequent [compatibility removals](legacy-removal.md) supersede its old-feature
> and dependency guidance; historical measurements are not current support promises.

Historical first-pass report. See the [original 12-step second-pass review](original-12-step-second-pass.md)
for current status, additional fixes, and corrected acceptance boundaries.

Date: 2026-09-04. Workspace changes are uncommitted. The package version remains
1.0.5; nothing was pushed or published. The user authorized the SQLite design and
continuation through Steps 6–14, superseding the earlier review checkpoint.

## Outcome

The remaining coding sequence is implemented. Driver management now uses a
transactional, platform-aware cache and streamed downloads. The subsequent work
addresses protocol handling, resource ownership, profile isolation, polling,
browser-specific defects, documentation, and candidate validation.

**636 tests pass on both locally available Python versions, 3.11.15 and 3.13.12,
on macOS 26.6.2 ARM64**, with asyncio debugging enabled and no pytest warnings or
xfails. Runtime-name lint passes across source, scripts and tests. The mypy gate
passes for nine modernized infrastructure modules. Dependency consistency checks
pass. Wheel/sdist creation, rebuild from sdist, and isolated installed-wheel
construction are tested. CI is configured, not represented as remotely executed.

Live headless Chrome and Edge also pass online provisioning followed by a strictly
offline second acquisition. Their tests use only disposable caches/profiles and
local data URLs; they do not use a personal profile or an external test website.

## Step-by-step delivery

| Step | Implemented result | Verification |
| --- | --- | --- |
| 6 — Transactional cache | SQLite v2; product/version/OS/architecture/type identity; process locks; atomic staging publication; manifest recovery; executable checksums; pin/lease-aware eviction; explicit copy-only Feather import | Round trips, database corruption/schema rejection, failed-commit preservation, competing processes, abrupt process death, pin/lease protection, stale pruning state, legacy-input preservation and migration |
| 7 — Responsive provisioning | Per-installation owned HTTP client; file-backed bounded downloads; SHA-256 while streaming; bounded GET retries and Retry-After; four-download/four-worker limits per loop; cancellation-owned workers | Offline request guards, fake vendor contracts, size-limit and cancellation faults, reuse/close assertions, generated-download memory measurements |
| 8 — Driver checkpoint | Offline policies, real driver identity checks, disposable native startup, artifact validation, performance record and guide | Chrome and Edge online/offline smoke; executable version output and SHA-256; installed-wheel import fence rejects pandas/pyarrow |
| 9 — Small API fixes | Awaited form submit; zero-timeout first lookup; unit-correct timeout equality; consistent mutable hashing policy; Shadow hash; print error formatting; README syntax and await corrections | Browser-free regressions and README Python-fence parsing |
| 10 — Protocol transport | Validated response envelopes; HTTP 4xx/5xx normalization; safe error construction; arbitrary JavaScript values retained; encoded identifiers; bounded GET redirects; redacted request logs and config repr | Success/error/malformed payload matrix; route escaping; redirect bounds; all WebDriver exception constructors; secret-redaction checks |
| 11 — Lifecycle and isolation | Acquisition snapshots; separate physical profile copies; startup readiness checks; owned process reaping; bounded teardown; cancellation shielding; retryable failed cleanup; service argument forwarding; command transactions | Distinct profile directories, independent configuration, teardown-failure retry, repeated start/stop, live service/session cleanup, transaction/wait interaction |
| 12 — Waits and DOM semantics | Shared monotonic polling budgets; immediate zero-timeout observation; frame re-resolution; bounded scrolling; additive DOM text, viewport and hit-test properties; legacy visibility defaults retained | Deadline tests, delayed-frame fixtures, root/element/shadow first-match tests, live frame/shadow use |
| 13 — Browser-specific behavior | Firefox unpacked add-on support, current manifest ID field and server ID assignment; Firefox restart port generation; reusable action chains; strict screenshot decoding; Safari restrictions retained pending evidence | Manifest/add-on/service fixtures; action and screenshot tests; native Chrome/Edge actions, tabs, frame, shadow, input and screenshots |
| 14 — Candidate preparation | py.typed, metadata correction, Python 3.10+ retention, dev quality gates, broader CI matrix, runnable opt-in smoke and benchmarks, migration guide, wheel/sdist artifacts | Both local test environments, lint/type gates, pip check, build/rebuild/install checks, diff whitespace checks |

Historical Step 1–5 reports and benchmark files remain intact. Feather-specific
tests were ported to SQLite invariants instead of retaining an unused production
backend solely to preserve test internals.

## Measured performance

The detailed samples and source digest are in
[the final benchmark record](baselines/modernization-final.json). Compare against
[the Step 3 baseline](baselines/driver-manager-step-3.json), on the same local
Python 3.13.12/macOS ARM64 environment.

The candidate imports in approximately **141 ms**, versus **252 ms** at Step 3:
about a 44% reduction. Post-import process RSS is approximately **44 MiB**,
versus **109 MiB**, largely following removal of eager pandas/pyarrow imports.
Exact cache hits at 1,000 entries are approximately **0.37 ms**, versus **0.58 ms**.
Exact misses are approximately **0.22 ms**, versus **0.48 ms**.

These are medians of seven samples, not service-level guarantees. Final import
samples ranged from 106 to 209 ms, illustrating local timing variability. The cache
benchmark uses small synthetic executable files; it now includes SHA-256 checks.
Larger executables cost more to verify. OS disk caches were not flushed. The
SQLite open/query measurement and Feather reload measurement are different
operations and are not advertised as a like-for-like speedup.

Generated downloads of 8, 64 and 128 MiB use approximately **0.5–0.6 MiB of peak
traced Python allocations**, rather than a complete archive-sized Python buffer.
This is a streaming implementation check, not a full RSS or live-network memory
benchmark: tracemalloc excludes the OS file cache and some native allocations.
See [the validation record](baselines/modernization-validation.json) and
`scripts/benchmark_download.py` for the workload and exact values.

Native acquisition measurements include driver startup and New Session, not just
cache lookup. Offline acquisitions were approximately **0.5 seconds** for both
tested browsers. Online timings varied between runs with network/vendor latency;
the recorded samples must not be treated as stable download-performance claims.

## Verified support and evidence boundaries

| Environment/feature | Evidence in this run |
| --- | --- |
| macOS ARM64, Python 3.13.12 | Full offline suite, quality gates, candidate builds, Chrome/Edge native smoke |
| macOS ARM64, Python 3.11.15 | Full offline suite and dependency check |
| Chrome 152.0.7977.76 + ChromeDriver 152.0.7977.82 | Online provisioning, offline reuse, executable identity, local navigation, input, clicking, W3C actions, tabs, frame, shadow root, screenshot, teardown |
| Edge 151.0.4129.93 + EdgeDriver 151.0.4129.107 | Same native smoke coverage as Chrome |
| Firefox | Offline manager/compatibility/add-on/profile/service fixtures; **no native Firefox run**, because Firefox is not installed |
| Safari | Offline discovery/facade coverage; **no native Safari run** and no automation settings changed; restricted operations were not enabled speculatively |
| Chromium facade / Chrome-for-Testing browser bundles | Offline resolution, manifests, architecture and archive fixtures; no separate native Chromium/CfT browser installation run |
| Windows/Linux native execution | Not run locally. CI includes Windows and macOS Python 3.13 plus Linux Python 3.10–3.14; those remote jobs have not run in this task |
| Shared/network filesystem caches | Not certified or assumed supported |
| Full-package strict typing | Not claimed. The enforced mypy scope is nine modernized infrastructure modules; legacy annotations outside that scope remain gradual |

The architecture matrix is version-specific, not a blanket promise. Resolution
checks the vendor manifest and fails for absent artifacts. Matching Chrome/Edge
build components and Firefox compatibility bounds follow the primary vendor
documentation, rather than assuming that a newer driver is universally compatible:
[Chrome version selection](https://developer.chrome.com/docs/chromedriver/downloads/version-selection),
[Chrome-for-Testing inventory](https://github.com/GoogleChromeLabs/chrome-for-testing),
[Edge WebDriver compatibility](https://learn.microsoft.com/en-us/microsoft-edge/webdriver/),
and [Mozilla support table](https://firefox-source-docs.mozilla.org/testing/geckodriver/Support.html).

Protocol envelope and routing work was checked against the
[W3C WebDriver draft](https://www.w3.org/TR/webdriver2/). The draft is not evidence
that every browser implements every optional or vendor-specific feature.

## Compatibility changes worth reviewing

- The cache is now `.aselenium/v2`; legacy Feather caches are not automatically
  imported. pandas/pyarrow are only in the optional `legacy-cache` extra.
- Full numeric pins are exact and persistently protected from eviction. The new
  asynchronous `manager.pin(..., pinned=False)` explicitly removes protection.
- `Timeouts` and options objects are mutable and unhashable. Timeouts compare in
  consistent units; configuration/proxy repr output is redacted.
- Invalid, nonfinite or nonpositive I/O deadlines are rejected. Polling waits allow
  zero and always perform an immediate observation.
- Malformed responses and authentication/TLS errors are no longer swallowed as
  successful empty responses or ordinary missing artifacts.
- Session cleanup does not retry commands forever. It retains failed resource
  ownership for another `quit()` attempt; cancelling a blocking operation may
  wait for the owned worker to finish.
- Action chains can be reused after `perform()`. Dispatch clears their prior
  inputs, including after a failure, so input is not silently replayed.
- Legacy `visible`/`viewable` behavior has not been silently redefined. New DOM
  helpers have explicit, narrower semantics documented in the usage guide.

## Release boundary

The implementation is ready for review as a **locally validated candidate**, not
an automatically published release or universal cross-platform certification.
Before a public release, run the configured remote CI and the relevant native
Firefox/Safari/Windows/Linux tests. Test real CfT browser bundles if they are part
of the advertised release matrix. Choose a new version and release notes in a
separate authorized publication step.

Private local caches remain the supported deployment assumption. Executable
digests detect local changes, not signed vendor authenticity or corruption in
every browser support library. Kernel-level stalled filesystem operations remain
outside Python's ability to forcibly cancel. Raw-path consumers not using an
acquisition lease must use pins if they need protection from cache eviction.
