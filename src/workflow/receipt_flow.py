from __future__ import annotations

from dataclasses import dataclass

from src.browser.base import BrowserAdapter
from src.support.selectors import ReceiptSelectors


@dataclass(slots=True)
class ReceiptFlow:
    adapter: BrowserAdapter
    selectors: ReceiptSelectors = ReceiptSelectors()

    def _first_visible(self, candidates: tuple[str, ...]) -> str:
        last_error: Exception | None = None
        for selector in candidates:
            try:
                self.adapter.wait_visible(selector, timeout_ms=1500)
                return selector
            except Exception as exc:
                last_error = exc
        raise LookupError(f"Unable to locate any selector in {candidates}") from last_error

    def input_order_id(self, order_id: str) -> None:
        if len(order_id) < 14:
            raise ValueError("order_id must contain the four-character prefix and receipt suffix")

        prefix = order_id[:4]
        suffix = order_id[4:]
        self.adapter.fill(self._first_visible(self.selectors.order_prefix_inputs), prefix)
        self.adapter.fill(self._first_visible(self.selectors.order_suffix_inputs), suffix)

    def search(self) -> None:
        self.adapter.click(self._first_visible(self.selectors.search_buttons))

    def open_pdf_view(self) -> None:
        self.adapter.click(self._first_visible(self.selectors.printer_buttons))
