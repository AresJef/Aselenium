# Local HTML demo

For the real-world Google demo, see [the Google guide](demo-google.md). For a comparison,
see [the demo overview](demo.md).

The runnable entry point is [`src/demo_local.py`](../src/demo_local.py). It is a feature tour
of the current source tree, not a benchmark or a substitute for the regression
suite. Driver management is always the first step.

The old demo's public websites, historical download matrix, personal profile
paths, assumed proxy, and global cancellation switch have been removed. The new
tour uses a small local website and explicit, independently selectable chapters.

## Start here

Use Python 3.10+ in your project virtual environment. From the repository root:

```bash
python -m pip install -e .
python src/demo_local.py
python src/demo_local.py list
```

The first demo command prints help; the second lists chapters. Neither creates a
cache, opens a listening socket, probes a browser, or downloads anything.

Install/provision a compatible driver explicitly, then run without vendor access:

```bash
python src/demo_local.py install --browser chrome --allow-download
python src/demo_local.py run --browser chrome
```

Or opt into provisioning and run the tour in one command:

```bash
python src/demo_local.py run --browser chrome --allow-download
```

Chrome, Chromium, Edge, and Firefox must already be installed. Chrome for Testing
is the separate exception described below. Use `--binary` if automatic detection
does not find the desired executable. On macOS this is the executable **inside**
the app bundle, not the `.app` directory:

```bash
python src/demo_local.py run --browser chrome \
  --binary "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

The browser runs headless by default, except Safari. Add `--headed` to watch the
tour. No real account, personal profile, or configured proxy is needed.

## Driver management and cache policies

`install` only provisions/probes executables; it does not start a browser session.
It prints the immutable result from `manager.install_result()`, including the
request, selected versions, executable paths, and channel. The demo validates the
driver/browser pair rather than reporting success for an incompatible pin.

Both commands default to an explicit **offline** resolution policy. An empty or
incompatible cache fails with an actionable error. There is no silent network
fallback. `--allow-download` permits vendor metadata and archive requests during
provisioning; all subsequent `run` acquisitions use the `"offline"` selector.

| Policy | Demo behavior |
| --- | --- |
| `offline` | Resolve from the cache only; fail if no matching usable artifact exists. |
| `cached-compatible` | Prefer a compatible cached driver; provision on a miss. Requires download opt-in. |
| `compatible-build` | Resolve a Chromium-family driver for the browser's build. Default online policy for Chrome/Chromium/Edge. |
| `compatible-major` | Request Chromium major-version matching; the demo still validates the resulting pair. |
| `latest-compatible` | Refresh vendor resolution for the latest compatible candidate. Requires download opt-in. |
| `exact` | Install a complete numeric driver version and protect the exact artifact from eviction. Requires a version and download opt-in. |

With `--allow-download`, Firefox defaults to `cached-compatible`. It supports
`exact`, `latest-compatible`, `cached-compatible`, and `offline`, not Chromium's
build/major policy examples. Safari uses the system driver and has no download
cache, numeric driver selector, or pin commands.

Examples:

```bash
python src/demo_local.py install --browser edge --allow-download --policy cached-compatible
python src/demo_local.py install --browser firefox --allow-download --policy latest-compatible
python src/demo_local.py install --browser chrome --policy offline
```

Exact Chromium-family versions require four numeric components; Gecko versions
require three. Substitute a full version compatible with your installed browser
for `FULL_VERSION` in these command templates:

```text
python src/demo_local.py install --browser chrome --version FULL_VERSION --allow-download
python src/demo_local.py install --browser chrome --version FULL_VERSION --policy offline --pin
python src/demo_local.py install --browser chrome --version FULL_VERSION --policy offline --unpin
```

An explicit version defaults to `exact` when downloads are allowed, and to
`offline` otherwise. An offline full version is an exact cache lookup, not a
request for a newer candidate. `--pin`/`--unpin` affect only the resolved **driver**
in the selected cache. Exact Chrome for Testing provisioning also pins its
browser; the CLI does not unpin browser artifacts.

`run` intentionally chooses a compatible cached pair rather than promising a
specific numeric pin. It has no `--version` flag. Consult the result and run report
for the actual versions; use the package API when your application requires a
different version-selection workflow.

### Chrome for Testing

CfT provisioning requires a complete numeric version and may download both a
driver and a browser:

```text
python src/demo_local.py install --browser chrome --channel cft --version FULL_VERSION --allow-download
```

To run the provisioned CfT browser offline, pass the returned `browser_location`
as `--binary` with the normal stable-channel facade, using the same cache:

```text
python src/demo_local.py run --browser chrome --binary "BROWSER_LOCATION_FROM_INSTALL_RESULT"
```

The CLI rejects `run --channel cft`: the package's CfT acquisition route requires
a numeric selector, and that route cannot accept the demo's `"offline"` selector.
This avoids advertising a nonfunctional or secretly online launch path.

### Cache location

The default cache parent is `.demo-cache` under the source tree. Aselenium creates
its `.aselenium` cache beneath that directory. It is separate from `~/.aselenium`.
Pass the same `--cache-dir` to installation and subsequent runs. Missing parent
directories are created on demand. Cache artifacts persist for offline reuse;
the demo never clears a cache or migrates an old one automatically.

```bash
python src/demo_local.py install --browser chrome --cache-dir /tmp/aselenium-demo-cache --allow-download
python src/demo_local.py run --browser chrome --cache-dir /tmp/aselenium-demo-cache
```

Offline provisioning is **not an operating-system network sandbox**. The demo
visits only loopback pages and loads no external page assets. Chromium background
network flags reduce unrelated traffic, but browser-internal background requests
are not guaranteed to be blocked. Use your own network controls if you need that
stronger guarantee.

## Select chapters

```bash
python src/demo_local.py run --sections navigation elements waits
python src/demo_local.py run --sections scripts actions artifacts
python src/demo_local.py run --sections concurrency cancellation --profile-demo
python src/demo_local.py run --sections all --profile-demo
```

Driver management and options setup always run first. Selected chapters run in
the listed order below, regardless of argument order. Each ordinary chapter
loads a fresh fixture page, so it does not depend on a previous chapter's DOM
changes. The concurrency and cancellation chapters create their own sessions
after the ordinary session has closed.

| Chapter | Features demonstrated |
| --- | --- |
| Driver management (automatic) | Immutable installation result, compatibility validation, opt-in downloads, offline acquisition. |
| Options (automatic) | Finite timeouts, zero implicit wait, defensive capabilities, browser arguments/preferences, proxy serialization without enabling a proxy. |
| `navigation` | Load, back, forward, refresh, URL/title waits, page dimensions/source, runtime timeout changes and reset. |
| `elements` | Single/multiple/fallback lookup, input/clear, checkbox selection, local file input, awaited form submission, DOM text, viewport/occlusion checks, scrolling, open shadow-root lookup. |
| `waits` | Bounded explicit polling, falsey immediate misses, and stateful sequences inside `session.transaction()`. |
| `cookies` | Create/read/delete a cookie on the loopback origin; values use `cookie["value"]`. |
| `windows` | Named tab creation, independent navigation, close, and deterministic focus restoration. |
| `frames` | Selector-based frame entry with a `finally` block restoring the top-level document. |
| `alerts` | Delayed local prompt, text inspection, input, and acceptance. |
| `scripts` | Cached JavaScript, `Element` arguments, asynchronous callbacks, cache removal, preservation of application data with an `error` field. |
| `actions` | Pointer movement/click, keyboard input, reuse without replay, remote input-state reset. |
| `artifacts` | PNG screenshot, PDF print where enabled, signature validation; Firefox full-page screenshot. |
| `vendor` | Chromium CDP, geolocation permission restore, network-emulation reset, log counts; Firefox content context and a temporary local add-on; Safari read-only permission inspection. |
| `concurrency` | Two owned sessions, acquisition-time option snapshots, independent cookies, and separate physical profile clones when requested. |
| `cancellation` | Wait until work is ready, cancel and await it, complete teardown, then acquire a new session from the same facade. |

The demo uses representative calls, not every overload of every method. Important
current API details include `Element.send()` (not `send_keys()`), `element.shadow`
(not `shadow_root`), `session.page_source`, and `save_screenshot()`. Visibility and
occlusion checks are observations, not a guarantee that a later click will succeed.

### Profile and lifecycle ownership

`--profile-demo` creates an empty temporary source profile, clones it into the
facade's options, and lets each acquisition create its own physical snapshot.
It never reads the user's real browser profile. Both session-owned resources and
the facade's template are explicitly closed; the empty source directory is then
removed. Without the flag, sessions use fresh browser profiles.

`--profile-root PATH` is a separate Firefox-only service option. It selects the
existing parent in which GeckoDriver creates those temporary profiles; it does
not select or reuse a personal browser profile. Ubuntu's Snap-packaged Firefox
and some Flatpak/container installations may need a non-hidden directory under
the user's home because Firefox cannot see GeckoDriver's ordinary host `/tmp`:

```bash
mkdir -p "$HOME/aselenium-firefox-profiles"
python src/demo_local.py run --browser firefox --allow-download \
  --profile-root "$HOME/aselenium-firefox-profiles" --profile-demo
```

The directory must already exist, be readable/writable by both processes, and
be used with GeckoDriver 0.32.0 or newer. The demo and package do not delete
this caller-owned parent. See Mozilla's
[container-package guidance](https://firefox-source-docs.mozilla.org/testing/geckodriver/Usage.html#running-firefox-in-a-container-based-package).

The concurrency example changes the facade's timeout **after** creating each
context, verifies that captured values remain unchanged, and checks independent
cookies after both workers have written. It owns and drains all worker tasks,
including failure and cancellation paths, without requiring Python 3.11's
`TaskGroup`.

The cancellation example intentionally waits inside an owned task, cancels that
task, awaits it, and calls idempotent `quit()`. It creates a **new** context for the
next session: a closed context is not restarted. The `--timeout` budget defaults
to 240 seconds; it bounds work, but cancellation-safe cleanup may take additional
time. `--session-timeout` separately controls each WebDriver command and session
startup; it defaults to 30 seconds. Increase it for a cold or containerized browser
when startup legitimately needs longer. Ctrl+C also initiates cleanup; forcibly
killing the process bypasses it.

## Browser-specific boundaries

All five facades have CLI routes. This does not imply identical feature support
or that every route has been validated on this machine.

| Browser | Notes |
| --- | --- |
| Chrome / Edge | Full headless tour, including CDP and browser-specific commands. Stable/beta/dev executable selection is supported. |
| Chromium | Same family of features; choose a compatible installed executable with `--binary`. No release-channel flag beyond stable. |
| Firefox | Uses Gecko selectors, `-headless`, full-page capture, and a bundled temporary add-on scoped to loopback pages. `--profile-root` supports Snap/Flatpak shared-filesystem startup. It does not enter the privileged `chrome` context. |
| Safari | macOS only, always headed. Remote Automation must already be enabled by the user. The current facade disables frame switching, action chains, and PDF printing; those examples are skipped. The concurrency chapter is skipped because Safari's automation service is single-session. |

Chromium PDF printing is skipped with `--headed` in this demo. Media/casting
devices are never discovered or activated automatically. The package's
`cast_sinks`, `set_cast_sink`, `start_casting`, and `stop_casting` APIs require
deliberate selection of a real device and are outside the automated local tour.
Real proxy connectivity, personal-profile migration, and Safari automation
settings are not exercised. Feather-cache import is no longer supported.

## Reports, failures, and validation

Each `run` creates a new directory under `.demo-output` (or `--output-dir`), with:

- `report.json`: request/actual versions, runtime/platform, chapter timings,
  pass/skip/fail/cancel/not-run statuses, counts, and feature-specific results.
- `page.png` and, when supported, `page.pdf` from the artifacts chapter.
- `full-page.png` when Firefox's full-page screenshot example runs.

The report does not dump cookies, proxy credentials, page source, script bodies,
or complete browser logs. It does include local executable paths and environment
information; review these before sharing. The run stops at the first unexpected
failure, saves its report, marks remaining selected chapters `not-run`, and exits
with code 1. Success is code 0; keyboard interruption is code 130. Documented
unsupported features are explicitly skipped, never counted as passed checks.

Useful checks from an environment with the development dependencies installed:

```bash
python -m pytest tests/test_demo_local.py -q
python -m pytest -q
python -m ruff check src tests scripts
```

The offline tests validate CLI defaults, browser argument dispatch, policy/pin
handling, defensive configuration, cloned profiles, fixture path restrictions,
report outcomes, and owned-task cleanup. Distribution tests verify the demo and
assets survive source-distribution packaging without becoming runtime packages
in the wheel. The demo is supplied with the source checkout/sdist; installing
only the wheel does not install a `demo` command or fixture files.

Live validation results for this rewrite are recorded in
[`baselines/demo-validation.json`](baselines/demo-validation.json). They are dated
observations of the tested browser/Python/platform combinations, not a promise
about untested browsers, future versions, or other operating systems. For the
package-wide behavior and recovery boundaries, see the
[modernization guide](modernization-guide.md).
