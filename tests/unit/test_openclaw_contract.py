from pathlib import Path

from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
from src.integrations.openclaw_contract import OpenClawContract


def test_openclaw_contract_builds_batch_request_and_response(tmp_path: Path) -> None:
    contract = OpenClawContract()
    request = contract.run_batch(excel_path="runtime/inbox/orders.xlsx", sheet="Sheet1")

    assert request["jobType"] == "batch"
    assert request["excelPath"] == "runtime/inbox/orders.xlsx"
    assert request["sheet"] == "Sheet1"

    report = BatchRunResult(
        job=ReceiptJob(order_ids=["A017X680406286"], output_dir=tmp_path),
        run_id="job_20260308_001",
        results=[
            ReceiptResult(
                order_id="A017X680406286",
                status=ExecutionStatus.SUCCEEDED,
            )
        ],
        started_at=__import__("datetime").datetime(2026, 3, 8, 12, 0, 0),
        finished_at=__import__("datetime").datetime(2026, 3, 8, 12, 1, 0),
    )

    response = contract.job_response(report)

    assert response["jobId"] == "job_20260308_001"
    assert response["status"] == "SUCCEEDED"
    assert response["success"] == 1
    assert response["failed"] == 0


def test_openclaw_contract_exposes_required_commands() -> None:
    contract = OpenClawContract()

    assert contract.run_single("A017X680406286")["jobType"] == "single"
    assert contract.retry_failed("job_20260308_001")["jobType"] == "retry_failed"
    assert contract.status("job_20260308_001")["jobType"] == "status"
    assert contract.get_artifact("job_20260308_001", "A017X680406286")["jobType"] == "get_artifact"
