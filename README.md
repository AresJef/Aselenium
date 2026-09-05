# Aselenium

**Asynchronous browser automation for Python, with integrated WebDriver management.**

Aselenium provides an `asyncio`-native interface to Chrome, Chromium, Microsoft
Edge, Firefox, and Safari. Provision a compatible driver, configure a browser,
and use an asynchronous session to navigate pages, interact with elements, run
JavaScript, and capture results. Separate sessions can run concurrently where
the browser backend permits it; Safari's current automation service is
single-session.

> **Version 2.0.0:** this README describes the current package. The 2.0 release
> removes legacy compatibility APIs and completes the driver-management and
> session-lifecycle modernization. Existing 1.x users should review the
> [breaking-change guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/legacy-removal.md) before upgrading.

Version 2.0 no longer includes legacy compatibility paths. Chrome/Chromium
provisioning requires version 115+, Firefox add-ons require WebExtension manifests,
and browser commands use W3C WebDriver responses.

To try the package, follow [installation](#installation), then choose the
[local HTML feature tour](#local-html-feature-tour) or the
[real-world Google demo](#real-world-google-demo). Both use real browsers:
the local tour is headless by default, while the Google demo opens a visible
window. Neither uses your personal browser profile.

## Contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
  - [Minimal local HTML example](#minimal-local-html-example)
  - [Recommended: Google homepage](#recommended-google-homepage)
- [Usage guide](#usage-guide)
  - [Driver management](#driver-management)
  - [Choosing a browser](#choosing-a-browser)
  - [Options and proxies](#options-and-proxies)
  - [Profiles and configuration isolation](#profiles-and-configuration-isolation)
  - [Session lifecycle](#session-lifecycle)
  - [Timeouts and explicit waits](#timeouts-and-explicit-waits)
  - [Navigation and page information](#navigation-and-page-information)
  - [Finding and interacting with elements](#finding-and-interacting-with-elements)
  - [DOM properties and visibility](#dom-properties-and-visibility)
  - [Windows and tabs](#windows-and-tabs)
  - [Frames and shadow DOM](#frames-and-shadow-dom)
  - [Alerts and prompts](#alerts-and-prompts)
  - [Cookies](#cookies)
  - [JavaScript](#javascript)
  - [Keyboard and pointer actions](#keyboard-and-pointer-actions)
  - [Scrolling](#scrolling)
  - [Screenshots and PDF output](#screenshots-and-pdf-output)
  - [Concurrent sessions and cancellation](#concurrent-sessions-and-cancellation)
  - [Browser-specific features](#browser-specific-features)
  - [Errors and logging](#errors-and-logging)
- [Runnable demo](#runnable-demo)
  - [Local HTML feature tour](#local-html-feature-tour)
  - [Real-world Google demo](#real-world-google-demo)
  - [Demo outputs and network behavior](#demo-outputs-and-network-behavior)
- [Troubleshooting](#troubleshooting)
- [Cache recovery](#cache-recovery)
- [Compatibility and verification](#compatibility-and-verification)
- [Development](#development)
- [Further documentation](#further-documentation)
- [License and acknowledgements](#license-and-acknowledgements)

## Features

- **Async browser sessions:** await browser operations without wrapping a
  synchronous Selenium client in application-managed threads.
- **Integrated driver provisioning:** browser discovery, release-channel selection,
  exact versions, compatible versions, offline reuse, and Chrome for Testing.
- **Persistent local cache:** SQLite-backed, platform-specific artifacts with
  executable integrity checks, atomic publication, persistent pins, and leases
  protecting active acquisitions from eviction.
- **Isolated configuration:** options are captured when a context is acquired;
  configured profiles are physically cloned for each acquisition.
- **Stateful automation:** elements, forms, cookies, windows, frames, shadow DOM,
  alerts, JavaScript, keyboard/pointer actions, screenshots, and PDF printing.
- **Bounded waits and owned cleanup:** shared wait deadlines, serialized commands,
  session transactions, and cancellation-aware teardown.
- **Browser-specific tools:** Chromium CDP, network emulation, permissions, logs,
  and casting; Firefox add-ons, contexts, and full-page screenshots; Safari's
  supported automation and permission commands.

Browser-specific features are not interchangeable. See the
[support boundaries](#compatibility-and-verification) before choosing a backend.

## Installation

Requires **Python 3.10 or newer**. Runtime dependencies are `aiohttp>=3.14.3`,
`psutil>=5.8.0`, and `orjson>=3.11.6`. No optional Feather-cache reader or
pandas/pyarrow dependency remains.
The usual browser must be installed separately, except when provisioning a
Chrome for Testing browser/driver pair. Safari requires macOS and an existing
Remote Automation setup.

Install version 2.0.0 from PyPI:

```bash
python -m pip install --upgrade aselenium==2.0.0
```

The [GitHub Release](https://github.com/AresJef/Aselenium/releases/tag/v2.0.0)
also provides the same wheel and source distribution with SHA-256 checksums.
To install its wheel directly:

```bash
python -m pip install --upgrade https://github.com/AresJef/Aselenium/releases/download/v2.0.0/aselenium-2.0.0-py3-none-any.whl
```

To develop from a source checkout, run the following from the repository root.
If you already have a `.venv`, reuse it and **skip the environment-creation
command**; you do not need to recreate it to update an editable installation.

On macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

On Windows, in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Check the interpreter and imports before launching a browser (macOS/Linux):

```bash
.venv/bin/python -c "import sys, aselenium, orjson; print(sys.executable); print(aselenium.__file__); print(orjson.__file__)"
```

An editable install should resolve `aselenium` to this checkout's
`src/aselenium` directory. Activation is optional when using the environment's
Python executable explicitly. In an editor, select that same executable for
Run/Debug; activating a terminal does not necessarily change the editor's choice.
See [dependency troubleshooting](#dependency-import-errors) if an import fails.

`python -m pip install aselenium` without a version pin installs the newest
distribution currently published. It does not obtain uncommitted changes from a
working tree. Installing from GitHub likewise only obtains code that has actually
been pushed. Confirm what the selected interpreter installed with:

```bash
.venv/bin/python -c "from importlib.metadata import version; print(version('aselenium'))"
```

## Quick start

For ready-made command-line examples with reports and screenshots, go directly
to the [runnable demos](#runnable-demo). The two examples below are small launch
scripts you can adapt for your own application. The Google example is the
recommended real-world introduction; the local HTML example is the deterministic
choice for learning element operations without consent pages, CAPTCHA, layout
changes, or an Internet dependency.

### Minimal local HTML example

Save this complete example as `quickstart.py` and run it in the environment where
you installed the checkout. It uses an installed Chrome and a local `data:` page.
It is **headless**, so no browser window is shown. Remove the `--headless=new`
argument to make the browser visible.
**The provisioning call may contact driver vendors and download a driver.**
Browser acquisition afterward explicitly uses the cache offline.

```python
import asyncio
from pathlib import Path
from urllib.parse import quote

from aselenium import Chrome


async def main():
    cache = Path("./browser-cache")
    cache.mkdir(parents=True, exist_ok=True)
    driver = Chrome(directory=cache)
    driver.options.add_arguments("--headless=new")
    driver.options.set_timeouts(implicit=0, pageLoad=20, script=5)
    driver.options.session_timeout = 30

    try:
        result = await driver.manager.install_result(
            version="build",
            policy="compatible-build",
            validate_compatibility=True,
        )
        print("Driver:", result.driver_version)
        print("Browser:", result.browser_version)

        async with driver.acquire(version="offline") as session:
            html = "<title>Aselenium</title><input id='name' aria-label='Name'>"
            await session.load("data:text/html;charset=utf-8," + quote(html))
            field = await session.wait_for(
                lambda: session.find_element("#name"), timeout=5
            )
            if field is None:
                raise RuntimeError("The input did not appear")
            await field.send("Hello from Aselenium")
            print(await session.title)
            print(await field.get_property("value"))
    finally:
        driver.options.close()


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
.venv/bin/python quickstart.py
```

On later runs, change the installation policy to `"offline"` if vendor requests
must be prohibited. The cache must contain a driver compatible with the current
browser; a browser update may require reprovisioning. Offline provisioning is
not a network sandbox for the browser itself.

In a notebook or another running event loop, use `await main()` instead of
nesting `asyncio.run()`.

### Recommended: Google homepage

Save this as `google_quickstart.py`. It uses the same lifecycle but opens the
real Google website in a **visible Chrome window**, prints the page URL/title,
and keeps the window open for five seconds before cleanup. It does not submit
a search, choose consent, or sign in. A minimal runnable copy is included as
[`src/quick_start.py`](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/quick_start.py).

```python
import asyncio
from pathlib import Path

from aselenium import Chrome


async def google_main():
    cache = Path("./browser-cache")
    cache.mkdir(parents=True, exist_ok=True)
    driver = Chrome(directory=cache)
    try:
        driver.options.set_timeouts(implicit=0, pageLoad=30, script=5)
        driver.options.session_timeout = 40

        result = await driver.manager.install_result(
            version="build",
            policy="compatible-build",
            validate_compatibility=True,
        )
        print("Driver:", result.driver_version)
        print("Browser:", result.browser_version)

        async with driver.acquire(version="offline") as session:
            await session.load("https://www.google.com/")
            print("URL:", await session.url)
            print("Title:", await session.title)
            await asyncio.sleep(5)
    finally:
        driver.options.close()


if __name__ == "__main__":
    asyncio.run(google_main())
```

```bash
.venv/bin/python google_quickstart.py
```

This minimal example only demonstrates navigation; a printed title does not
prove that Google's normal homepage or search results are ready. For readiness
checks, optional search, screenshots, and consent/challenge diagnostics, use
[`src/demo_google.py`](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_google.py). Google access requires an Internet
connection even when driver provisioning uses `policy="offline"`.

## Usage guide

Most recipes below define functions to call from inside an active session, such
as `await fill_form(session, upload_path)`. They are not standalone launch scripts;
use the quick-start lifecycle around them. Replace example selectors and URLs
with those of your application. The [demo fixtures](https://github.com/AresJef/Aselenium/tree/v2.0.0/src/demo_assets) provide a
local form, iframe, shadow root, and other targets for experimentation.

An important convention: some properties perform browser requests and must be
awaited (`await session.title`, `await element.text`). Local metadata and
configuration are synchronous (`session.id`, `driver.options`, `element.id`).

Filesystem paths follow one package-wide contract:

| Layer | Path behavior |
| --- | --- |
| Public and high-level APIs | Accept `str`, `pathlib.Path`, and compatible string-valued `os.PathLike[str]` objects. Byte-valued paths are rejected. |
| Core-function entry | Convert and validate the supplied value once, expand `~`, and anchor a relative path to the current working directory. |
| Internal workflow | Retain and pass host-native `pathlib.Path` objects without converting them to strings and parsing them again. Path-valued public results also remain `Path` objects. |
| Text or portable path boundary | Use `str` only for external interfaces that require text, such as process arguments, JSON/WebDriver payloads, URLs, SQLite/JSON records, and cache keys. Use `PurePosixPath` only for portable archive-member names. |

You do not need to call `str()` or `resolve()` before passing a path. Keeping the
native `Path` after the boundary avoids platform-specific reparsing differences,
especially on Windows. Filesystem operations can still perform scoped
canonicalization when security or ownership checks require it; that is validation
of an established `Path`, not a return to string-based path handling.

### Driver management

Each facade owns a manager, available as `driver.manager`. You can also use a
standalone manager without creating a browser session:

```python
from pathlib import Path
from aselenium import ChromeDriverManager


async def provision_chrome(cache_directory: str | Path, *, offline: bool = False):
    directory = Path(cache_directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    manager = ChromeDriverManager(directory=directory)
    result = await manager.install_result(
        version="build",
        policy="offline" if offline else "compatible-build",
        validate_compatibility=True,
    )
    return result
```

The standalone classes are `ChromeDriverManager`, `ChromiumDriverManager`,
`EdgeDriverManager`, `FirefoxDriverManager`, and `SafariDriverManager`.

`await manager.install(...)` returns an absolute `pathlib.Path` to the selected
driver executable.
`await manager.install_result(...)` returns an immutable snapshot with:

| Field | Meaning |
| --- | --- |
| `request` | Requested product, selector, channel, parsed `Path` executable overrides, platform, policy, and compatibility-validation flag. |
| `driver_location` | Absolute `Path` to the selected driver executable. |
| `driver_version` | Selected driver version string, or `None` only when a custom manager cannot report it. |
| `browser_location` | Absolute browser-executable `Path`, or `None` when a custom manager does not select a browser. |
| `browser_version` | Selected browser version string, or `None` when it cannot be reported. |
| `channel` | The resolved browser channel. |

Use the returned result when coordinating concurrent calls. Mutable manager
properties and `last_result` describe the last successful installation, not the
installation belonging to a particular caller.

#### Resolution policies and selectors

Pass a policy to **`install_result()`**, not to `driver.acquire()`:

| Policy | Intended use |
| --- | --- |
| `compatible-build` | Match the installed Chromium-family browser's build. |
| `compatible-major` | Match a Chromium-family major version; session startup still validates compatibility. |
| `latest-compatible` | Refresh vendor resolution for a compatible candidate rather than immediately returning a cache hit. It does not upgrade an installed browser. |
| `cached-compatible` | Prefer a compatible cached driver; provision if one is missing. |
| `offline` | Use cached artifacts without vendor requests; fail on a miss. |
| `exact` | Resolve the complete numeric driver version rather than substitute a newer patch. |

The familiar selectors remain available through `install()` and `acquire()`:

| Browser family | Selectors |
| --- | --- |
| Chrome / Chromium / Edge | `"build"` (default), `"major"`, `"patch"`, `"latest"`, `"cached"`, `"offline"`; a numeric major, three-part build, or four-part exact version. `"patch"` targets the detected browser's complete version, not any latest patch. |
| Firefox | `"latest"` (default), `"auto"` / `"cached"` (cache first), `"offline"`, or a full three-part Gecko version. Chromium build/major policies do not describe Gecko compatibility. |
| Safari | `channel="stable"` or `channel="dev"`; optional `driver` and `binary` paths. No downloadable driver-version selector or cache. |

Two-component Chromium selectors are rejected. Numeric selectors must not have
decorations such as a `v` prefix. A complete Chromium pin has four components;
a Gecko pin has three. The version must actually exist for the target platform.

```python
from aselenium import Chrome


async def install_exact(driver: Chrome, version: str):
    # Supply a real four-part driver version compatible with your Chrome.
    result = await driver.manager.install_result(
        version=version, policy="exact", validate_compatibility=True
    )
    # Exact installation already pins the artifact against eviction.
    # Explicit pin/unpin is also available:
    if result.driver_version is None:
        raise RuntimeError("The driver manager did not report an installed version")
    await driver.manager.pin(result.driver_version, pinned=True)
    return result


async def allow_eviction(driver: Chrome, version: str):
    await driver.manager.pin(version, pinned=False)
```

Standalone provisioning defaults to `validate_compatibility=False`, allowing
prewarming for another browser version. Set it to `True` when checking a pair
you intend to use locally. Session acquisition always validates the pair.

For offline startup, use `driver.acquire(version="offline")`. Supplying an exact
numeric version to `acquire()` instead can download it if absent. A preceding
exact installation does not force a later `"offline"` acquisition to select that
same version if several compatible cached versions exist; inspect the actual
session version and keep version-selection requirements explicit.

#### Chrome for Testing

Chrome can provision a matching Chrome for Testing (CfT) browser and driver:

```python
from aselenium import Chrome


async def provision_cft(driver: Chrome, version: str, *, offline: bool = False):
    # Supply a published, complete four-part CfT version.
    result = await driver.manager.install_result(
        version=version,
        channel="cft",
        policy="offline" if offline else "exact",
        validate_compatibility=True,
    )
    return result
```

`driver.acquire(version=version, channel="cft")` starts that CfT pair and can
provision missing assets. The CfT route requires a numeric selector; it does not
accept `version="offline"`. For the offline-compatible-binary workflow used by
the local demo, see [the CfT instructions](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo-local.md#chrome-for-testing).

CfT availability is verified against the version manifest. OS/architecture
support depends on the assets actually published for that version; unsupported
ARM combinations are not silently treated as x64. Exact CfT installation pins
both artifacts. Use `manager.pin(version, artifact="binary", pinned=False)` to
unpin its browser separately from its driver.

#### Cache directory and limits

Without `directory`, downloadable managers use `~/.aselenium`. With an explicit
existing cache parent, the v2 index is
`<directory>/.aselenium/v2/index.sqlite3`. Create the parent before constructing
a facade/manager. Use a private local filesystem, not a multi-host shared cache.

`max_cache_size` limits retained cached versions, not bytes. Pins and active
session leases can keep the cache above that soft limit. Raw executable paths
used outside Aselenium session contexts are not automatically leased; pin an
artifact before relying on it under eviction pressure.

Executable hashes detect local executable changes; they are not vendor
signatures or validation of every file in a browser bundle. Corrupt entries and
unsupported database schemas are reported and preserved, not silently erased.

### Choosing a browser

Import the facade you need from `aselenium`. Browser selection belongs to the
facade and its `acquire()` arguments, not to a generic Selenium driver object.

| Facade | Acquisition example | Configuration notes |
| --- | --- | --- |
| `Chrome()` | `driver.acquire("build", channel="stable", binary=path)` | Stable, beta, dev, and numeric CfT route. Headless: `--headless=new`. |
| `Chromium()` | `driver.acquire("build", binary=path)` | No channel parameter. Headless: `--headless=new`. |
| `Edge()` | `driver.acquire("build", channel="stable", binary=path)` | Stable, beta, dev; no CfT channel. Headless: `--headless=new`. |
| `Firefox()` | `driver.acquire("auto", binary=path)` | Gecko compatibility resolution; no channel parameter. Headless: `-headless`. |
| `Safari()` | `driver.acquire(channel="stable", binary=path)` | System Safari driver, macOS, headed automation. `dev` selects Technology Preview. |

Omit `binary` or pass `None` for discovery. An explicit path identifies the actual
executable. For example, a macOS Chrome path is
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, not the app bundle
directory. On Windows, use the browser's `.exe` path.

Chrome/Chromium/Edge/Firefox constructors accept `directory`, `max_cache_size`,
`request_timeout`, `download_timeout`, a provisioning `proxy`, and
`service_timeout`. Safari does **not** accept download/cache constructor settings;
do not copy those keyword arguments into `Safari()`.

Firefox additionally accepts `profile_root`. This is the parent in which
GeckoDriver creates temporary browser profiles; it is not the same setting as
`driver.options.set_profile()`, which selects profile content to clone.

### Options and proxies

Configure `driver.options` before calling `acquire()`. Importing a separate
options class is optional.

```python
from aselenium import Chrome


def configure_chrome(driver: Chrome):
    options = driver.options
    options.add_arguments("--headless=new", "--window-size=1200,900")
    options.accept_insecure_certs = False
    options.page_load_strategy = "normal"  # Also: "eager" or "none".
    options.unhandled_prompt_behavior = "ignore"  # Handle prompts explicitly.
    options.strict_file_interactability = True
    options.session_timeout = 30
    options.set_timeouts(implicit=0, pageLoad=20, script=5)
    options.set_preferences(
        **{
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
    )
    options.add_experimental_options(excludeSwitches=["enable-logging"])
```

Arguments, preferences, and experimental options are browser-specific. Do not
assume Chromium keys have meaning in Firefox or Safari. For trusted Chromium
extensions, `options.add_extensions(*paths)` accepts packaged extension paths;
Firefox's session-level add-on APIs are described below.

Capability/preference dictionaries and argument lists returned by accessors are
defensive copies. Changing `driver.options.capabilities["pageLoadStrategy"]`
does not reconfigure the driver. Use properties or methods such as
`set_capability()`, `set_preferences()`, and `add_arguments()`. An invalid argument
or extension batch does not partially apply earlier items in that batch.

There are two distinct proxy settings:

- The facade/manager constructor's `proxy` configures **driver-provisioning HTTP
  requests**. It does not configure browser page traffic.
- `driver.options.proxy` configures **the browser's proxy capability**, where
  supported. It does not control driver downloads.

```python
from aselenium import Chrome, Proxy


def configure_browser_proxy(driver: Chrome, proxy_url: str):
    # Supply a real reachable URL, for example http://proxy.example:8080.
    driver.options.proxy = Proxy(
        http_proxy=proxy_url,
        https_proxy=proxy_url,
        no_proxy=["localhost", "127.0.0.1"],
    )
```

Construct `Proxy` with keyword arguments and explicit URL schemes; the old FTP
proxy option and positional constructor arguments have been removed.
Proxy bypass entries serialize to the WebDriver
`noProxy` array. Credentials are redacted from proxy representations, but avoid
printing full capability dictionaries or storing credentials in source files.
Actual proxy authentication support varies by browser. Safari's facade does not
support custom proxy configuration. Provisioning keeps TLS verification enabled
and does not implicitly use environment-proxy discovery.

### Profiles and configuration isolation

`set_profile()` makes a temporary copy instead of launching against the original
profile. Chromium-family browsers take a user-data directory and profile folder;
Firefox takes a profile directory directly. Safari does not expose this feature.
The Chromium profile folder must be a portable single child-directory name, not
a path: separators, absolute or drive syntax, `.`/`..`, and reserved names are
rejected.

```python
from aselenium import Chrome


async def use_dedicated_profile(profile_directory: str):
    driver = Chrome()
    driver.options.add_arguments("--headless=new")
    try:
        # profile_directory must exist and contain a "Default" profile folder.
        driver.options.set_profile(profile_directory, "Default")
        async with driver.acquire("build") as session:
            await session.load("data:text/html,<title>Cloned profile</title>")
            return await session.title
    finally:
        # Release the facade's template as well as session-owned snapshots.
        driver.options.close()
```

For Firefox, the corresponding call is
`driver.options.set_profile(profile_directory)`.

Prefer a small, dedicated automation profile. Copying an actively modified
personal profile does not produce a guaranteed consistent snapshot and may copy
cookies or other sensitive data. The demo's `--profile-demo` uses an empty
temporary source instead.

`driver.acquire()` captures configuration **when called**, before it is awaited.
Later option changes only affect later contexts. Configured profiles receive
separate physical clones, so closing one acquisition does not remove another's
profile. The synchronous acquisition API still copies an explicitly configured
profile synchronously; large profiles can block the event loop during this step.

Do not share a manually supplied `--user-data-dir` between running sessions.
Same-process active sharing is rejected; cross-process sharing is unsupported.

#### Firefox Snap/Flatpak profile root

Container-packaged Firefox can have a different temporary-filesystem view from
the host GeckoDriver. On affected Linux systems, pass an existing, non-hidden
directory under your home directory that both processes can read and write:

```python
from pathlib import Path

from aselenium import Firefox


async def open_google_with_containerized_firefox():
    profile_root = Path.home() / "aselenium-firefox-profiles"
    profile_root.mkdir(parents=True, exist_ok=True)

    driver = Firefox(profile_root=profile_root)
    driver.options.add_arguments("-headless")
    try:
        async with driver.acquire("auto") as session:
            await session.load("https://www.google.com/")
            return await session.title
    finally:
        driver.options.close()
```

The public argument accepts `str`, `pathlib.Path`, or a string-valued
`os.PathLike`. The reusable Firefox facade parses and validates it once, then
retains the resulting `Path` across acquisitions. Each service launch rechecks
that the retained directory still exists without converting it back to text.
The directory must already exist and GeckoDriver must be 0.32.0 or newer. It
remains caller-owned and is never deleted by Aselenium. Do not also pass a raw
`--profile-root` service argument.
See Mozilla's [container-package guidance](https://firefox-source-docs.mozilla.org/testing/geckodriver/Usage.html#running-firefox-in-a-container-based-package)
for the underlying GeckoDriver/Firefox filesystem constraint.

### Session lifecycle

Use `async with driver.acquire(...) as session` for ordinary work. It owns the
driver service, HTTP client, session state, cache leases, and profile snapshot.

For explicit lifecycle control:

```python
from aselenium import Chrome


async def managed_session(driver: Chrome):
    context = driver.acquire("offline")  # Requires a compatible cached driver.
    try:
        session = await context.start()
        await session.load("data:text/html,<title>Managed session</title>")
        return await session.title
    finally:
        await context.quit()
```

Repeated `start()` calls share an already running context. A closed context is
single-use: create a new acquisition instead of restarting it. `quit()` is
idempotent after successful cleanup and protects owned teardown from cancellation.
If cleanup fails, the context retains resource handles for an explicit `quit()`
retry; do not overwrite it with a restart. Keep the original exception visible
when deciding how to report a cleanup failure.

### Timeouts and explicit waits

These settings solve different problems:

| Setting | Unit and scope |
| --- | --- |
| `request_timeout` / `download_timeout` | Seconds; provisioning metadata requests and downloads. |
| `service_timeout` | Seconds; driver-service startup/shutdown operations. |
| `options.session_timeout` | Seconds; a WebDriver command budget including ownership/connection queueing and the HTTP request. |
| `set_timeouts(implicit=...)` | Seconds; element-lookup waiting. Zero avoids combining a long implicit wait with explicit polling. |
| `set_timeouts(pageLoad=...)` | Seconds; the browser's page-load timeout. |
| `set_timeouts(script=...)` | Seconds; the browser's asynchronous-script timeout. |
| `wait_for(..., timeout=...)` and `wait_until_*` | Seconds; a total polling budget shared with nested waits and their commands. |

Manager, service, and command budgets must be finite and positive. Polling permits
zero: `timeout=0` or `None` makes one immediate observation, not an infinite wait.
`Timeouts.dict` is a WebDriver wire representation in **milliseconds**; the ordinary
setter arguments and attributes above use seconds. Explicit `*_ms` attributes also
exist on `Timeouts`.

```python
from aselenium import Session


async def wait_for_input(session: Session):
    await session.set_timeouts(implicit=0, pageLoad=20, script=5)
    field = await session.wait_for(lambda: session.find_element("#name"), timeout=5)
    if not field:
        raise TimeoutError("#name did not appear within five seconds")
    if not await field.wait_until("enabled", timeout=2):
        raise TimeoutError("#name did not become enabled")
    return field
```

`wait_for()` takes an asynchronous, no-argument predicate and returns its first
truthy value, or a falsey value when its deadline expires. Other exceptions
propagate. It does not automatically ignore every transient element exception;
re-locate elements in a predicate when the page can replace them.

Useful built-ins include `wait_until_title()`, `wait_until_url()`,
`wait_until_element()`, and `wait_until_elements()`. Title/URL conditions are
`equals`, `contains`, `startswith`, and `endswith`. Session element conditions
include `exist`, `gone`, `in_viewport`, `unobscured`, `enabled`, and `selected`.
For example, `await session.wait_until_element("unobscured", "#name", timeout=5)`
waits for the element's center-point hit test to succeed. The old `visible` and
`viewable` properties and wait conditions have been removed, not aliased.
Boolean wait helpers return `False` on an unmet deadline; check their results.
`await session.reset_timeouts()` restores the acquisition's original settings.

### Navigation and page information

```python
from aselenium import Session


async def inspect_google_homepage(session: Session):
    await session.load("https://www.google.com/", timeout=30)
    return {
        "url": await session.url,
        "title": await session.title,
        "source": await session.page_source,
        "page_width": await session.page_width,
        "page_height": await session.page_height,
        "viewport": await session.viewport,
        "window_rect": await session.window_rect,
    }
```

Google may redirect to a regional or consent page, so this example deliberately
reports the resulting URL instead of asserting that it is byte-for-byte equal to
the requested URL. For a controlled application URL, use
`wait_until_url("equals", expected_url, timeout=5)`; for redirecting applications,
choose `contains`, `startswith`, or `endswith` according to the routing contract.
The guarded [Google demo](#real-world-google-demo) additionally checks the origin,
consent state and challenge pages before attempting interaction.

`await session.refresh()`, `await session.backward()`, and
`await session.forward()` operate on the active window. Navigation can redirect;
choose a URL condition appropriate to the application.

`load()` and `refresh()` have an explicit `retry` option for native WebDriver
page-load timeouts. They do not retry command transport timeouts automatically.
Only enable retries when repeating the navigation is safe for your application.

### Finding and interacting with elements

Session and element-scoped lookup support CSS selectors (`by="css"`, the default)
and XPath (`by="xpath"`). Use relative XPath such as `.//input` when searching
within an element.

| Lookup | Missing-result behavior |
| --- | --- |
| `find_element(selector)` | Returns `Element` or `None`. |
| `find_elements(selector)` | Returns a list, empty on a miss. |
| `find_1st_element(selector_a, selector_b, ...)` | Returns the first found element or `None`; every locator is checked once even with zero implicit wait. |
| `element_exists(selector)` / `elements_exist(...)` | Immediate boolean existence checks, ignoring implicit wait. |

```python
from pathlib import Path
from aselenium import Session


async def fill_form(session: Session, upload_path: str | Path):
    # This recipe uses the form IDs in src/demo_assets/index.html.
    field = await session.find_1st_element("#name", "input[name='name']")
    if field is None:
        raise LookupError("Name input not found")
    await field.clear()
    await field.send("Aselenium")  # Element.send(), not send_keys().

    checkbox = await session.find_element("#subscribe")
    if checkbox is not None and not await checkbox.selected:
        await checkbox.click()

    upload = await session.find_element("#upload")
    if upload is None:
        raise LookupError("File input not found")
    await upload.upload(upload_path)
    await field.submit()  # Awaited submission of the enclosing form.
```

`upload()` targets an `<input type="file">`; it is not automation of a native file
picker. Selecting a file makes it available to the page, so only upload files to
origins you trust. `submit()` and button clicks may trigger application side
effects; wait for an application-specific result rather than assuming immediate
completion. Re-find stale elements after navigation or DOM replacement.

The form recipe intentionally remains local: Google selectors, consent flows and
search-result behavior can change and automated search may encounter a challenge.
For a real-world, defensive lookup that checks multiple Google search-field
layouts, enabled state, obstruction, redirects and CAPTCHA without bypassing
them, use [`src/demo_google.py`](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_google.py).

### DOM properties and visibility

```python
from aselenium import Element


async def inspect_element(element: Element):
    return {
        "rendered_text": await element.text,
        "dom_text": await element.dom_text,
        "value": await element.get_property("value"),
        "placeholder_attribute": await element.get_attribute_dom("placeholder"),
        "css_color": await element.get_property_css("color"),
        "enabled": await element.enabled,
        "selected": await element.selected,
        "in_viewport": await element.in_viewport,
        "unobscured": await element.unobscured,
        "aria_role": await element.aria_role,
        "aria_label": await element.aria_label,
    }
```

`text` is WebDriver's rendered text; `dom_text` reads DOM `textContent`.
`get_attribute_dom()` reads a DOM attribute, while `get_property()` reads a
JavaScript property. For example, an input's current value can differ from its
original `value` attribute.

`in_viewport` requires a nonempty rectangle intersecting the viewport.
`unobscured` uses center-point hit testing, including open shadow-root traversal.
These are different observations, not promises that a later click will succeed.
Geometry alone does not imply CSS visibility: a `visibility:hidden` element can
still have a nonempty rectangle. Use `get_property_css()` when checking a specific
style condition. The hybrid `get_attribute()` helper is removed; choose
`get_attribute_dom()` or `get_property()` explicitly. Unsupported inspection
commands may return `None`.

### Windows and tabs

`Window` objects have synchronous `name` and `handle` properties. Window lists and
focus are asynchronous: `await session.windows`, `await session.active_window`.

```python
from aselenium import Session


async def inspect_another_tab(session: Session, url: str):
    async with session.transaction():
        original = await session.active_window
        await session.new_window("details", win_type="tab", switch=True)
        try:
            await session.load(url)
            return await session.title
        finally:
            await session.close_window(switch_to=original)
```

Use `win_type="window"` for a separate window. `switch_window()` accepts a name,
handle, or `Window`. Names must be nonempty and unique among open windows.
`close_window()` closes the **active** window; `switch_to` names the remaining
window to focus, not the window to close.

`set_window_rect(width=..., height=..., x=..., y=...)`, `maximize_window()`,
`minimize_window()`, and `fullscreen_window()` control window geometry where the
browser supports it. Commands on one connection are serialized, but separate
multi-command tasks can still interleave. A `transaction()` protects a related
sequence such as switching tabs and reading from the selected tab.
Transaction ownership follows the inherited async context. Child tasks created
inside an explicit transaction share that ownership, so await dependent operations
sequentially there rather than running them concurrently with `asyncio.gather()`.
Waiting to enter the transaction is bounded by the enclosing command/wait
deadline, or `options.session_timeout` if there is none. This is an admission
budget, not a total deadline for the context body, and it provides no rollback.
If admission expires, no command from that waiting context has been sent.

### Frames and shadow DOM

Switch frames before locating elements inside them, then restore the top-level
document in a `finally` block. The current Safari facade disables frame switching.

```python
from aselenium import Session


async def read_frame(session: Session):
    try:
        if not await session.switch_frame("#frame", timeout=5):
            raise TimeoutError("Frame not available")
        element = await session.find_element("#frame-text")
        return None if element is None else await element.text
    finally:
        await session.default_frame()


async def read_shadow_content(session: Session):
    host = await session.find_element("#host")
    if host is None:
        return None
    shadow = await host.shadow  # The property is named shadow, not shadow_root.
    if shadow is None:
        return None
    element = await shadow.find_element("#shadow-text")
    return None if element is None else await element.text
```

Frames can also be selected by an `Element` or by index using `by="index"`.
`parent_frame()` moves up one level; `default_frame()` returns to the document
root. Selector-based frame waits re-resolve the element on each attempt.
Shadow lookup uses CSS selectors; a `Shadow` is a separate search context, not a
normal DOM element. Do not assume closed shadow roots are accessible.

### Alerts and prompts

Configure `unhandled_prompt_behavior="ignore"` before acquisition if your code
will handle prompts explicitly. Use an application action to open the prompt, or
schedule a local one after the script returns:

```python
from aselenium import Session


async def answer_prompt(session: Session):
    await session.execute_script("setTimeout(() => prompt('Your name?', ''), 100)")
    alert = await session.get_alert(timeout=5)
    if alert is None:
        raise TimeoutError("Prompt did not appear")
    try:
        print(await alert.text)
        await alert.send("Aselenium")  # Text input applies to a prompt.
    finally:
        await alert.accept()
```

Use `dismiss()` to cancel an alert/confirmation/prompt. Handle modal prompts before
issuing unrelated page commands, which may be rejected while the prompt is open.

### Cookies

Navigate to the intended HTTP(S) origin before manipulating its cookies.
`data:` pages, including the quick start's page, are not suitable cookie origins.

```python
from aselenium import Session


async def round_trip_cookie(session: Session):
    # Assumes the session is already on your HTTP(S) page.
    await session.add_cookie(
        {
            "name": "demo-preference",
            "value": "compact",
            "path": "/",
            "sameSite": "Lax",
        }
    )
    try:
        cookie = await session.get_cookie("demo-preference")
        return None if cookie is None else cookie["value"]
    finally:
        await session.delete_cookie("demo-preference")
```

Cookie results are `Cookie` objects with dictionary-style field access and a
`.dict` snapshot, not a `.value` property. `await session.cookies` retrieves all
cookies for the active page context; `await session.delete_cookies()` deletes
them. Treat cookie values as secrets and respect domain, secure, expiry, and
same-site constraints.

### JavaScript

`execute_script()` returns the script's result. Values and `Element` arguments
are serialized for WebDriver. Do not interpolate user input directly into script
source when it can be passed as an argument.

```python
from aselenium import Session


async def javascript_examples(session: Session):
    title = await session.execute_script("return document.title")
    field = await session.find_element("#name")
    if field is not None:
        await session.execute_script("arguments[0].focus()", field)

    cached = session.cache_script("sum", "return arguments[0] + arguments[1]", 2, 3)
    try:
        total = await session.execute_script(cached)
        overridden = await session.execute_script("sum", 10, 20)
    finally:
        session.remove_script("sum")

    result = await session.execute_async_script("""
        const done = arguments[arguments.length - 1];
        setTimeout(() => done({ready: true}), 25);
    """)
    return title, total, overridden, result
```

`cache_script()` and `remove_script()` are synchronous local operations. A cached
script can be addressed by its returned `JavaScript` object or name; supplied
execution arguments override its cached arguments. `execute_async_script()` uses
WebDriver's callback convention, bounded by the script timeout.

A returned dictionary containing `error` or `message` is ordinary application
data when the WebDriver response itself succeeded. Raw element-reference objects
returned inside script results are not automatically turned into `Element`
instances; use the element lookup APIs when you need element wrappers.

### Keyboard and pointer actions

Use `Element.send()` for simple input. For pointer movement, clicks, keyboard
combinations, drag operations, or wheel actions, construct an `Actions` chain.
Building the chain is synchronous; `perform()` and `reset()` are asynchronous.

```python
from aselenium import Session


async def type_with_actions(session: Session):
    field = await session.find_element("#name")
    if field is None:
        raise LookupError("Name input not found")
    await field.clear()
    chain = session.actions()
    try:
        await chain.move_to(field).click().send_keys("first").perform()
        await chain.send_keys("-second").perform()
        return await field.get_property("value")
    finally:
        await chain.reset()
```

`perform()` detaches the pending batch before awaiting the browser. Later input
queued through the builder belongs to a new batch and is retained even if the
earlier dispatch fails or is cancelled. A dispatched batch is never automatically
replayed. Overlapping calls do not duplicate the batch, but dependent interactions
should still be awaited sequentially.
`reset()` clears the then-pending local batch and requests release of remote input
state. Input added after reset starts is kept for a later `perform()`.
`send_key_combo()` accepts `KeyboardKeys` values for modifiers; choose the
appropriate Control/Command modifier for the operating system. `MouseButtons`
provides button constants. Durations must be finite and nonnegative.
Optional `pause=` values on elements, alerts, and scrolling, and `explicit_wait=`
on `perform()`, are validated before sending a browser mutation. Booleans,
negative values, and non-finite numbers are rejected; `None` means no delay.
The current Safari facade disables action chains; Firefox support should be
validated for the operations and browser versions your application needs.

### Scrolling

```python
from aselenium import Session


async def reach_section(session: Session, selector: str):
    await session.scroll_by(height=300)
    if not await session.scroll_into_view(selector, timeout=5):
        raise TimeoutError("Scroll target not available")
    # Read or interact with the target here.
    await session.scroll_to(x=0, y=0)
```

An `Element` also has `scroll_into_view()`. Helpers `scroll_to_top()`,
`scroll_to_bottom()`, `scroll_to_left()`, and `scroll_to_right()` perform stepped
scrolling. They stop on repeated lack of progress or bounded iteration/deadline
limits; they do not promise to exhaust an endlessly growing feed. For infinite
scrolling, define an application-specific item or time limit.

### Screenshots and PDF output

```python
import asyncio
from pathlib import Path
from aselenium import Session


async def capture_page(
    session: Session, output_directory: str | Path, *, pdf: bool = False
):
    output = Path(output_directory).expanduser()
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    if not await session.save_screenshot(output / "page.png"):
        raise RuntimeError("Screenshot was not saved")
    if pdf and not await session.save_page(output / "page.pdf", background=True):
        raise RuntimeError("PDF was not saved or printing is unsupported")
```

`take_screenshot()` returns PNG bytes; `print_page()` returns PDF data where
supported. `Element.take_screenshot()` / `save_screenshot()` capture an individual
element. `save_page()` also accepts orientation, scale, dimensions, margins,
shrink-to-fit, and page ranges. A parent directory must exist. Relative filenames
are supported; PNG/PDF output is published atomically using off-loop file work.
Successful saves can replace an existing file, so choose unique names when
preserving prior captures matters. Check boolean/optional results.

Chromium printing is demonstrated and validated in headless mode; Safari's
facade disables printing. Firefox adds `take_full_screenshot()` and
`save_full_screenshot()` for full-page capture. Captures can contain sensitive
page content; handle their storage and sharing accordingly.

### Concurrent sessions and cancellation

Separate sessions are the simplest concurrency boundary. A single connection
serializes its commands; launching many coroutines against one session does not
give independent tab, frame, cookie, or focus state.

This Python 3.10-compatible recipe bounds active sessions and owns all its tasks.
Provision the shared cache first and pass a finite batch of URLs.

```python
import asyncio
from aselenium import Chrome


async def collect_titles(driver: Chrome, urls: list[str], parallelism: int = 3):
    if parallelism < 1:
        raise ValueError("parallelism must be positive")
    slots = asyncio.Semaphore(parallelism)

    async def worker(url: str):
        async with slots:
            async with driver.acquire("offline") as session:
                await session.load(url)
                return await session.title

    tasks = [asyncio.create_task(worker(url)) for url in urls]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        cleanup = asyncio.gather(*tasks, return_exceptions=True)
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # Repeated cancellation must not abandon owned workers.
                continue
        cleanup.result()
```

Configure the facade before launching workers. Each `acquire()` snapshots options;
use independent facades if workers require different configurations. This pattern
is not intended for Safari's single-session automation service.

For a work deadline, wrap an owned coroutine in `asyncio.wait_for()`. Cancellation
must unwind the session context; do not simply cancel a task and discard it.
Cleanup may exceed the work deadline while owned subprocess/filesystem work
finishes. Python cannot forcibly interrupt a blocking kernel operation just
because it was moved to a worker thread. See the runnable demo's
[`cancellation` chapter](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo-local.md#profile-and-lifecycle-ownership) for cancellation
followed by a fresh acquisition.

### Browser-specific features

#### Chromium: CDP, network conditions, permissions, and logs

These APIs belong to `ChromeSession`, `ChromiumSession`, and `EdgeSession`.
They are not portable Firefox/Safari methods.

```python
from aselenium import ChromeSession, ChromiumSession, EdgeSession


async def chromium_diagnostics(session: ChromeSession | ChromiumSession | EdgeSession):
    command = session.cache_cdp_cmd("browser-version", "Browser.getVersion")
    version = await session.execute_cdp_cmd(command)

    # Keep preserve/use/restore together so another task cannot interleave a
    # network change that this example would then overwrite.
    async with session.transaction():
        original = await session.network
        try:
            await session.set_network(
                offline=False,
                latency=25,
                download_throughput=1024 * 1024,
                upload_throughput=512 * 1024,
            )
            conditions = await session.network
        finally:
            await session.set_network(
                offline=original.offline,
                latency=original.latency,
                download_throughput=original.download_throughput,
                upload_throughput=original.upload_throughput,
            )

    log_types = await session.log_types
    logs = await session.get_logs("browser") if "browser" in log_types else []
    return version, conditions, logs
```

Network latency is milliseconds; throughput is bytes per second. `reset_network()`
restores default conditions; the example above preserves the caller's prior
settings instead. Browser network emulation does not control driver downloads.
Fetching logs consumes the returned entries. Avoid indiscriminately persisting
logs from sensitive applications.

On an appropriate page origin, `get_permission(name)` returns a `Permission` or
`None`; `set_permission(name, state)` accepts `granted`, `denied`, or `prompt`.
For example, use `geolocation` and restore its previous state in `finally`.
The setter owns its update and confirming observation as one transaction. Use
your own `session.transaction()` when subsequent operations depend on that state.
CDP command availability depends on the Chromium version; Aselenium does not
guarantee every command across releases.

Casting APIs include `cast_sinks`, `cast_issue`, `set_cast_sink()`,
`start_casting(sink_name, mirror="tab")`, and `stop_casting(sink_name)`. These
operate on real receivers and can expose browser/desktop content. Select a device
deliberately; the local demo does not discover or start casting automatically.

#### Firefox: add-ons, context, and full-page capture

```python
from pathlib import Path
from aselenium import FirefoxSession


async def use_temporary_addon(session: FirefoxSession, addon_path: str | Path):
    # Use a trusted .xpi file or an unpacked extension directory.
    addons = await session.install_addons(addon_path, temporary=True)
    try:
        return [addon.id for addon in addons]
    finally:
        for addon in addons:
            await session.uninstall_addon(addon)
```

`session.addons` is local add-on metadata. Add-ons must contain `manifest.json`
with `manifest_version` 2 or 3; `install.rdf` and the old `applications` key are
unsupported. Use `browser_specific_settings.gecko.id`; a driver-returned ID is used
when a manifest ID is absent. Install only trusted extensions: they can access
data according to their browser permissions.

`await session.context` reports `"content"` or `"chrome"`. `set_context()` and
`reset_context()` switch/restore it and observe the result under one transaction.
Wrap any dependent browser work in your own transaction as well.
Firefox's `"chrome"` context means privileged
browser UI, **not Google Chrome**; it may need browser-specific startup permission
and is not required for ordinary webpage automation. Prefer the content context.

#### Safari: system automation and permissions

Use `Safari()` with `acquire(channel="stable")`, or `channel="dev"` for Technology
Preview. A custom `driver=` executable can be supplied to `acquire()`. Enable
Remote Automation yourself before running; Aselenium's demo does not change
system/browser automation settings.

Safari has its own `permissions`, `get_permission(name)`, and
`set_permission(name, value)` APIs, with **boolean values**, not Chromium's
permission-state strings. Its options include `automatic_inspection`,
`automatic_profiling`, and `technology_preview`. Permission updates serialize
their read/merge/write/observation sequence to preserve other concurrent updates.
Frames, W3C action chains, custom proxies, and PDF printing are disabled by the
current facade. `switch_frame()` returns `False`; `parent_frame()` and
`default_frame()` are no-ops that return `True`. Those return values do
not establish that Safari changed frame focus.

### Errors and logging

Errors are exported from `aselenium`. Distinguish provisioning/service failures
from application-level element misses and ambiguous command timeouts.

| Situation | Examples / handling |
| --- | --- |
| Browser/driver unavailable | `BrowserBinaryNotDetectedError`, `DriverExecutableNotDetectedError`; check executable, platform, selector, and cache. |
| Vendor request or download failed | `DriverRequestFailedError`, `DriverDownloadFailedError`, `DriverManagerTimeoutError`; inspect the cause and network configuration. |
| Incompatible version | `InvalidDriverVersionError`, `IncompatibleWebDriverError`; resolve a supported pair rather than suppress the error. |
| Driver service problem | `ServiceError` and subclasses; inspect permissions, executable health, and service startup/cleanup. |
| Command budget expired | `SessionTimeoutError`; the remote operation may have executed. Inspect state before deciding to retry. |
| Page interaction failed | `ElementStaleReferenceError`, `ElementClickInterceptedError`, other `WebDriverError` subclasses; re-locate/wait or adjust the interaction. |
| Optional lookup missed | `find_element()` returns `None`; an ordinary missing lookup is not necessarily an exception. |

```python
import logging
from aselenium import Session, SessionTimeoutError, WebDriverError


def configure_logging():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("aselenium").setLevel(logging.INFO)


async def load_with_diagnostics(session: Session, url: str):
    try:
        await session.load(url)
    except SessionTimeoutError:
        logging.getLogger(__name__).warning(
            "Navigation command timed out; inspect state before retrying"
        )
        raise
    except WebDriverError:
        logging.getLogger(__name__).warning("Browser rejected navigation")
        raise
```

The library installs a `NullHandler`; the application controls logging output.
Command logs omit request bodies, query strings, and proxy credentials. Review
exception text and application logs separately before sharing diagnostics.

Provisioning GETs retry a limited set of transient network/HTTP failures under a
shared deadline. Authentication/TLS failures are not treated as cache misses.
Mutating WebDriver commands are not automatically replayed after an ambiguous
transport failure. Do not use broad retries around clicks, uploads, submissions,
or other operations that may already have succeeded remotely.

## Runnable demo

Two named demos distinguish repeatable local checks from live website automation:

| Demo | Website | Default browser mode | Purpose |
| --- | --- | --- | --- |
| [demo_local.py](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_local.py) | Local HTML served on loopback | Headless, except Safari | Full selectable package feature tour. |
| [demo_google.py](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_google.py) | Real [Google.com](https://www.google.com/) | Visible / headed | Open Google, optionally submit one search, and capture the live page. |

Use your project interpreter explicitly on macOS/Linux (on Windows, use
`.venv\Scripts\python.exe`), or activate the environment before using `python`.
Run commands from the repository root. The first run may need `--allow-download`
to populate the demo cache; later runs can use the compatible cached driver.

### Local HTML feature tour

[`src/demo_local.py`](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_local.py) serves bundled HTML on an ephemeral
`127.0.0.1` port and controls a real browser against it. It does not navigate to
Google or another public website. Start with:

```bash
.venv/bin/python src/demo_local.py list
.venv/bin/python src/demo_local.py run --browser chrome --allow-download
```

Once provisioned, run offline, make the browser visible, or select chapters:

```bash
.venv/bin/python src/demo_local.py run --browser chrome
.venv/bin/python src/demo_local.py run --browser chrome --headed
.venv/bin/python src/demo_local.py run --sections concurrency cancellation --profile-demo
```

For a Snap/Flatpak Firefox, create a shared directory once and pass it explicitly:

```bash
mkdir -p "$HOME/aselenium-firefox-profiles"
.venv/bin/python src/demo_local.py run --browser firefox --allow-download \
  --profile-root "$HOME/aselenium-firefox-profiles" --session-timeout 60
```

Driver management and options run first. The 13 selectable chapters cover
navigation, elements, waits, cookies, windows, frames, alerts, scripts, actions,
artifacts, vendor commands, concurrency, and cancellation: **15 stages** in a full
tour. Browser-specific limitations are reported as skipped, not counted as passes.
The `--profile-demo` option clones a new empty profile template, never your
personal profile.
The local tour's `--session-timeout` option is the per-command and session-start
deadline (30 seconds by default); a cold Snap/Flatpak Firefox launch may need a
larger value such as 60 seconds. Its separate `--timeout` option bounds the whole
tour and defaults to 240 seconds.

To provision without opening a browser:

```bash
.venv/bin/python src/demo_local.py install --browser chrome --allow-download
```

See the [local HTML guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo-local.md) for all CLI options, browser
prerequisites, exact-version policies, and Chrome for Testing.

### Real-world Google demo

[`src/demo_google.py`](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_google.py) visits `https://www.google.com/` in
**visible Chrome by default**. Without `--query`, it opens only the homepage,
waits for an enabled, unobscured search field, records the page URL/title, saves
`google-home.png`, and leaves the page open for five seconds before cleanup:

```bash
.venv/bin/python src/demo_google.py run --browser chrome --allow-download
```

With a compatible cached driver, submit one optional search or run headless:

```bash
.venv/bin/python src/demo_google.py run --query "Aselenium Python" --hold-seconds 10
.venv/bin/python src/demo_google.py run --headless --hold-seconds 0
```

The search example uses `clear()` and `send(..., KeyboardKeys.ENTER)`, then waits
for a Google `/search` URL carrying the query and visible result headings. On
success, it records up to five heading samples and saves `google-results.png`.
It does not click result links or ads. The wait can fail if Google changes its
layout, returns no results, or restricts the request.

If a consent dialog appears in a visible browser, make your own choice while
the readiness wait is active. Allow more time when needed:

```bash
.venv/bin/python src/demo_google.py run --wait-timeout 60 --hold-seconds 10
```

The demo does not select consent, sign in, solve CAPTCHA, or retry a blocked
search. Its key options are:

| Option | Behavior |
| --- | --- |
| `--browser chrome\|chromium\|edge\|firefox\|safari` | Select the installed browser; Chrome is the default. |
| `--binary PATH` | Use an explicit executable, such as the executable inside a macOS `.app` bundle. |
| `--query TEXT` | Submit one search; omit for homepage-only navigation. |
| `--headless` | Hide the window; Safari is always headed. |
| `--hold-seconds N` | Wait on the final/attention page before cleanup; default 5, range 0–60. |
| `--wait-timeout N` | Readiness budget per page in seconds; default 20. |
| `--timeout N` | Overall work budget in seconds; default 180. Owned cleanup can take longer. |
| `--allow-download` | Allow driver vendor requests during provisioning, not a toggle for website access. |
| `--cache-dir PATH` / `--output-dir PATH` | Override the shared demo cache parent or run-output parent. |

**Recorded live result, 2026-09-04:** the homepage-only run passed in visible
Chrome. One search encountered Google's unusual-traffic CAPTCHA; the demo saved
an attention screenshot and exited with `needs-attention`. A normal live search
results page was **not verified** in that run. See the [Google guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo-google.md)
and [validation record](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/baselines/demo-google-validation.json) for the exact
environment and evidence boundaries.

### Demo outputs and network behavior

Both entry points print help without launching a browser when run with no arguments:

```bash
.venv/bin/python src/demo_local.py
.venv/bin/python src/demo_google.py
```

Both share `.demo-cache` under the checkout, separate from the minimal examples'
`./browser-cache` and the library's default `~/.aselenium` cache. By default,
the demo commands prohibit driver vendor requests; use `--allow-download` to
enable compatible provisioning. This restriction is a demo CLI policy, not the
library's default behavior for online selectors. Neither offline driver resolution
nor local HTML prevents browser-internal background network activity.

Each run writes a unique `local-<browser>-...` or `google-<browser>-...` directory
under `.demo-output`, so separate runs do not overwrite one another:

| Output | Contents |
| --- | --- |
| `report.json` | Selected/actual versions, run status, diagnostics, and artifact names; local runs also include per-stage results. |
| Local `page.png` / `page.pdf` | Fixture captures from the artifact chapter, where supported by the selected browser/mode. |
| Google `google-home.png` | Homepage after its search field becomes usable. |
| Google `google-results.png` | Results page only when the optional search completes. |
| Google `google-attention.png` | Best-effort capture of a challenge, consent timeout, or other workflow error. |

For the Google demo, exit **0** means completion, **2** means the page needs
attention, **1** means another failure, and **130** means keyboard interruption.
Homepage-only success does not claim that searching was tested. Reports and
captures can contain query text, page content, local paths, and IP/network
diagnostics; review them before sharing.

Use `src/demo_local.py` or `src/demo_google.py` in scripts and documentation;
the former `src/demo.py` entry point is no longer present in this checkout. The
demos, shared helper, and fixtures remain repository examples; production wheels
and source distributions intentionally contain only the package and its required
metadata and runtime resources. See the
[demo overview](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo.md) to compare the two workflows.

## Troubleshooting

### Dependency import errors

If you see `ModuleNotFoundError: No module named 'orjson'` despite installing it
in `.venv`, first check whether the failing script actually uses that environment.
An installed dependency is available to its interpreter, not every Python on the
machine. From the repository root, compare:

```bash
python -c "import sys; print(sys.executable)"
.venv/bin/python -c "import sys, orjson; print(sys.executable); print(orjson.__file__)"
.venv/bin/python -m pip show aselenium orjson
```

Run the script with `.venv/bin/python`, or set your editor's interpreter to the
same executable. If imports still fail under that exact interpreter, install the
checkout there with `.venv/bin/python -m pip install -e .` and read any dependency
installation error. Do not add arbitrary `sys.path` entries or suppress the
missing import. The file path in a traceback identifies the source that was
loaded, not necessarily the interpreter that loaded it.

### Browser, cache, and website problems

| Symptom | What to check |
| --- | --- |
| No browser window appears | The local tour is headless by default; add `--headed`. The Google demo is visible unless `--headless` is set. With no subcommand, either script only prints help. |
| Browser executable is not detected | Install the browser or provide `--binary` to the demo; supply the executable, not a directory or `.app` bundle. |
| Offline provisioning reports no compatible driver | Confirm the selected `--cache-dir` and browser version. Run once with `--allow-download` when vendor access is permitted, especially after a browser update. |
| Google opens but search stops with exit code 2 | Read `report.json` and inspect `google-attention.png`. Consent, CAPTCHA, redirects, or layout changes can prevent completion; the demo does not bypass restrictions. |
| Google consent needs more time | Use a headed run with `--wait-timeout 60` and choose manually; `--hold-seconds` controls the final pause, not readiness time. |
| A script immediately closes its browser | Leaving `async with` closes the session. The Google CLI provides `--hold-seconds` for observation; your own script should await its work inside the context. |
| Safari rejects a feature | Review the [Safari boundaries](#safari-system-automation-and-permissions), enable Remote Automation yourself, and do not pass Chromium-only options. |

Avoid deleting caches as a first response to errors. Record the interpreter,
browser/driver versions, selected cache, and exact failure before deciding on a
scoped repair. See [cache recovery](#cache-recovery).

## Cache recovery

SQLite v2 is the only cache format. Old Feather metadata is neither read nor
imported; the import module and extra have been removed. Existing files outside
the v2 cache are left untouched. Reprovision a supported browser/driver pair with
`install_result(policy="compatible-build", validate_compatibility=True)` for
Chrome/Chromium/Edge, or `policy="cached-compatible"` for Firefox. See
[driver management](#driver-management) for selectors and offline behavior.

Cache publication is staged and atomic. Matching orphan publications can be
reindexed after a crash. Advanced scoped `recover()` and `clean_staging()`
maintenance APIs are explained in the [cache recovery guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/modernization-guide.md#sqlite-v2-and-recovery).
Run synchronous maintenance with `asyncio.to_thread()` in async applications.
Do not delete an entire cache or its persistent lock files as a routine repair.
NFS/SMB, multi-host caches, hostile concurrent writers, and hardware power-loss
durability are outside the verified support boundary.

## Compatibility and verification

The public API targets Python 3.10+ and five browser facades. Declared support,
configured CI jobs, and results from a particular machine are different things.
See the [pre-deployment review](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/pre-deployment-review.md)
for the latest tested candidate, exact counts, installed-wheel checks, and
remaining deployment gates. Older reports are dated snapshots, not current badges.

| Area | Capability and verification boundary |
| --- | --- |
| Chrome and Edge | Shared Chromium automation, CDP, network emulation, permissions, logging, and PDF output. Installed-wheel local tours and reliability harnesses exist; the latest review identifies which were rerun. |
| Chromium and Chrome for Testing | Standalone Chromium and managed CfT browser/driver pairs are supported by the manager. Provider, cache, and command regressions do not substitute for native acceptance of a separate browser bundle. |
| Firefox | WebDriver automation, action chains, add-ons, contexts, and full-page screenshots. The local tour checks the applicable features; driver resolution fails closed for unrecorded future Gecko releases. |
| Safari | macOS system automation with Remote Automation enabled beforehand. The current facade disables frames, action chains, and concurrent acquisitions; the tour records these as three exclusions, not passes. Custom proxies and PDF printing are also unavailable. |
| Python and operating systems | The configured CI matrix covers Python 3.10–3.14, Linux/Windows/macOS, and exact runtime minimum dependencies. A local Python/macOS pass does not establish a pass for the other jobs. |
| Native CI | Installed-wheel jobs cover Chrome/Firefox on Linux and macOS, Edge on Windows, and Safari on macOS. Chrome/Edge reliability checks include recovery, proxy routing, and sustained use; scheduled and release runs request a 600-second soak. |
| Real Google website | A dated visible-Chrome homepage run passed. An optional search encountered CAPTCHA and stopped with `needs-attention`; a normal live results-page pass is not claimed. |
| Not locally certified | Other OS/browser/version combinations, Linux Snap/Flatpak profile access, separate Chromium/CfT bundles, WebView2, beta/dev channels, and casting hardware need environment-specific acceptance. |

The regular test suite includes deterministic regressions and real disposable
loopback HTTP/TCP/TLS tests. Native acceptance imports a built wheel from outside
the checkout and checks its origin. Coverage, typing, executable examples, and
metadata checks are separate gates; none alone proves full feature correctness.

Before deployment, run the configured CI/release gates on the exact commit and
test the installed distribution on your target platform. A bounded soak does not
prove unlimited uptime or an absence of leaks. SHA checks and safe extraction do
not turn browser automation into a security sandbox for untrusted websites.

The [earlier production review](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/final-production-review.md),
[release-acceptance guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/release-acceptance.md),
and [Google validation record](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/baselines/demo-google-validation.json)
retain the history and reproduction instructions without implying that every
earlier environment was rerun for the latest source changes.

## Development

Install development dependencies into the same environment as the checkout,
then run the quality gates. Commands below use macOS/Linux executable paths;
substitute `.venv\Scripts\python.exe` on Windows:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest --asyncio-debug
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m ruff format --check src tests scripts
.venv/bin/python scripts/check_api_quality.py
.venv/bin/python scripts/check_example_contracts.py
.venv/bin/python -m mypy
.venv/bin/python -m coverage run --branch --source=aselenium -m pytest --asyncio-debug
.venv/bin/python -m coverage report
.venv/bin/python -m pip check
.venv/bin/python -m pip_audit --skip-editable
.venv/bin/python -m build --no-isolation
.venv/bin/python -m twine check --strict dist/*
```

Default tests prohibit external network requests and installed-browser launches.
The `loopback` tests use real HTTP/TCP and HTTPS against their own strictly allowlisted
temporary local servers and require permission to bind a local socket. In a
restricted environment, `-m "not loopback"` explicitly deselects those tests;
it does not establish their behavior. See the [feature-testing guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/feature-testing.md#reproduce).
Some tests use controlled subprocesses for cache concurrency and distribution
builds. Installed-wheel browser checks and the individual crash/proxy/soak
harnesses are described in the [release-acceptance guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/release-acceptance.md).
They use controlled local pages and dedicated caches/profiles. Browser launches
remain opt-in outside the explicitly configured native CI jobs.
Google demo tests use fake
sessions; passing them does not imply that Google allowed a live search.

Strict expected failures report known defects separately from passing tests.
An unexpected pass fails the run so its marker must be revisited after a fix.
There are currently no expected-failure markers: the previously identified issue
families and the additional final-review fixes have passing regressions. A green
local suite still does not certify unavailable native targets or every production
deployment; see the [final review](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/final-production-review.md) and
[acceptance guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/release-acceptance.md).

For a focused documentation/demo check:

```bash
.venv/bin/python -m pytest tests/test_examples.py tests/test_demo_local.py tests/test_demo_google.py -q
```

README checks compile/import Python examples, validate known API call signatures
and local links, and exercise selected recipes without launching browsers.

All maintained Python definitions have Google-style docstrings and annotated
signatures. Ruff enforces import ordering, unused-import detection, documentation
style, and annotation coverage. The structural audit additionally rejects imports
inside functions and enforces the public-`PathInput`/internal-`Path` architecture,
including a guard against stringifying and reparsing paths. Module-level platform
guards and `TYPE_CHECKING` imports remain intentional. See the [contributor
API-quality guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/api-quality.md).

Docstring examples use singular `Example:` with Python `>>>` and `...` prompts.
They are syntax-checked and checked against resolvable API signatures. The added
runtime suite executes 38 distinct docstrings verbatim with controlled fixtures,
in addition to existing pure examples and README recipe checks. See the guide for
required setup and execution limits.

Mypy checks the complete package, both executable demos, their shared support
module, the quick-start program, and all maintained release/acceptance scripts
under `src/` and `scripts/`. An additional installed-wheel consumer gate verifies
public asynchronous and path return types and requires deliberate API misuse to
fail type checking. Dynamic WebDriver/JavaScript data, extension arguments, and
test doubles still use `Any` only where their shape is intentionally open.
Runtime/resource metadata lives in `pyproject.toml`.
Distribution tests build a wheel and sdist, rebuild the wheel from the sdist, and
verify imports/resources outside the checkout. Local builds do not publish a
release. Follow the configured gated release workflow and verify its external
settings before publishing.

## Further documentation

- [Pre-deployment review](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/pre-deployment-review.md): latest concurrency/deadline fixes, current candidate verification, README reconciliation, and remaining deployment gates.
- [Earlier production review](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/final-production-review.md): preceding local and multi-environment evidence, path/input/profile contracts, and packaging checks.
- [Release acceptance](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/release-acceptance.md): real transport, installed-wheel/browser, crash/proxy/soak, typing, docstring and CI gates, with current validation evidence.
- [Known-issue fixes](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/known-issue-fixes.md): the preceding 10 fixes, passing regressions and historical validation evidence.
- [Feature-testing expansion](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/feature-testing.md): historical coverage expansion, original defect findings, real local transport/proxy tests and unavailable checks.
- [Production-readiness review](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/production-readiness.md): earlier hardening changes, security defaults, validation evidence, and remaining release gates.
- [Demo overview](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo.md): choose the local HTML tour or real-world Google demo.
- [Local HTML demo](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo-local.md): CLI policies, chapters, outputs, and safety boundaries.
- [Google website demo](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/demo-google.md): visible browser, optional search, captures, and live-site limitations.
- [Named-demo validation](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/baselines/demo-google-validation.json): offline-test evidence, live local/homepage passes, and the challenged Google search.
- [Breaking-change guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/legacy-removal.md): removed features, replacement APIs, and current-only support boundaries.
- [API-quality guide](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/api-quality.md): import policy, docstring convention, examples, annotation coverage, and verification limits.
- [Modern usage notes](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/modernization-guide.md): cache internals, ownership, deadlines, and compatibility changes.
- [Original 12-step second-pass review](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/original-12-step-second-pass.md): implementation audit and remaining verification gaps.
- [Driver-management testing](https://github.com/AresJef/Aselenium/blob/v2.0.0/docs/driver-management-testing.md): test organization and offline isolation.
- [Local demo source](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_local.py), [Google demo source](https://github.com/AresJef/Aselenium/blob/v2.0.0/src/demo_google.py), and [package source](https://github.com/AresJef/Aselenium/tree/v2.0.0/src/aselenium): executable examples and exact API implementation.

## License and acknowledgements

Aselenium is distributed under the [Apache License 2.0](https://github.com/AresJef/Aselenium/blob/v2.0.0/LICENSE).
The accompanying [NOTICE](https://github.com/AresJef/Aselenium/blob/v2.0.0/NOTICE)
preserves the attribution referenced by inherited source headers.

It uses [aiohttp](https://github.com/aio-libs/aiohttp),
[psutil](https://github.com/giampaolo/psutil), and
[orjson](https://github.com/ijl/orjson), and draws inspiration and adapted code
from [arsenic](https://github.com/HENNGE/arsenic),
[Selenium](https://github.com/SeleniumHQ/selenium), and
[webdriver-manager](https://github.com/SergeyPirogov/webdriver_manager).
Original source-file license and attribution notices are retained.
