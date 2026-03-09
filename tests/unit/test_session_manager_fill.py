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
