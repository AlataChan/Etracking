"""
Application service layer for Etracking receipt processing.

Provides a unified API for CLI, MCP, and HTTP adapters.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from src.core.config import AppSettings, load_settings
from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
from src.core.paths import RuntimePaths
from src.core.results import (
    build_run_id,
    latest_results_by_order,
    load_results_jsonl,
    run_id_from_results_path,
)
from src.integrations.report_writer import ReportWriter
from src.integrations.run_ledger import RunLedger
from src.session_manager import BatchSessionProcessor, SessionManager
from src.workflow.batch_runner import BatchRunner


class ReceiptApplicationService:
    """Core application service — the single entry point for all adapters."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        paths: RuntimePaths | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._paths = paths or RuntimePaths.from_settings(self._settings).ensure()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_single(
        self,
        order_id: str,
        use_saved_state: bool = True,
    ) -> BatchRunResult:
        """Process a single order and write a job report."""
        started_at = datetime.now(UTC)
        run_id = build_run_id(started_at)

        logger.info(f"\n===== 处理订单: {order_id} =====")
        result = self._process_single_with_retry(order_id, use_saved_state)

        job = ReceiptJob(
            order_ids=[order_id],
            use_saved_state=use_saved_state,
            output_dir=self._paths.receipts_dir,
            run_id=run_id,
            max_retries=self._settings.max_retries,
        )
        report = BatchRunResult(
            job=job,
            run_id=run_id,
            results=[result],
            started_at=started_at,
            finished_at=datetime.now(UTC),
            planned_total=1,
        )

        writer = ReportWriter(self._paths)
        return writer.write(report)

    def run_batch(
        self,
        excel_path: str | Path | None = None,
        sheet_name: str | None = None,
        resume_results_path: str | Path | None = None,
        use_saved_state: bool = True,
        should_stop: Callable[[], bool] | None = None,
    ) -> BatchRunResult:
        """Process batch orders from Excel."""
        started_at = datetime.now(UTC)
        logger.info("\n===== 开始批量处理订单 =====")

        runner = BatchRunner()
        resume_path = Path(resume_results_path) if resume_results_path else None
        run_id = run_id_from_results_path(resume_path) if resume_path else None

        job = ReceiptJob(
            order_ids=[],
            excel_path=Path(excel_path) if excel_path else self._settings.excel_path,
            sheet_name=sheet_name or self._settings.excel_sheet_name,
            use_saved_state=use_saved_state,
            output_dir=self._paths.receipts_dir,
            run_id=run_id,
            max_retries=self._settings.max_retries,
            min_artifact_bytes=self._settings.min_pdf_bytes,
            resume_results_path=resume_path,
        )
        job.order_ids = runner.load_order_ids(job)
        if not job.run_id:
            job.run_id = build_run_id(started_at)

        writer = ReportWriter(self._paths)
        previous_results = load_results_jsonl(resume_path) if resume_path else []
        effective_results = latest_results_by_order(previous_results)
        ledger = RunLedger(self._paths.report_paths_for(job.run_id))

        processor = BatchSessionProcessor(
            use_saved_state=use_saved_state,
            settings=self._settings,
            paths=self._paths,
        )

        def snapshot_report(finished_at: datetime | None = None) -> BatchRunResult:
            ordered = [
                effective_results[oid]
                for oid in job.order_ids
                if oid in effective_results
            ]
            return BatchRunResult(
                job=job,
                run_id=job.run_id or "",
                results=ordered,
                started_at=started_at,
                finished_at=finished_at,
                planned_total=len(job.order_ids),
                stopped_early=should_stop() if should_stop else False,
            )

        def on_result(result: ReceiptResult) -> None:
            effective_results[result.order_id] = result
            ledger.append_result(result)
            ledger.write_summary_snapshot(snapshot_report())

        ledger.write_summary_snapshot(snapshot_report())

        try:
            report = runner.run(
                job=job,
                process_order=processor.process_order_result,
                previous_results=previous_results,
                on_result=on_result,
                should_stop=should_stop,
            )
        finally:
            processor.close()

        return writer.write(report)

    def retry_failed(
        self,
        job_id: str | None = None,
        results_path: str | Path | None = None,
        use_saved_state: bool = True,
    ) -> BatchRunResult:
        """Retry failed orders from a previous job."""
        if job_id:
            resolved_path = self._paths.report_paths_for(job_id).results_path
        elif results_path:
            resolved_path = Path(results_path)
        else:
            raise ValueError("Either job_id or results_path must be provided")

        previous_results = load_results_jsonl(resolved_path)
        runner = BatchRunner()
        retry_job = runner.retry_failed_job(
            previous_results,
            base_job=ReceiptJob(
                order_ids=[],
                use_saved_state=use_saved_state,
                output_dir=self._paths.receipts_dir,
                max_retries=self._settings.max_retries,
            ),
        )
        writer = ReportWriter(self._paths)

        with SessionManager(
            use_saved_state=use_saved_state,
            settings=self._settings,
            paths=self._paths,
        ) as session:
            report = runner.run(
                job=retry_job,
                process_order=session.process_order_result,
            )

        return writer.write(report)

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Read job status from summary.json snapshot."""
        summary_path = self._paths.report_paths_for(job_id).summary_path
        if not summary_path.exists():
            return {"error": f"Job {job_id} not found", "jobId": job_id}
        return json.loads(summary_path.read_text(encoding="utf-8"))

    def get_artifact(self, job_id: str, order_id: str) -> dict[str, Any]:
        """Look up artifact metadata for a specific order within a job."""
        results_path = self._paths.report_paths_for(job_id).results_path
        if not results_path.exists():
            return {
                "error": f"Job {job_id} not found",
                "jobId": job_id,
                "orderId": order_id,
            }

        results = load_results_jsonl(results_path)
        for result in results:
            if result.order_id == order_id and result.artifact:
                artifact = result.artifact
                exists = artifact.path.exists()
                return {
                    "jobId": job_id,
                    "orderId": order_id,
                    "status": "found",
                    "path": str(artifact.path),
                    "source": artifact.source,
                    "byteSize": artifact.byte_size,
                    "contentType": artifact.content_type,
                    "fileExists": exists,
                    "actualSize": artifact.path.stat().st_size if exists else 0,
                }

        return {
            "jobId": job_id,
            "orderId": order_id,
            "status": "not_found",
            "reason": "No artifact found for this order in the specified job",
        }

    def health_check(self) -> dict[str, Any]:
        """Check system health: config, browser, runtime paths, session."""
        checks: dict[str, Any] = {}

        checks["config"] = {
            "status": "ok",
            "loginUrl": self._settings.login_url,
            "hasTaxId": bool(self._settings.tax_id),
            "hasBranchId": bool(self._settings.branch_id),
        }

        cdp_url = self._settings.browser_cdp_url
        if cdp_url:
            checks["browser"] = {
                "mode": "cdp",
                "cdpUrl": cdp_url,
                "status": "configured",
            }
        else:
            checks["browser"] = {
                "mode": "playwright",
                "headless": self._settings.browser_headless,
                "status": "configured",
            }

        checks["runtime"] = {
            "status": "ok",
            "receiptsDir": str(self._paths.receipts_dir),
            "reportsDir": str(self._paths.reports_dir),
            "receiptsExists": self._paths.receipts_dir.exists(),
            "reportsExists": self._paths.reports_dir.exists(),
        }

        session_file = self._paths.session_state_file
        checks["session"] = {
            "status": "ok" if session_file.exists() else "no_saved_state",
            "path": str(session_file),
        }

        healthy = all(
            c.get("status") in ("ok", "configured", "no_saved_state")
            for c in checks.values()
        )

        return {"healthy": healthy, "checks": checks}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_single_with_retry(
        self,
        order_id: str,
        use_saved_state: bool,
    ) -> ReceiptResult:
        """Process a single order with exception-level retry."""
        max_retries = self._settings.max_retries
        delay = self._settings.retry_delay

        for retry in range(max_retries):
            try:
                current_saved_state = use_saved_state and retry == 0
                with SessionManager(
                    use_saved_state=current_saved_state,
                    settings=self._settings,
                    paths=self._paths,
                ) as session:
                    return session.process_order_result(order_id)
            except Exception as e:
                if retry < max_retries - 1:
                    logger.warning(f"第{retry + 1}次尝试失败，准备重试: {e}")
                    time.sleep(delay)
                    continue
                logger.exception(f"处理订单 {order_id} 时出错: {e}")

        return ReceiptResult(
            order_id=order_id,
            status=ExecutionStatus.FAILED,
            reason="all retries exhausted before a valid PDF was captured",
        )
