# Etracking Entry Flow Correction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Correct the live flow assumptions for `https://e-tracking.customs.go.th/ETS/` and make the project reliably reach search results and the print trigger path from `ERVQ1020`, while keeping PDF acquisition strategy explicit and evidence-driven.

**Architecture:** Treat the ETS-to-ERV transition, taxpayer validation, and search preparation on `ERVQ1020` as one bounded state machine before any PDF capture is attempted. Split the design into two layers: an Excel preprocessing layer that produces normalized order ids, and a browser execution layer that consumes those order ids one by one. Keep final PDF extraction strategy explicit until network evidence confirms whether the site returns a direct PDF, a blob, or a base64 payload.

**Tech Stack:** Python 3.12, Playwright, real Chrome channel, pytest, live browser smoke checks, structured logging

---

## Scope Boundary

This document tracks only the live flow confirmed by the user on March 9, 2026 through search results and print trigger entry:

1. Open `https://e-tracking.customs.go.th/ETS/`
2. Wait for the terms modal
3. Check the checkbox beside `ยอมรับเงื่อนไขการใช้งาน`
4. Click the green `ตกลง` button
5. Reach the home page shown in screenshot 2
6. Do not enter username or password
7. Click the large e-payment tile at bottom-right
8. Enter `https://e-tracking.customs.go.th/ERV/MAIN`
9. Click the second left-menu item: `พิมพ์ใบเสร็จรับเงิน กศก.123`
10. Reach `https://e-tracking.customs.go.th/ERV/ERVQ1020`
11. Select `กระทำการแทน (สำหรับนิติบุคคล)`
12. Select `ผู้นำของเข้า/ผู้ส่งของออก`
13. Fill tax-id inputs with `0105564083643` and `1`
14. Click `ตรวจสอบ`
15. Wait for the page to expand with the next form section
16. Fill `หมายเลขบัตรผู้พิมพ์` with `3101400478778`
17. Fill `หมายเลขโทรศัพท์ (มือถือ) ผู้พิมพ์` with `0927271000`
18. Fill `เลขที่ใบขนสินค้า` with an order id sourced from a preprocessed Excel input
19. Click `ค้นหา`
20. Wait for search results
21. Click the rightmost print icon on the matching result row
22. Enter the print page or print-artifact flow

Explicitly out of scope for this document:

- final PDF extraction/storage mechanism after the print trigger
- long-term support for non-Excel order sources

Those belong to the next correction pass after the search and print-trigger flow are stable.

## Current Verified Facts

The following was tested live on March 9, 2026 with real Chrome and Playwright:

- Step 1 works: the ETS landing page loads.
- Step 2 works: the terms modal is present.
- Step 3 works: checking `input#agree` makes the green confirm button visible.
- Step 4 works: clicking `button#UPDETL0050` exits the modal and lands on the home page.
- Step 5 is confirmed as a real page state:
  - URL remains `https://e-tracking.customs.go.th/ETS/`
  - username field `input#usrCde` exists
  - password field `input#pwd` exists
  - the bottom-right e-payment tile `img#ePayImg` is visible
- The e-payment tile carries `onclick="toPageERV();"`
- `typeof toPageERV === "function"`
- Step 8 is confirmed as a reachable target:
  - controlled invocation of `toPageERV()` navigates to `https://e-tracking.customs.go.th/ERV/MAIN`
- Step 9 is confirmed:
  - the second left-menu item can be located by text `พิมพ์ใบเสร็จรับเงิน กศก.123`
- Step 10 is confirmed:
  - clicking that menu item navigates to `https://e-tracking.customs.go.th/ERV/ERVQ1020`
  - the resulting page content matches the screenshot provided by the user
- Steps 11 and 12 are confirmed:
  - `กระทำการแทน (สำหรับนิติบุคคล)` can be selected by visible text
  - `ผู้นำของเข้า/ผู้ส่งของออก` can be selected by visible text
- Step 13 is confirmed:
  - the first visible text input accepts `0105564083643`
  - the second visible text input accepts `1`
- Step 14 is confirmed:
  - clicking `ตรวจสอบ` triggers the taxpayer validation request sequence
- Step 15 is confirmed:
  - the page expands to show the next form section
  - new fields including `หมายเลขบัตรผู้พิมพ์ :`, `หมายเลขโทรศัพท์ (มือถือ) ผู้พิมพ์ :`, and `เลขที่ใบขนสินค้า` become visible
  - the second tax input is normalized from `1` to `000001`
  - both validated tax inputs become disabled after expansion

Most important live finding:

- A normal Playwright `.click()` on `img#ePayImg` did **not** navigate.
- That click only requested the active image asset:
  - `https://e-tracking.customs.go.th/ETS/img/icon_ePayment_active.png`
- User-provided empirical guidance says a second click on the same tile is materially more stable than a single click.
- A live probe on March 9, 2026 confirmed that behavior:
  - first click stayed on ETS
  - second click navigated to `https://e-tracking.customs.go.th/ERV/MAIN`
- A direct JavaScript invocation of `toPageERV()` **did** navigate to:
  - `https://e-tracking.customs.go.th/ERV/MAIN`
- After entering `ERV/MAIN`, a text-based click on `พิมพ์ใบเสร็จรับเงิน กศก.123` **did** navigate to:
  - `https://e-tracking.customs.go.th/ERV/ERVQ1020`
- On `ERVQ1020`, the taxpayer validation button **did** expand the page after the requested selections and inputs were provided.

This means the user-corrected flow is directionally right, and the browser can now be driven all the way to the expanded taxpayer-validated form state. The remaining automation problem is now narrow: the ETS home-page tile interaction is still the unstable point, while the ERV-side steps tested so far are behaving deterministically.

## User-Confirmed Next Steps Pending Live Validation

The following steps have been confirmed by the user but are not yet marked as browser-validated in this document:

- fill `หมายเลขบัตรผู้พิมพ์` with `3101400478778`
- fill `หมายเลขโทรศัพท์ (มือถือ) ผู้พิมพ์` with `0927271000`
- fill `เลขที่ใบขนสินค้า` from an uploaded Excel-derived order source
- click `ค้นหา`
- wait up to roughly 15 seconds for delayed search results
- if the first search click does not trigger a visible search effect, retry once
- click the rightmost print icon on the matching row

These steps are now part of the implementation plan and should be validated next.

## Data Source Decision

The user's Excel-preprocessing idea is correct and should be adopted.

Recommended design:

- `OrderSource` reads the current Excel file
- `normalize_order_id(raw)` cleans and normalizes each order id
- `build_order_jobs()` produces a deduplicated iterable of normalized order ids
- the browser flow consumes one normalized order id at a time

Why this is the right split:

- Excel formats can change over time
- preprocessing and DOM automation have different failure modes
- batch reruns are easier when normalized order ids are materialized before browser actions begin
- the same normalized order stream can later support retries, reports, and alternate file sources

Initial scope decision:

- support Excel only in phase 1
- do not yet generalize to arbitrary document parsing

## Latest Validation Evidence

Probe artifacts from March 9, 2026:

- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/entry_flow_probe/home.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/entry_flow_probe/after_click.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/entry_flow_probe/after_js.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/erv_flow_probe/home.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/erv_flow_probe/erv_main.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/erv_flow_probe/ervq1020.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/double_click_probe/after_first_click.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/double_click_probe/after_second_click.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/taxpayer_expand_probe/ervq1020_before.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/taxpayer_expand_probe/filled.png`
- `/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/runtime/logs/taxpayer_expand_probe/after_check.png`

Observed command outcome:

```text
landing_url= https://e-tracking.customs.go.th/ETS/
agree_visible= True
confirm_visible_before= False
confirm_visible_after= True
home_url= https://e-tracking.customs.go.th/ETS/
home_has_user= 1
home_has_pwd= 1
epay_visible= True
epay_onclick= toPageERV();
toPageERV_type= function
after_click_url= https://e-tracking.customs.go.th/ETS/
after_click_new_requests= ['https://e-tracking.customs.go.th/ETS/img/icon_ePayment_active.png']
after_js_url= https://e-tracking.customs.go.th/ERV/MAIN
after_js_new_requests= [
  'https://e-tracking.customs.go.th/ETS/SecurityServlet',
  'https://e-tracking.customs.go.th/ERV/MAIN',
  'https://e-tracking.customs.go.th/ERV/static/js/main.0a917f99.js',
  'https://e-tracking.customs.go.th/ERV/static/css/main.864fcd8b.css'
]
erv_main_url= https://e-tracking.customs.go.th/ERV/MAIN
target_count= 0
fallback_target_count= 1
after_menu_click_url= https://e-tracking.customs.go.th/ERV/ERVQ1020
after_first_click_url= https://e-tracking.customs.go.th/ETS/
after_first_click_requests= ['https://e-tracking.customs.go.th/ETS/img/icon_ePayment_active.png']
after_second_click_url= https://e-tracking.customs.go.th/ERV/MAIN
after_second_click_requests= [
  'https://e-tracking.customs.go.th/ETS/img/icon_certificate_active.png',
  'https://e-tracking.customs.go.th/ETS/SecurityServlet',
  'https://e-tracking.customs.go.th/ERV/MAIN',
  'https://e-tracking.customs.go.th/ERV/static/js/main.0a917f99.js',
  'https://e-tracking.customs.go.th/ERV/static/css/main.864fcd8b.css',
  'https://e-tracking.customs.go.th/ERV/static/media/page_bg.423f87436c71fbe4cd04.png'
]
after_check_url= https://e-tracking.customs.go.th/ERV/ERVQ1020
after_check_requests= [
  'https://webservice-api.customs.go.th/customs-org/api/oauth-provider/oauth2/token',
  'https://webservice-api.customs.go.th/customs-org/api/ERVAPI/v1/ErvService/insertAccessLogInfo',
  'https://webservice-api.customs.go.th/customs-org/api/ERVAPI/v1/ErvService/insertLogRequest',
  'https://webservice-api.customs.go.th/customs-org/api/ERVAPI/v1/CASService/validateCustomsRegisterERV',
  'https://webservice-api.customs.go.th/customs-org/api/ERVAPI/v1/ErvService/updateAccessLogInfo',
  'https://webservice-api.customs.go.th/customs-org/api/ERVAPI/v1/ErvService/updateLogResponse'
]
text_values_after= [
  {'index': 0, 'value': '0105564083643', 'visible': True, 'disabled': True},
  {'index': 1, 'value': '000001', 'visible': True, 'disabled': True}
]
has_printer_card_label= 1
has_phone_label= 1
has_order_label= 1
```

## March 9 PDF Path Decision

Additional live evidence from March 9, 2026 confirms the post-print path:

- clicking the matching result-row print icon shows an in-page loading dialog first
- the print action then opens a new browser tab
- the new tab lands on a Chrome PDF viewer backed by a `blob:` URL under `https://e-tracking.customs.go.th`
- the visible viewer URL shape is:
  - `blob:https://e-tracking.customs.go.th/<uuid>`

This narrows the next implementation choice materially. The user approved the following acquisition order:

1. primary: capture the popup/new tab deterministically and fetch the PDF bytes from the `blob:` URL in that page context
2. fallback: if blob capture fails, use the viewer download control path
3. defer deeper network reverse-engineering unless popup/blob evidence stops being reliable

This means the project should no longer treat direct download or `page.pdf()` export as the primary strategy for this phase. Those remain fallback mechanisms only.

## Acceptance Criteria For This First-Part Correction

This phase is complete only when all of the following are true:

- the automation can reliably accept the terms modal
- the automation can reliably detect the post-consent home page
- the automation can reliably trigger the e-payment handoff
- the automation can reliably reach `ERV/MAIN`
- the automation can reliably select the second left-menu entry and reach `ERVQ1020`
- the automation can reliably select the two taxpayer role/company radio options
- the automation can reliably submit the tax-id validation step
- the automation can reliably detect the expanded form state after validation
- the automation can reliably fill printer-card and phone fields
- the automation can reliably consume one normalized order id from the Excel preprocessing layer
- the automation can reliably trigger search and wait for a delayed result set
- the automation can reliably activate the rightmost print icon for the matching row
- success for this phase is based on one or more of:
  - URL changes to the ERV app
  - the `SecurityServlet` plus `ERV/MAIN` request sequence appears
  - the `ERVQ1020` URL appears
  - the `พิมพ์ใบเสร็จรับเงิน กศก.123` page content appears
  - the `validateCustomsRegisterERV` request appears
  - the printer-card, phone, and order-entry labels appear
  - a result row appears for the requested order id
  - the print icon on the result row becomes actionable
- final PDF capture is not required for this phase to pass

## Recommended Implementation Direction

Recommended approach: treat the ETS-to-ERV receipt entry flow as four linked transitions plus a data-preparation layer:

Data preparation layer:
0. Excel input -> normalized order id stream

1. ETS home -> ERV home
2. ERV home -> `ERVQ1020`
3. `ERVQ1020` taxpayer-validation section -> expanded form state
4. expanded form state -> search results -> print trigger

For the `ตรวจสอบ` action, use a bounded three-attempt recovery strategy:

1. Click once on the current page
2. Poll for expansion evidence for a short window
3. If no expansion evidence appears, click a second time on the same page
4. Poll again
5. If the page still does not expand, return to the `ERVQ1020` initial state and replay this taxpayer-validation subsection once
6. Submit `ตรวจสอบ` one final time after that replay
7. If expansion evidence is still absent, fail the run instead of continuing

Why this is the right approach:

- the live site already proves the tile is semantically correct
- the direct `toPageERV()` call proves the handoff target is real
- the second left-menu item is now verified and stable enough to use as the end-point of this phase
- the taxpayer-validation section is now verified far enough to prove the next form state can be reached
- the user-provided Excel preprocessing idea cleanly separates data preparation from browser actions
- the instability remains narrowed to the ETS home tile, not the ERV-side controls tested so far
- this keeps the current fix bounded and avoids mixing the search path with premature PDF assumptions

Alternatives considered:

1. Keep only image-click automation
   - Too weak. Live evidence already shows the click can toggle image state without handoff.
2. Skip the home page entirely and hardcode ERV URLs
   - Rejected. This bypasses the real site transition and may break session assumptions.
3. Model the handoff with fallback behavior
   - Recommended. Try semantic click first, wait for proof, click the tile a second time if still on ETS, then use validated page-side invocation only when both real clicks did not cause handoff and the page still exposes `toPageERV()`.
4. Repeatedly hammer the taxpayer validation button
   - Rejected. More than two submissions risks duplicate validation calls and a dirtier browser state without giving a clearer success signal.
5. Refresh the current page indefinitely
   - Rejected. Unbounded refresh/retry loops make failures harder to classify and can hide real state problems.
6. Read Excel and fill the browser directly in one function
   - Rejected. This couples file-shape drift, normalization bugs, and browser timing failures into one opaque step.
7. Assume the printable artifact is base64 without evidence
   - Rejected. The browser trigger should stay real, and the actual artifact source must be discovered from network evidence.

## Tasks

### Task 1: Freeze The First-Part Source Of Truth

**Files:**
- Modify: `docs/references/账号.md`
- Modify: `docs/references/e-tracking process.md`
- Maintain: `docs/plans/2026-03-09-etracking-entry-flow-correction.md`

**Step 1: Normalize the wording**

- Remove the old claim that the home page itself proves successful handoff.
- Keep the user-confirmed first-part steps exactly as the new source of truth.

**Step 2: Add the validated live findings**

- Record that `img#ePayImg` is the correct tile.
- Record that a plain Playwright click did not navigate during the March 9, 2026 probe.
- Record that `toPageERV()` did navigate to `/ERV/MAIN`.

**Step 3: Verify**

Run:

```bash
sed -n '1,260p' docs/references/账号.md
sed -n '1,260p' docs/references/e-tracking\ process.md
sed -n '1,260p' docs/plans/2026-03-09-etracking-entry-flow-correction.md
```

Expected:

- the first-part flow is consistent across all three documents

### Task 2: Create A Dedicated ETS-To-Expanded-ERVQ1020 Flow Boundary

**Files:**
- Modify: `src/support/selectors.py`
- Create or modify: `src/workflow/entry_flow.py`
- Modify: `src/session_manager.py`
- Test: `tests/unit/test_entry_flow.py`

**Step 1: Write the failing unit test**

Cover:

- terms modal detection
- confirm-button visibility after checking consent
- post-consent home detection
- ERV home detection
- second left-menu receipt entry detection
- `ERVQ1020` proof detection
- taxpayer role selection detection
- taxpayer validation success detection
- expanded form detection

**Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_entry_flow.py -q
```

Expected:

- FAIL because `entry_flow.py` or the target behavior does not exist yet

**Step 3: Implement minimal entry flow**

Add:

- `accept_terms()`
- `is_home_page()`
- `trigger_epayment_handoff()`
- `detect_erv_home()`
- `open_receipt_gsk123_page()`
- `detect_ervq1020()`
- `select_taxpayer_role()`
- `submit_taxpayer_identity()`
- `detect_expanded_form()`

Keep this code limited to the ETS-to-expanded-ERVQ1020 flow only.

**Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_entry_flow.py -q
```

Expected:

- PASS

### Task 3: Add Excel Preprocessing And Order Streaming

**Files:**
- Modify: `src/excel_reader.py`
- Create or modify: `src/workflow/order_source.py`
- Modify: `src/core/models.py`
- Test: `tests/unit/test_order_source.py`

**Step 1: Write the failing unit test**

Cover:

- reading order ids from the current Excel input
- normalizing raw values into a stable order-id format
- dropping empty rows
- deduplicating repeated order ids while preserving order

**Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_order_source.py -q
```

Expected:

- FAIL because the normalized order-source boundary does not exist yet

**Step 3: Implement minimal preprocessing**

Add:

- `normalize_order_id(raw)`
- `build_order_jobs()`
- a narrow Excel-backed `OrderSource`

Keep phase 1 scoped to Excel only.

**Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_order_source.py -q
```

Expected:

- PASS

### Task 4: Add Search Preparation And Search Execution On ERVQ1020

**Files:**
- Modify: `src/support/selectors.py`
- Create or modify: `src/workflow/search_flow.py`
- Modify: `src/session_manager.py`
- Test: `tests/unit/test_search_flow.py`

**Step 1: Write the failing unit test**

Cover:

- filling printer-card field
- filling phone field
- filling order-id field from a normalized input
- clicking `ค้นหา`
- detecting delayed search success
- detecting no-result vs no-response conditions

**Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_search_flow.py -q
```

Expected:

- FAIL because the search-specific flow boundary does not exist yet

**Step 3: Implement minimal search flow**

Add:

- `fill_printer_context()`
- `fill_order_id()`
- `submit_search()`
- `detect_search_results()`

Search retry rule:

- click `ค้นหา` once
- if no request, result change, or loading evidence appears quickly, click `ค้นหา` a second time
- once search evidence appears, stop clicking and wait up to `15` to `20` seconds for a result row or a no-result state
- if still unresolved, replay this subsection once from the expanded `ERVQ1020` form state

**Step 4: Run the test to verify it passes**

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_search_flow.py -q
```

Expected:

- PASS

### Task 5: Add A Live Smoke Test For ETS-To-Search-Results-And-Print-Trigger

**Files:**
- Modify: `tests/integration/test_live_receipt_smoke.py`
- Or create: `tests/integration/test_live_entry_flow.py`

**Step 1: Write the failing live smoke**

The test must verify only:

- consent modal accepted
- home page reached
- `ERV/MAIN` reached
- the second left-menu item is activated
- `ERVQ1020` reached
- taxpayer role/company selection applied
- taxpayer validation submitted
- expanded form state reached
- printer-card and phone fields filled
- order id filled from the normalized order stream
- search results or explicit no-result state observed
- print icon availability determined

**Step 2: Run it to verify the current failure mode**

Run:

```bash
ETRACKING_RUN_LIVE=1 ./.venv/bin/python -m pytest tests/integration/test_live_entry_flow.py -q
```

Expected:

- current behavior fails until the interaction logic is corrected

**Step 3: Implement the minimal fix**

Implementation rule:

- try semantic tile click first
- wait briefly and check for handoff proof
- if still on ETS, click the same tile a second time
- wait briefly and re-check for handoff proof
- if both clicks fail and `toPageERV()` is available, use the page-side invocation as a controlled fallback
- locate the receipt page entry by visible text, not brittle array position
- locate the taxpayer role/company options by visible text
- fill the first two visible tax-id inputs with `0105564083643` and `1`
- click `ตรวจสอบ` once, then poll `2.5` to `3` seconds for expansion evidence
- if expansion evidence is absent, click `ตรวจสอบ` a second time
- poll `3` to `4` seconds again for expansion evidence
- if expansion evidence is still absent after two same-page attempts, return to the `ERVQ1020` initial state
- replay this subsection once:
  - select `กระทำการแทน (สำหรับนิติบุคคล)`
  - select `ผู้นำของเข้า/ผู้ส่งของออก`
  - refill `0105564083643`
  - refill `1`
  - click `ตรวจสอบ` one final time
- do not allow more than three total taxpayer-validation attempts
- treat expansion as proven only when one or more of these appear:
  - `หมายเลขบัตรผู้พิมพ์ :`
  - `หมายเลขโทรศัพท์ (มือถือ) ผู้พิมพ์ :`
  - `เลขที่ใบขนสินค้า`
  - the first two tax inputs become disabled
  - the second tax input is normalized to `000001`
- record `validateCustomsRegisterERV` as supporting evidence, not sole success evidence
- if the page still does not expand after the third total attempt, stop and fail the run
- distinguish at least two failure reasons:
  - `validation_request_not_observed`
  - `validation_request_observed_but_form_not_expanded`
  - `validation_retry_exhausted_after_section_replay`
- fill printer-card with `3101400478778`
- fill phone with `0927271000`
- feed order ids from the normalized Excel-backed order source
- click `ค้นหา` once, retry once only if there is no early search evidence
- wait up to `15` to `20` seconds for a result row or explicit no-result state
- if a matching result row appears, target the rightmost print icon in that row
- capture enough page/network evidence to decide whether the print action leads to:
  - a new page
  - a blob/document viewer
  - a direct PDF response
  - a base64-bearing API payload

**Step 4: Run the live smoke again**

Run:

```bash
ETRACKING_RUN_LIVE=1 ./.venv/bin/python -m pytest tests/integration/test_live_entry_flow.py -q
```

Expected:

- PASS with a handoff into the ERV application, successful search behavior, and a verified print-trigger path

### Task 6: Inspect The Printable Artifact Path Before Locking PDF Strategy

**Files:**
- Modify: `src/browser/devtools_inspector.py`
- Modify: `docs/devtools-debugging.md`
- Test: `tests/unit/test_devtools_inspector.py`

**Step 1: Extend capture requirements**

The project must observe enough evidence to answer:

- does the print icon open a new browser page?
- does it navigate to a blob URL?
- does it request `application/pdf` directly?
- does it return JSON carrying base64 or equivalent binary payload data?

**Step 2: Implementation rule**

- keep the real print icon click as the trigger
- do not assume base64 exists before evidence is captured
- prefer a deterministic popup capture flow when the print action opens a new tab
- when the popup resolves to `blob:`, fetch the artifact bytes directly from that page context before attempting viewer UI automation
- prefer artifact acquisition order:
  - popup/blob capture from the new viewer tab
  - direct PDF response if network evidence proves it exists
  - validated base64 payload reconstruction if evidence proves it exists
  - viewer download control fallback
  - browser-export fallback only if explicitly justified later

**Step 3: Verify**

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_devtools_inspector.py -q
```

Expected:

- PASS with any new artifact-path assertions

### Task 7: Keep The Final PDF Capture Phase Explicitly Deferred

**Files:**
- Maintain: `docs/plans/2026-03-09-etracking-entry-flow-correction.md`

**Step 1: Do not mix in receipt-page work**

- Do not finalize PDF capture/storage before the print-trigger network evidence is inspected.

**Step 2: Add a handoff note for the next iteration**

The next correction document must begin from:

- print trigger reached
- artifact source identified
- final PDF capture and validation path selected

## Current Conclusion

As of March 9, 2026:

- the ETS-to-expanded-ERVQ1020 route is **mostly validated**
- steps through `ERV/MAIN`, the second left-menu item, and taxpayer validation are confirmed
- the expanded receipt-entry form state is confirmed
- the remaining validated gap on the current path is still the ETS home-page tile interaction
- the next unvalidated phase is printer/phone/order search plus print-trigger discovery
