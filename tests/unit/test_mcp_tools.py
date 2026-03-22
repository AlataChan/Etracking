"""Tests for MCP server tool surface."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
from src.mcp.server import (
    _browser_lock,
    get_artifact,
    get_status,
    health_check,
    run_single,
    retry_failed,
    run_batch,
)


def _fake_report(run_id: str = "job_test_001") -> BatchRunResult:
    return BatchRunResult(
        job=ReceiptJob(order_ids=["ORD001"]),
        run_id=run_id,
        results=[
            ReceiptResult(order_id="ORD001", status=ExecutionStatus.SUCCEEDED),
        ],
        started_at=__import__("datetime").datetime(2026, 3, 22, 12, 0, 0),
        finished_at=__import__("datetime").datetime(2026, 3, 22, 12, 1, 0),
        planned_total=1,
    )


class TestRunSingleTool:
    @patch("src.mcp.server._get_service")
    def test_returns_job_id_and_result(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.run_single.return_value = _fake_report()
        mock_get_service.return_value = mock_service

        result = run_single("ORD001")

        assert result["jobId"] == "job_test_001"
        assert result["orderId"] == "ORD001"
        assert result["status"] == "SUCCEEDED"
        mock_service.run_single.assert_called_once_with("ORD001")

    @patch("src.mcp.server._get_service")
    def test_returns_error_on_exception(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.run_single.side_effect = RuntimeError("browser crashed")
        mock_get_service.return_value = mock_service

        result = run_single("ORD001")

        assert "error" in result
        assert "browser crashed" in result["error"]


class TestBrowserLock:
    @patch("src.mcp.server._get_service")
    def test_returns_busy_when_locked(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        _browser_lock.acquire()
        try:
            result = run_single("ORD001")
            assert "error" in result
            assert "busy" in result["error"].lower()
            mock_service.run_single.assert_not_called()
        finally:
            _browser_lock.release()

    @patch("src.mcp.server._get_service")
    def test_lock_released_after_error(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.run_single.side_effect = RuntimeError("crash")
        mock_get_service.return_value = mock_service

        run_single("ORD001")

        assert not _browser_lock.locked()


class TestReadOnlyTools:
    @patch("src.mcp.server._get_service")
    def test_get_status_delegates_to_service(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.get_status.return_value = {"jobId": "job_001", "status": "SUCCEEDED"}
        mock_get_service.return_value = mock_service

        result = get_status("job_001")

        assert result["jobId"] == "job_001"
        mock_service.get_status.assert_called_once_with("job_001")

    @patch("src.mcp.server._get_service")
    def test_get_artifact_delegates_to_service(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.get_artifact.return_value = {"status": "found", "path": "/test.pdf"}
        mock_get_service.return_value = mock_service

        result = get_artifact("job_001", "ORD001")

        assert result["status"] == "found"
        mock_service.get_artifact.assert_called_once_with("job_001", "ORD001")

    @patch("src.mcp.server._get_service")
    def test_health_check_delegates_to_service(self, mock_get_service):
        mock_service = MagicMock()
        mock_service.health_check.return_value = {"healthy": True, "checks": {}}
        mock_get_service.return_value = mock_service

        result = health_check()

        assert result["healthy"] is True
        mock_service.health_check.assert_called_once()
