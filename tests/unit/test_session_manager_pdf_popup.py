from __future__ import annotations

from dataclasses import dataclass

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.session_manager import SessionManager


class FakeClickable:
    def __init__(self, owner: "FakeRow", selector: str) -> None:
        self.owner = owner
        self.selector = selector

    def click(self) -> None:
        self.owner.clicked_selector = self.selector


class FakeChildLocator:
    def __init__(self, owner: "FakeRow", selector: str, count: int) -> None:
        self.owner = owner
        self.selector = selector
        self._count = count

    def count(self) -> int:
        return self._count

    @property
    def last(self) -> FakeClickable:
        return FakeClickable(self.owner, self.selector)


class FakeRow:
    def __init__(self, child_counts: dict[str, int] | None = None) -> None:
        self.child_counts = child_counts or {}
        self.clicked_selector: str | None = None

    def locator(self, selector: str) -> FakeChildLocator:
        return FakeChildLocator(self, selector, self.child_counts.get(selector, 0))


class FakeCollectionLocator:
    def __init__(self, rows: list[FakeRow]) -> None:
        self.rows = rows

    def nth(self, index: int) -> FakeRow:
        return self.rows[index]


class FakePage:
    def __init__(self, evaluate_result: object | None = None, url: str = "https://customs.invalid/result") -> None:
        self.evaluate_result = evaluate_result
        self.url = url
        self.locators: dict[str, object] = {}

    def evaluate(self, _script: str, _arg: object | None = None) -> object | None:
        return self.evaluate_result

    def locator(self, selector: str) -> object:
        return self.locators[selector]

    def on(self, _event: str, _handler: object) -> None:
        return None


class FakeExpectPage:
    def __init__(self, popup_page: FakePage | None = None, error: Exception | None = None) -> None:
        self.popup_page = popup_page
        self.error = error
        self.value: FakePage | None = None

    def __enter__(self) -> "FakeExpectPage":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.error is not None:
            raise self.error
        self.value = self.popup_page


class FakeContext:
    def __init__(self, popup_page: FakePage | None = None, error: Exception | None = None) -> None:
        self.popup_page = popup_page
        self.error = error
        self.timeout_ms: int | None = None

    def expect_page(self, timeout: int) -> FakeExpectPage:
        self.timeout_ms = timeout
        return FakeExpectPage(popup_page=self.popup_page, error=self.error)


def test_session_manager_clicks_rightmost_print_icon_in_matching_row() -> None:
    row = FakeRow(
        child_counts={
            "button:has(img[src*='icon_printer_fee'])": 2,
            "img[src*='icon_printer_fee']": 1,
        }
    )
    page = FakePage(
        evaluate_result={
            "match": {"selector": "tr", "index": 0},
            "noResults": False,
            "loadingVisible": False,
        }
    )
    page.locators["tr"] = FakeCollectionLocator([row])

    session = SessionManager()
    session.page = page  # type: ignore[assignment]

    session._click_print_icon_for_order("A017X680406306")

    assert row.clicked_selector == "button:has(img[src*='icon_printer_fee'])"


def test_session_manager_uses_popup_page_for_pdf_capture(monkeypatch) -> None:
    popup_page = FakePage(url="blob:https://e-tracking.customs.go.th/receipt")
    context = FakeContext(popup_page=popup_page)
    session = SessionManager()
    session.context = context  # type: ignore[assignment]
    session.page = FakePage()  # type: ignore[assignment]

    clicked_orders: list[str] = []
    waited_pages: list[str] = []
    monkeypatch.setattr(
        session,
        "_click_print_icon_for_order",
        lambda order_id: clicked_orders.append(order_id),
    )
    monkeypatch.setattr(
        session,
        "_wait_for_pdf_viewer_ready",
        lambda pdf_page: waited_pages.append(pdf_page.url),
    )

    resolved = session._open_pdf_page_for_order("A017X680406306")

    assert resolved is popup_page
    assert clicked_orders == ["A017X680406306"]
    assert waited_pages == ["blob:https://e-tracking.customs.go.th/receipt"]
    assert context.timeout_ms == 15000


def test_session_manager_falls_back_when_popup_is_not_observed(monkeypatch) -> None:
    fallback_page = FakePage(url="blob:https://e-tracking.customs.go.th/fallback")
    context = FakeContext(error=PlaywrightTimeoutError("timeout"))
    session = SessionManager()
    session.context = context  # type: ignore[assignment]
    session.page = FakePage()  # type: ignore[assignment]

    clicked_orders: list[str] = []
    waited_pages: list[str] = []
    monkeypatch.setattr(
        session,
        "_click_print_icon_for_order",
        lambda order_id: clicked_orders.append(order_id),
    )
    monkeypatch.setattr(
        session,
        "_resolve_pdf_page",
        lambda: fallback_page,
    )
    monkeypatch.setattr(
        session,
        "_wait_for_pdf_viewer_ready",
        lambda pdf_page: waited_pages.append(pdf_page.url),
    )

    resolved = session._open_pdf_page_for_order("A017X680406306")

    assert resolved is fallback_page
    assert clicked_orders == ["A017X680406306"]
    assert waited_pages == ["blob:https://e-tracking.customs.go.th/fallback"]
