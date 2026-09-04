# Original 12-step plan: second-pass review and improvements

> Historical audit: this records the implementation at its original checkpoint.
> Subsequent [compatibility removals](legacy-removal.md) supersede its old-feature
> and dependency guidance; historical measurements are not current support promises.

Date: 2026-09-04. This report uses the **original 12-step numbering**, not the
later 14-step driver-first sequence. It supersedes the earlier completion report
for current status. Package version remains 1.0.5, Python remains >=3.10, and all
changes are local and uncommitted. Nothing has been pushed or published.

## Outcome and correction to the previous status

The previous 636-test suite passed unchanged at the start of this review, but it
did not establish that every item in the original plan was finished. This pass
found real untested defects and unfinished packaging/release work. In particular,
options updates were not consistently atomic, relative output filenames failed,
command queueing could exceed a command timeout, and metadata consolidation and
release-workflow hardening had not been completed.

Each of the 12 workstreams was re-examined. Confirmed defects were fixed and
covered by regressions; unchanged safety/resolution code was revalidated rather
than rewritten without evidence. The current deliverable is a locally validated
candidate, not universal browser certification or proof that no defects remain.

## Step-by-step audit

| Original step | Review finding and action | Evidence / boundary |
| --- | --- | --- |
| **1. Regression foundation** | Re-ran all 636 existing tests. The default test guard blocked manager probes but not the service module's imported Popen; extended the guard. Added targeted second-pass regressions and release-configuration checks. | Offline tests cannot launch an unmocked service through the package. Controlled child processes remain necessary for cache and distribution tests. |
| **2. Packaging and small API fixes** | Bare filenames such as `capture.png` incorrectly failed parent-directory validation. Normalize output paths to absolute paths. Invalid rectangle values triggered a formatting exception instead of the intended package error; fixed escaped braces. Verify wheel metadata after migration. | Before/after regressions; wheel and sdist construction, rebuild from sdist, installed-wheel import and resource checks. |
| **3. Filesystem/provisioning safety** | Rechecked archive containment, link handling, expansion limits, owned staging, bounded filesystem retries, and literal executable probes. Existing protection tests continue to pass; no speculative extraction rewrite. Output publication is additionally atomic under Step 9. | Archive, probe, filesystem and crash-injection fixtures. Native Windows behavior and hardware power-loss durability remain unverified. Probe runtime is bounded, but version-probe stdout is not byte-capped. |
| **4. Transport/errors/diagnostics** | A command's timeout started only after acquiring its locks. Its budget now covers ownership queueing, wire queueing and HTTP execution. Malformed New Session IDs could raise AttributeError/TypeError; require a nonempty string and raise InvalidSessionError. Removed a duplicate error-map key without changing its effective mapping. | Queued commands time out without dispatch, locks remain reusable, arbitrary successful JavaScript values are preserved, malformed-session tests fail cleanly, and existing route/redaction/redirect tests pass. |
| **5. Lifecycle/cleanup** | A second start after failed cleanup could overwrite still-owned resources. Such contexts now require quit() and a new acquisition. Child process handles could be forgotten once their parent exited; retain original child identities until cleanup succeeds. | Regressions reproduce both failures. Live repeated acquire/use/close works on Chrome and Edge. Kernel-stalled filesystem operations cannot be forcibly cancelled; native process semantics on other OSes still need runners. |
| **6. Acquisition/configuration isolation** | Arguments and extensions could partially apply before a later invalid item; batches now validate before committing. Mutable capability/preference inputs and returned dictionaries could bypass cache invalidation; copy at boundaries. Proxy mutations now refresh future capability snapshots while acquisition snapshots remain independent. Correct noProxy to an array and omit the nonstandard autodetect flag. | Atomicity, mutable-aliasing, proxy serialization, profile-isolation and transaction tests. Existing vendor-specific FTP/SOCKS-auth fields are retained for compatibility, not claimed as portable W3C fields. |
| **7. Version selection/discovery** | Rechecked exact pins, compatible selectors, offline misses, platform keys, CfT manifests and Firefox compatibility bounds. No new resolver substitution was justified by this pass. | All deterministic resolution/discovery tests rerun; Chrome/Edge live online and offline acquisitions pass. Firefox unknown-version fail-closed behavior retained. No separate native CfT browser-bundle validation. |
| **8. Cache/dependency reduction** | Added an index on leases(key); eviction no longer needs a full lease-table scan for each candidate artifact. Kept SQLite schema compatibility and rechecked pins, leases, platform separation, corruption, process contention, crash recovery and copy-only migration. | Query-plan assertion confirms index use, plus existing multiprocess/cache tests. Core wheel imports with pandas/pyarrow blocked. Legacy cache input remains untouched. |
| **9. Downloads/bounded work** | An asynchronously entered provisioning client could be created twice by sibling requests; serialize client initialization. Validate every vendor redirect before following it: HTTPS, no URL credentials, bounded hops, one existing request deadline. Move PNG/PDF output, session capability/profile encoding and Firefox add-on work to owned workers. Outputs publish atomically. | Concurrent-client, safe-CDN/downgrade/credential redirect tests, worker cancellation/heartbeat checks, old-file preservation, streaming memory measurements and live output checks. Synchronous acquire() still copies an explicitly configured profile; see limitations below. |
| **10. Waits/DOM behavior** | Reject invalid poll intervals before invoking predicates. Added nested-wait deadline regression. Hit-testing an element inside a shadow root previously stopped at its host; descend through its shadow-root chain while checking external occlusion. | Nested deadline and invalid-input tests; live hidden, zero-size, offscreen, covered and shadow-root fixtures. Legacy visible/viewable semantics remain unchanged. Hit tests are observations, not promises a later click will succeed. |
| **11. Browser-specific behavior** | Safari inspection/profiling/Technology Preview setters failed to invalidate cached capabilities; fixed. Action durations now consistently reject bool, nonfinite and negative inputs across construction, movement and pauses. Firefox full-page screenshot output uses the same atomic worker path. | Safari configuration tests only; unsupported operations were not enabled. Chrome/Edge live tests cover actions, windows, frame/shadow DOM, PNG, PDF and repeated offline startup. Firefox and Safari native execution remain not run. |
| **12. Quality controls/candidate** | Moved metadata from setup.cfg into pyproject.toml, retained setuptools and runtime requirements, and added SPDX license metadata. Expanded Ruff from selected name errors to all F checks plus E9, and typing from 9 to 11 modules. Added optional-migration CI, strict Twine metadata checks, reusable test workflow, immutable action pins, tag/version validation, least-privilege release jobs and opt-in publication. | Full suites on two interpreters, build/rebuild/install checks, static gates, workflow YAML/guardrail tests and rebuilt candidate artifacts. Remote CI execution and external publication settings are not validated by local YAML tests. |

## Verification

- **688 tests pass on Python 3.13.12 and Python 3.11.15**, on macOS 26.6.2 ARM64,
  with asyncio debug enabled and no pytest warnings or xfails.
- Ruff `E9,F` passes across source, scripts and tests. Mypy passes for **11**
  infrastructure modules; package-wide strict typing is not claimed.
- Dependency consistency checks pass in both local environments.
- Wheel/sdist, sdist-to-wheel rebuild, isolated installed-wheel imports, packaged
  compatibility data, py.typed and runtime metadata are checked automatically.
- Release workflow YAML and its security guardrails are tested locally; no GitHub
  job was dispatched. Strict Twine checks are run on the final candidate artifacts.

| Native browser | Browser / driver version | This pass |
| --- | --- | --- |
| Chrome | 152.0.7977.76 / 152.0.7977.82 | Online provisioning, offline reuse, DOM state fixtures, actions, windows, frame, shadow hit test, PNG/PDF output and teardown passed |
| Edge | 151.0.4129.93 / 151.0.4129.107 | Same expanded local fixture passed |
| Firefox / Safari | Not run natively | Offline coverage only; no installation or automation-setting changes |
| Windows / Linux / separate CfT browser bundle | Not run natively | CI/fixtures prepared; not represented as passing |

Browser tests used local data URLs and disposable caches/profiles. No personal
profile or public test website was used. Temporary browser-test artifacts were
removed on exit; no legacy user cache was deleted.

## Performance record

The new seven-sample local run recorded an **88 ms median import**, approximately
**44.3 MiB post-import RSS**, and **0.319 ms hit / 0.204 ms miss** at 1,000 synthetic
cache entries. These are observations, not attribution of a speedup to this pass:
system activity and filesystem caching vary between runs. The final first-pass
record was about 141 ms/44 MiB and had substantially wider import timing variation.

The download-streaming check again used roughly **0.5–0.6 MiB of peak traced Python
allocations** for generated 8, 64 and 128 MiB streams. It measures Python allocations,
not total RSS or live-network performance. The benchmark record includes raw samples,
runtime/dependency versions and an uncommitted-source digest.

See [second-pass benchmark](baselines/original-12-step-second-pass.json) and
[second-pass validation](baselines/original-12-step-validation.json). Earlier
records are retained for comparison; they are not silently overwritten.

## Compatibility changes to review

- Option dictionaries returned by accessors are independent copies. Use setters
  to change options; mutating a returned dictionary no longer changes hidden state.
- Failed argument/extension batches leave earlier configuration unchanged.
- noProxy is serialized as a list, and autodetection uses proxyType alone.
- Per-command timeouts now include queueing. A timed-out command may have an unknown
  remote outcome if it had already been dispatched; it is never automatically replayed.
- Contexts with failed cleanup reject restart. Call quit() to retry cleanup, then
  obtain a fresh context. Original child-process handles remain owned across retries.
- Screenshot/PDF saves support bare relative filenames and use an adjacent temporary
  file plus atomic replacement. Existing output symlinks are replaced as directory
  entries, not followed. New output permissions are private (typically 0600 on POSIX).
  Hard links to a previous output keep its old contents. Cancellation waits for the
  owned writer and can occur after successful publication.
- Build tooling now requires setuptools >=77.0.3 for standardized license metadata;
  this does **not** increase the runtime Python minimum or mandatory runtime dependencies.
- setup.cfg was removed after its metadata was transferred to pyproject.toml. Its
  tracked original remains recoverable through Git; no package metadata was discarded.

## Remaining acceptance limits, not hidden completion claims

1. Run the configured native platform/browser matrix before advertising universal
   support. The local tests are not a replacement for Windows/Linux subprocess,
   Firefox add-on/profile, Safari automation or real CfT bundle execution.
2. Acquire-time copying of an explicit user profile is still synchronous to preserve
   the existing synchronous acquire() snapshot boundary. Large-profile users should
   use a dedicated smaller profile or offload acquisition. New-session profile
   encoding is now off-loop. There is no global browser-session pool or session-count cap.
3. Complete README blocks are syntax-checked; the local smoke script exercises a
   representative workflow, not every public API example. Legacy annotations and
   optional browser operations still need gradual coverage, not blanket certification.
4. Private local caches are the supported assumption. Executable hashes are not vendor
   signatures or whole-browser-bundle integrity checks. Probe stdout is not byte-capped,
   and driver diagnostic capture remains limited; these are follow-up hardening items.
5. A public GitHub Release is created only after the pushed version tag passes the
   complete release workflow. PyPI promotion is separate and requires
   `ASELENIUM_PUBLISH_ENABLED=true`, a configured `pypi` environment, and a matching
   Trusted Publisher; declaring the environment in YAML does not create its approval
   policy or its PyPI authorization.

## Primary references checked for this pass

The proxy payload fixes were checked against the
[WebDriver proxy definition](https://www.w3.org/TR/webdriver2/#proxy).
Metadata migration follows the [PyPA pyproject.toml guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
Least-privilege and immutable action references follow
[GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
[PyPI Trusted Publishing documentation](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
establishes why changing to OIDC requires separately configured publisher identity.
