from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
from src.core.results import build_run_id
from src.excel_reader import ExcelReader


class BatchRunner:
    def __init__(self, excel_reader_factory: type[ExcelReader] = ExcelReader) -> None:
        self.excel_reader_factory = excel_reader_factory

    def load_order_ids(self, job: ReceiptJob) -> list[str]:
        if job.order_ids:
            return list(job.order_ids)

        reader = self.excel_reader_factory(job.excel_path)
        return reader.get_order_ids(job.sheet_name)

    def run(
        self,
        job: ReceiptJob,
        process_order: Callable[[str], ReceiptResult | bool],
    ) -> BatchRunResult:
        started_at = datetime.now(UTC)
        run_id = job.run_id or build_run_id(started_at)
        order_ids = self.load_order_ids(job)
        results: list[ReceiptResult] = []

        for order_id in order_ids:
            raw_result = process_order(order_id)
            if isinstance(raw_result, ReceiptResult):
                result = raw_result
            else:
                result = ReceiptResult(
                    order_id=order_id,
                    status=ExecutionStatus.SUCCEEDED if raw_result else ExecutionStatus.FAILED,
                    reason="" if raw_result else "legacy processor returned False",
                )
            results.append(result)

        return BatchRunResult(
            job=ReceiptJob(
                order_ids=order_ids,
                excel_path=Path(job.excel_path) if job.excel_path else None,
                sheet_name=job.sheet_name,
                use_saved_state=job.use_saved_state,
                output_dir=Path(job.output_dir) if job.output_dir else None,
                run_id=run_id,
                max_retries=job.max_retries,
            ),
            run_id=run_id,
            results=results,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )
