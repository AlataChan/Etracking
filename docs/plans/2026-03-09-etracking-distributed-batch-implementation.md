# Etracking Distributed Batch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement recoverable large-batch processing first, then add coordinator-based multi-machine execution without changing the core browser automation flow.

**Architecture:** Phase 1 hardens the current single-worker batch runner with incremental persistence, resume, graceful interruption, and browser recycle. Phase 2 introduces immutable batch manifests and a strict file-system model where Excel is imported once and then archived. Phase 3 adds a central coordinator with leases and heartbeats so multiple machines can process the same batch safely. Phase 4 hardens artifact storage, reporting, and operating procedures.

**Tech Stack:** Python 3.12, Playwright, pytest, openpyxl-based Excel ingest, JSONL snapshots, small HTTP coordinator service, SQLite-on-host then Postgres later, SMB/NFS or S3-compatible shared artifact storage

---

## Phase Overview

### Phase 1: Recoverable Single Worker

Deliver a single-machine batch runner that can:

- process every valid order id from the imported order column
- persist progress after every completed item
- resume after interruption without redoing successful work
- recycle browser state automatically during long runs

Exit criteria:

- killing the process mid-batch does not lose finished results
- rerunning the same batch skips valid successful items
- a large batch can continue until the imported set is exhausted

### Phase 2: Manifest Import And File-System Discipline

Replace ad-hoc Excel-as-runtime-input with immutable manifests and a clean source/archive model.

Exit criteria:

- Excel is imported exactly once into a manifest
- the original Excel is archived under the batch id
- workers no longer need direct access to Excel files once a batch starts

### Phase 3: Coordinator And Multi-Machine Workers

Add lease-based distributed claiming so 5 machines can process one batch safely.

Exit criteria:

- no two workers claim the same order at the same time
- worker crash recovery works through lease expiry
- multiple machines can finish one imported batch without manual file splitting

### Phase 4: Artifact Hardening And Operations

Harden shared PDF storage, reporting, and operator workflow.

Exit criteria:

- final PDFs are atomically finalized and discoverable by batch
- operators can see batch progress and rerun failed items
- there is a runbook for adding more worker machines

## Multi-Machine Excel And File-System Decision

This is the explicit file-system model for many Excel files and many worker machines.

### Decision 1: Excel Is Import Input Only

Do not copy active Excel files to every worker machine. Do not let workers read Excel directly during execution.

Instead:

1. one control machine or coordinator host receives the Excel file
2. the Excel file is imported once into a normalized batch manifest
3. the original Excel file is archived under the generated `batch_id`
4. workers process manifest items, not Excel rows

This avoids version drift, duplicate processing, and file-sync problems across 5 machines.

### Decision 2: Separate Shared Storage From Local Worker Storage

Use two storage classes:

- local worker storage for browser state, temp downloads, debug logs, and screenshots captured before upload
- shared storage for archived source Excel files, manifests, final PDFs, failure screenshots, and batch reports

Workers should be disposable. Shared batch artifacts should not be disposable.

### Decision 3: Batch-Oriented Shared Layout

Use a batch-oriented layout like:

```text
shared/
  inbox/
    incoming/
    archived/
  batches/
    <batch_id>/
      source/
        orders.xlsx
      manifest/
        manifest.jsonl
      receipts/
      failures/
      reports/
```

Rules:

- `inbox/incoming/` is for operator upload only
- import moves the Excel file into `batches/<batch_id>/source/orders.xlsx`
- workers never modify the archived source Excel
- workers write final outputs only inside the owning batch directory

### Decision 4: Workers Keep Only Local Runtime State

Each machine keeps its own local runtime root, for example:

```text
runtime/
  workers/
    <worker_id>/
      logs/
      session/
      tmp/
      downloads/
```

This keeps browser sessions and temp files isolated per machine. Deleting a worker runtime should not destroy shared batch truth.

## Phase 1 Tasks: Recoverable Single Worker

### Task 1: Add append-only run ledger and snapshot writer

**Files:**
- Create: `src/integrations/run_ledger.py`
- Modify: `src/integrations/report_writer.py`
- Modify: `src/core/results.py`
- Modify: `src/core/paths.py`
- Test: `tests/unit/test_run_ledger.py`
- Test: `tests/unit/test_paths.py`

**Step 1: Write the failing tests**

- add a test that appending one `ReceiptResult` immediately creates or extends `results.jsonl`
- add a test that summary snapshot reflects partial progress before batch completion
- add a test that path helpers expose a stable per-run report directory early

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_run_ledger.py tests/unit/test_paths.py -q`
Expected: FAIL because `run_ledger.py` and related APIs do not exist yet

**Step 3: Write minimal implementation**

- implement a small append-only ledger writer
- add `append_result()`
- add `write_summary_snapshot()`
- update path helpers so a run/report directory can be created before the batch completes

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_run_ledger.py tests/unit/test_paths.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/integrations/run_ledger.py src/integrations/report_writer.py src/core/results.py src/core/paths.py tests/unit/test_run_ledger.py tests/unit/test_paths.py
git commit -m "feat: add incremental batch run ledger"
```

### Task 2: Resume batches by skipping valid successful items

**Files:**
- Modify: `src/workflow/batch_runner.py`
- Modify: `src/core/models.py`
- Modify: `src/core/results.py`
- Modify: `src/main.py`
- Test: `tests/unit/test_batch_runner.py`
- Test: `tests/unit/test_main_cli.py`

**Step 1: Write the failing tests**

- add a test that a rerun skips order ids already marked `SUCCEEDED` with a valid artifact
- add a test that failed or human-review items remain eligible
- add a CLI parsing test for explicit resume controls such as `--resume-run` or `--resume-results`

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_batch_runner.py tests/unit/test_main_cli.py -q`
Expected: FAIL because the batch runner currently always iterates the full set

**Step 3: Write minimal implementation**

- teach the runner to preload an existing ledger
- skip succeeded items only when the artifact still exists and validates
- leave failed and review items in scope
- expose resume options in the CLI

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_batch_runner.py tests/unit/test_main_cli.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/workflow/batch_runner.py src/core/models.py src/core/results.py src/main.py tests/unit/test_batch_runner.py tests/unit/test_main_cli.py
git commit -m "feat: add recoverable batch resume semantics"
```

### Task 3: Add graceful stop and browser recycle policy

**Files:**
- Modify: `src/main.py`
- Modify: `src/workflow/batch_runner.py`
- Modify: `src/session_manager.py`
- Modify: `src/core/config.py`
- Test: `tests/unit/test_batch_runner.py`
- Test: `tests/unit/test_session_manager_resume.py`

**Step 1: Write the failing tests**

- add a test that a stop flag prevents claiming or starting the next order after current completion
- add a test that browser recycle triggers after a configured completed-order threshold
- add a test that browser recycle also triggers after repeated retryable failures

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_batch_runner.py tests/unit/test_session_manager_resume.py -q`
Expected: FAIL because stop/recycle policy does not exist

**Step 3: Write minimal implementation**

- add stop handling for `SIGINT` and `SIGTERM`
- finalize the current result before exiting
- close and recreate session state every configured N orders or after failure threshold
- add configuration keys for recycle thresholds

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_batch_runner.py tests/unit/test_session_manager_resume.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/main.py src/workflow/batch_runner.py src/session_manager.py src/core/config.py tests/unit/test_batch_runner.py tests/unit/test_session_manager_resume.py
git commit -m "feat: add graceful stop and browser recycle policy"
```

## Phase 2 Tasks: Manifest Import And File-System Discipline

### Task 4: Build immutable batch manifest import with logical dedupe

**Files:**
- Create: `src/core/batch_manifest.py`
- Create: `src/workflow/manifest_builder.py`
- Modify: `src/excel_reader.py`
- Modify: `src/core/models.py`
- Test: `tests/unit/test_manifest_builder.py`

**Step 1: Write the failing tests**

- add a test that all valid non-empty rows in the configured column are imported
- add a test that normalized duplicates collapse to one logical batch item
- add a test that original row numbers are preserved for auditability

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_manifest_builder.py -q`
Expected: FAIL because manifest builder types and behavior do not exist

**Step 3: Write minimal implementation**

- define manifest models
- build manifest import from `ExcelReader`
- normalize and dedupe order ids
- preserve original row metadata

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_manifest_builder.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/batch_manifest.py src/workflow/manifest_builder.py src/excel_reader.py src/core/models.py tests/unit/test_manifest_builder.py
git commit -m "feat: add immutable batch manifest import"
```

### Task 5: Add batch-oriented source/archive/shared-path layout

**Files:**
- Modify: `src/core/paths.py`
- Modify: `src/main.py`
- Modify: `src/core/config.py`
- Create: `src/integrations/batch_storage.py`
- Test: `tests/unit/test_paths.py`
- Test: `tests/unit/test_batch_storage.py`

**Step 1: Write the failing tests**

- add a test that importing an Excel file copies or moves it into `batches/<batch_id>/source/orders.xlsx`
- add a test that manifest and report paths resolve under one batch root
- add a test that worker-local runtime paths remain separate from shared batch paths

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_paths.py tests/unit/test_batch_storage.py -q`
Expected: FAIL because batch storage conventions do not exist

**Step 3: Write minimal implementation**

- add batch-root path helpers
- implement Excel archive helper
- separate local worker runtime directories from shared batch directories
- add config for shared root and worker id

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_paths.py tests/unit/test_batch_storage.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/core/paths.py src/main.py src/core/config.py src/integrations/batch_storage.py tests/unit/test_paths.py tests/unit/test_batch_storage.py
git commit -m "feat: add batch storage and archived excel layout"
```

## Phase 3 Tasks: Coordinator And Multi-Machine Workers

### Task 6: Add coordinator store and lease state machine

**Files:**
- Create: `src/distributed/models.py`
- Create: `src/distributed/store.py`
- Create: `src/distributed/service.py`
- Modify: `src/core/models.py`
- Test: `tests/unit/test_distributed_store.py`

**Step 1: Write the failing tests**

- add a test that only one worker can claim a `QUEUED` item
- add a test that expired `LEASED` items return to claimable state
- add a test that success and failure transitions are terminal

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_distributed_store.py -q`
Expected: FAIL because distributed lease store does not exist

**Step 3: Write minimal implementation**

- define batch item state model
- implement claim, heartbeat, complete, and expire operations
- start with SQLite on coordinator local disk

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_distributed_store.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/distributed/models.py src/distributed/store.py src/distributed/service.py src/core/models.py tests/unit/test_distributed_store.py
git commit -m "feat: add coordinator lease state machine"
```

### Task 7: Add worker client claim-heartbeat-complete loop

**Files:**
- Create: `src/distributed/client.py`
- Create: `src/distributed/worker.py`
- Modify: `src/main.py`
- Modify: `src/workflow/batch_runner.py`
- Test: `tests/unit/test_worker_client.py`
- Test: `tests/integration/test_distributed_claiming.py`

**Step 1: Write the failing tests**

- add a unit test that a worker sends heartbeat while processing
- add an integration test with two workers proving distinct order claims
- add an integration test that one crashed worker's lease is reclaimed by another worker

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_worker_client.py tests/integration/test_distributed_claiming.py -q`
Expected: FAIL because worker client and distributed runner do not exist

**Step 3: Write minimal implementation**

- implement coordinator client
- implement worker polling loop
- map one claimed item to one browser-processing call
- expose CLI modes such as `create-batch`, `run-worker`, and `retry-batch`

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_worker_client.py tests/integration/test_distributed_claiming.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/distributed/client.py src/distributed/worker.py src/main.py src/workflow/batch_runner.py tests/unit/test_worker_client.py tests/integration/test_distributed_claiming.py
git commit -m "feat: add distributed worker execution loop"
```

## Phase 4 Tasks: Artifact Hardening And Operations

### Task 8: Add atomic shared artifact finalization and rerun-safe detection

**Files:**
- Create: `src/integrations/artifact_store.py`
- Modify: `src/workflow/pdf_flow.py`
- Modify: `src/core/results.py`
- Test: `tests/unit/test_artifact_store.py`
- Test: `tests/unit/test_pdf_flow.py`

**Step 1: Write the failing tests**

- add a test that PDFs are written to a temp path then atomically finalized
- add a test that a partial temp file is not treated as success
- add a test that an existing valid finalized PDF can satisfy resume checks

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/unit/test_artifact_store.py tests/unit/test_pdf_flow.py -q`
Expected: FAIL because shared artifact finalization logic does not exist

**Step 3: Write minimal implementation**

- move PDF writes through an artifact store helper
- validate before finalize
- use deterministic batch-aware artifact naming

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/unit/test_artifact_store.py tests/unit/test_pdf_flow.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/integrations/artifact_store.py src/workflow/pdf_flow.py src/core/results.py tests/unit/test_artifact_store.py tests/unit/test_pdf_flow.py
git commit -m "feat: harden shared pdf artifact finalization"
```

### Task 9: Add operator reporting, docs, and multi-machine smoke coverage

**Files:**
- Modify: `src/integrations/report_writer.py`
- Modify: `src/main.py`
- Create: `docs/operations/distributed-batches.md`
- Create: `tests/integration/test_distributed_batch_smoke.py`
- Modify: `README.md`

**Step 1: Write the failing tests**

- add an integration test that a batch report updates correctly as distributed results arrive
- add a smoke test harness for one coordinator and two fake workers

**Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest tests/integration/test_distributed_batch_smoke.py -q`
Expected: FAIL because distributed reporting and smoke harness do not exist

**Step 3: Write minimal implementation**

- expose batch progress summary commands
- document operator workflow for:
  - importing Excel
  - starting workers on 5 machines
  - adding a new machine
  - rerunning failed items
- update README with the supported storage model

**Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest tests/integration/test_distributed_batch_smoke.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/integrations/report_writer.py src/main.py docs/operations/distributed-batches.md tests/integration/test_distributed_batch_smoke.py README.md
git commit -m "docs: add distributed batch operations runbook"
```

## Recommended Delivery Sequence

Implement in this order:

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 8
7. Task 6
8. Task 7
9. Task 9

Reason:

- Phase 1 is the highest-value stability work and immediately useful even before distributed mode
- Phase 2 makes source ingestion and batch identity explicit
- Task 8 should land before distributed rollout so artifact semantics are solid
- Phase 3 should build on a proven recoverable worker core

## Verification Gates

### Gate A: Single Worker Recovery

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_run_ledger.py tests/unit/test_batch_runner.py tests/unit/test_main_cli.py tests/unit/test_session_manager_resume.py -q
```

Expected:

- all tests pass
- a manual interrupted local batch can resume without reprocessing successful PDFs

### Gate B: Manifest And Storage Discipline

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_manifest_builder.py tests/unit/test_batch_storage.py tests/unit/test_paths.py -q
```

Expected:

- all tests pass
- imported Excel files are archived under batch ids

### Gate C: Distributed Coordination

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_distributed_store.py tests/unit/test_worker_client.py tests/integration/test_distributed_claiming.py -q
```

Expected:

- all tests pass
- two workers never hold the same order concurrently

### Gate D: Operations Hardening

Run:

```bash
./.venv/bin/python -m pytest tests/unit/test_artifact_store.py tests/integration/test_distributed_batch_smoke.py -q
```

Expected:

- all tests pass
- artifact finalization and batch progress reporting behave correctly

## Non-Goals For This Plan

- building a full web dashboard before the coordinator works
- enabling multithreaded processing inside one browser session
- treating shared Excel files as a live distributed queue
- supporting consumer sync products as the correctness layer for coordination
