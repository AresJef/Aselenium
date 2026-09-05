# Real-world Google website demo

[`src/demo_google.py`](../src/demo_google.py) demonstrates Aselenium against the
real [Google homepage](https://www.google.com/), using a visible browser by default.
It complements the [local HTML feature tour](demo-local.md); it is not an offline
fixture test or a general-purpose search scraper.

## Quick start

Run from the source checkout with the project's Python environment. On macOS/Linux:

```bash
.venv/bin/python src/demo_google.py
.venv/bin/python src/demo_google.py run --allow-download
```

The first command prints help. The second provisions a compatible Chrome driver
if necessary, starts a fresh headed Chrome session, loads `https://www.google.com/`,
waits for a usable search field, records the title/URL, saves a screenshot, waits
five seconds, and closes the session. It does not automatically search or sign in.

To perform one search:

```bash
.venv/bin/python src/demo_google.py run --query "Aselenium Python" --allow-download --hold-seconds 10
```

Once the driver is cached, omit `--allow-download`. Provisioning then uses the
cache offline; navigation to Google always requires website connectivity.
Search text is sent to Google and included in the report. Do not use sensitive
queries in a demo you intend to share.

To run without a visible window:

```bash
.venv/bin/python src/demo_google.py run --query "Python asyncio" --headless --hold-seconds 0
```

Headless mode is a browser display choice, not a way to avoid website access
controls. Safari is always headed; the CLI rejects `--headless` for Safari.

## What the code demonstrates

The readable website workflow is the `browse_google()` function. Provisioning and
command-line/report handling are separate from that function. It demonstrates:

1. An immutable `manager.install_result()` with compatibility validation.
2. Options set before `acquire()`, followed by offline cached-driver acquisition.
3. Loading a real HTTPS page and reading its URL/title.
4. Bounded waits with zero implicit timeout, supporting Google's textarea/input layouts.
5. Checking that a search field is enabled and not covered before interacting.
6. Optional `clear()` and `send(query, KeyboardKeys.ENTER)` to submit one search.
7. Waiting for a Google `/search` URL carrying the query and visible result headings.
8. Sampling up to five heading texts, without following result links or clicking ads.
9. Atomic PNG screenshot saving and signature verification.
10. Context-managed, cancellation-aware browser cleanup and a structured result report.

The heading samples are illustrative visible page content, not a complete result
list or a guarantee of ranking. Layout variations, no-result pages, and region or
language differences may prevent that particular example from completing.

## Command-line options

| Option | Meaning |
| --- | --- |
| `--browser` | `chrome` (default), `chromium`, `edge`, `firefox`, or `safari`. Availability is not proof of live validation on every backend. |
| `--binary` | Explicit executable path instead of discovery; on macOS, the executable inside the `.app` bundle. |
| `--channel` | Stable by default; beta/dev for Chrome/Edge, dev for Safari Technology Preview. Firefox/Chromium use `--binary` instead. |
| `--query` | One nonempty search query, up to 512 characters. Omit to only visit the homepage. |
| `--headless` | Hide the browser window; unsupported for Safari. |
| `--hold-seconds` | Keep the final/attention page open before cleanup, 0–60 seconds; default 5. |
| `--wait-timeout` | Per-page readiness wait in seconds; default 20. Increase if you need time to review a consent dialog manually. |
| `--timeout` | Total work budget in seconds; default 180. Owned cleanup may finish after the deadline. |
| `--allow-download` | Permit driver vendor requests/downloads during provisioning. Does not toggle Google connectivity. |
| `--cache-dir` | Cache parent, shared with the local tour; defaults to `.demo-cache`. |
| `--profile-root` | Existing shared writable Firefox profile parent; Firefox-only workaround for Snap/Flatpak temporary-filesystem isolation. Requires GeckoDriver 0.32.0 or newer. |
| `--output-dir` | Parent for a unique `google-<browser>-...` output directory; defaults to `.demo-output`. |

For example, select an installed Edge explicitly:

```bash
.venv/bin/python src/demo_google.py run --browser edge \
  --binary "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  --allow-download
```

For a container-packaged Firefox that cannot access GeckoDriver's host temporary
directory, use a non-hidden caller-owned directory under your home:

```bash
mkdir -p "$HOME/aselenium-firefox-profiles"
.venv/bin/python src/demo_google.py run --browser firefox --allow-download \
  --profile-root "$HOME/aselenium-firefox-profiles"
```

On Windows use `.venv\Scripts\python.exe`. If a dependency exists in `.venv` but
the script cannot import it, check the selected interpreter rather than adding a
path workaround to the demo. An editor's Run button may use a different interpreter
from the terminal.

## Consent, challenges, and failures

The demo never chooses consent, signs into an account, loads your personal profile,
rotates proxies, spoofs its user agent, solves CAPTCHA, or repeatedly retries a
blocked search.

If Google displays a consent dialog in a headed run, make your own choice while
the readiness wait is active. You can use `--wait-timeout 60` for more time. No
choice is made automatically. Google traffic/CAPTCHA challenges stop automation
and are reported as `needs-attention`. Headless consent/dialogs also need attention
if the page cannot become ready. The demo does not promise to detect every future
variant of Google's restriction pages; inspect the captured page on an unexpected
timeout or layout change.

The example expects `google.com`/`www.google.com` (and recognizes the consent
origin). A redirect to another origin, including an unhandled regional variant,
is reported for inspection rather than silently interacting with a different site.
This check does not prevent the browser itself from following an HTTP redirect.

Output includes:

- `report.json`: configuration, selected/actual browser and driver versions,
  homepage details, optional query/heading samples, artifacts, status, and timing.
- `google-home.png`: the ready homepage.
- `google-results.png`: the results page when the optional search completes.
- `google-attention.png`: best-effort capture on a site restriction or other
  workflow error, without masking the original error if capture itself fails.

Exit codes are **0** for completion, **2** for a page needing attention, **1** for
other failures, and **130** for keyboard interruption. A successful homepage-only
run does not claim that searching was tested. Captures and reports can contain
query text, page content, network diagnostics (including an IP address on some
challenge pages), and local executable paths; review them before sharing.

The deterministic tests use fake sessions and no Google requests. Live validation
is opt-in, dependent on the current network/browser/site state, and recorded
separately from the original local-demo baseline.

### Recorded validation

The [2026-09-04 validation record](baselines/demo-google-validation.json) separates
offline regression coverage from live website results. On macOS with Python 3.13
and visible Chrome, the homepage-only run passed. One optional search encountered
Google's unusual-traffic CAPTCHA: the demo saved the attention screenshot,
reported `needs-attention` with exit code 2, and closed the browser. The screenshot
was inspected; no bypass or repeated search was attempted. A live normal-results
page has **not** been validated in this environment. The search success path is
covered by deterministic fake-session tests, not claimed as a live Google pass.
