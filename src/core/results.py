from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from src.core.models import BatchRunResult, ExecutionStatus, PdfArtifact, ReceiptResult


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


def receipt_result_from_dict(payload: dict[str, object]) -> ReceiptResult:
    artifact_payload = payload.get("artifact")
    artifact = None
    if isinstance(artifact_payload, dict):
        artifact = PdfArtifact(
            order_id=str(artifact_payload["orderId"]),
            path=Path(str(artifact_payload["path"])),
            source=str(artifact_payload["source"]),
            byte_size=int(artifact_payload["byteSize"]),
            content_type=str(artifact_payload.get("contentType", "application/pdf")),
        )

    metadata = payload.get("metadata")
    return ReceiptResult(
        order_id=str(payload["orderId"]),
        status=ExecutionStatus(str(payload["status"])),
        artifact=artifact,
        reason=str(payload.get("reason", "")),
        attempts=int(payload.get("attempts", 1)),
        screenshot_path=Path(str(payload["screenshotPath"])) if payload.get("screenshotPath") else None,
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def load_results_jsonl(path: str | Path) -> list[ReceiptResult]:
    results: list[ReceiptResult] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            results.append(receipt_result_from_dict(json.loads(stripped)))
    return results
