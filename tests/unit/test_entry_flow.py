from dataclasses import dataclass, field

from src.browser.base import BrowserAdapter
from src.support.selectors import ReceiptSelectors
from src.workflow.entry_flow import EntryFlow


@dataclass
class FakeBrowserAdapter(BrowserAdapter):
    visible: set[str]
    click_calls: list[str] = field(default_factory=list)

    def goto(self, url: str) -> None:
        raise NotImplementedError

    def wait_visible(self, selector: str, timeout_ms: int = 0) -> None:
        if selector not in self.visible:
            raise LookupError(selector)

    def click(self, selector: str) -> None:
        self.click_calls.append(selector)

    def fill(self, selector: str, value: str) -> None:
        raise NotImplementedError

    def text_snapshot(self) -> str:
        return ""

    def screenshot(self, name: str) -> str:
        return name


def test_entry_flow_separates_epayment_handoff_from_receipt_menu_click() -> None:
    selectors = ReceiptSelectors(
        epayment_tiles=("img#ePayImg",),
        receipt_menu_items=("span:has-text('พิมพ์ใบเสร็จรับเงิน')",),
    )
    adapter = FakeBrowserAdapter(visible={"img#ePayImg", "span:has-text('พิมพ์ใบเสร็จรับเงิน')"})
    flow = EntryFlow(adapter=adapter, selectors=selectors)

    flow.click_epayment_tile()
    flow.open_receipt_menu()

    assert adapter.click_calls == [
        "img#ePayImg",
        "span:has-text('พิมพ์ใบเสร็จรับเงิน')",
    ]


def test_entry_flow_selects_both_taxpayer_role_options() -> None:
    selectors = ReceiptSelectors(
        taxpayer_delegate_options=("label:has-text('กระทำการแทน (สำหรับนิติบุคคล)')",),
        taxpayer_importer_exporter_options=("label:has-text('ผู้นำของเข้า/ผู้ส่งของออก')",),
    )
    adapter = FakeBrowserAdapter(
        visible={
            "label:has-text('กระทำการแทน (สำหรับนิติบุคคล)')",
            "label:has-text('ผู้นำของเข้า/ผู้ส่งของออก')",
        }
    )
    flow = EntryFlow(adapter=adapter, selectors=selectors)

    flow.select_taxpayer_roles()

    assert adapter.click_calls == [
        "label:has-text('กระทำการแทน (สำหรับนิติบุคคล)')",
        "label:has-text('ผู้นำของเข้า/ผู้ส่งของออก')",
    ]
