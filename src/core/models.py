from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ExecutionStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


OrderId = str


@dataclass(slots=True, frozen=True)
class PdfArtifact:
    order_id: OrderId
    path: Path
    source: str
    byte_size: int
    content_type: str = "application/pdf"

    def to_dict(self) -> dict[str, Any]:
        return {
            "orderId": self.order_id,
            "path": str(self.path),
            "source": self.source,
            "byteSize": self.byte_size,
            "contentType": self.content_type,
        }


@dataclass(slots=True)
class ReceiptJob:
    order_ids: list[OrderId]
    excel_path: Path | None = None
    sheet_name: str | None = None
    use_saved_state: bool = True
    output_dir: Path | None = None
    run_id: str | None = None
    max_retries: int = 1
    min_artifact_bytes: int = 1
    resume_results_path: Path | None = None


@dataclass(slots=True)
class ReceiptResult:
    order_id: OrderId
    status: ExecutionStatus
    artifact: PdfArtifact | None = None
    reason: str = ""
    attempts: int = 1
    screenshot_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "orderId": self.order_id,
            "status": self.status.value,
            "reason": self.reason,
            "attempts": self.attempts,
            "metadata": self.metadata,
        }
        if self.artifact is not None:
            payload["artifact"] = self.artifact.to_dict()
        if self.screenshot_path is not None:
            payload["screenshotPath"] = str(self.screenshot_path)
        return payload


@dataclass(slots=True)
class BatchRunResult:
    job: ReceiptJob
    run_id: str
    results: list[ReceiptResult]
    started_at: datetime
    finished_at: datetime | None
    planned_total: int | None = None
    stopped_early: bool = False
    report_dir: Path | None = None
    summary_path: Path | None = None
    results_path: Path | None = None
    csv_path: Path | None = None

    @property
    def total(self) -> int:
        return self.planned_total if self.planned_total is not None else len(self.results)

    @property
    def completed(self) -> int:
        return len(self.results)

    @property
    def remaining(self) -> int:
        return max(self.total - self.completed, 0)

    @property
    def succeeded(self) -> int:
        return sum(result.status is ExecutionStatus.SUCCEEDED for result in self.results)

    @property
    def failed(self) -> int:
        return sum(result.status is ExecutionStatus.FAILED for result in self.results)

    @property
    def needs_human_review(self) -> int:
        return sum(result.status is ExecutionStatus.NEEDS_HUMAN_REVIEW for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.run_id,
            "status": (
                ExecutionStatus.NEEDS_HUMAN_REVIEW.value
                if self.needs_human_review
                else ExecutionStatus.FAILED.value
                if self.failed
                else ExecutionStatus.SUCCEEDED.value
            ),
            "success": self.succeeded,
            "failed": self.failed,
            "needsHumanReview": self.needs_human_review,
            "total": self.total,
            "completed": self.completed,
            "remaining": self.remaining,
            "startedAt": self.started_at.isoformat(),
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
            "stoppedEarly": self.stopped_early,
            "artifacts": [
                str(result.artifact.path)
                for result in self.results
                if result.artifact is not None
            ],
            "results": [result.to_dict() for result in self.results],
        }
