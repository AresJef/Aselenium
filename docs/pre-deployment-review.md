# Pre-deployment review of Aselenium 2.0.0

Review date: **2026-09-05**. This is a follow-up to the
[preceding production review](final-production-review.md), not a claim that every
browser, operating system, or failure sequence is certified. The reviewed source
includes the existing path-first cleanup and retains version 2.0.0. Nothing was
committed, pushed, tagged, or published as part of this review.

## Scope and corrections

The review covered driver provisioning and cache integrity first, followed by
path ownership, service/session cleanup, transport scheduling, browser adapters,
DOM/input/value helpers, imports and types, examples, documentation, and release
configuration. Existing unrelated working-tree changes were preserved.

1. **Action batches have explicit dispatch ownership.** Previously, input added
   while `perform()` awaited the browser could change the in-flight payload and
   then be discarded. Overlapping dispatches could replay the same pending input.
   The batch is now detached before the first await. Later input remains queued
   after success, failure, or cancellation; a consumed batch is not retried.
   `reset()` clears only the batch present when reset begins, preserving input
   added while remote release is pending. This does not promise arbitrary-thread
   safety or protection from application code mutating the exposed action dict.
2. **Transaction admission is bounded.** Multi-command operations could wait
   indefinitely for ownership before reaching the command timeout. Admission now
   respects an enclosing command/wait deadline or the configured session timeout.
   Explicit command timeout overrides retain their meaning. Cancellation releases
   a waiting admission without leaving ownership behind. This bounds admission,
   not the complete user-written transaction body, and does not roll back state.
3. **Vendor mutations and observations stay together.** Chromium permission
   setters and Firefox context setters/resetters now own their update and
   confirming read in one transaction. Safari owns the complete permission
   read/merge/write/read sequence, preventing lost concurrent updates. Application
   operations that depend on these states still need their own transaction.
4. **Invalid delays fail before browser mutation.** Element, alert, and scrolling
   operations and action dispatch validate optional delays before clicks, text,
   uploads, prompt responses, scripts, or action commands are sent. The shared
   validator rejects booleans, negative/non-finite/nonnumeric inputs, and integer
   magnitudes that cannot be represented by the timer. `None` and zero are valid.
5. **Diagnostic output is passive.** Session, element, shadow, and alert reprs use
   the service endpoint already allocated, if any. Inspecting a handle no longer
   asks the service to allocate a port.
6. **Unused state was removed.** Firefox options no longer allocate a dead
   extension list or define a constructor that otherwise only forwarded to the
   base class. Imports and affected public docstrings were reconciled.

The focused [deployment regressions](../tests/test_deployment_review.py) reproduce
the action ownership, unbounded admission, premature browser mutation, passive
diagnostic, and vendor-state cases. The original behavioral cases failed before
their fixes; deadline-override and cancellation controls also guard intended
existing behavior. Existing browser test doubles now expose the transaction
interface used by the real connection.

## Public path and documentation contracts

Public filesystem inputs continue to accept `str`, `Path`, and text-returning
`os.PathLike` objects. Core boundaries normalize and validate once; the internal
workflow keeps `Path` objects. Conversion to text remains at actual protocol,
process, archive-name, database, or serialization boundaries. Archive names use
portable path semantics rather than the host's filesystem rules.

The README now separates stable API instructions from dated validation evidence,
clarifies publication-dependent installation commands, documents the action and
transaction guarantees above, and states Safari's frame no-op behavior directly.
It retains real Google navigation examples and the separate deterministic local
feature tour. A previously observed Google CAPTCHA remains a limitation, not a
claimed successful search. Docstrings retain singular `Example:` sections and
Python `>>>` / `...` prompts.

## Verification of this candidate

The current source was tested on **Python 3.13.12, macOS 26.6.2 ARM64**. Resolved
runtime dependencies are aiohttp 3.14.3, psutil 7.2.2, and orjson 3.12.0. A new
environment outside the checkout contains a non-editable installation of the
newly built wheel, with matching runtime dependency versions.

| Gate | Result |
| --- | --- |
| Full suite with asyncio debugging and branch coverage | **3,263 passed, 1 skipped**, in 123.24 seconds. The skip is Windows drive-relative syntax on macOS; there are no expected failures. |
| New deployment regressions | **36 passing cases**, included in the full suite. |
| Coverage | **92.47% statements** (7,199/7,785), **83.41% branches** (1,835/2,200), **90.48% combined**. Every configured component floor passes. |
| Ruff lint and formatting | Passed across **137 Python files**. |
| Structural documentation/import/type audit | **136 files, 2,425 functions/methods, 294 classes, 196 prompted examples**; no findings. All example-contract checks pass. |
| Mypy | All **78 maintained files** under `src/` and `scripts/` pass. This is the configured gate, not an `Any`-free strict-typing claim. |
| Updated README recipes | **83 tests pass** after the final README changes, including imports, signatures, local links, and controlled execution. |
| Dependency checks | No broken requirements in the source or clean wheel environment. The advisory audit finds no known vulnerabilities; the editable Aselenium entry is intentionally skipped. |
| Distribution | Wheel and sdist build; strict Twine checks pass. All **59 runtime/resource files** in the wheel match the checkout; README metadata, `LICENSE`, and `NOTICE` also match. |
| Installed-wheel typing | Valid public consumer passes; three deliberate misuse controls fail as required, including byte-valued output paths. |

Installed-wheel native acceptance uses temporary profiles and controlled local
pages, not personal browser data:

| Browser | Browser / driver version | Feature tour |
| --- | --- | --- |
| Chrome | 152.0.7977.76 / 152.0.7977.82 | **15/15 stages pass**. |
| Edge | 152.0.4191.62 / 152.0.4191.62 | **15/15 stages pass** after provisioning the missing compatible cached driver. |
| Firefox | 155.0.1 / 0.37.1 | **15/15 stages pass**, including action chains, temporary add-on removal, and full-page capture. |
| Safari | 26.6.2 / 26.6.2 | **12/12 applicable stages pass**, with frames, actions, and concurrency explicitly excluded. PDF is not tested as a supported Safari feature. |

The first offline Edge attempt correctly failed during provisioning because the
selected cache lacked its compatible driver. No browser stage was counted as a
pass in that attempt. Allowing the existing manager to provision the matching
official driver resolved the precondition; the successful tour subsequently
acquired sessions offline. Safari's vendor stage only reads permissions; its new
permission-update race is verified by deterministic protocol tests. Firefox's
privileged `chrome` context is not entered by the native tour.

Chrome's browser HTTP/HTTPS proxy check, six manager authenticated-CONNECT/TLS
cases, and 30-second sustained-session check pass. The sustained run completed
34 iterations and four controlled script timeouts, met the resource-growth
thresholds, and reported no remaining owned tasks/processes. Browser proxy
authentication is not inferred from manager proxy-authentication coverage.

The initial combined reliability invocation is retained as **failed**: its first
browser-crash scenario timed out while acquiring a session, before a session ID
or fault-injection acknowledgement was recorded. It removed the owned profile
and successfully reacquired afterward; the other three recovery scenarios passed.
Other native browser tours were running concurrently. Resource contention is a
possible explanation, not a proven root cause.

The complete recovery gate was then run alone against the **same wheel**, with
the **same five-second command/startup budget** and unchanged assertions. All
four scenarios passed: browser crash, driver crash, browser hang, and driver hang.
They acknowledged the outstanding command before injection, failed with typed
errors within 4.94 seconds after injection, removed their owned profiles, reported
no remaining observed processes/tasks, and reacquired usable fresh sessions. The
independent acceptance validator accepts the retry and the three other original
reliability reports. This is a passing targeted retry, not an uninterrupted pass
of the original combined invocation; both attempts remain in the validation record.

## Candidate artifacts and reproduction

The reviewed distributions are retained locally under
`/private/tmp/aselenium-2.0.0-deployment.4Er0Dq/dist/`:

| Artifact | SHA-256 |
| --- | --- |
| `aselenium-2.0.0-py3-none-any.whl` | `d322d0111f49a101409be2ae6deb82d092fbd52bb46253a517910129c3affcf3` |
| `aselenium-2.0.0.tar.gz` | `5c9e0d0bb685169fea9bf4589b6942f9a8056a6354247eb8e66bde4f24992cd3` |

The wheel is built from the sdist by `python -m build --no-isolation`. The full
suite also independently builds a direct source wheel and an sdist-derived wheel,
compares their contents, and imports them outside the checkout. Documentation
reports are not bundled runtime files. The source remains an uncommitted working
tree; the existing HEAD alone does not identify these reviewed bytes.

Use the [release-acceptance guide](release-acceptance.md) to reproduce native,
typing, and reliability checks. Its commands require an explicit installed-wheel
interpreter and a dedicated compatible driver cache. Reports and temporary wheel
environments can eventually be removed by the operating system; they are local
evidence, not a GitHub release or a package-index publication.

The [machine-readable validation record](baselines/pre-deployment-review-validation.json)
contains artifact/source fingerprints, test totals, all five native-tour attempts
(including the initial Edge miss), and both Chrome recovery outcomes.

## Deployment boundary

Run the hosted Python/OS/minimum-dependency/native matrix on the exact candidate
commit before publishing. The local run does not prove Windows/Linux behavior,
all Python versions, standalone Chromium/CfT bundles, Linux containerized Firefox,
WebView2, casting hardware, beta/dev channels, or GitHub/PyPI account permissions.
Remote publishing configuration is not executed by a local metadata check.

The dependency audit describes known advisories for the resolved environment at
the review date, not a security proof for the package. No bounded local test can
prove unlimited uptime or make browser automation a sandbox for untrusted sites.
