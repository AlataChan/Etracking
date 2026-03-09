from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.config import load_settings, with_settings_overrides
from src.core.models import ExecutionStatus, ReceiptResult
from src.session_manager import BatchSessionProcessor, SessionManager


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
        self.closed = False

    def screenshot(self, path: str, full_page: bool) -> None:
        Path(path).write_bytes(b"png")

    def on(self, _event: str, _handler: object) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakePdfFlow:
    def acquire(self, **kwargs) -> ReceiptResult:
        return ReceiptResult(order_id="A017X680406306", status=ExecutionStatus.SUCCEEDED, metadata={})


class FakeSessionContext:
    def __init__(self, results: list[ReceiptResult]) -> None:
        self.results = list(results)
        self.processed_orders: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeSessionContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.closed = True

    def process_order_result(self, order_id: str) -> ReceiptResult:
        self.processed_orders.append(order_id)
        return self.results.pop(0)


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


def test_process_single_order_only_probes_existing_search_state_once_per_session(monkeypatch, tmp_path: Path) -> None:
    session = SessionManager()
    session.attached_over_cdp = True
    session.resumed_from_expanded_form = True
    session.page = FakePdfPage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")  # type: ignore[assignment]
    session.receipt_flow = FakeReceiptFlow(input_calls=[])  # type: ignore[assignment]
    session.pdf_flow = FakePdfFlow()  # type: ignore[assignment]

    poll_calls = {"count": 0}
    open_pages: list[FakePdfPage] = []
    monkeypatch.setattr(
        SessionManager,
        "_poll_search_state",
        lambda self, order_id, timeout_seconds=0: poll_calls.__setitem__("count", poll_calls["count"] + 1)
        or {"match": None, "noResults": False, "loadingVisible": False},
    )
    monkeypatch.setattr(
        SessionManager,
        "_wait_for_search_results",
        lambda self, order_id: None,
    )
    monkeypatch.setattr(
        SessionManager,
        "_capture_screenshot",
        lambda self, name, page=None: str(tmp_path / f"{name}.png"),
    )
    monkeypatch.setattr(
        SessionManager,
        "_open_pdf_page_for_order",
        lambda self, order_id: open_pages.append(FakePdfPage(url=f"blob:https://e-tracking.customs.go.th/{order_id}"))
        or open_pages[-1],
    )
    monkeypatch.setattr(session.inspector, "snapshot", lambda current_url, screenshot_path=None: {"currentUrl": current_url})

    first = session.process_single_order("A017X680406306")
    second = session.process_single_order("A017X680406307")

    assert first is True
    assert second is True
    assert poll_calls["count"] == 1
    assert session.receipt_flow.input_calls == ["A017X680406306", "A017X680406307"]


def test_process_single_order_can_skip_success_pdf_viewer_screenshot(monkeypatch, tmp_path: Path) -> None:
    settings = with_settings_overrides(
        load_settings(project_root=tmp_path),
        {"batch": {"capture_pdf_viewer_screenshot": False}},
    )
    session = SessionManager(settings=settings)
    session.attached_over_cdp = True
    session.resumed_from_expanded_form = True
    session.page = FakePdfPage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")  # type: ignore[assignment]
    session.receipt_flow = FakeReceiptFlow(input_calls=[])  # type: ignore[assignment]
    session.pdf_flow = FakePdfFlow()  # type: ignore[assignment]

    capture_calls: list[str] = []
    popup_page = FakePdfPage(url="blob:https://e-tracking.customs.go.th/receipt")
    monkeypatch.setattr(SessionManager, "_poll_search_state", lambda self, order_id, timeout_seconds=0: {"match": None})
    monkeypatch.setattr(SessionManager, "_wait_for_search_results", lambda self, order_id: None)
    monkeypatch.setattr(SessionManager, "_open_pdf_page_for_order", lambda self, order_id: popup_page)
    monkeypatch.setattr(
        SessionManager,
        "_capture_screenshot",
        lambda self, name, page=None: capture_calls.append(name) or str(tmp_path / f"{name}.png"),
    )
    monkeypatch.setattr(session.inspector, "snapshot", lambda current_url, screenshot_path=None: {"currentUrl": current_url})

    success = session.process_single_order("A017X680406306")

    assert success is True
    assert capture_calls == []
    assert popup_page.closed is True


def test_batch_session_processor_recycles_after_completed_order_threshold() -> None:
    sessions: list[FakeSessionContext] = []
    session_results = [
        [
            ReceiptResult(order_id="A017X680406286", status=ExecutionStatus.SUCCEEDED),
            ReceiptResult(order_id="A017X680406287", status=ExecutionStatus.SUCCEEDED),
        ],
        [
            ReceiptResult(order_id="A017X680406288", status=ExecutionStatus.SUCCEEDED),
        ],
    ]

    def factory(**kwargs) -> FakeSessionContext:
        session = FakeSessionContext(session_results[len(sessions)])
        sessions.append(session)
        return session

    processor = BatchSessionProcessor(
        session_factory=factory,
        recycle_every_orders=2,
        recycle_after_retryable_failures=5,
    )

    processor.process_order_result("A017X680406286")
    processor.process_order_result("A017X680406287")
    processor.process_order_result("A017X680406288")
    processor.close()

    assert len(sessions) == 2
    assert sessions[0].processed_orders == ["A017X680406286", "A017X680406287"]
    assert sessions[1].processed_orders == ["A017X680406288"]
    assert sessions[0].closed is True
    assert sessions[1].closed is True


def test_batch_session_processor_recycles_after_retryable_failures() -> None:
    sessions: list[FakeSessionContext] = []
    session_results = [
        [
            ReceiptResult(
                order_id="A017X680406286",
                status=ExecutionStatus.FAILED,
                metadata={"retryable": True},
            ),
            ReceiptResult(
                order_id="A017X680406287",
                status=ExecutionStatus.FAILED,
                metadata={"retryable": True},
            ),
        ],
        [
            ReceiptResult(order_id="A017X680406288", status=ExecutionStatus.SUCCEEDED),
        ],
    ]

    def factory(**kwargs) -> FakeSessionContext:
        session = FakeSessionContext(session_results[len(sessions)])
        sessions.append(session)
        return session

    processor = BatchSessionProcessor(
        session_factory=factory,
        recycle_every_orders=50,
        recycle_after_retryable_failures=2,
    )

    processor.process_order_result("A017X680406286")
    processor.process_order_result("A017X680406287")
    processor.process_order_result("A017X680406288")
    processor.close()

    assert len(sessions) == 2
    assert sessions[0].processed_orders == ["A017X680406286", "A017X680406287"]
    assert sessions[1].processed_orders == ["A017X680406288"]
    assert sessions[0].closed is True
