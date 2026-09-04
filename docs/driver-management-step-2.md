# Driver management: Step 2 packaging and discovery

> Historical audit: this records the implementation at its original checkpoint.
> Subsequent [compatibility removals](legacy-removal.md) supersede its old-feature
> and dependency guidance; historical measurements are not current support promises.

> Historical Step 2 checkpoint. Step 3 is now complete; see
> [the Step 3 handoff](driver-management-step-3.md) for current validation results.

Completed 2026-09-04. This step fixes installed-package Firefox resource loading
and browser/Safari discovery. It builds on the uncommitted Step 1 test foundation;
no commit, push, version bump or publication was performed.

## Result

The suite now contains 303 cases. On both tested interpreters, Python 3.11.15 and
3.13.12 on macOS ARM64, it reports **282 passed and 21 expected failures**. The
original five expected-failure cases for Firefox distribution data and Safari
plist discovery now pass normally. The Safari cases also cover both plist formats.
No new expected-failure exemptions were added.

## Changes made

### Firefox data is included and loaded as a package resource

- `MANIFEST.in` explicitly includes the compatibility JSON in source distributions.
- `setup.cfg` explicitly declares the JSON as data belonging to `aselenium.manager`.
- `FirefoxDriverManager.load_driver_compatibility_table()` uses
  `importlib.resources`, rather than constructing a filesystem path beside
  `driver.py`. A ZIP-backed resource is covered by a test as well as normal files.
- The loader validates a non-empty mapping, required minimum/maximum fields,
  numeric version strings, bound ordering and duplicate normalized Gecko versions.
  These are resource-integrity checks, not a refreshed browser-compatibility policy.
- Missing, unreadable or malformed resources raise `DriverManagerError` naming the
  resource, with the original exception chained. Class state is published only
  after successful validation; a failed load can be retried after repair.

The checked-in compatibility JSON is unchanged. In particular, the historical
Gecko 0.33.0 Firefox bounds remain a tracked Step 5 defect. Successful loading does
not establish that the existing compatibility information is current or correct.

### Safari discovers real metadata and existing driver paths

- `load_plist_file()` opens files in binary mode without an incompatible encoding
  argument. Both XML and binary plists now work.
- Safari reads metadata relative to its own executable's bundle location, avoiding
  confusion when an ancestor directory also contains `Contents/MacOS`.
- `version.plist` remains preferred. `Info.plist` is used only if the first file is
  missing; malformed or inaccessible metadata produces a clear failure instead
  of silently selecting different metadata. Malformed XML `ExpatError` and other
  parsing/IO causes are preserved in `BrowserBinaryNotDetectedError`.
- Explicit Safari driver paths must be existing files whose basename is exactly
  `safaridriver`, rather than merely ending in that string.
- Bundle-search candidates are checked again before return. The existing system
  driver fallback for an explicit browser bundle is retained only when that file
  exists. A nonexistent default no longer appears to be a successful installation.
- Safari's application search paths now work as relative bundle paths under both
  the default applications directory and configured search roots.

No Safari process was started. Driver/browser version compatibility of a chosen
system fallback remains unverified, as before this step.

### Discovery paths and failures are consistent

- Explicit browser and Safari-driver overrides accept strings and string-valued
  `PathLike` objects, expand `~`, validate the file and return absolute strings.
  Literal Unicode, spaces, quotes and filename punctuation are not stripped.
- Absolute conversion deliberately preserves symlinks and `..` components that
  affect filesystem traversal. Tests include a symlink/parent path with a decoy
  file that naïve lexical normalization would incorrectly select.
- Linux lookup uses `shutil.which`, not a shell `which` command. It no longer
  interprets trailing command-output newlines as part of a filename, and does not
  fall back to a non-executable regular file. A real lookup of a synthetic
  executable is tested without running it.
- Missing PATH is safe. Empty roots are ignored, roots are made absolute and
  duplicates removed. Empty PATH components do not imply searching the current
  working directory; an explicit `.` is still a deliberate root.
- Windows retains vendor/channel-specific relative installation paths. PATH may
  supply additional installation roots; it is not a blind basename search that
  could confuse stable Chrome with another channel.
- Channels are validated even when an explicit browser path is supplied.
- Browser probe errors, including Windows PowerShell discovery errors, are mapped
  to the existing browser-location exception with their original causes. Invalid
  browser versions use `InvalidBrowserVersionError`, not the driver-version error.
- An unsupported old Firefox version now produces the intended package diagnostic
  instead of failing while formatting the error message.

Public exports, parameter names/defaults and installation return types are
unchanged. The Python minimum remains 3.10 and runtime requirements are unchanged.

## Compatibility notes

These corrections intentionally tighten previously unreliable behavior:

| Input or situation | Behavior after Step 2 |
| --- | --- |
| Relative explicit executable path | Returned/stored as an absolute string |
| Byte-valued, empty or non-path input | Rejected through the existing package location error |
| Unsupported channel with an explicit binary | Rejected before probing the browser |
| `prefix-safaridriver` or a directory named `safaridriver` | Rejected as an explicit Safari driver |
| Missing PATH or empty entries | Safely omitted; no implicit current-directory search |
| Invalid packaged Firefox resource | Actionable manager error; no partial class cache |

Browser command-output parsing remains tolerant. Strict user-version pin parsing
and version-selection policies are deferred to Step 5; resource validation does
not change those public selectors.

## Verification performed

All commands below run from the repository root using the prepared development
environment. Dependency installation was already completed in Step 1.

```sh
.venv/bin/python -m pytest -q --asyncio-debug
.venv/bin/python -m pytest -q --runxfail --tb=no
.venv/bin/python -m pip check
git diff --check
```

| Check | Observed result |
| --- | --- |
| Full suite with async debug, Python 3.13.12 | 282 passed, 21 xfailed |
| Full suite with async debug, Python 3.11.15 in a separate venv | 282 passed, 21 xfailed |
| Python 3.13 with expected-failure handling disabled | Exactly 21 remaining known failures, 282 passed; exit 1 |
| Dependency consistency, both venvs | Passed |
| Whitespace / patch check | Passed |

No unexpected failures or local skips occurred. The existing Python 3.13 TAR
filter deprecation warnings remain visible. No leaked-task or unawaited-coroutine
warnings were reported. The test matrix is still configured for Ubuntu/Python
3.10–3.14, but remote CI and native Windows/Linux execution were not performed.
Platform-specific unit branches are not a substitute for native OS validation.

Distribution verification now does all of the following in disposable directories:

1. Builds a direct wheel and source distribution with no isolated dependency download.
2. Rebuilds a wheel from that source distribution.
3. Verifies that all three artifacts contain JSON byte-identical to the source file.
4. Actually installs each wheel offline into a separate temporary target using pip
   with `--no-deps --no-index --no-compile --no-cache-dir`.
5. Imports each installed package in a fresh `-S` Python subprocess, excluding the
   source checkout and editable-install hooks, with explicit existing dependency
   directories. It verifies installed-package origins, loads the data, and
   constructs a Firefox manager with an explicit disposable cache.
6. Constructs all five browser facades (Chrome, Chromium, Edge, Firefox and Safari)
   from each installed wheel, with process launches, network access and profile
   creation blocked. Source-checkout tests cover the same construction contract.
   Managers retain unset browser/driver installation fields; non-Safari caches
   are explicit and disposable, and Safari creates no cache.

The main new test modules are `test_resources.py`, `test_discovery_paths.py`, and
`test_safari_discovery.py`; Step 1 distribution/Safari tests were strengthened.
All real browser/version probes remain mocked. The new resource/filesystem checks
do not access personal browser profiles or caches, and no driver/browser downloads
or launches occurred.

## Still deferred

The remaining 21 expected failures are the already tracked filesystem/security,
concurrency, exact-pin and Gecko-range defects. Python 3.10-specific HTTP timeout
cases also remain conditionally tracked but have not been executed locally.

Most importantly, replacing Linux location lookup does **not** fix the existing
shell-interpolated browser-version probe. The unusual-filename tests prove path
and metadata handling under mocked probes, not safe execution of such filenames.
Step 3 will replace shell probing, bound filesystem retries, and secure archive,
executable-selection and deletion paths.

No new performance claim is made. The original Step 1 benchmark JSON remains an
unchanged historical baseline, not a measurement of these new sources. Cache
redesign, download streaming, process coordination, live vendor tests and real
browser smoke tests remain in their scheduled later steps.

**Review checkpoint:** Step 2 is complete. Step 3 has not been started.
