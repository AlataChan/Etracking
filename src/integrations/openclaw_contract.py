from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.models import BatchRunResult


@dataclass(slots=True)
class OpenClawContract:
    def run_batch(self, excel_path: str, sheet: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jobType": "batch",
            "excelPath": excel_path,
        }
        if sheet:
            payload["sheet"] = sheet
        return payload

    def run_single(self, order_id: str) -> dict[str, Any]:
        return {
            "jobType": "single",
            "orderId": order_id,
        }

    def retry_failed(self, job_id: str) -> dict[str, Any]:
        return {
            "jobType": "retry_failed",
            "jobId": job_id,
        }

    def status(self, job_id: str) -> dict[str, Any]:
        return {
            "jobType": "status",
            "jobId": job_id,
        }

    def get_artifact(self, job_id: str, order_id: str) -> dict[str, Any]:
        return {
            "jobType": "get_artifact",
            "jobId": job_id,
            "orderId": order_id,
        }

    def job_response(self, report: BatchRunResult) -> dict[str, Any]:
        payload = report.to_dict()
        return {
            "jobId": payload["jobId"],
            "status": payload["status"],
            "success": payload["success"],
            "failed": payload["failed"],
            "needsHumanReview": payload["needsHumanReview"],
            "artifacts": payload["artifacts"],
        }

    def artifact_response(self, artifact_path: str | Path) -> dict[str, Any]:
        return {
            "status": "SUCCEEDED",
            "artifactPath": str(artifact_path),
        }
