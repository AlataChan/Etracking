from dataclasses import dataclass, field

import pytest

from src.browser.base import BrowserAdapter
from src.support.selectors import ReceiptSelectors
from src.workflow.receipt_flow import ReceiptFlow


@dataclass
class FakeBrowserAdapter(BrowserAdapter):
    visible: set[str]
    fill_calls: list[tuple[str, str]] = field(default_factory=list)
    click_calls: list[str] = field(default_factory=list)

    def goto(self, url: str) -> None:
        raise NotImplementedError

    def wait_visible(self, selector: str, timeout_ms: int = 0) -> None:
        if selector not in self.visible:
            raise LookupError(selector)

    def click(self, selector: str) -> None:
        self.click_calls.append(selector)

    def fill(self, selector: str, value: str) -> None:
        self.fill_calls.append((selector, value))

    def text_snapshot(self) -> str:
        return ""

    def screenshot(self, name: str) -> str:
        return name


def test_receipt_flow_uses_semantic_selectors_not_numeric_indexes() -> None:
    selectors = ReceiptSelectors(
        order_prefix_inputs=("input[data-testid='order-prefix']",),
        order_suffix_inputs=("input[data-testid='order-suffix']",),
        search_buttons=("button[data-testid='receipt-search']",),
        printer_buttons=("button[data-testid='print-receipt']",),
    )
    adapter = FakeBrowserAdapter(visible=set(selectors.all_candidates()))
    flow = ReceiptFlow(adapter=adapter, selectors=selectors)

    flow.input_order_id("A017X680406286")
    flow.search()
    flow.open_pdf_view()

    assert adapter.fill_calls == [
        ("input[data-testid='order-prefix']", "A017"),
        ("input[data-testid='order-suffix']", "X680406286"),
    ]
    assert adapter.click_calls == [
        "button[data-testid='receipt-search']",
        "button[data-testid='print-receipt']",
    ]


def test_receipt_flow_rejects_short_order_ids() -> None:
    adapter = FakeBrowserAdapter(visible=set())
    flow = ReceiptFlow(adapter=adapter)

    with pytest.raises(ValueError):
        flow.input_order_id("SHORT")
