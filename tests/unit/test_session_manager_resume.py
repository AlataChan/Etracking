from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.models import ExecutionStatus, ReceiptResult
from src.session_manager import SessionManager


@dataclass
class FakeReceiptFlow:
    input_calls: list[str]
    search_calls: int = 0

    def input_order_id(self, order_id: str) -> None:
        self.input_calls.append(order_id)

    def search(self) -> None:
        self.search_calls += 1


class FakePdfPage:
    def __init__(self, url: str) -> None:
        self.url = url

    def screenshot(self, path: str, full_page: bool) -> None:
        Path(path).write_bytes(b"png")


class FakePdfFlow:
    def acquire(self, **kwargs) -> ReceiptResult:
        return ReceiptResult(order_id="A017X680406306", status=ExecutionStatus.SUCCEEDED, metadata={})


def test_process_single_order_skips_refill_and_search_when_result_row_already_exists(monkeypatch, tmp_path: Path) -> None:
    session = SessionManager()
    session.attached_over_cdp = True
    session.page = FakePdfPage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")  # type: ignore[assignment]
    session.receipt_flow = FakeReceiptFlow(input_calls=[])  # type: ignore[assignment]
    session.pdf_flow = FakePdfFlow()  # type: ignore[assignment]

    fill_calls = {"count": 0}
    open_calls: list[str] = []
    monkeypatch.setattr(
        SessionManager,
        "_observe_search_state",
        lambda self, order_id: {"match": {"selector": "tr", "index": 0}, "noResults": False, "loadingVisible": False},
    )
    monkeypatch.setattr(
        SessionManager,
        "_fill_printer_info",
        lambda self: fill_calls.__setitem__("count", fill_calls["count"] + 1),
    )
    monkeypatch.setattr(
        SessionManager,
        "_open_pdf_page_for_order",
        lambda self, order_id: open_calls.append(order_id) or FakePdfPage(url="blob:https://e-tracking.customs.go.th/receipt"),
    )
    monkeypatch.setattr(SessionManager, "_capture_screenshot", lambda self, name, page=None: str(tmp_path / f"{name}.png"))
    monkeypatch.setattr(session.inspector, "snapshot", lambda current_url, screenshot_path=None: {"currentUrl": current_url})

    success = session.process_single_order("A017X680406306")

    assert success is True
    assert fill_calls["count"] == 0
    assert session.receipt_flow.input_calls == []
    assert session.receipt_flow.search_calls == 0
    assert open_calls == ["A017X680406306"]


def test_process_single_order_skips_printer_refill_when_resuming_from_expanded_page(monkeypatch, tmp_path: Path) -> None:
    session = SessionManager()
    session.attached_over_cdp = True
    session.resumed_from_expanded_form = True
    session.page = FakePdfPage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")  # type: ignore[assignment]
    session.receipt_flow = FakeReceiptFlow(input_calls=[])  # type: ignore[assignment]
    session.pdf_flow = FakePdfFlow()  # type: ignore[assignment]

    fill_calls = {"count": 0}
    search_wait_calls = {"count": 0}
    open_calls: list[str] = []
    monkeypatch.setattr(
        SessionManager,
        "_observe_search_state",
        lambda self, order_id: {"match": None, "noResults": False, "loadingVisible": False},
    )
    monkeypatch.setattr(
        SessionManager,
        "_fill_printer_info",
        lambda self: fill_calls.__setitem__("count", fill_calls["count"] + 1),
    )
    monkeypatch.setattr(
        SessionManager,
        "_wait_for_search_results",
        lambda self, order_id: search_wait_calls.__setitem__("count", search_wait_calls["count"] + 1),
    )
    monkeypatch.setattr(
        SessionManager,
        "_open_pdf_page_for_order",
        lambda self, order_id: open_calls.append(order_id) or FakePdfPage(url="blob:https://e-tracking.customs.go.th/receipt"),
    )
    monkeypatch.setattr(SessionManager, "_capture_screenshot", lambda self, name, page=None: str(tmp_path / f"{name}.png"))
    monkeypatch.setattr(session.inspector, "snapshot", lambda current_url, screenshot_path=None: {"currentUrl": current_url})

    success = session.process_single_order("A017X680406306")

    assert success is True
    assert fill_calls["count"] == 0
    assert session.receipt_flow.input_calls == ["A017X680406306"]
    assert search_wait_calls["count"] == 1
    assert open_calls == ["A017X680406306"]
