# OpenClaw Integration

## Positioning

OpenClaw sits above the browser layer as the control plane.

Responsibilities:

- trigger `run_batch`
- trigger `run_single`
- trigger `retry_failed`
- query `status`
- retrieve `get_artifact`
- route reports and PDFs to chat, webhook, or cron outputs
- escalate to human takeover when login, DOM, or session problems occur

Non-goal:

- OpenClaw does not own receipt browser automation in phase 1

## Contract Surface

Implemented in [openclaw_contract.py](/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/src/integrations/openclaw_contract.py).

Supported commands:

- `run_batch`
- `run_single`
- `retry_failed`
- `status`
- `get_artifact`

## Example Batch Request

```json
{
  "jobType": "batch",
  "excelPath": "runtime/inbox/orders.xlsx",
  "sheet": "Sheet1"
}
```

## Example Job Response

```json
{
  "jobId": "job_20260308_001",
  "status": "SUCCEEDED",
  "success": 10,
  "failed": 2,
  "needsHumanReview": 1,
  "artifacts": [
    "runtime/receipts/A017X680406286_20260308.pdf"
  ]
}
```

## Recommended Wiring

- Chat or webhook receives user intent
- OpenClaw builds a contract payload
- Etracking executes the browser job and writes reports to `runtime/reports/<job_id>/`
- OpenClaw polls `status` or receives job completion
- OpenClaw fetches artifacts and routes them outward

## Retry Model

- Retry only transient browser failures
- Do not blindly retry validation failures
- Use `retry_failed` with a previous `results.jsonl` to rerun only failed orders
