from __future__ import annotations

from pathlib import Path

import pytest

from src.core.config import AppSettings
from src.core.paths import RuntimePaths
from src.session_manager import SessionManager


class FakePage:
    def __init__(self, url: str = "https://customs.invalid/receipt") -> None:
        self.url = url
        self.handlers: dict[str, object] = {}
        self.closed = False

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler

    def close(self) -> None:
        self.closed = True

    def locator(self, selector: str) -> "FakeLocator":
        return FakeLocator()


class FakeLocator:
    @property
    def first(self) -> "FakeLocator":
        return self

    def is_visible(self, timeout: int = 0) -> bool:
        return False


class FakeContext:
    def __init__(self, pages: list[FakePage] | None = None) -> None:
        self.pages = pages or []
        self.closed = False

    def new_page(self) -> FakePage:
        page = FakePage(url="about:blank")
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, contexts: list[FakeContext]) -> None:
        self.contexts = contexts
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.connected_url: str | None = None
        self.launch_calls: list[dict[str, object]] = []

    def connect_over_cdp(self, endpoint_url: str) -> FakeBrowser:
        self.connected_url = endpoint_url
        return self.browser

    def launch(self, **kwargs: object) -> FakeBrowser:
        self.launch_calls.append(kwargs)
        return self.browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeSyncPlaywright:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    def start(self) -> FakePlaywright:
        return self.playwright


class FakeAdapter:
    def __init__(self) -> None:
        self.goto_calls: list[str] = []

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)


class FakeLoginFlow:
    def __init__(self) -> None:
        self.navigate_calls = 0

    def navigate_to_receipt_page(self) -> None:
        self.navigate_calls += 1


def build_settings(project_root: Path) -> AppSettings:
    return AppSettings(
        project_root=project_root,
        raw={
            "login": {
                "login_url": "https://e-tracking.customs.go.th/ETS/",
                "tax_id": "",
                "branch_id": "",
                "printer_card_number": "",
                "printer_phone_number": "",
                "browser": {
                    "headless": True,
                    "timeout": 120000,
                    "channel": "",
                    "cdp_url": "http://127.0.0.1:9222",
                },
            },
            "file": {
                "output_dir": "runtime/receipts",
                "min_pdf_bytes": 1024,
            },
            "logging": {
                "level": "INFO",
                "log_file": "runtime/logs/etracking.log",
                "screenshot_dir": "runtime/logs/screenshots",
                "session_state_file": "runtime/session/state.json",
            },
            "retry": {
                "max_retries": 3,
                "delay": 0.5,
                "use_exponential_backoff": True,
            },
            "excel": {
                "path": "data/orders.xlsx",
                "sheet_name": None,
                "column": "F",
                "skip_header": True,
            },
        },
    )


def test_session_manager_attaches_over_cdp_and_reuses_existing_page(monkeypatch, tmp_path: Path) -> None:
    existing_page = FakePage()
    existing_context = FakeContext(pages=[existing_page])
    browser = FakeBrowser(contexts=[existing_context])
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)

    monkeypatch.setattr("src.session_manager.sync_playwright", lambda: FakeSyncPlaywright(playwright))
    monkeypatch.setattr(SessionManager, "_ensure_ready_for_receipt_search", lambda self: None)

    settings = build_settings(tmp_path)
    paths = RuntimePaths.from_settings(settings).ensure()

    with SessionManager(use_saved_state=True, settings=settings, paths=paths) as session:
        assert chromium.connected_url == "http://127.0.0.1:9222"
        assert chromium.launch_calls == []
        assert session.page is existing_page
        assert set(existing_page.handlers) == {"console", "pageerror", "request", "response"}

    assert existing_page.closed is False
    assert existing_context.closed is False
    assert browser.closed is True
    assert playwright.stopped is True


def test_session_manager_prefers_non_blob_business_page_when_attached_over_cdp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    receipt_page = FakePage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")
    pdf_viewer_page = FakePage(url="blob:https://e-tracking.customs.go.th/511f2e30")
    existing_context = FakeContext(pages=[receipt_page, pdf_viewer_page])
    browser = FakeBrowser(contexts=[existing_context])
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)

    monkeypatch.setattr("src.session_manager.sync_playwright", lambda: FakeSyncPlaywright(playwright))
    monkeypatch.setattr(SessionManager, "_ensure_ready_for_receipt_search", lambda self: None)

    settings = build_settings(tmp_path)
    paths = RuntimePaths.from_settings(settings).ensure()

    with SessionManager(use_saved_state=True, settings=settings, paths=paths) as session:
        assert session.page is receipt_page


def test_session_manager_cleans_up_playwright_when_enter_fails(monkeypatch) -> None:
    def fail_connect(self: SessionManager) -> FakeBrowser:
        raise RuntimeError("boom")

    monkeypatch.setattr(SessionManager, "_connect_browser", fail_connect)

    first_session = SessionManager()
    with pytest.raises(RuntimeError, match="boom"):
        first_session.__enter__()

    second_session = SessionManager()
    with pytest.raises(RuntimeError, match="boom"):
        second_session.__enter__()


def test_session_manager_does_not_reenter_home_flow_when_already_on_ervq1020(monkeypatch) -> None:
    session = SessionManager()
    session.attached_over_cdp = True
    session.page = FakePage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")  # type: ignore[assignment]
    session.adapter = FakeAdapter()  # type: ignore[assignment]
    session.login_flow = FakeLoginFlow()  # type: ignore[assignment]

    fill_calls = {"count": 0}
    monkeypatch.setattr(SessionManager, "_receipt_page_ready", lambda self: False)
    monkeypatch.setattr(
        SessionManager,
        "_fill_tax_information",
        lambda self: fill_calls.__setitem__("count", fill_calls["count"] + 1),
    )

    session._prepare_browser_session()

    assert session.login_flow.navigate_calls == 0
    assert fill_calls["count"] == 1


def test_session_manager_skips_tax_refill_when_attached_page_is_already_expanded(monkeypatch) -> None:
    session = SessionManager()
    session.attached_over_cdp = True
    session.page = FakePage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")  # type: ignore[assignment]
    session.adapter = FakeAdapter()  # type: ignore[assignment]
    session.login_flow = FakeLoginFlow()  # type: ignore[assignment]

    fill_calls = {"count": 0}
    monkeypatch.setattr(SessionManager, "_receipt_page_ready", lambda self: False)
    monkeypatch.setattr(SessionManager, "_receipt_form_expanded", lambda self: True)
    monkeypatch.setattr(
        SessionManager,
        "_fill_tax_information",
        lambda self: fill_calls.__setitem__("count", fill_calls["count"] + 1),
    )

    session._prepare_browser_session()

    assert fill_calls["count"] == 0


def test_session_manager_marks_resumed_expanded_form_when_attached_page_is_already_ready(monkeypatch) -> None:
    session = SessionManager()
    session.attached_over_cdp = True
    session.page = FakePage(url="https://e-tracking.customs.go.th/ERV/ERVQ1020")  # type: ignore[assignment]
    session.adapter = FakeAdapter()  # type: ignore[assignment]

    monkeypatch.setattr(SessionManager, "_receipt_page_ready", lambda self: True)
    monkeypatch.setattr(SessionManager, "_receipt_form_expanded", lambda self: True)

    session._prepare_browser_session()

    assert session.resumed_from_expanded_form is True
