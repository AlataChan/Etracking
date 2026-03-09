from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReceiptSelectors:
    policy_accept_labels: tuple[str, ...] = ("span.textTH-ind",)
    policy_agree_inputs: tuple[str, ...] = ("input#agree",)
    policy_confirm_buttons: tuple[str, ...] = ("button#UPDETL0050",)
    epayment_tiles: tuple[str, ...] = ("img#ePayImg",)
    receipt_menu_items: tuple[str, ...] = ("span:has-text('พิมพ์ใบเสร็จรับเงิน')",)
    tax_id_inputs: tuple[str, ...] = (
        "input[name='taxId']",
        "input[aria-label='Tax ID']",
        "input[placeholder*='เลขประจำตัวผู้เสียภาษี']",
    )
    branch_id_inputs: tuple[str, ...] = (
        "input[name='branchId']",
        "input[aria-label='Branch ID']",
        "input[placeholder*='สาขา']",
    )
    taxpayer_validate_buttons: tuple[str, ...] = (
        "button[data-testid='validate-taxpayer']",
        "button.MuiButton-containedWarning",
        "button:has-text('ตรวจสอบ')",
    )
    printer_card_inputs: tuple[str, ...] = (
        "input[name='printerCardNumber']",
        "input[aria-label='Printer card number']",
        "div[mask='enUpperNumber'][length='17'] input[type='text']",
        "xpath=(//*[contains(normalize-space(.), 'หมายเลขบัตรผู้พิมพ์')]/following::input[@type='text'])[1]",
    )
    printer_phone_inputs: tuple[str, ...] = (
        "input[name='printerPhoneNumber']",
        "input[aria-label='Printer phone number']",
        "div[mask='mobile'][length='12'] input[type='text']",
        "xpath=(//*[contains(normalize-space(.), 'หมายเลขโทรศัพท์ (มือถือ) ผู้พิมพ์')]/following::input[@type='text' or @type='tel'])[1]",
    )
    order_prefix_inputs: tuple[str, ...] = (
        "input[data-testid='order-prefix']",
        "input[name='receiptPrefix']",
        "input[aria-label='Receipt prefix']",
        "div[mask='receiptPrefix'][length='4'] input[type='text']",
        "xpath=(//*[contains(normalize-space(.), 'เลขที่ใบขนสินค้า')]/following::input[@type='text'])[1]",
    )
    order_suffix_inputs: tuple[str, ...] = (
        "input[data-testid='order-suffix']",
        "input[name='receiptNumber']",
        "input[aria-label='Receipt number']",
        "div[mask='receiptNumber'][length='10'] input[type='text']",
        "xpath=(//*[contains(normalize-space(.), 'เลขที่ใบขนสินค้า')]/following::input[@type='text'])[2]",
    )
    search_buttons: tuple[str, ...] = (
        "button[data-testid='receipt-search']",
        "button:has-text('ค้นหา')",
        "button.MuiButton-outlinedWarning",
    )
    printer_buttons: tuple[str, ...] = (
        "button[data-testid='print-receipt']",
        "button:has(img[src*='icon_printer_fee'])",
        "img[src*='icon_printer_fee']",
    )

    def all_candidates(self) -> tuple[str, ...]:
        return (
            *self.policy_accept_labels,
            *self.policy_agree_inputs,
            *self.policy_confirm_buttons,
            *self.epayment_tiles,
            *self.receipt_menu_items,
            *self.tax_id_inputs,
            *self.branch_id_inputs,
            *self.taxpayer_validate_buttons,
            *self.printer_card_inputs,
            *self.printer_phone_inputs,
            *self.order_prefix_inputs,
            *self.order_suffix_inputs,
            *self.search_buttons,
            *self.printer_buttons,
        )
