from pathlib import Path

from src.core.models import ExecutionStatus
from src.support.validation import PdfValidationPolicy, validate_pdf_artifact


def test_real_pdf_is_reported_as_success(tmp_path: Path) -> None:
    pdf_path = tmp_path / "A017X680406286_20260308.pdf"
    pdf_bytes = b"%PDF-1.7\n" + (b"order A017X680406286\n" * 32) + b"%%EOF\n"
    pdf_path.write_bytes(pdf_bytes)

    result = validate_pdf_artifact(
        order_id="A017X680406286",
        pdf_path=pdf_path,
        policy=PdfValidationPolicy(min_bytes=128),
    )

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.artifact is not None
    assert result.artifact.byte_size == pdf_path.stat().st_size


def test_marker_pdf_and_screenshot_are_not_reported_as_success(tmp_path: Path) -> None:
    pdf_path = tmp_path / "A017X680406286_20260308.pdf"
    screenshot_path = tmp_path / "A017X680406286_20260308.png"
    pdf_path.write_bytes(
        b"%PDF-1.5\n%This is an auto-generated PDF marker, full page was saved as PNG\n%EOF\n"
    )
    screenshot_path.write_bytes(b"png-bytes")

    result = validate_pdf_artifact(
        order_id="A017X680406286",
        pdf_path=pdf_path,
        fallback_path=screenshot_path,
        policy=PdfValidationPolicy(min_bytes=128),
    )

    assert result.status is ExecutionStatus.NEEDS_HUMAN_REVIEW
    assert "marker" in result.reason.lower() or "png" in result.reason.lower()
