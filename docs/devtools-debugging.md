# DevTools Debugging

## Role

Chrome DevTools inspection is a diagnostic sidecar for this project. The implementation uses Playwright `connect_over_cdp(...)` plus [DevToolsInspector](/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/src/browser/devtools_inspector.py) to:

- trace receipt search requests
- inspect console and page errors
- confirm where the PDF or blob is generated
- capture high-value failure context

It is not the default batch execution engine, and it does not require `chrome-devtools-mcp`.

## Attach To An Existing Logged-In Browser

1. Start Chrome with remote debugging enabled and a reusable profile.
2. Log in to the customs site in that Chrome window.
3. Open the receipt workflow manually until the page that searches or prints receipts is visible.
4. Point this project at that browser with one of:
   - `--cdp-url http://127.0.0.1:9222`
   - `--cdp-url ws://127.0.0.1:9222/devtools/browser/<id>`
   - `ETRACKING_BROWSER_CDP_URL=http://127.0.0.1:9222`
   - `login.browser.cdp_url` in `config/settings.local.yaml`
5. Run the normal command. Example:

```bash
./.venv/bin/python -m src.main --cdp-url http://127.0.0.1:9222 --order-id A017X680406286
```

On macOS, one way to start Chrome is:

```bash
open -a "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir=/tmp/etracking-chrome-debug
```

If local proxy environment variables interfere with the HTTP endpoint, prefer the `webSocketDebuggerUrl` returned by:

```bash
curl --noproxy '*' http://127.0.0.1:9222/json/version
```

and run the attach command with proxy variables unset for that invocation.

Attach mode reuses an existing tab when possible. If the current tab is already on the receipt page, the workflow stays there. If not, it tries to continue from the attached page before falling back to the configured login URL.

When the run exits, the project disconnects from the CDP session but does not intentionally close your existing Chrome tab or overwrite `runtime/session/state.json`.

## What Gets Captured

The attached page is instrumented with [DevToolsInspector](/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/src/browser/devtools_inspector.py), which records:

- current URL
- XHR/fetch requests containing `search`, `receipt`, `print`, `pdf`
- blob/document requests
- console warnings and errors
- page runtime errors

## Debugging A Failed Receipt

When a run fails, the project stores:

- current URL
- console errors
- interesting network requests
- screenshot path

These fields are written into the per-order result metadata and appear in the machine-readable reports under `runtime/reports/<job_id>/`.

## Current Preferred Artifact Path

As of March 9, 2026, the live receipt print flow has confirmed a stable shape:

- clicking the matching receipt-row print icon opens a new browser tab
- that tab resolves into a Chrome PDF viewer
- the viewer URL is a `blob:` URL under `https://e-tracking.customs.go.th`

The preferred acquisition order is therefore:

1. capture the popup/new tab
2. wait for the viewer to resolve to `blob:` or expose a blob-backed embed/iframe/object
3. fetch the blob bytes directly inside that page context
4. only if blob capture fails, try the viewer download control path

## What To Look For

- Did the search request return the expected receipt row?
- Did clicking the printer action open a new page, navigate to a blob URL, or emit a PDF-related request?
- Did the browser viewer expose a blob URL in `embed`, `iframe`, `object`, or the page URL itself?
- Did the page raise console or runtime errors before PDF creation?

## PDF Truth Checks

Do not trust a visible viewer alone. A run is only successful when the saved artifact:

- exists
- has a real `%PDF` header
- is above the minimum byte threshold
- matches the requested order id

Screenshot fallback remains failure or human review, never success.
