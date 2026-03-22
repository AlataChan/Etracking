"""
MCP Server adapter for Etracking receipt automation.

Exposes 6 tools over stdio transport:
  run_single, run_batch, retry_failed, get_status, get_artifact, health_check

Usage:
  python -m src.mcp.server
"""

from __future__ import annotations

import threading
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.application.receipt_service import ReceiptApplicationService

mcp = FastMCP(
    "etracking",
    instructions=(
        "Thai Customs E-Tracking receipt download automation. "
        "Use run_single for one order, run_batch for Excel-based batch jobs. "
        "Use get_status/get_artifact to check results. "
        "Only one browser job can run at a time."
    ),
)

_service: ReceiptApplicationService | None = None
_browser_lock = threading.Lock()


def _get_service() -> ReceiptApplicationService:
    global _service
    if _service is None:
        _service = ReceiptApplicationService()
    return _service


# ------------------------------------------------------------------
# Browser job tools (mutually exclusive via _browser_lock)
# ------------------------------------------------------------------


@mcp.tool()
def run_single(order_id: str) -> dict[str, Any]:
    """Download a single receipt PDF by customs order ID.

    Returns the download result with a jobId for later status/artifact queries.
    Only one browser job can run at a time — returns an error if busy.

    Args:
        order_id: Customs order ID, e.g. A017X680406286
    """
    if not _browser_lock.acquire(blocking=False):
        return {"error": "Browser is busy with another job. Try again later."}
    try:
        service = _get_service()
        report = service.run_single(order_id)
        single = report.results[0].to_dict() if report.results else {}
        return {"jobId": report.run_id, **single}
    except Exception as e:
        return {"error": str(e), "orderId": order_id}
    finally:
        _browser_lock.release()


@mcp.tool()
def run_batch(excel_path: str, sheet: str | None = None) -> dict[str, Any]:
    """Download receipt PDFs in batch from an Excel file.

    Processes all order IDs from the specified Excel file and worksheet.
    Writes incremental progress to runtime/reports/<jobId>/.
    Only one browser job can run at a time — returns an error if busy.

    Args:
        excel_path: Path to Excel file containing order IDs
        sheet: Optional worksheet name (uses default if omitted)
    """
    if not _browser_lock.acquire(blocking=False):
        return {"error": "Browser is busy with another job. Try again later."}
    try:
        service = _get_service()
        report = service.run_batch(excel_path=excel_path, sheet_name=sheet)
        return report.to_dict()
    except Exception as e:
        return {"error": str(e), "excelPath": excel_path}
    finally:
        _browser_lock.release()


@mcp.tool()
def retry_failed(job_id: str) -> dict[str, Any]:
    """Retry only the failed orders from a previous batch job.

    Reads the results from the specified job and re-processes orders
    that had status FAILED. Writes a new job report.
    Only one browser job can run at a time — returns an error if busy.

    Args:
        job_id: The job ID from a previous run (e.g. job_20260322_091500)
    """
    if not _browser_lock.acquire(blocking=False):
        return {"error": "Browser is busy with another job. Try again later."}
    try:
        service = _get_service()
        report = service.retry_failed(job_id=job_id)
        return report.to_dict()
    except Exception as e:
        return {"error": str(e), "jobId": job_id}
    finally:
        _browser_lock.release()


# ------------------------------------------------------------------
# Read-only tools (no lock needed)
# ------------------------------------------------------------------


@mcp.tool()
def get_status(job_id: str) -> dict[str, Any]:
    """Get the current status of a batch job.

    Reads the summary.json snapshot from runtime/reports/<job_id>/.
    Can be called while a batch job is still running to see progress.

    Args:
        job_id: The job ID to check (e.g. job_20260322_091500)
    """
    service = _get_service()
    return service.get_status(job_id)


@mcp.tool()
def get_artifact(job_id: str, order_id: str) -> dict[str, Any]:
    """Get metadata about a downloaded receipt PDF artifact.

    Returns file path, size, type, and whether the file exists on disk.

    Args:
        job_id: The job ID that processed this order
        order_id: The specific order ID to look up
    """
    service = _get_service()
    return service.get_artifact(job_id, order_id)


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Check Etracking system health.

    Verifies configuration, browser availability, runtime directories,
    and session state. Use this to diagnose issues before running jobs.
    """
    service = _get_service()
    return service.health_check()


if __name__ == "__main__":
    mcp.run(transport="stdio")
