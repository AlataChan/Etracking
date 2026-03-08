from __future__ import annotations

from dataclasses import dataclass

from src.browser.base import BrowserAdapter
from src.support.selectors import ReceiptSelectors


@dataclass(slots=True)
class LoginFlow:
    adapter: BrowserAdapter
    selectors: ReceiptSelectors = ReceiptSelectors()

    def _first_visible(self, candidates: tuple[str, ...]) -> str:
        last_error: Exception | None = None
        for selector in candidates:
            try:
                self.adapter.wait_visible(selector, timeout_ms=1500)
                return selector
            except Exception as exc:  # pragma: no cover - adapter-specific failures
                last_error = exc
        raise LookupError(f"Unable to locate any selector in {candidates}") from last_error

    def accept_policy(self) -> None:
        self.adapter.click(self._first_visible(self.selectors.policy_accept_labels))
        self.adapter.click(self._first_visible(self.selectors.policy_agree_inputs))
        self.adapter.click(self._first_visible(self.selectors.policy_confirm_buttons))

    def navigate_to_receipt_page(self) -> None:
        self.adapter.click(self._first_visible(self.selectors.epayment_tiles))
        self.adapter.click(self._first_visible(self.selectors.receipt_menu_items))

    def validate_taxpayer_data(self, tax_id: str, branch_id: str) -> bool:
        snapshot = self.adapter.text_snapshot()
        return tax_id in snapshot and branch_id in snapshot
