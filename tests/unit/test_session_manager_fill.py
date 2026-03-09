from __future__ import annotations

import pytest

from src.session_manager import SessionManager


class FakeEditableLocator:
    def __init__(self, disabled: bool, value: str = "") -> None:
        self._disabled = disabled
        self._value = value
        self.fill_calls: list[str] = []

    @property
    def first(self) -> "FakeEditableLocator":
        return self

    def is_disabled(self) -> bool:
        return self._disabled

    def input_value(self) -> str:
        return self._value

    def fill(self, value: str) -> None:
        self.fill_calls.append(value)
        self._value = value


class FakeFillPage:
    def __init__(self, locator: FakeEditableLocator) -> None:
        self._locator = locator

    def wait_for_selector(self, _selector: str, timeout: int, state: str) -> None:
        return None

    def locator(self, _selector: str) -> FakeEditableLocator:
        return self._locator


class FakeSelectorAwarePage:
    def __init__(self, visible_selector: str, locator: FakeEditableLocator) -> None:
        self.visible_selector = visible_selector
        self._locator = locator
        self.wait_calls: list[tuple[str, int, str]] = []

    def wait_for_selector(self, selector: str, timeout: int, state: str) -> None:
        self.wait_calls.append((selector, timeout, state))
        if selector != self.visible_selector:
            raise LookupError(selector)

    def locator(self, selector: str) -> FakeEditableLocator:
        if selector != self.visible_selector:
            raise LookupError(selector)
        return self._locator


class FakeEntryFlow:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def select_taxpayer_roles(self) -> None:
        self._events.append("roles")


def test_fill_first_visible_skips_disabled_input_when_value_already_matches() -> None:
    locator = FakeEditableLocator(disabled=True, value="3101400478778")
    session = SessionManager()
    session.page = FakeFillPage(locator)  # type: ignore[assignment]

    session._fill_first_visible(("input[name='printerCardNumber']",), "3101400478778")

    assert locator.fill_calls == []


def test_fill_first_visible_skips_refill_when_value_already_matches() -> None:
    locator = FakeEditableLocator(disabled=False, value="3101400478778")
    session = SessionManager()
    session.page = FakeFillPage(locator)  # type: ignore[assignment]

    session._fill_first_visible(("input[name='printerCardNumber']",), "3101400478778")

    assert locator.fill_calls == []


def test_fill_first_visible_rejects_disabled_input_when_value_differs() -> None:
    locator = FakeEditableLocator(disabled=True, value="")
    session = SessionManager()
    session.page = FakeFillPage(locator)  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="disabled"):
        session._fill_first_visible(("input[name='printerCardNumber']",), "3101400478778")


def test_fill_tax_information_selects_taxpayer_roles_before_validation(monkeypatch) -> None:
    session = SessionManager()
    session.page = FakeFillPage(FakeEditableLocator(disabled=False))  # type: ignore[assignment]
    events: list[str] = []
    session.entry_flow = FakeEntryFlow(events)  # type: ignore[attr-defined]

    monkeypatch.setattr(SessionManager, "_receipt_form_expanded", lambda self: False)
    monkeypatch.setattr(
        SessionManager,
        "_fill_first_visible",
        lambda self, candidates, value: events.append(f"fill:{value}"),
    )
    monkeypatch.setattr(
        SessionManager,
        "_click_first_visible",
        lambda self, candidates: events.append("validate"),
    )
    monkeypatch.setattr(SessionManager, "_wait_for_receipt_form_expanded", lambda self, timeout_seconds: True)

    session._fill_tax_information()

    assert events == [
        "roles",
        f"fill:{session.settings.tax_id}",
        f"fill:{session.settings.branch_id}",
        "validate",
    ]


def test_fill_first_visible_uses_generic_tax_input_fallback_selector() -> None:
    locator = FakeEditableLocator(disabled=False, value="")
    session = SessionManager()
    generic_selector = "xpath=(//input[not(@type='hidden') and (not(@type) or @type='text')])[1]"
    session.page = FakeSelectorAwarePage(generic_selector, locator)  # type: ignore[assignment]

    session._fill_first_visible(session.selectors.tax_id_inputs, "0105564083643")

    assert locator.fill_calls == ["", "0105564083643"]
    assert locator.fill_calls == ["", "0105564083643"]


def test_fill_first_visible_uses_generic_branch_input_fallback_selector() -> None:
    locator = FakeEditableLocator(disabled=False, value="")
    session = SessionManager()
    generic_selector = "xpath=(//input[not(@type='hidden') and (not(@type) or @type='text')])[2]"
    session.page = FakeSelectorAwarePage(generic_selector, locator)  # type: ignore[assignment]

    session._fill_first_visible(session.selectors.branch_id_inputs, "1")

    assert locator.fill_calls == ["", "1"]


def test_wait_for_first_visible_uses_short_probe_timeout_per_candidate() -> None:
    locator = FakeEditableLocator(disabled=False, value="")
    session = SessionManager()
    generic_selector = "xpath=(//input[not(@type='hidden') and (not(@type) or @type='text')])[1]"
    page = FakeSelectorAwarePage(generic_selector, locator)
    session.page = page  # type: ignore[assignment]

    selector = session._wait_for_first_visible(session.selectors.tax_id_inputs)

    assert selector == generic_selector
    assert [timeout for _, timeout, _ in page.wait_calls] == [1500] * len(session.selectors.tax_id_inputs)


def test_ensure_printer_info_ready_skips_refill_after_first_fill(monkeypatch) -> None:
    session = SessionManager()
    session.page = FakeFillPage(FakeEditableLocator(disabled=False))  # type: ignore[assignment]

    fill_calls: list[str] = []
    monkeypatch.setattr(SessionManager, "_receipt_form_expanded", lambda self: True)
    monkeypatch.setattr(SessionManager, "_fill_printer_info", lambda self: fill_calls.append("fill"))

    session._ensure_printer_info_ready()
    session._ensure_printer_info_ready()

    assert fill_calls == ["fill"]
    assert session.printer_info_ready is True
