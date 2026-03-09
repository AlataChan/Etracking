from pathlib import Path

from src.core.models import BatchRunResult, ExecutionStatus, PdfArtifact, ReceiptJob, ReceiptResult
from src.workflow.batch_runner import BatchRunner


class FakeExcelReader:
    instances: list["FakeExcelReader"] = []

    def __init__(self, excel_path: Path | None = None) -> None:
        self.excel_path = excel_path
        self.sheet_calls: list[str | None] = []
        type(self).instances.append(self)

    def get_order_ids(self, sheet_name: str | None = None) -> list[str]:
        self.sheet_calls.append(sheet_name)
        return ["A017X680406286", "A017X680406287"]


def test_batch_runner_honors_excel_and_sheet_arguments(tmp_path: Path) -> None:
    results_by_order = {
        "A017X680406286": ReceiptResult(order_id="A017X680406286", status=ExecutionStatus.SUCCEEDED),
        "A017X680406287": ReceiptResult(order_id="A017X680406287", status=ExecutionStatus.FAILED, reason="missing pdf"),
    }

    runner = BatchRunner(excel_reader_factory=FakeExcelReader)
    job = ReceiptJob(
        order_ids=[],
        excel_path=tmp_path / "orders.xlsx",
        sheet_name="SheetA",
        use_saved_state=False,
        output_dir=tmp_path / "runtime" / "receipts",
    )

    report = runner.run(job=job, process_order=lambda order_id: results_by_order[order_id])

    assert isinstance(report, BatchRunResult)
    assert FakeExcelReader.instances[-1].excel_path == job.excel_path
    assert FakeExcelReader.instances[-1].sheet_calls == ["SheetA"]
    assert report.total == 2
    assert report.succeeded == 1
    assert report.failed == 1
    assert report.needs_human_review == 0


def test_batch_runner_retries_only_transient_failures(tmp_path: Path) -> None:
    attempts: dict[str, int] = {"A017X680406286": 0, "A017X680406287": 0}
    runner = BatchRunner(excel_reader_factory=FakeExcelReader)
    job = ReceiptJob(
        order_ids=["A017X680406286", "A017X680406287"],
        excel_path=tmp_path / "orders.xlsx",
        use_saved_state=False,
        output_dir=tmp_path / "runtime" / "receipts",
        max_retries=2,
    )

    def process_order(order_id: str) -> ReceiptResult:
        attempts[order_id] += 1
        if order_id == "A017X680406286" and attempts[order_id] == 1:
            return ReceiptResult(
                order_id=order_id,
                status=ExecutionStatus.FAILED,
                reason="temporary timeout",
                metadata={"retryable": True},
            )
        if order_id == "A017X680406287":
            return ReceiptResult(
                order_id=order_id,
                status=ExecutionStatus.FAILED,
                reason="invalid marker pdf",
                metadata={"retryable": False},
            )
        return ReceiptResult(order_id=order_id, status=ExecutionStatus.SUCCEEDED)

    report = runner.run(job=job, process_order=process_order)

    assert attempts["A017X680406286"] == 2
    assert attempts["A017X680406287"] == 1
    assert report.succeeded == 1
    assert report.failed == 1


def test_batch_runner_can_rerun_failed_orders_only() -> None:
    runner = BatchRunner(excel_reader_factory=FakeExcelReader)
    failed = ReceiptResult(order_id="A017X680406286", status=ExecutionStatus.FAILED)
    review = ReceiptResult(order_id="A017X680406287", status=ExecutionStatus.NEEDS_HUMAN_REVIEW)
    passed = ReceiptResult(order_id="A017X680406288", status=ExecutionStatus.SUCCEEDED)

    rerun_job = runner.retry_failed_job([failed, review, passed])

    assert rerun_job.order_ids == ["A017X680406286"]


def test_batch_runner_skips_resumed_success_with_valid_artifact(tmp_path: Path) -> None:
    runner = BatchRunner(excel_reader_factory=FakeExcelReader)
    artifact_path = tmp_path / "runtime" / "receipts" / "A017X680406286.pdf"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"%PDF-valid-artifact")
    resumed_success = ReceiptResult(
        order_id="A017X680406286",
        status=ExecutionStatus.SUCCEEDED,
        artifact=PdfArtifact(
            order_id="A017X680406286",
            path=artifact_path,
            source="blob",
            byte_size=artifact_path.stat().st_size,
        ),
    )
    calls: list[str] = []
    job = ReceiptJob(
        order_ids=["A017X680406286", "A017X680406287"],
        output_dir=tmp_path / "runtime" / "receipts",
        min_artifact_bytes=4,
    )

    report = runner.run(
        job=job,
        process_order=lambda order_id: calls.append(order_id) or ReceiptResult(order_id=order_id, status=ExecutionStatus.SUCCEEDED),
        previous_results=[resumed_success],
    )

    assert calls == ["A017X680406287"]
    assert [result.order_id for result in report.results] == ["A017X680406286", "A017X680406287"]
    assert report.succeeded == 2


def test_batch_runner_reprocesses_failed_and_review_results_on_resume(tmp_path: Path) -> None:
    runner = BatchRunner(excel_reader_factory=FakeExcelReader)
    previous_results = [
        ReceiptResult(order_id="A017X680406286", status=ExecutionStatus.FAILED, reason="temporary timeout"),
        ReceiptResult(order_id="A017X680406287", status=ExecutionStatus.NEEDS_HUMAN_REVIEW, reason="manual review"),
    ]
    calls: list[str] = []
    job = ReceiptJob(
        order_ids=["A017X680406286", "A017X680406287"],
        output_dir=tmp_path / "runtime" / "receipts",
        min_artifact_bytes=4,
    )

    report = runner.run(
        job=job,
        process_order=lambda order_id: calls.append(order_id) or ReceiptResult(order_id=order_id, status=ExecutionStatus.SUCCEEDED),
        previous_results=previous_results,
    )

    assert calls == ["A017X680406286", "A017X680406287"]
    assert report.succeeded == 2


def test_batch_runner_stops_before_starting_next_order_when_stop_requested(tmp_path: Path) -> None:
    runner = BatchRunner(excel_reader_factory=FakeExcelReader)
    calls: list[str] = []
    stop_requested = {"value": False}
    job = ReceiptJob(
        order_ids=["A017X680406286", "A017X680406287", "A017X680406288"],
        output_dir=tmp_path / "runtime" / "receipts",
    )

    report = runner.run(
        job=job,
        process_order=lambda order_id: calls.append(order_id) or ReceiptResult(order_id=order_id, status=ExecutionStatus.SUCCEEDED),
        on_result=lambda result: stop_requested.__setitem__("value", True),
        should_stop=lambda: stop_requested["value"],
    )

    assert calls == ["A017X680406286"]
    assert report.stopped_early is True
    assert report.completed == 1
    assert report.total == 3
