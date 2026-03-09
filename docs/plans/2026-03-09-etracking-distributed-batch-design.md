# Etracking Recoverable Distributed Batch Processing Design

**Date:** 2026-03-09

## Goal

Design a batch-processing architecture that can:

1. run the full imported Excel order column reliably, whether that batch contains 800, 1000, 1400, or any other practical volume
2. survive interruption without losing finished work
3. scale from 1 machine to roughly 5 worker machines immediately
4. keep a path open for future horizontal expansion

The system should continue using the current browser automation flow, but the batch orchestration model must change from a long-lived script into a recoverable job-processing system.

## Current Constraints

The current codebase is not yet designed for multi-hour or multi-machine execution:

- [`src/workflow/batch_runner.py`](../../src/workflow/batch_runner.py) processes the whole order list sequentially in one in-memory run.
- [`src/integrations/report_writer.py`](../../src/integrations/report_writer.py) writes result files only after the full batch completes.
- [`src/main.py`](../../src/main.py) keeps one `SessionManager` alive for the full batch.
- retries exist, but they assume a previous `results.jsonl` already exists.

That model is acceptable for tens of orders. It is too fragile for 1000-order jobs or for 5 machines working at the same time.

## Requirements

### Functional

- ingest one Excel file and turn it into a normalized immutable batch manifest
- read every valid order id in the configured Excel column and continue until that imported set is exhausted
- let workers pick unprocessed orders safely without double-claiming
- write PDFs and per-order outcomes incrementally
- resume after worker crash, browser crash, machine reboot, or manual stop
- support rerunning only failed or human-review items
- support 5 machines in parallel without manual partitioning

### Non-Functional

- no completed PDF should be lost because a run stops mid-batch
- browser state drift should be bounded by periodic worker self-recycle
- coordination should remain correct when workers stop unexpectedly
- operator workflow should stay simple enough for non-engineering daily use
- future scale-out should not require redesigning the artifact layout
- success-path diagnostic screenshots should be configurable because they are useful during debugging but expensive during sustained batch throughput

## Approaches Considered

### Approach A: Single-Machine Recoverable Batch Only

Add incremental result writes, resume, and browser recycle, but keep processing on one machine.

Pros:

- lowest implementation cost
- fixes the most urgent interruption problem
- minimal new infrastructure

Cons:

- does not solve 5-machine parallelism
- operator must still split Excel files manually
- future scale requires another orchestration redesign

### Approach B: Shared Filesystem Coordination

Use a shared folder as both queue and result store. Workers claim orders by creating lease files and update shared JSONL files directly.

Pros:

- no always-on service required
- cheap to start if there is already a NAS or SMB share
- conceptually simple

Cons:

- correctness depends on network-share locking semantics
- hard to reason about under concurrent writes
- weak observability
- unsafe on consumer sync tools such as iCloud, Dropbox, or OneDrive
- becomes brittle as hardware count increases

### Approach C: Recommended Hybrid

Use a central coordinator for work assignment and state, keep workers single-threaded, and store PDFs in shared artifact storage.

Pros:

- correct multi-machine claiming and resume semantics
- scales from 1 worker to 5 workers cleanly
- workers remain simple and stable because each worker still runs one browser session at a time
- shared output layout stays stable as throughput grows

Cons:

- requires a small central service or database
- higher initial implementation cost than purely local recovery

## Recommendation

Choose Approach C, but implement it in two phases:

1. make the worker itself recoverable and incrementally persistent
2. add a coordinator so multiple workers can safely share one batch

This is the right trade-off because the local-recovery work is required anyway, and it becomes the execution core for distributed workers later.

## Architecture

### Components

#### 1. Manifest Builder

Input is the operator-provided Excel file.

Output is an immutable batch manifest:

- `batch_id`
- source Excel path and sheet
- normalized order ids for every valid non-empty row in the imported order column
- original row number for auditability
- deduplicated logical items

The important design rule is: workers do not read Excel directly once a batch starts. Excel is converted once into a manifest, and the manifest becomes the source of truth for execution.

#### 2. Coordinator

The coordinator owns global job state. It can be implemented as:

- preferred: a small HTTP service backed by Postgres
- acceptable early variant: a small HTTP service backed by SQLite on the coordinator host's local disk

The coordinator must not rely on a SQLite file placed on a shared network folder.

The coordinator stores:

- batches
- batch items
- worker registrations
- leases
- completion events
- artifact metadata

#### 3. Worker

Each machine runs one or more workers. Each worker:

- claims one order at a time from the coordinator
- runs the existing browser automation sequentially
- writes the PDF to shared storage
- reports completion back to the coordinator
- heartbeats while work is in progress
- recycles its browser session periodically

Each worker should run only one active browser flow at a time. Concurrency comes from multiple workers across machines, not from threads inside one browser session.

Within one worker session, the steady-state loop after the receipt form is already expanded should stay minimal:

- fill the next order id
- search
- click print
- wait only until the PDF/blob source is fetchable
- persist the PDF
- close the popup/viewer immediately if a new tab was opened
- continue to the next order

That loop should not re-run early setup steps on every item. Resume probes for pre-existing search results should be limited to the first order after attach or after a session recycle.

#### 4. Shared Artifact Storage

The artifact store holds:

- final PDFs
- per-order screenshots for failures
- optional per-batch exported reports

Recommended options:

- SMB/NFS NAS for local office setup
- S3-compatible object storage if infrastructure already exists

Do not use consumer sync folders for active coordination. They are acceptable only as secondary archival destinations.

#### 5. Operator CLI

Operators should have two simple actions:

- create batch from Excel
- start or stop workers on any machine

Daily operation should not require manual Excel partitioning once distributed mode exists.

## State Model

### Batch Item Status

Each order item should move through:

- `QUEUED`
- `LEASED`
- `SUCCEEDED`
- `FAILED`
- `NEEDS_HUMAN_REVIEW`
- `CANCELLED`

`LEASED` is not a final state. It means a worker currently owns the item. If the lease expires, the item returns to `QUEUED`.

### Lease Model

Each lease contains:

- `batch_id`
- `order_id`
- `worker_id`
- `lease_started_at`
- `lease_expires_at`
- `heartbeat_at`
- `attempt_number`

Workers heartbeat while processing. If a machine dies, another worker can reclaim the order after lease expiry.

### Artifact Model

Artifact records should store:

- canonical artifact path
- byte size
- content type
- capture source such as `blob` or `viewer-download`
- checksum if practical

Artifact write should use a temporary file plus atomic finalize. A half-written PDF must never be treated as success.

## Execution Flow

1. Operator imports Excel and creates a new batch.
2. Manifest Builder normalizes order ids and stores immutable batch items.
3. Each worker asks the coordinator for the next available item.
4. Coordinator grants one lease if an item is available.
5. Worker runs the browser flow for that order.
6. Worker writes the PDF to shared storage using a temp path.
7. Worker validates the PDF and finalizes the file atomically.
8. Worker reports `SUCCEEDED`, `FAILED`, or `NEEDS_HUMAN_REVIEW`.
9. Coordinator updates aggregate batch progress immediately.
10. Worker requests the next item.

Batch completion condition:

- the batch ends only when there are no remaining `QUEUED` items and no active `LEASED` items that may still complete or expire back to the queue
- in operator terms, that means the imported order column has been fully consumed and every imported item has reached a terminal state

## Fault Tolerance Strategy

### 1. Incremental Persistence

Every order completion must be persisted immediately. The system must never wait until the end of a 1000-order batch to materialize results.

### 2. Lease Expiry Recovery

If a worker disappears:

- the current order remains in `LEASED` only until the lease expires
- another worker can then reclaim it
- the batch continues without manual cleanup

### 3. Browser Self-Recycle

Long-lived browser sessions drift. Each worker should restart or reattach its browser after:

- 50 completed orders initially
- or 20-30 minutes of continuous runtime
- or 5 consecutive retryable failures

The exact threshold can be tuned with production evidence. Start conservative.

### 4. Circuit Breaker

If the site starts failing globally, workers should not hammer it indefinitely. Add a worker-level circuit breaker that pauses claiming new work after a threshold such as:

- 5 consecutive failures
- or failure ratio above 50% in the last 20 attempts

This prevents multiplying an upstream outage by 5 machines at once.

### 5. Graceful Stop

On manual stop or `SIGINT`, a worker should:

- finish the current order if feasible
- report final status
- release or expire its lease cleanly
- stop claiming new items

## Concurrency And Scaling

### Recommended Unit of Parallelism

One worker equals one browser session processing one order at a time.

This keeps the failure domain small and matches the behavior of the current Playwright flow. It also avoids popup races and shared-page corruption.

### Initial Deployment

For 5 machines:

- start with 1 worker per machine
- total concurrency = 5
- observe success rate and site tolerance before increasing worker count

If one machine is stronger, adding a second worker on that machine is possible later, but only after confirming CPU, memory, and site behavior remain stable.

### Horizontal Scale

With the coordinator model, scaling out means:

- add another machine
- assign it a unique `worker_id`
- point it to the same coordinator and shared artifact store

No Excel repartitioning is needed.

## Shared File Strategy

### Source Files

Excel should be treated as import input only. It is not the live coordination medium.

### Artifact Layout

Use a batch-oriented shared layout such as:

```text
shared/
  batches/
    <batch_id>/
      manifest.jsonl
      reports/
      receipts/
      failures/
```

This keeps outputs isolated and makes reruns auditable.

### Local vs Shared Logs

Keep verbose browser and debug logs local to each worker machine. Only push compact structured execution events and final artifact metadata into the coordinator.

This prevents shared storage from turning into a hot write path for noisy logs.

## Exactly-Once vs At-Least-Once

The practical target should be at-least-once processing with idempotent completion handling.

Why not promise exactly-once:

- a worker can crash after writing a valid PDF but before posting success
- network partitions can make completion acknowledgement ambiguous

Therefore the design should:

- use deterministic artifact naming
- validate existing artifacts before reprocessing
- treat a valid existing PDF plus matching success metadata as already complete

This is sufficient for this business workflow and much simpler than distributed exactly-once guarantees.

## Operational Workflow

### Batch Creation

1. operator imports Excel
2. system generates `batch_id`
3. system stores manifest and marks all items `QUEUED`

### Distributed Execution

1. operator starts workers on up to 5 machines
2. workers pull leases and process orders independently
3. operator monitors aggregate progress from the coordinator
4. execution continues until every imported order from the manifest reaches a terminal state

### Resume

If any worker or machine stops:

1. unfinished leased items expire
2. surviving workers continue
3. restarted workers simply rejoin and claim new items

### Rerun Failed

Operators can create a derived batch containing only:

- `FAILED`
- `NEEDS_HUMAN_REVIEW`

This is cleaner than asking workers to scan old Excel files again.

## Rollout Plan

### Phase 1: Recoverable Single Worker

Implement first:

- append-only per-order result persistence
- resume by skipping successful items
- browser recycle policy
- graceful stop handling
- deterministic artifact validation

This immediately makes 1000-order single-machine runs safer.

### Phase 2: Coordinator And Distributed Workers

Implement next:

- manifest import command
- coordinator schema and lease API
- worker claim and heartbeat loop
- shared artifact store layout
- batch progress reporting

### Phase 3: Controlled Horizontal Tuning

After production evidence:

- test 5 concurrent workers
- add worker-level backoff tuning
- evaluate whether 2 workers on selected machines is safe

## Testing Strategy

### Unit

- manifest normalization and deduplication
- lease expiry and reclaim logic
- artifact finalization and partial-file recovery
- resume rules for existing success artifacts

### Integration

- one coordinator plus multiple fake workers claiming distinct orders
- worker crash during `LEASED` state and successful reclaim
- batch rerun containing only failed items

### Live

- one real worker end-to-end smoke
- then two real workers against the same coordinator
- only after that, expand to 5 machines

## Risks

- upstream site rate limits or anti-automation rules may make 5 concurrent workers too aggressive
- shared NAS performance may become a bottleneck if screenshots and logs are written too eagerly
- operators may expect exact-once semantics unless the resume model is explained clearly

## Final Decision

Build a recoverable single-thread worker core first, but design it from day one to plug into a central coordinator. Do not use multithreading inside one browser session. Do not use shared Excel or shared JSONL files as the distributed coordination mechanism. Use Excel only as batch import input, then let multiple machines process claimed orders through coordinator-managed leases and shared artifact storage.
