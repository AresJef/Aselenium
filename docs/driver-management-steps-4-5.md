# Driver management: Steps 4 and 5

> Historical audit: this records the implementation at its original checkpoint.
> Subsequent [compatibility removals](legacy-removal.md) supersede its old-feature
> and dependency guidance; historical measurements are not current support promises.

Completed 2026-09-04, following the user's authorization to finish the remaining
sequence. No commit, push, release or dependency change was made.

## Result and current checkpoint

Both local environments—Python 3.11.15 and 3.13.12 on macOS ARM64—report
**562 passed, zero xfails, zero warnings** with asyncio debugging enabled.
The 13 previously tracked failures are now passing tests: seven concurrency/task
ownership cases, four exact-pin cases and two Gecko compatibility bounds.
Another 76 cases were added for installation results and resolution policies.

This is a historical checkpoint. The user subsequently authorized SQLite v2 and
all remaining steps without routine pauses. See
[the Steps 6–14 completion report](modernization-completion.md) for the current
implementation and validation results; the Feather backend described below has
been replaced, with legacy import remaining explicit and copy-only.

## Step 4: isolated requests and owned tasks

### Implementation

- Added frozen `InstallationRequest` and `InstallationResult` records. Their
  version/path/platform/policy values are snapshots rather than mutable Version
  instances shared between calls.
- Existing installation implementation fields now resolve through request-local
  context state. Concurrent calls and their owned child tasks use their own
  invocation, rather than overwriting the manager's pending target fields.
- Existing `install()` signatures and string returns remain. The additive
  `install_result()` method returns an immutable result suitable for concurrent
  consumers. `last_result` and existing location/version properties describe the
  last successful completion; they are not per-consumer synchronization APIs.
- A failed installation no longer clears another call's last successful result.
  `reset()` explicitly clears the published result but does not cancel running
  installations.
- Installation locks are obtained for the current event loop and cache root.
  There is no import-time global asyncio lock. Separate cache roots can progress
  independently. Weak references prevent idle locks from retaining closed loops.
- Chrome-for-Testing owns both download tasks. Failure cancels unfinished siblings
  and drains them before propagating the original error. Repeated cancellation
  does not abandon sibling cleanup. This uses Python 3.10-compatible primitives.
- `SessionContext` uses its returned installation snapshot, including Safari's
  selected channel, rather than rereading shared manager result properties.

### Verified cases

- Concurrent calls for different versions remain isolated across Chrome,
  Chromium, Edge, Firefox and Chrome-for-Testing paths.
- Repeated event loops work, including contended installations.
- Failure and cancellation drain owned downloads.
- Results remain unchanged after later installations or reset.
- In-flight target fields are not exposed to unrelated tasks.
- A delayed acquisition consumes the result belonging to its own request.

Cross-process cache coordination is not implemented by an event-loop lock. It
remains Step 6. Separate options/profile ownership remains Step 11. Downloads and
filesystem work remain synchronous/buffered where they were before; Step 7 is
still required for responsiveness and streaming.

## Step 5: explicit version policies

### Existing API compatibility

- Full numeric Chromium and Gecko pins are preserved on both cold and warm cache
  paths. They are not replaced with a latest-patch response on cache misses.
- Existing `major`, `build`, `patch`, Firefox `latest`/`auto`, and CfT channel
  selectors remain available.
- Numeric user selectors are now strict, unlike tolerant browser/vendor output
  parsing. Decorations, surrounding whitespace, leading-zero aliases, empty
  components and trailing garbage are rejected. Chromium selectors may be a
  major, three-part build or four-part exact version; ambiguous two-part selectors
  are rejected. Gecko pins require three components.
- Explicit `install()` pins retain the existing prewarming contract: a driver
  can be provisioned for a browser other than the locally detected browser.
  This is not a promise that the detected browser can use that driver.
- `install_result(validate_compatibility=True)` validates the resolved pair.
  Session acquisition now requests this check before constructing its service.
  Chromium/Edge builds must match; Firefox uses the complete recorded range.
  Safari's existing bundle-version assumption is not independent verification of
  a separately supplied safaridriver executable.

### Additive policy API

```python
result = await manager.install_result(
    "120.0.6099.71",
    binary="/absolute/path/to/browser",
    policy="offline",
)
print(result.driver_location, result.driver_version)
```

| Policy | Intended behavior |
| --- | --- |
| `exact` | Preserve a full requested driver version, or the detected Chromium patch when applicable |
| `compatible-build` | Prefer a cached matching build, resolving a matching vendor build on miss |
| `compatible-major` | Explicit Chromium major-level selection; not a guarantee of session compatibility |
| `latest-compatible` | Refresh compatible version resolution before selecting a cached/downloaded asset |
| `cached-compatible` | Prefer an existing compatible cached driver, then resolve/download if needed |
| `offline` | Use only an existing matching/compatible cache entry, otherwise raise an actionable miss |

Firefox compatibility is table-based rather than Chromium's numeric build
matching. Existing selectors map to the relevant policy. Omitting the new policy
argument preserves the existing default selector. An explicit policy can override
the selector's normal resolution behavior; do not use a latest-compatible override
when intending to keep an exact pin.

Offline selection is guarded at the request helpers as well as the resolver.
No vendor request is made on an offline miss. CfT partial-version offline selection
can choose an older complete driver/browser pair when the newest driver has no
matching cached browser.

### Vendor contracts and source boundary

- Chrome/CfT exact downloads select the artifact and architecture from a
  per-version JSON manifest. The manifest version must match exactly; asset URLs
  must identify the expected HTTPS Google storage object. Missing architectures
  and malformed/foreign assets fail clearly. Automatic build resolution validates
  the returned build rather than accepting a major-only mismatch.
  Sources: [ChromeDriver version selection](https://developer.chrome.com/docs/chromedriver/downloads/version-selection)
  and [CfT endpoint documentation](https://github.com/GoogleChromeLabs/chrome-for-testing).
- Architecture selection distinguishes Linux ARM64 from Linux x64. An ARM64 CfT
  asset is accepted only when the selected version's manifest actually lists it.
  The current [CfT dashboard](https://googlechromelabs.github.io/chrome-for-testing/)
  showed Linux ARM64 on some channels, not every release. No blanket availability
  claim is made. Native Windows ARM CfT is not silently relabeled as an x64 asset.
- Edge now uses `msedgedriver.microsoft.com`, with the OS-specific latest-release
  lookup shape corroborated by the
  [upstream Selenium Edge resolver](https://github.com/SeleniumHQ/selenium/blob/trunk/rust/src/edge.rs).
  Linux ARM and non-64-bit Linux are rejected rather than selecting a mislabeled
  native artifact. Automatic selection rejects a different build, consistent with
  [Microsoft's first-three-components requirement](https://learn.microsoft.com/en-us/microsoft-edge/webdriver/).
  If the latest-major endpoint no longer supplies the required older build,
  provision an exact matching version rather than silently using another build.
- The packaged Gecko table was refreshed against
  [Mozilla's support table](https://firefox-source-docs.mozilla.org/testing/geckodriver/Support.html)
  on 2026-09-04. Versions 0.34.0–0.37.1 use Firefox 115 as their minimum; 0.33.0
  and 0.32.x cover 102–120; 0.31.0 covers 91–120; 0.30.0 covers 78–90. Existing
  minimum supported Gecko 0.30.0 is retained. A maximum with no published upper
  bound uses the existing sentinel representation; this is not certification of
  every future Firefox version.
- Firefox selection sorts versions explicitly and checks both bounds. An unknown
  future latest Gecko release fails closed until its compatibility information is
  available, instead of inheriting the previous release's range automatically.

The deterministic tests use synthetic vendor-shaped responses based on these
contracts. The web reader could not retrieve the individual CfT fixture manifest
and Edge latest-release URL during this run. Source/documentation checks are not
live endpoint acceptance tests; those remain opt-in work for Step 8.

## Verification and files

```sh
.venv/bin/python -m pytest -q --asyncio-debug --tb=short
/private/tmp/aselenium-py311.wnNkJd/venv/bin/python -m pytest -q --asyncio-debug --tb=short
git diff --check
```

Both full suites passed 562 cases, including direct-wheel and sdist-rebuilt-wheel
offline installation checks. New tests are in `test_installation_results.py` and
`test_resolution_policies.py`. Relevant source changes are `_installation.py`,
`driver.py`, the compatibility JSON, a cache-version enumeration method in
`file.py`, and minimal acquisition integration in the base/Safari webdriver code.

No browsers or drivers were downloaded/launched. Tests used disposable caches,
mocked vendor/browser behavior and the existing scoped Python-child/packaging
checks. Personal profiles and caches were untouched. No new performance claims
are made; the Step 3 measurements are historical snapshots of the prior source.

## Remaining execution order

1. **Step 6, design confirmation pending:** SQLite v2 metadata, process-safe cache
   coordination, leases/pins, non-destructive optional Feather import and removal
   of pandas/pyarrow from mandatory runtime dependencies.
2. **Steps 7–8:** streaming/responsive provisioning, broader cache/cancellation
   validation, opt-in live contracts and driver-management documentation.
3. **Steps 9–14:** non-manager defects, command transport, lifecycle/options/profile
   isolation, waits/DOM semantics, browser-specific features, and candidate QA.

The latest user request authorizes the remaining sequence, so routine per-step
review stops are not required. The explicitly reserved cache-design decision and
any material public-semantics choices still require direction. No release will be
published automatically.
