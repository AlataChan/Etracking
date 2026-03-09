from pathlib import Path

from src.core.models import ExecutionStatus
from src.workflow.pdf_flow import PdfFlow


def test_pdf_flow_uses_direct_then_download_then_export_order(tmp_path: Path) -> None:
    pdf_path = tmp_path / "A017X680406286.pdf"
    calls: list[str] = []

    def direct() -> bytes | None:
        calls.append("direct")
        return None

    def browser_download() -> bytes | None:
        calls.append("download")
        return b"%PDF-1.7\norder A017X680406286\n" + (b"x" * 256)

    def export_pdf() -> bytes | None:
        calls.append("export")
        return b"%PDF-1.7\nunused\n"

    flow = PdfFlow(min_bytes=128)
    result = flow.acquire(
        order_id="A017X680406286",
        pdf_path=pdf_path,
        direct_fetch=direct,
        browser_download=browser_download,
        export_pdf=export_pdf,
    )

    assert calls == ["direct", "download"]
    assert result.status is ExecutionStatus.SUCCEEDED
    assert pdf_path.exists()


def test_pdf_flow_never_marks_screenshot_fallback_as_success(tmp_path: Path) -> None:
    pdf_path = tmp_path / "A017X680406286.pdf"
    screenshot_path = tmp_path / "A017X680406286.png"
    screenshot_path.write_bytes(b"png")

    flow = PdfFlow(min_bytes=128)
    result = flow.acquire(
        order_id="A017X680406286",
        pdf_path=pdf_path,
        screenshot_path=screenshot_path,
        direct_fetch=lambda: None,
        browser_download=lambda: None,
        export_pdf=lambda: None,
    )

    assert result.status is ExecutionStatus.NEEDS_HUMAN_REVIEW


def test_pdf_flow_accepts_list_of_ints_from_browser_evaluate(tmp_path: Path) -> None:
    pdf_path = tmp_path / "A017X680406306.pdf"

    flow = PdfFlow(min_bytes=128)
    result = flow.acquire(
        order_id="A017X680406306",
        pdf_path=pdf_path,
        direct_fetch=lambda: list(b"%PDF-1.7\norder A017X680406306\n" + (b"x" * 256)),
        browser_download=lambda: None,
        export_pdf=lambda: None,
    )

    assert result.status is ExecutionStatus.SUCCEEDED
    assert pdf_path.exists()
