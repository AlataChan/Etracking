"""Tests for ReceiptApplicationService."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.application.receipt_service import ReceiptApplicationService
from src.core.config import AppSettings
from src.core.models import (
    BatchRunResult,
    ExecutionStatus,
    PdfArtifact,
    ReceiptJob,
    ReceiptResult,
)
from src.core.paths import RuntimePaths


def _make_settings(tmp_path: Path) -> AppSettings:
    from src.core.config import DEFAULT_SETTINGS
    from copy import deepcopy

    raw = deepcopy(DEFAULT_SETTINGS)
    raw["file"]["output_dir"] = str(tmp_path / "runtime" / "receipts")
    return AppSettings(project_root=tmp_path, raw=raw)


def _make_paths(tmp_path: Path, settings: AppSettings) -> RuntimePaths:
    return RuntimePaths.from_settings(settings).ensure()


def _make_service(tmp_path: Path) -> ReceiptApplicationService:
    settings = _make_settings(tmp_path)
    paths = _make_paths(tmp_path, settings)
    return ReceiptApplicationService(settings=settings, paths=paths)


def _fake_receipt_result(order_id: str, artifact_path: Path | None = None) -> ReceiptResult:
    artifact = None
    if artifact_path:
        artifact = PdfArtifact(
            order_id=order_id,
            path=artifact_path,
            source="blob",
            byte_size=1024,
        )
    return ReceiptResult(
        order_id=order_id,
        status=ExecutionStatus.SUCCEEDED,
        artifact=artifact,
    )


class TestRunSingle:
    @patch("src.application.receipt_service.SessionManager")
    def test_returns_batch_result_with_run_id(self, mock_sm_cls, tmp_path):
        service = _make_service(tmp_path)
        mock_session = MagicMock()
        mock_session.process_order_result.return_value = _fake_receipt_result("ORD001")
        mock_sm_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_sm_cls.return_value.__exit__ = MagicMock(return_value=False)

        report = service.run_single("ORD001")

        assert isinstance(report, BatchRunResult)
        assert report.run_id.startswith("job_")
        assert report.total == 1
        assert report.succeeded == 1
        assert len(report.results) == 1
        assert report.results[0].order_id == "ORD001"

    @patch("src.application.receipt_service.SessionManager")
    def test_writes_report_files(self, mock_sm_cls, tmp_path):
        service = _make_service(tmp_path)
        mock_session = MagicMock()
        mock_session.process_order_result.return_value = _fake_receipt_result("ORD001")
        mock_sm_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_sm_cls.return_value.__exit__ = MagicMock(return_value=False)

        report = service.run_single("ORD001")

        assert report.report_dir is not None
        assert report.report_dir.exists()
        assert report.summary_path is not None
        assert report.summary_path.exists()
        assert report.results_path is not None
        assert report.results_path.exists()

        summary = json.loads(report.summary_path.read_text(encoding="utf-8"))
        assert summary["jobId"] == report.run_id
        assert summary["success"] == 1

    @patch("src.application.receipt_service.SessionManager")
    def test_retries_on_exception(self, mock_sm_cls, tmp_path):
        service = _make_service(tmp_path)
        mock_session = MagicMock()
        mock_session.process_order_result.side_effect = [
            RuntimeError("browser crashed"),
            _fake_receipt_result("ORD001"),
        ]
        mock_sm_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_sm_cls.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.application.receipt_service.time.sleep"):
            report = service.run_single("ORD001")

        assert report.succeeded == 1
        assert mock_session.process_order_result.call_count == 2


class TestGetStatus:
    def test_returns_summary_for_existing_job(self, tmp_path):
        service = _make_service(tmp_path)
        settings = _make_settings(tmp_path)
        paths = _make_paths(tmp_path, settings)

        job_id = "job_20260322_120000"
        report_dir = paths.reports_dir / job_id
        report_dir.mkdir(parents=True)
        summary = {"jobId": job_id, "status": "SUCCEEDED", "total": 5}
        (report_dir / "summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )

        result = service.get_status(job_id)
        assert result["jobId"] == job_id
        assert result["total"] == 5

    def test_returns_error_for_missing_job(self, tmp_path):
        service = _make_service(tmp_path)
        result = service.get_status("job_nonexistent")
        assert "error" in result


class TestGetArtifact:
    def test_returns_metadata_for_existing_artifact(self, tmp_path):
        service = _make_service(tmp_path)
        settings = _make_settings(tmp_path)
        paths = _make_paths(tmp_path, settings)

        job_id = "job_20260322_120000"
        report_dir = paths.reports_dir / job_id
        report_dir.mkdir(parents=True)

        artifact_path = paths.receipts_dir / "ORD001.pdf"
        artifact_path.write_bytes(b"%PDF-test-content")

        result_dict = {
            "orderId": "ORD001",
            "status": "SUCCEEDED",
            "reason": "",
            "attempts": 1,
            "metadata": {},
            "artifact": {
                "orderId": "ORD001",
                "path": str(artifact_path),
                "source": "blob",
                "byteSize": 17,
                "contentType": "application/pdf",
            },
        }
        (report_dir / "results.jsonl").write_text(
            json.dumps(result_dict) + "\n", encoding="utf-8"
        )

        result = service.get_artifact(job_id, "ORD001")
        assert result["status"] == "found"
        assert result["fileExists"] is True
        assert result["actualSize"] == 17

    def test_returns_not_found_for_missing_order(self, tmp_path):
        service = _make_service(tmp_path)
        settings = _make_settings(tmp_path)
        paths = _make_paths(tmp_path, settings)

        job_id = "job_20260322_120000"
        report_dir = paths.reports_dir / job_id
        report_dir.mkdir(parents=True)
        (report_dir / "results.jsonl").write_text(
            json.dumps({
                "orderId": "OTHER",
                "status": "SUCCEEDED",
                "reason": "",
                "attempts": 1,
                "metadata": {},
            }) + "\n",
            encoding="utf-8",
        )

        result = service.get_artifact(job_id, "ORD001")
        assert result["status"] == "not_found"


class TestHealthCheck:
    def test_returns_healthy_structure(self, tmp_path):
        service = _make_service(tmp_path)
        result = service.health_check()

        assert "healthy" in result
        assert "checks" in result
        assert "config" in result["checks"]
        assert "browser" in result["checks"]
        assert "runtime" in result["checks"]
        assert "session" in result["checks"]


class TestRetryFailed:
    @patch("src.application.receipt_service.SessionManager")
    def test_accepts_job_id(self, mock_sm_cls, tmp_path):
        service = _make_service(tmp_path)
        settings = _make_settings(tmp_path)
        paths = _make_paths(tmp_path, settings)

        job_id = "job_20260322_120000"
        report_dir = paths.reports_dir / job_id
        report_dir.mkdir(parents=True)

        results_data = [
            {"orderId": "ORD001", "status": "FAILED", "reason": "timeout", "attempts": 1, "metadata": {}},
            {"orderId": "ORD002", "status": "SUCCEEDED", "reason": "", "attempts": 1, "metadata": {}},
        ]
        (report_dir / "results.jsonl").write_text(
            "\n".join(json.dumps(r) for r in results_data) + "\n",
            encoding="utf-8",
        )

        mock_session = MagicMock()
        mock_session.process_order_result.return_value = _fake_receipt_result("ORD001")
        mock_sm_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_sm_cls.return_value.__exit__ = MagicMock(return_value=False)

        report = service.retry_failed(job_id=job_id)

        assert isinstance(report, BatchRunResult)
        mock_session.process_order_result.assert_called_once_with("ORD001")

    def test_raises_without_job_id_or_path(self, tmp_path):
        service = _make_service(tmp_path)
        with pytest.raises(ValueError, match="Either job_id or results_path"):
            service.retry_failed()
