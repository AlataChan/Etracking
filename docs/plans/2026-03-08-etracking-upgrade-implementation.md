# Etracking Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild `etracking/` from a fragile single-file browser script into a deterministic browser worker with DevTools observability, strict PDF success criteria, and a clean integration seam for OpenClaw.

**Architecture:** Keep `etracking/` as its own project boundary for now and do not use a Git worktree yet. Build a deterministic browser execution layer first, add Chrome DevTools inspection as a diagnostic sidecar, then expose a stable job/report interface that OpenClaw can call for chat, webhook, cron, and file-delivery workflows.

**Tech Stack:** Python 3.12, Playwright or Chrome/CDP adapter, Chrome DevTools inspection workflow, pytest, structured logging, optional FastAPI/CLI interface, OpenClaw as control plane

---

## Workspace Decision

- **Decision:** Do not start with a Git worktree.
- **Why:** Git worktrees isolate whole-repo branch work. They do not turn `etracking/` into an isolated subdirectory workspace. Right now `etracking/` is an untracked project boundary inside the `openclaw` workspace, so creating a worktree would duplicate the entire `openclaw` repository while still leaving `etracking/` conceptually mixed with unrelated code.
- **Near-term rule:** Treat `etracking/` as the project root for planning and implementation.
- **Later option:** After the first stable milestone, either:
  - extract `etracking/` into its own repository, or
  - keep it in this workspace but only then use a repo-level worktree if we need parallel feature branches.

## Conversation Context And Decision Log

This section records the architectural judgments already made in chat so a new session does not need to rediscover them.

### Current assessment of the legacy project

- The current implementation is functionally ambitious but structurally fragile.
- The primary problem is not the lack of browser automation options. The real problems are:
  - weak success criteria
  - brittle selectors and field indexing
  - runtime artifacts mixed into source control
  - CLI parameters not flowing through the batch path
  - almost all real logic concentrated in one oversized module
- A screenshot fallback or marker file must never be counted as a successful PDF result.

### OpenClaw role decision

- OpenClaw should be the **control plane**, not the first-phase browser execution engine.
- OpenClaw is a strong fit for:
  - chat entry points
  - webhook triggers
  - cron/scheduled runs
  - status reporting
  - file delivery
  - human-in-the-loop escalation
- OpenClaw is **not** the recommended place to put the primary receipt extraction logic in phase 1.
- The first stable version should keep browser execution deterministic and code-driven, then expose a clean seam for OpenClaw integration.

### Browser tooling decision

- Playwright remains acceptable as one execution option.
- Chrome DevTools tooling should be added, but with the correct role:
  - use it for observability
  - use it for reverse-engineering the real network/blob/PDF path
  - use it for console and DOM diagnostics
  - do not make it the default batch executor in phase 1
- `chrome-devtools-mcp` is valuable as a diagnostic sidecar, especially for:
  - attaching to an already logged-in browser
  - inspecting network requests
  - confirming where the PDF/blob is actually generated
  - capturing high-value failure context
- `awesome-chrome-devtools` is a reference list, not a production dependency.

### PinchTab reference decision

- `pinchtab` is considered a good architectural reference.
- The parts worth borrowing are:
  - stable browser interaction via snapshots/refs instead of fragile CSS-only assumptions
  - persistent browser profile/session handling
  - a separate browser worker boundary
  - a clean API surface between orchestrator and browser runtime
  - stronger debugging and observability posture
- The parts **not** to cargo-cult immediately are:
  - stealth-first complexity
  - premature engine replacement before we have corrected success criteria and result validation
- In other words: use PinchTab as an architecture reference, not as a mandate to rewrite everything around its exact stack on day one.

### What phase 1 must optimize for

- determinism over agent cleverness
- auditability over convenience
- strict PDF truth over "best effort" UI heuristics
- stable interfaces over large rewrites
- migration safety over ambitious parallelism

### Explicit non-decisions

- We have **not** yet committed to replacing Playwright.
- We have **not** yet committed to making DevTools MCP the main executor.
- We have **not** yet committed to extracting `etracking/` into a separate repository immediately.
- We have **not** yet committed to concurrency or multi-browser scaling before single-run correctness is trustworthy.

## New Session Bootstrap Context

If a new chat session starts from this document, assume the following:

- The working project is `etracking/`.
- The immediate task is to execute this plan from phase 1, not to redesign the architecture again.
- The north-star architecture is:
  - deterministic browser worker
  - DevTools observability sidecar
  - strict PDF validation
  - OpenClaw control-plane integration
- The first implementation milestone is considered successful only when:
  - runtime files are separated from source files
  - batch input arguments are honored correctly
  - real PDF validation is enforced
  - screenshot/marker fallbacks are reported as failure or human review, not success

Suggested handoff line for a new session:

```text
Use etracking/docs/plans/2026-03-08-etracking-upgrade-implementation.md as the source of truth. Execute Phase 1 first. Do not re-argue the control-plane decision unless new evidence appears.
```

## Target End State

- Browser automation is deterministic and does not report success unless a real PDF is captured and validated.
- Runtime data, session state, screenshots, downloads, and secrets are not stored as source-controlled project files.
- The browser layer has a clear adapter boundary:
  - execution adapter
  - DevTools inspection adapter
  - PDF acquisition/validation adapter
- Batch processing produces explicit job results:
  - succeeded
  - failed
  - needs-human-review
- OpenClaw integrates above that seam:
  - trigger jobs
  - query status
  - receive PDFs and reports
  - request human takeover when login/session/DOM issues occur

## Proposed Directory Shape

```text
etracking/
  config/
    settings.example.yaml
  docs/
    plans/
  runtime/
    .gitkeep
  src/
    main.py
    core/
      models.py
      config.py
      paths.py
      results.py
    browser/
      base.py
      playwright_adapter.py
      devtools_inspector.py
      snapshots.py
    workflow/
      login_flow.py
      receipt_flow.py
      pdf_flow.py
      batch_runner.py
    integrations/
      cli.py
      report_writer.py
      openclaw_contract.py
    support/
      logging.py
      selectors.py
      validation.py
  tests/
    fixtures/
    unit/
    integration/
```

### Task 1: Clean Project Boundary And Runtime Hygiene

**Files:**
- Create: `etracking/.gitignore`
- Modify: `etracking/README.md`
- Modify: `etracking/config/settings.yaml`
- Move/replace later: `etracking/session/state.json`, `etracking/logs/`, `etracking/downloads/`, `etracking/data/`

**Step 1: Stop treating runtime artifacts as source files**

- Ignore:
  - `logs/`
  - `downloads/`
  - `runtime/`
  - session state files
  - local spreadsheets
  - local screenshots
  - `.venv/`, `venv/`, cache files

**Step 2: Split config into source-safe and local-only**

- Keep only non-secret defaults in `etracking/config/settings.example.yaml`.
- Move real values to:
  - environment variables, or
  - a local non-committed `settings.local.yaml`.

**Step 3: Update README to document the new boundary**

- Add sections for:
  - local config
  - runtime directories
  - secrets handling
  - job outputs

**Step 4: Verify**

Run:

```bash
cd etracking
git status --short
```

Expected:
- runtime files no longer pollute status
- committed source tree becomes reviewable

### Task 2: Replace The God-Class With Explicit Modules

**Files:**
- Modify: `etracking/src/main.py`
- Replace gradually: `etracking/src/session_manager.py`
- Create: `etracking/src/core/models.py`
- Create: `etracking/src/core/config.py`
- Create: `etracking/src/core/paths.py`
- Create: `etracking/src/core/results.py`
- Create: `etracking/src/support/logging.py`
- Create: `etracking/src/support/selectors.py`
- Create: `etracking/src/support/validation.py`

**Step 1: Define core types first**

- Add typed models for:
  - `OrderId`
  - `ReceiptJob`
  - `ReceiptResult`
  - `PdfArtifact`
  - `ExecutionStatus`

**Step 2: Move path/config logic out of browser flow**

- `config.py` owns config loading and env overrides.
- `paths.py` owns runtime directories.
- `results.py` owns status/result serialization.

**Step 3: Stop adding new logic to `session_manager.py`**

- Freeze it as a migration source only.
- All new flow code goes into `workflow/` and `browser/`.

**Step 4: Verify**

Run:

```bash
cd etracking
python -m src.main --help
```

Expected:
- CLI still opens
- no import regressions

### Task 3: Build A Deterministic Browser Execution Layer

**Files:**
- Create: `etracking/src/browser/base.py`
- Create: `etracking/src/browser/playwright_adapter.py`
- Create: `etracking/src/workflow/login_flow.py`
- Create: `etracking/src/workflow/receipt_flow.py`
- Modify: `etracking/src/main.py`

**Step 1: Define a small browser adapter interface**

The interface should cover only what this project needs:

```python
class BrowserAdapter(Protocol):
    def goto(self, url: str) -> None: ...
    def wait_visible(self, selector: str, timeout_ms: int = 0) -> None: ...
    def click(self, selector: str) -> None: ...
    def fill(self, selector: str, value: str) -> None: ...
    def text_snapshot(self) -> str: ...
    def screenshot(self, name: str) -> str: ...
```

**Step 2: Rewrite flow logic around semantic steps**

- `login_flow.py`
  - accept policy
  - navigate to receipt page
  - validate taxpayer data
- `receipt_flow.py`
  - input order id
  - search
  - open print/PDF view

**Step 3: Eliminate brittle field indexing**

- Remove logic that depends on:
  - `inputs[0]`, `inputs[1]`, `inputs[4]`, `inputs[5]`
  - hashed class names like `.css-1czfed0`

**Step 4: Verify**

Run:

```bash
cd etracking
pytest tests/unit -q
```

Expected:
- adapter and selector tests pass before live browser work

### Task 4: Add Chrome DevTools Inspection As A Sidecar

**Files:**
- Create: `etracking/src/browser/devtools_inspector.py`
- Create: `etracking/docs/devtools-debugging.md`
- Modify: `etracking/README.md`

**Step 1: Scope the DevTools role correctly**

- Use DevTools inspection for:
  - network tracing
  - console tracing
  - PDF/blob discovery
  - DOM/debug snapshots
- Do not make DevTools MCP the primary batch executor in phase 1.

**Step 2: Document the inspection workflow**

- How to:
  - attach to an already logged-in Chrome
  - observe the search request
  - find the PDF/blob source
  - confirm whether the page really generated a valid receipt

**Step 3: Add inspector hooks to failure reports**

- On failure, store:
  - current URL
  - console errors
  - interesting network requests
  - screenshot path

**Step 4: Verify**

Run:

```bash
cd etracking
pytest tests/unit/test_devtools_inspector.py -q
```

Expected:
- captured diagnostic payload shape is stable

### Task 5: Rebuild PDF Acquisition Around Truth, Not UI Guessing

**Files:**
- Create: `etracking/src/workflow/pdf_flow.py`
- Modify: `etracking/src/support/validation.py`
- Replace logic from: `etracking/src/session_manager.py`

**Step 1: Define strict success criteria**

A receipt is only successful when all are true:
- the file exists
- the file is a real PDF
- the PDF is above a minimum byte threshold
- the artifact is associated with the requested order id

**Step 2: Prefer direct acquisition order**

- First: direct network/blob retrieval
- Second: browser-native file download
- Third: controlled PDF export only if it still yields a real PDF
- Never: mark screenshot fallback as success

**Step 3: Add explicit result classes**

- `SUCCEEDED`
- `FAILED`
- `NEEDS_HUMAN_REVIEW`

**Step 4: Verify**

Run:

```bash
cd etracking
pytest tests/unit/test_pdf_validation.py -q
```

Expected:
- marker files and screenshots do not count as success

### Task 6: Make Batch Runs Auditable

**Files:**
- Create: `etracking/src/workflow/batch_runner.py`
- Create: `etracking/src/integrations/report_writer.py`
- Modify: `etracking/src/excel_reader.py`
- Modify: `etracking/src/main.py`

**Step 1: Fix batch argument flow**

- `--excel`
- `--sheet`
- `--no-saved-state`
- runtime output directory

must propagate into the batch runner instead of being silently ignored.

**Step 2: Persist machine-readable reports**

- per-run summary JSON
- per-order result JSONL or CSV
- failure reasons
- artifact paths

**Step 3: Add retry semantics**

- retry only transient failures
- do not retry validation failures blindly
- allow rerun of only failed orders

**Step 4: Verify**

Run:

```bash
cd etracking
pytest tests/unit/test_batch_runner.py -q
```

Expected:
- input file and sheet selection are honored
- success/failed counts match real results

### Task 7: Create The OpenClaw Integration Seam

**Files:**
- Create: `etracking/src/integrations/openclaw_contract.py`
- Create: `etracking/docs/openclaw-integration.md`
- Modify: `etracking/README.md`

**Step 1: Define a stable command contract**

Minimum contract:
- `run_batch`
- `run_single`
- `retry_failed`
- `status`
- `get_artifact`

**Step 2: Define payloads before wiring OpenClaw**

Input:

```json
{
  "jobType": "batch",
  "excelPath": "runtime/inbox/orders.xlsx",
  "sheet": "Sheet1"
}
```

Output:

```json
{
  "jobId": "job_20260308_001",
  "status": "SUCCEEDED",
  "success": 10,
  "failed": 2,
  "artifacts": ["runtime/receipts/A017....pdf"]
}
```

**Step 3: Keep OpenClaw above the browser layer**

- OpenClaw should:
  - trigger jobs
  - receive status
  - send PDFs/reports to chat
  - escalate human takeover
- OpenClaw should not own the receipt browser logic in phase 1.

**Step 4: Verify**

Run:

```bash
cd etracking
pytest tests/unit/test_openclaw_contract.py -q
```

Expected:
- contract remains stable without live browser access

### Task 8: Add Real Tests Before Live Rollout

**Files:**
- Create: `etracking/tests/unit/`
- Create: `etracking/tests/integration/`
- Create: `etracking/tests/fixtures/`
- Replace/retire: `etracking/src/test_session.py`
- Replace/retire: `etracking/src/test_roles.py`
- Replace/retire: `etracking/src/test_batch_download.py`

**Step 1: Move tests out of `src/`**

- test code belongs under `tests/`
- production imports become cleaner

**Step 2: Create fixture-driven tests**

- sample HTML snapshots
- sample PDF bytes
- fake blob/network metadata
- fake Excel input

**Step 3: Separate live tests from default tests**

- unit tests run offline
- live tests require explicit opt-in

**Step 4: Verify**

Run:

```bash
cd etracking
pytest tests/unit -q
```

Expected:
- default test suite is deterministic and does not touch the live customs site

## Rollout Phases

### Phase 1

- project hygiene
- module split
- strict PDF validation
- batch/report correctness

### Phase 2

- DevTools inspection workflow
- OpenClaw contract
- retry and human-review states

### Phase 3

- OpenClaw webhook/cron/chat integration
- optional PinchTab-style browser worker evaluation
- optional extraction into a separate repository

## Non-Goals For The First Upgrade

- no full rewrite into a pure agent-controlled browser flow
- no stealth-heavy browser masking unless the site proves it is necessary
- no parallelism before single-threaded determinism is trustworthy
- no UI/dashboard beyond reports needed for debugging and OpenClaw integration

## Exit Criteria

- A failed PDF is never counted as success.
- Batch runs honor CLI inputs exactly.
- Runtime files are cleanly separated from source files.
- The browser layer is replaceable without rewriting the business workflow.
- OpenClaw can call the project through a stable contract instead of driving ad hoc browser steps.
