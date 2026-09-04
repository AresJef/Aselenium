# Current-only package: removed compatibility paths

Aselenium **2.0.0 is a breaking release**. Review this guide before updating
applications from the 1.x series.

## What was removed

| Removed feature or file | Current replacement |
| --- | --- |
| `aselenium.manager.migration`, `import_legacy_cache()`, and the `legacy-cache` extra | Provision supported artifacts into the SQLite v2 cache. No Feather import is provided. |
| pandas/pyarrow optional dependencies and the migration-only CI job | The package has only its current runtime dependencies; the normal CI matrix covers the supported implementation. |
| The former `src/demo.py` launcher and its manifest/test references | Use `src/demo_local.py` or `src/demo_google.py`. |
| Unreferenced `src/test_files/` CAPTCHA image and two bundled third-party Firefox add-ons | The local tour uses the maintained `src/demo_assets/` fixtures and minimal example WebExtension. |
| Pre-CfT ChromeDriver URLs, old Mac M1 archive names, and split Chrome 113/114 browser/driver resolution | Chrome and Chromium require 115 or newer; normal matching and exact CfT pairs use the CfT release pipeline. |
| Firefox `install.rdf` parsing, the manifest `applications` alias, and `FirefoxAddon.unpack` | WebExtensions with `manifest.json`, `manifest_version` 2 or 3, and optional `browser_specific_settings.gecko.id`. A missing ID can be supplied by the driver. |
| `Element.visible`, `Element.viewable`, and the corresponding wait conditions | Use `in_viewport` for geometry or `unobscured` for center-point hit testing. These are deliberately different checks, not renamed equivalents. |
| Hybrid `Element.get_attribute()` and its bundled Selenium/IE JavaScript atom | Choose `get_attribute_dom(name)` for the current DOM attribute or `get_property(name)` for a JavaScript property. |
| The old `javascript/is_viewable.py` atom | Explicit geometry/hit-test scripts; no bundled old-browser/XPath compatibility engine. |
| Numeric JSON Wire error codes, JSON-string/nested error-envelope fallbacks, top-level new-session IDs, and raw-PNG response fallback | W3C JSON responses, nested `value.sessionId`, string error codes, and base64 PNG data inside `value`. |
| Redundant `sessionId`/element/shadow IDs and send-key `value` arrays in request bodies | IDs are encoded in command URLs; send keys/uploads use W3C `text` parameters. |
| JSON Wire `/execute_async`, old mobile orientation/network/context routes, Chrome-app launch, and unused delete-session/network declarations | W3C `/execute/async`, current browser-specific commands, and the existing session/network reset methods. Unsupported old routes are no longer exposed. |
| `Proxy.ftp_proxy`, the `ftp_proxy` constructor argument, and positional `Proxy(...)` construction | Use keyword-only HTTP/HTTPS/SOCKS/PAC/bypass options. Keyword-only arguments prevent an old FTP positional argument from silently becoming an HTTP proxy. |
| IME-only, element-not-visible/not-selectable, and old element-coordinate exceptions | Current W3C errors such as `ElementNotInteractableError`, `ElementClickInterceptedError`, and `InvalidCoordinatesError`. |
| The misspelled private `_request_reponse_json()` helper and unused singleton registry | `_request_response_json()` and independent SQLite-backed managers. No compatibility aliases remain for these removed members. |

`SessionDataError` remains a package exception but no longer inherits the unrelated
`UnicodeDecodeError` constructor contract. Catch the package exception for malformed
protocol data. Error parsing uses the HTTP status, so successful JavaScript objects
containing `error`, `message`, or `status` fields remain ordinary application data.

## Update element checks

```python
from aselenium import Session


async def inspect_input(session: Session):
    if not await session.wait_until_element("unobscured", "#name", timeout=5):
        raise TimeoutError("Input did not become reachable by a center-point hit test")
    field = await session.find_element("#name")
    if field is None:
        raise LookupError("The page replaced the input")
    return {
        "value": await field.get_property("value"),
        "placeholder": await field.get_attribute_dom("placeholder"),
        "in_viewport": await field.in_viewport,
        "unobscured": await field.unobscured,
    }
```

The same `in_viewport` and `unobscured` conditions are accepted by
`Element.wait_until()` and session/element/shadow `wait_until_element()` and
`wait_until_elements()`. Removed names fail as invalid conditions, rather than
silently changing their meaning. `scroll_into_view()` now verifies viewport
intersection after scrolling.

`in_viewport` does not assert CSS visibility. An overlay can cover a rectangle
that is still in the viewport. `unobscured` tests the clipped rectangle's center;
it does not promise a future click will succeed. Use explicit style checks or
an application-specific predicate where needed.

## Browser and cache boundaries

Chrome's release-process boundary is documented in Google's
[ChromeDriver version-selection guide](https://developer.chrome.com/docs/chromedriver/downloads/version-selection).
The 115+ requirement applies to Chrome/Chromium and their CfT path, **not** an
invented minimum for Edge or Firefox. Edge retains its own vendor resolution;
Firefox retains recorded Gecko compatibility ranges, and Safari retains its
system-driver workflow. Exact pins and offline policies remain supported.

The protocol implementation targets [W3C WebDriver](https://www.w3.org/TR/webdriver2/).
Firefox manifests use
[`browser_specific_settings`](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/browser_specific_settings).
Manifest V2 is not removed merely because an older non-WebExtension format was
removed; supported WebExtension versions remain explicit in the parser.

Existing SQLite v2 caches are reusable. No user cache, old Feather file, browser
profile, or installed dependency is deleted as part of this source cleanup.
Old cache artifacts are not imported; provision again with the current manager
when needed. Corruption preservation, integrity checks, leases, pins, and scoped
SQLite recovery remain enabled. Python 3.10+ and all five browser facades remain.

## Source and distribution checks

Tests explicitly reject removed formats/APIs and confirm current replacements.
Distribution tests inspect both wheels and the source archive to ensure deleted
implementation modules and the old demo entry point do not ship. The source
checkout's old `setup.cfg` is also absent; setuptools may generate an egg-info-only
`setup.cfg` inside an sdist as build metadata, not legacy project configuration.
The source archive retains dated audit reports as historical evidence, not as executable
compatibility features; older reports describing migration or visibility behavior
are superseded by this guide. Original license notices remain intact.

Run from the checkout with the configured development environment:

```bash
python -m pytest --asyncio-debug
python -m ruff check src tests scripts
python -m mypy
```

The [local demo](demo-local.md) is the repeatable native-browser regression tour.
The [Google demo](demo-google.md) is a live-site example; a homepage pass does not
prove that Google allowed search or that every supported backend was validated.

## Validation of this cleanup

On 2026-09-04, the full suite passed **974 tests** with asyncio debugging enabled
on Python 3.11.15. Ruff passed, and mypy passed its configured eleven-module scope.
The suite builds and inspects a wheel and sdist, rebuilds a wheel from the sdist,
and checks installed-wheel imports outside the checkout. Both Chrome and Edge
completed all **15 local-demo stages**, with no failures or skips, using Python
3.13.12 on macOS ARM64, fresh temporary profiles, and cached drivers.

See the [validation record](baselines/legacy-removal-validation.json) for exact
versions, commands, reports, and limitations. Firefox, Safari, other operating
systems, vendor downloads, and the Google live-site demo were not rerun in this
cleanup. A Python 3.13 full test-suite run is not claimed.

Removed source files, stale bytecode, obsolete test assets, and old build
candidates are recoverable under
`/private/tmp/aselenium-legacy-removal.zdqbBy/`. This is temporary system storage,
not a permanent archive; retain a separate copy if recovery may be needed later.
