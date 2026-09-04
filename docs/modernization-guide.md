# Using the modernization candidate

Aselenium 2.0.0 targets Python 3.10+ and contains the current SQLite/W3C
implementation. Existing 1.x users should review the breaking-change guide
before upgrading.
The public Chrome, Chromium, Edge, Firefox and Safari facades remain available.

For current breaking changes, read the [current-only package guide](legacy-removal.md).
The earlier audit is the [original 12-step second-pass review](original-12-step-second-pass.md).
Its compatibility notes cover copied option dictionaries, queue-inclusive command
timeouts, failed-cleanup restart behavior, and atomic PNG/PDF output.

## Provisioning and cache policies

```python
import asyncio
from pathlib import Path
from aselenium import ChromeDriverManager

async def main():
    cache = Path("./browser-cache")
    cache.mkdir(exist_ok=True)
    manager = ChromeDriverManager(directory=str(cache))
    # Discover the installed browser; resolve its compatible driver build.
    result = await manager.install_result(version="build")
    print(result.driver_version, result.driver_location)
    # Same platform and cache, strictly no vendor requests.
    cached = await manager.install_result(policy="offline")
    assert cached.driver_location == result.driver_location

asyncio.run(main())
```

`install()` still returns a path string. `install_result()` returns immutable
request/result snapshots; use those in concurrent code. Manager properties and
`last_result` describe the last successful call, not a particular caller.

Policies are `exact`, `compatible-build`, `compatible-major`,
`latest-compatible`, `cached-compatible`, and `offline`. Full numeric pins are
exact, not aliases for the latest patch. A Chromium pin has four components; a
Gecko pin has three. Ambiguous two-component Chromium pins and decorated numeric
selectors are rejected. Existing named selectors remain supported.

Standalone installation can prewarm a pin that does not match the installed
browser. Session acquisition validates the pair before starting it. Firefox
resolution checks both ends of its recorded compatibility range and fails closed
for unknown future driver releases. Chrome-for-Testing verifies each asset against
the official version manifest; a platform is supported only if that version
actually publishes the relevant asset. Unsupported Linux/Windows ARM combinations
are not silently treated as x64.

Exact installations pin the indexed driver and, when applicable, browser binary.
Pins are persistent. Use `await manager.pin("152.0.7977.82", pinned=False)` to
allow eviction again. Cache limits are soft when pins or live acquisition leases
protect entries. `SessionContext` releases its leases after successful teardown;
dead-process leases can be reclaimed. External consumers of a raw path returned
by `install()` are not tracked—pin their artifact before using an eviction limit.

## SQLite v2 and recovery

The new cache is `<directory>/.aselenium/v2/index.sqlite3`, with immutable,
platform-specific artifact folders alongside it. Keys include browser product,
version, OS, architecture and artifact type. Connections are short-lived and
transactions are bounded by a busy timeout. Cross-process kernel locks coordinate
downloads and publication. Kernel locks are released if a process dies.

Artifacts are extracted in private staging folders, validated, then renamed into
place. A manifest supports reindexing after a process dies between publication
and index commit. Exact lookups recover a matching orphan publication. For a
broader recovery scan, use the appropriately scoped file manager's `recover()`.
`clean_staging()` removes only marked staging owned by a provably dead process;
unmarked, malformed and live staging is preserved. These synchronous maintenance
operations should be called using `asyncio.to_thread()` from async applications.

Executable SHA-256 is checked before a cached executable is returned. This detects
local executable changes; it is **not a vendor signature**, a signed provenance
claim, or verification of every supporting file in a browser bundle. A corrupt
entry or unsupported database schema is preserved and reported, not silently
overwritten. Stop its consumers, inspect it, and move the exact damaged artifact
aside before reprovisioning. Do not delete an entire cache as a routine remedy.

The supported cache assumption is a **private local filesystem**. NFS/SMB,
multi-host caches, hostile concurrent writers and hardware power-loss durability
are not certified. Lock files intentionally remain: deleting them can split the
lock identity held by existing waiters.

## Cache format

SQLite v2 is the only supported format. Feather import and its optional dependency
extra have been removed. Existing files outside the v2 cache are preserved, not
read or imported. Provision supported artifacts with the current driver manager
instead. See the [breaking-change guide](legacy-removal.md).

## Downloads, errors and cancellation

Each installation owns one reusable aiohttp client. TLS verification remains
enabled; an explicit HTTP proxy is supported, and environment proxy discovery is
not enabled implicitly. Request bodies, query strings and proxy credentials are
not written to command logs. Applications configure logging; the library uses a
NullHandler rather than installing a console handler.

Downloads stream through temporary files in 256 KiB chunks. Download and metadata
limits are 2 GiB and 8 MiB respectively. Extraction has separate entry/size/path
limits. Concurrent downloads and blocking filesystem workers each have a limit
of four per event loop. Completed extraction discards its compressed input.

Vendor GETs retry transient connection/payload failures and HTTP 429, 500, 502,
503 and 504 at most three times, under one request deadline. Retry-After delays
are capped at 30 seconds and at the remaining deadline. Authentication/permission
errors and TLS errors are not mislabeled as cache misses. A 404 remains a missing
vendor artifact. Original causes are retained in raised exceptions.

Cancelling extraction waits for the owned blocking worker to finish before
releasing its resources. This deliberately favors safe ownership over instant
cancellation of an operation Python cannot forcibly interrupt. A hung kernel I/O
operation is not made interruptible by moving it to a thread.

WebDriver command mutations are not automatically replayed by Aselenium after
an ambiguous transport failure. Only same-origin GET redirects are followed,
with a finite redirect budget. HTTP errors through 5xx are normalized; malformed
successful envelopes fail explicitly. Ordinary JavaScript results containing
fields named `error` or `message` are preserved.

## Isolated sessions and waits

`driver.acquire()` snapshots configuration. Later edits to `driver.options`
affect later acquisitions, not an existing context. Configured profiles receive
separate physical clones; closing one session does not delete another's profile.
The original user profile is not modified. Snapshotting an explicitly configured
profile copies files synchronously because `acquire()` is a synchronous API.
For large profiles, acquire from a worker or prepare smaller dedicated profiles.

```python
import asyncio
from aselenium import Chrome

async def main():
    browser = Chrome()
    browser.options.add_arguments("--headless=new")
    async with browser.acquire("build") as session:
        await session.load("data:text/html,<title>Local</title><input id='name'>")
        await session.set_timeouts(implicit=0)
        element = await session.find_1st_element("#missing", "#name")
        await element.send("Aselenium")
        async with session.transaction():
            assert await session.wait_until_title("equals", "Local", timeout=1)

asyncio.run(main())
```

Commands are serialized on one connection. Use `session.transaction()` to own a
related multi-command sequence, such as switching a window and interacting with
it. This does not make independently scheduled sequences on the same browser state
commutative; separate sessions remain the simplest concurrency boundary.

Repeated starts share a running context; a closed context cannot be restarted.
Use a new acquisition. `quit()` is idempotent after successful cleanup and shields
owned teardown from cancellation. Failed teardown retains handles for a retry.
Explicit `--user-data-dir` sharing is rejected between active sessions in the same
process. Cross-process user-profile sharing is not supported; prefer `set_profile()`
clones. Port allocation is advisory, not a guarantee against another local process
binding the same port before the driver starts.

Waits share a monotonic total budget with their WebDriver requests. `timeout=0`
or `None` means one immediate observation. First-match methods check every locator
once even when implicit timeout is zero. Frame waits resolve the selector again
on each attempt. Edge-scrolling helpers stop after three unchanged observations,
1,000 iterations, or a 30-second polling budget instead of looping forever.

Use explicit DOM observations; the old `visible`, `viewable`, and hybrid
`get_attribute()` APIs are removed:

- `element.text`: WebDriver rendered text; `element.dom_text`: raw textContent.
- `element.get_attribute_dom(name)`: DOM attribute; `get_property(name)`: property.
- `element.in_viewport`: nonempty rectangle intersects the viewport.
- `element.unobscured`: center-point hit testing, not a guarantee that a later click succeeds.
- `session.wait_for(async_predicate, timeout=...)`: reusable custom polling.

Mutable `Timeouts` and options objects are intentionally unhashable; timeout
equality uses consistent units. Manager/service/command deadlines must be finite
and positive; polling waits permit zero. Options/proxy repr output is redacted.
Shadow-root hashing is usable. `submit()` awaits its script. Action
chains clear dispatched input and can be reused; they do not replay failed input.
Firefox add-ons require WebExtension manifests (version 2 or 3). Use
`browser_specific_settings.gecko.id`; a driver-returned ID replaces an absent
manifest ID. The `applications` key and RDF manifests are rejected.

## Verification commands

```bash
python -m pip install -r requirements-dev.txt
python -m pytest --asyncio-debug
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python scripts/check_api_quality.py
python -m mypy
python -m pip check
python scripts/benchmark_manager.py
python scripts/benchmark_download.py
python -m build --no-isolation
python -m twine check --strict dist/*
```

The default tests forbid real network requests and installed-browser launches.
Live smoke is a separate opt-in command; its cache and profiles are disposable:

```bash
python scripts/smoke_browser.py --browser chrome \
  --binary '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  --allow-download
```

Dated audit reports record their original versions and unverified matrix cells;
see the current-only guide for subsequent removals. The typing gate now covers
fourteen infrastructure/validation modules. All maintained Python signatures are
annotated, but the entire package is not claimed to pass strict mypy. The
[API-quality guide](api-quality.md) records the import/docstring conventions,
example checks, and the distinction between coverage and type correctness.
