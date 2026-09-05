# Release acceptance and reliability testing

The latest [pre-deployment review](pre-deployment-review.md) records the current
candidate after additional concurrency and deadline fixes. The preceding
[final production review](final-production-review.md) retains its 3,227-test
snapshot and expanded typing/path/docstring gates. The 2,652-test results below
remain the historical acceptance-expansion snapshot; the reproduction guidance
and stated scope boundaries still apply.

This guide separates deterministic regressions, real local transport tests,
installed-wheel browser acceptance, and environment-specific validation.
Passing a callable-body coverage check is not proof that every browser/OS
combination or failure sequence works.

## Driver management comes first

`tests/manager/test_http_integration.py` uses the real aiohttp client against a
strictly allowlisted ephemeral HTTPS server. It covers certificate rejection,
bounded redirects, downgrade/credential rejection, retry exhaustion, deadlines,
truncated transfers, cancellation, decoded-body limits, corrupt archives, cache
publication, and subsequent offline reuse. Only the fixture certificate is
trusted, through a test-owned client factory. System trust is never modified.

The PEM files in `tests/fixtures/tls` are deliberately public test material, not
production credentials. They remain in the repository checkout for CI and local
development; the production source distribution excludes the test suite.

```bash
python -m pytest tests/manager/test_http_integration.py --asyncio-debug -q
```

The ordinary suite continues to block external requests and installed-browser
launches. Tests marked `loopback` narrowly admit their own exact local endpoints.
They need permission to bind local sockets; deselecting them does not verify them.

## Installed-wheel acceptance

Build a wheel and install it into a **new environment outside the checkout**.
Do not use an editable install for this gate. For example, replace the paths
below with dedicated locations on your machine:

```bash
python -m build --no-isolation
python -m venv /tmp/aselenium-wheel-check
/tmp/aselenium-wheel-check/bin/python -m pip install dist/aselenium-2.0.0-py3-none-any.whl
/tmp/aselenium-wheel-check/bin/python -m pip check
python scripts/check_public_typing.py --python /tmp/aselenium-wheel-check/bin/python
python scripts/test_installed_browser.py \
  --python /tmp/aselenium-wheel-check/bin/python \
  --browser firefox \
  --cache-dir /tmp/aselenium-acceptance-cache \
  --output-dir /tmp/aselenium-acceptance-reports \
  --allow-download
```

The outer interpreter needs development tools; the inner environment contains
the installed wheel and its declared runtime dependencies. On Windows, use the
environment's `Scripts/python.exe` path. Browser executables are discovered from
known installed locations; `--binary` supplies an explicit executable override.

The harness copies only the demo and local assets into a disposable directory,
checks the imported package's origin in the actual tour process, then runs all
feature chapters. Missing stages, duplicates, failures and unexpected skips fail
acceptance. Browser and driver versions are retained in `installed-acceptance.json`.
The current Safari facade has three exact exclusions: frames, action chains and
concurrent sessions. Those are recorded as skips, never counted as passes.

Safari must already have Remote Automation enabled. The local harness does not
enable it, change permissions, or use a personal profile. Firefox uses a fresh
profile and installs/removes only the bundled temporary demonstration add-on.
On Linux Firefox, the harness creates a disposable non-hidden profile root under
the current user's home and places its copied upload fixtures beneath that same
root. This follows GeckoDriver's container-package guidance while continuing to
test the manager-downloaded host GeckoDriver. The owned root is removed after the
tour; no permanent profile or personal Firefox data is used.

## Crash, hang and resource checks

After provisioning the dedicated cache, Chrome/Edge reliability can run as one
gate. It does not perform downloads:

```bash
python scripts/run_reliability.py \
  --python /tmp/aselenium-wheel-check/bin/python \
  --browser chrome \
  --cache-dir /tmp/aselenium-acceptance-cache \
  --output-dir /tmp/aselenium-acceptance-reports/reliability \
  --duration 120
```

This runs:

1. **Four crash/hang cases.** A per-run loopback acknowledgement establishes that
   a real asynchronous WebDriver command is outstanding before an owned driver
   or browser is killed/suspended. PID/create-time identities and fresh-profile
   ownership protect unrelated processes. Acceptance requires a bounded typed
   failure, clean library teardown and successful fresh acquisition. Emergency
   fixture cleanup is reported as a failure, not credited as library cleanup.
   Setup and fresh-session commands use a 30-second transport budget; the held
   command under fault retains its independent 5-second deadline. Each scenario
   is bounded by 120 seconds, and the four-case runner by 540 seconds including
   process/report cleanup. Slow setup does not relax the fault-response limit.
2. **HTTP and HTTPS CONNECT browser routing.** Only the exact local origin is
   permitted. The HTTPS browser fixture explicitly enables insecure certificates
   for this disposable test; it does not establish browser certificate validation.
3. **Authenticated CONNECT through the manager HTTP client.** Actual TLS trust
   and hostname checking remain enabled. Missing/wrong credentials, disallowed
   destinations and direct bypass are rejected. This does not claim that browser
   HTTP proxy credentials can be supplied through the `Proxy` capability.
4. **A long-lived mixed session.** One session repeatedly exercises input,
   actions, cached/asynchronous scripts, DOM updates, temporary windows and
   timeout recovery. Resource growth is compared with an explicit post-warm-up
   baseline; process/task/profile cleanup is checked after the session ends.

Individual harnesses remain available:

```bash
python scripts/test_browser_recovery.py --help
python scripts/test_browser_proxy.py --help
python scripts/soak_browser.py --help
```

Soak mode `fresh` retains the existing repeated-acquisition test. Mode
`long-lived` accepts durations from 1 to 3,600 seconds and configurable memory,
handle and process-growth limits. These are bounded observations, not a promise
of unlimited uptime or proof that no memory leak exists.

## Documentation and typing

Prompted examples use singular `Example:` with `>>>` and continuation `...`
prompts. Structural checks compile every example and check resolvable API names.
`tests/test_docstring_runtime.py` executes selected actual docstrings with
explicit fixtures, preserving statement order and checking behavior. It does
not execute arbitrary examples against personal data or uncontrolled websites.

`scripts/check_public_typing.py` checks consumer programs against the installed
typed wheel. It also requires invalid navigation argument types and dereferencing
an optional element without checking it to be rejected. This complements the
configured mypy gate, which checks all maintained Python under `src/` and
`scripts/`.

## CI and release gates

The reusable `.github/workflows/tests.yml` defines:

- One canonical wheel/source-distribution build. Native installed-package jobs
  download that immutable workflow artifact instead of rebuilding it; the tag
  workflow promotes the same files.
- The existing Python 3.10–3.14 Linux suite and additional Windows/macOS jobs.
- A Python 3.11 exact-minimum runtime dependency job, with constraints checked
  against `pyproject.toml` to prevent drift.
- Separate statement and branch floors for the canonical Linux run, including
  the driver transport/cache, acquisition, connection and process-service code.
  Missing coverage data fails the gate.
- Installed-wheel native jobs for Linux Chrome/Firefox, Windows Edge, and macOS
  Chrome/Firefox/Safari. Required stages cannot silently skip.
- Chrome/Edge crash, proxy and 30-second sustained-session gates on ordinary
  runs; scheduled and release-tag runs use a 600-second sustained workload.
- Retained native reports and diagnostic artifacts. External actions remain
  pinned to full commits, and jobs do not use `continue-on-error`.

The selected hosted images document their preinstalled browsers:
[Ubuntu 24.04](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md),
[Windows 2025](https://github.com/actions/runner-images/blob/main/images/windows/Windows2025-Readme.md),
and [macOS 15](https://github.com/actions/runner-images/blob/main/images/macos/macos-15-arm64-Readme.md).
Versions are discovered and recorded at runtime; the configuration does not pin
an indefinitely compatible browser/driver pair. Only the disposable hosted
Safari runner enables its system automation service automatically.

The release workflow starts only from a pushed `v*` tag. It validates the tag
against `pyproject.toml`, calls the reusable suite, and creates the public GitHub
Release only after those gates succeed. The Release attaches the exact native-
tested wheel and source distribution plus SHA-256 checksums and the curated
version notes.

`ASELENIUM_PUBLISH_ENABLED=true` opts into a PyPI promotion of those same files
using Trusted Publishing. If the variable is absent or false, the PyPI job is
skipped and the validated GitHub Release is still published. If PyPI promotion
is enabled but fails, the GitHub Release is blocked so the two public channels
cannot silently diverge. Configure the PyPI project, `pypi` environment and OIDC
publisher before enabling the variable.

Editing or locally validating these definitions does **not** establish a remote
CI pass, publish a release, or activate the schedule before the workflow reaches
the repository's default branch.

## Evidence and remaining boundaries

### Preceding 2.0.0 follow-up on 2026-09-05

The preceding unrestricted Python 3.13.12 run passed **3,227 tests**, with only the
Windows-specific drive-relative syntax case skipped on macOS. Statement and
branch coverage are **92.41%** and **83.45%**, respectively, and all configured
component floors pass. Ruff checks 136 formatted files; mypy checks all 78
maintained source/demo/script files; the structural audit covers 135 files,
2,407 functions/methods, 294 classes and 196 prompted examples. The 2.0.0 wheel
and source archive pass strict metadata/integrity checks, and the refreshed
resolved-environment advisory audit reports no known vulnerabilities.

That exact wheel also passes fresh installed-package local-fixture tours on
macOS Chrome (15/15 stages), Firefox (15/15), and Safari (12/12 applicable, with
the three documented facade exclusions). Its isolated public-typing consumer and
all three deliberate negative controls pass.

The hosted Python/OS/native-browser matrix must still run on the final tagged
commit. The earlier Python 3.11/minimum-dependency, Edge, and Chrome/Edge
reliability evidence below is retained as a dated baseline and must not be read
as a fresh execution of the final 2.0.0 bytes.

The subsequent [pre-deployment review](pre-deployment-review.md) supersedes this
snapshot for current source and distribution evidence.

### Earlier multi-environment and native verification on 2026-09-05

The final regression suite passed **2,652 tests in each environment**, with no
failures, errors, expected failures or skipped tests:

- Python 3.13.12 with the current resolved dependencies.
- Python 3.11.15 with the current resolved dependencies.
- Python 3.11.15 with exact runtime minima: aiohttp 3.14.3, psutil 5.8.0,
  and orjson 3.11.6.

All runs included asyncio debugging, isolated loopback transport and owned-process
regressions. The Python 3.13 run measured **92.03% statement coverage** and
**81.91% branch coverage** across `aselenium`; all configured critical-component
floors passed. These percentages are separate measures, not full path coverage.

Fresh installed-wheel tours on macOS 26.6.2 ARM64 produced:

| Browser | Browser / driver version | Passed stages | Explicit skips |
| --- | --- | ---: | ---: |
| Chrome | 152.0.7977.76 / 152.0.7977.82 | 15 | 0 |
| Edge | 152.0.4191.62 / 152.0.4191.62 | 15 | 0 |
| Firefox | 155.0.1 / 0.37.1 | 15 | 0 |
| Safari | 26.6.2 / 26.6.2 | 12 | 3 |

Safari's three exclusions are listed in the installed-wheel section above; its
artifact chapter checks PNG output, not its disabled PDF-printing facade.
All four tours were rerun after the final timeout-exception fix. The imported
installed package's 56 Python/resource files matched the checkout byte-for-byte.

Both Chrome and Edge passed the combined reliability gate: all four crash/hang
scenarios, HTTP/HTTPS browser proxy routing, and all six manager CONNECT
authentication/routing cases. No fault scenario required emergency harness
cleanup. Each also completed a sustained session of at least 120 seconds:

| Browser | Mixed-workload iterations | Controlled native script timeouts recovered |
| --- | ---: | ---: |
| Chrome | 251 | 26 |
| Edge | 250 | 25 |

Observed resource growth stayed within the explicit limits. Both sessions ended
with no observed owned processes or tasks remaining and their temporary profiles
removed. This is bounded stability evidence, not a claim of zero memory growth.

Additional checks passed: 38 verbatim docstring examples, structural validation
of 181 prompted example sections, lint, formatting, the 19-module mypy gate,
installed-wheel consumer typing with two negative controls, dependency consistency,
and wheel/source-distribution metadata validation. Public callable-body execution
is still distinct from native verification of each browser-specific operation.

### Defects found by the new acceptance checks

- **Safari acquisition:** driver discovery succeeded, but session creation tried
  to reconstruct the immutable result through unimplemented Safari version
  parsers. Both browser/driver parsers are now present, with 19 regression cases
  covering valid/invalid values and the real discovery-to-session handoff.
- **Abrupt driver death:** teardown originally discovered browser descendants
  only after the driver exited, too late to recover its former process tree.
  The service now retains original process identities after the session handshake
  and refreshes descendants from surviving owned roots during teardown. Ordinary
  browser commands incur no recurring process-tree scan. Eighteen new regressions
  cover ancestry loss, late descendants, PID reuse, failed cleanup and cancellation.
- **Native timeout identity:** the outer command deadline handler also caught
  the package's browser-reported timeout exceptions, since they inherit from
  Python's timeout type. A real script timeout was consequently relabelled as a
  transport timeout. The command wrapper now preserves package exceptions before
  translating actual deadline expiry; the sustained test requires the specific
  JavaScript timeout and then continues using the same session.
- **Three docstring defects:** the session-timeout example awaited a synchronous
  options property, and two JavaScript examples attempted to cache the same name
  twice. Verbatim runtime tests caught these; the examples now use the correct
  session property and retrieve the previously cached scripts.

The acceptance harnesses also reject malformed/incomplete reports, isolate each
run's outputs, and guard cleanup of their own observed subprocess trees if an
outer deadline expires. Harness safety cleanup cannot turn a failed library
cleanup into a passing result. Process tracking is not a sandbox against hostile
executables or processes that escape observation entirely between samples.

The dated validation record for this work is
[`baselines/release-acceptance-validation.json`](baselines/release-acceptance-validation.json).
It distinguishes current passes from intentionally failing pre-fix controls and
from checks that have only been configured for another environment.

Native Windows/Linux execution, alternate channels, standalone Chromium/CfT,
WebView2, physical casting devices, SOCKS/PAC/WPAD deployment behavior, and
unattended multi-hour/day operation need their own acceptance evidence. A Google
CAPTCHA or another uncontrolled website is not a deterministic release test.
The new crash/hang and sustained fault harnesses target Chrome/Edge; Firefox and
Safari have live feature-tour coverage, not equivalent fault-injection coverage.
