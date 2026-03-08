from pathlib import Path

from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
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
