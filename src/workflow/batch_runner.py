from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
from src.core.results import build_run_id, latest_results_by_order, result_has_valid_artifact
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
        previous_results: list[ReceiptResult] | None = None,
        on_result: Callable[[ReceiptResult], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> BatchRunResult:
        started_at = datetime.now(UTC)
        run_id = job.run_id or build_run_id(started_at)
        order_ids = self.load_order_ids(job)
        results_by_order = latest_results_by_order(previous_results or [])
        stopped_early = False

        for order_id in order_ids:
            if should_stop and should_stop():
                stopped_early = True
                break

            previous = results_by_order.get(order_id)
            if previous and self._should_skip_previous_result(previous, job.min_artifact_bytes):
                continue

            result = self._run_single_order(
                order_id=order_id,
                process_order=process_order,
                max_attempts=max(1, job.max_retries),
            )
            results_by_order[order_id] = result
            if on_result is not None:
                on_result(result)

        results = [results_by_order[order_id] for order_id in order_ids if order_id in results_by_order]

        return BatchRunResult(
            job=ReceiptJob(
                order_ids=order_ids,
                excel_path=Path(job.excel_path) if job.excel_path else None,
                sheet_name=job.sheet_name,
                use_saved_state=job.use_saved_state,
                output_dir=Path(job.output_dir) if job.output_dir else None,
                run_id=run_id,
                max_retries=job.max_retries,
                min_artifact_bytes=job.min_artifact_bytes,
                resume_results_path=Path(job.resume_results_path) if job.resume_results_path else None,
            ),
            run_id=run_id,
            results=results,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            planned_total=len(order_ids),
            stopped_early=stopped_early,
        )

    def _run_single_order(
        self,
        order_id: str,
        process_order: Callable[[str], ReceiptResult | bool],
        max_attempts: int,
    ) -> ReceiptResult:
        attempts = 0
        latest_result: ReceiptResult | None = None

        while attempts < max_attempts:
            attempts += 1
            raw_result = process_order(order_id)
            if isinstance(raw_result, ReceiptResult):
                latest_result = raw_result
            else:
                latest_result = ReceiptResult(
                    order_id=order_id,
                    status=ExecutionStatus.SUCCEEDED if raw_result else ExecutionStatus.FAILED,
                    reason="" if raw_result else "legacy processor returned False",
                )
            latest_result.attempts = attempts

            retryable = bool(latest_result.metadata.get("retryable"))
            if latest_result.status is ExecutionStatus.SUCCEEDED:
                return latest_result
            if not retryable:
                return latest_result

        if latest_result is None:
            return ReceiptResult(
                order_id=order_id,
                status=ExecutionStatus.FAILED,
                reason="no execution result produced",
            )
        return latest_result

    def _should_skip_previous_result(self, result: ReceiptResult, min_artifact_bytes: int) -> bool:
        return result_has_valid_artifact(result, min_bytes=min_artifact_bytes)

    def retry_failed_job(
        self,
        previous_results: list[ReceiptResult],
        base_job: ReceiptJob | None = None,
    ) -> ReceiptJob:
        return ReceiptJob(
            order_ids=[
                result.order_id
                for result in previous_results
                if result.status is ExecutionStatus.FAILED
            ],
            excel_path=base_job.excel_path if base_job else None,
            sheet_name=base_job.sheet_name if base_job else None,
            use_saved_state=base_job.use_saved_state if base_job else True,
            output_dir=base_job.output_dir if base_job else None,
            max_retries=base_job.max_retries if base_job else 1,
        )
