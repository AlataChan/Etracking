from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.models import ExecutionStatus, PdfArtifact, ReceiptResult


@dataclass(slots=True, frozen=True)
class PdfValidationPolicy:
    min_bytes: int = 1024


def _looks_like_marker_pdf(pdf_bytes: bytes) -> bool:
    lowered = pdf_bytes.lower()
    return b"auto-generated pdf marker" in lowered or b"saved as png" in lowered


def _contains_order_reference(order_id: str, pdf_path: Path, sample: bytes) -> bool:
    if order_id in pdf_path.stem:
        return True
    return order_id.encode("utf-8") in sample


def validate_pdf_artifact(
    order_id: str,
    pdf_path: Path,
    fallback_path: Path | None = None,
    source: str = "browser-download",
    policy: PdfValidationPolicy | None = None,
) -> ReceiptResult:
    effective_policy = policy or PdfValidationPolicy()
    screenshot_path = fallback_path if fallback_path and fallback_path.exists() else None

    if not pdf_path.exists():
        status = (
            ExecutionStatus.NEEDS_HUMAN_REVIEW
            if screenshot_path is not None
            else ExecutionStatus.FAILED
        )
        return ReceiptResult(
            order_id=order_id,
            status=status,
            reason="pdf artifact does not exist",
            screenshot_path=screenshot_path,
        )

    pdf_bytes = pdf_path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF"):
        status = (
            ExecutionStatus.NEEDS_HUMAN_REVIEW
            if screenshot_path is not None
            else ExecutionStatus.FAILED
        )
        return ReceiptResult(
            order_id=order_id,
            status=status,
            reason="artifact is not a real PDF",
            screenshot_path=screenshot_path,
        )

    if _looks_like_marker_pdf(pdf_bytes):
        return ReceiptResult(
            order_id=order_id,
            status=ExecutionStatus.NEEDS_HUMAN_REVIEW if screenshot_path else ExecutionStatus.FAILED,
            reason="marker PDF detected; screenshot fallback cannot be treated as success",
            screenshot_path=screenshot_path,
        )

    if len(pdf_bytes) < effective_policy.min_bytes:
        status = (
            ExecutionStatus.NEEDS_HUMAN_REVIEW
            if screenshot_path is not None
            else ExecutionStatus.FAILED
        )
        return ReceiptResult(
            order_id=order_id,
            status=status,
            reason=f"pdf is smaller than minimum threshold ({effective_policy.min_bytes} bytes)",
            screenshot_path=screenshot_path,
        )

    if not _contains_order_reference(order_id, pdf_path, pdf_bytes[:8192]):
        return ReceiptResult(
            order_id=order_id,
            status=ExecutionStatus.FAILED,
            reason="pdf could not be associated with the requested order id",
            screenshot_path=screenshot_path,
        )

    return ReceiptResult(
        order_id=order_id,
        status=ExecutionStatus.SUCCEEDED,
        artifact=PdfArtifact(
            order_id=order_id,
            path=pdf_path,
            source=source,
            byte_size=len(pdf_bytes),
        ),
        screenshot_path=screenshot_path,
    )
