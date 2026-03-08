from __future__ import annotations

from datetime import UTC, datetime

from src.core.models import BatchRunResult, ExecutionStatus, ReceiptResult


def build_run_id(now: datetime | None = None) -> str:
    timestamp = now or datetime.now(UTC)
    return f"job_{timestamp:%Y%m%d_%H%M%S}"


def summarize_results(results: list[ReceiptResult]) -> dict[str, int]:
    return {
        "total": len(results),
        "success": sum(result.status is ExecutionStatus.SUCCEEDED for result in results),
        "failed": sum(result.status is ExecutionStatus.FAILED for result in results),
        "needsHumanReview": sum(
            result.status is ExecutionStatus.NEEDS_HUMAN_REVIEW for result in results
        ),
    }


def report_status(report: BatchRunResult) -> ExecutionStatus:
    if report.needs_human_review:
        return ExecutionStatus.NEEDS_HUMAN_REVIEW
    if report.failed:
        return ExecutionStatus.FAILED
    return ExecutionStatus.SUCCEEDED
