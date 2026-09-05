# Choose a demo

Aselenium has two demos with deliberately different purposes:

| Entry point | Website | Browser mode | Use it for |
| --- | --- | --- | --- |
| [`src/demo_local.py`](../src/demo_local.py) | Bundled HTML served at `127.0.0.1` | Headless by default; `--headed` to watch | Repeatable feature coverage: driver management, elements, frames, cookies, actions, outputs, concurrency, and cancellation. |
| [`src/demo_google.py`](../src/demo_google.py) | Real [Google.com](https://www.google.com/) | Visible by default; `--headless` to hide | Real website navigation, optional search, explicit waits, screenshots, and remote-page diagnostics. |

Both use real WebDriver/browser processes. The local tour is not a mock browser;
the Google example does not substitute local HTML for Google.

## Run the local HTML tour

From the checkout, using the project's interpreter on macOS/Linux:

```bash
.venv/bin/python src/demo_local.py list
.venv/bin/python src/demo_local.py run --allow-download
.venv/bin/python src/demo_local.py run --headed
```

See the [local HTML guide](demo-local.md) for the complete chapter list and
provisioning policies.

## Run the Google website demo

```bash
.venv/bin/python src/demo_google.py run --allow-download
.venv/bin/python src/demo_google.py run --query "Aselenium Python"
.venv/bin/python src/demo_google.py run --headless --hold-seconds 0
```

With no `--query`, the Google demo opens the homepage, checks the search field,
takes a screenshot, and leaves the browser visible for five seconds before
closing it. With a query, it performs one search and captures the result page.
See the [Google guide](demo-google.md) for browser choices and consent/challenge
handling. Normal results are not guaranteed by an external website.

## Shared setup and naming

- With no arguments, each entry point prints help without launching a browser.
- `--allow-download` allows driver vendor requests; omit it once `.demo-cache`
  contains a compatible driver. The Google website still needs Internet access.
- Reports and screenshots go to unique `local-...` or `google-...` subdirectories
  beneath `.demo-output`. Override both parents with `--cache-dir`/`--output-dir`.
- Browsers use fresh/disposable profiles, not your logged-in personal profile.
- On Windows use `.venv\Scripts\python.exe` instead, or activate your environment.
- Use the two named entry points; the former `src/demo.py` launcher is removed.
  Shared provisioning code lives in `src/_demo_support.py`; importing it does not
  run either demo. See [removed compatibility paths](legacy-removal.md).
- The historical [local validation record](baselines/demo-validation.json) retains
  the filename/hash used when those runs were measured. It is not a Google test.
- The [renaming and Google validation record](baselines/demo-google-validation.json)
  records the new local entry point's full Chrome pass, a live Google homepage pass,
  and a single search stopped by Google's CAPTCHA. A normal live results page was
  not validated.

The demo scripts and fixtures are maintained in the repository checkout. The
production wheel and source distribution intentionally contain only the package
and its required metadata/resources, so obtain the checkout to run the demos.
