from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReceiptSelectors:
    policy_accept_labels: tuple[str, ...] = ("span.textTH-ind",)
    policy_agree_inputs: tuple[str, ...] = ("input#agree",)
    policy_confirm_buttons: tuple[str, ...] = ("button#UPDETL0050",)
    epayment_tiles: tuple[str, ...] = ("img#ePayImg",)
    receipt_menu_items: tuple[str, ...] = ("span:has-text('พิมพ์ใบเสร็จรับเงิน')",)
    order_prefix_inputs: tuple[str, ...] = (
        "input[data-testid='order-prefix']",
        "input[name='receiptPrefix']",
        "input[aria-label='Receipt prefix']",
    )
    order_suffix_inputs: tuple[str, ...] = (
        "input[data-testid='order-suffix']",
        "input[name='receiptNumber']",
        "input[aria-label='Receipt number']",
    )
    search_buttons: tuple[str, ...] = (
        "button[data-testid='receipt-search']",
        "button:has-text('ค้นหา')",
        "button.MuiButton-outlinedWarning",
    )
    printer_buttons: tuple[str, ...] = (
        "button[data-testid='print-receipt']",
        "img[src*='icon_printer_fee']",
    )

    def all_candidates(self) -> tuple[str, ...]:
        return (
            *self.policy_accept_labels,
            *self.policy_agree_inputs,
            *self.policy_confirm_buttons,
            *self.epayment_tiles,
            *self.receipt_menu_items,
            *self.order_prefix_inputs,
            *self.order_suffix_inputs,
            *self.search_buttons,
            *self.printer_buttons,
        )
