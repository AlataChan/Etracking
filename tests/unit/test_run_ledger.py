from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from src.core.models import BatchRunResult, ExecutionStatus, PdfArtifact, ReceiptJob, ReceiptResult
from src.core.paths import RuntimePaths
from src.integrations.run_ledger import RunLedger


def test_run_ledger_appends_results_immediately(tmp_path: Path) -> None:
    paths = RuntimePaths.from_project_root(tmp_path).ensure()
    report_paths = paths.report_paths_for("job_20260309_120000")
    artifact_path = paths.receipts_dir / "A017X680406286_20260309.pdf"
    artifact_path.write_bytes(b"%PDF-test-artifact")
    result = ReceiptResult(
        order_id="A017X680406286",
        status=ExecutionStatus.SUCCEEDED,
        artifact=PdfArtifact(
            order_id="A017X680406286",
            path=artifact_path,
            source="blob",
            byte_size=artifact_path.stat().st_size,
        ),
    )

    ledger = RunLedger(report_paths)
    ledger.append_result(result)

    lines = report_paths.results_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["orderId"] == "A017X680406286"


def test_run_ledger_writes_partial_summary_snapshot(tmp_path: Path) -> None:
    paths = RuntimePaths.from_project_root(tmp_path).ensure()
    report_paths = paths.report_paths_for("job_20260309_120001")
    report = BatchRunResult(
        job=ReceiptJob(order_ids=["A017X680406286", "A017X680406287", "A017X680406288"]),
        run_id="job_20260309_120001",
        results=[
            ReceiptResult(order_id="A017X680406286", status=ExecutionStatus.SUCCEEDED),
        ],
        started_at=datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
        finished_at=None,
        planned_total=3,
    )

    ledger = RunLedger(report_paths)
    ledger.write_summary_snapshot(report)

    payload = json.loads(report_paths.summary_path.read_text(encoding="utf-8"))
    assert payload["total"] == 3
    assert payload["completed"] == 1
    assert payload["remaining"] == 2
    assert payload["finishedAt"] is None

