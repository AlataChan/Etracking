"""
Browser session lifecycle and deterministic receipt workflow.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import urlparse

from loguru import logger
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Download,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from src.browser.devtools_inspector import DevToolsInspector
from src.browser.playwright_adapter import PlaywrightAdapter
from src.core.config import AppSettings, load_settings
from src.core.models import ExecutionStatus, ReceiptResult
from src.core.paths import RuntimePaths
from src.excel_reader import ExcelReader
from src.support.selectors import ReceiptSelectors
from src.workflow.login_flow import LoginFlow
from src.workflow.pdf_flow import PdfFlow
from src.workflow.receipt_flow import ReceiptFlow

T = TypeVar("T")


class BatchSessionProcessor:
    def __init__(
        self,
        use_saved_state: bool = True,
        settings: Optional[AppSettings] = None,
        paths: Optional[RuntimePaths] = None,
        session_factory: Callable[..., Any] | None = None,
        recycle_every_orders: int | None = None,
        recycle_after_retryable_failures: int | None = None,
    ) -> None:
        self.use_saved_state = use_saved_state
        self.settings = settings or load_settings()
        self.paths = (paths or RuntimePaths.from_settings(self.settings)).ensure()
        self.session_factory = session_factory or SessionManager
        self.recycle_every_orders = (
            self.settings.batch_session_recycle_orders if recycle_every_orders is None else recycle_every_orders
        )
        self.recycle_after_retryable_failures = (
            self.settings.batch_session_retryable_failure_threshold
            if recycle_after_retryable_failures is None
            else recycle_after_retryable_failures
        )
        self._session_context: Any | None = None
        self._session: Any | None = None
        self._completed_since_recycle = 0
        self._consecutive_retryable_failures = 0

    def process_order_result(self, order_id: str) -> ReceiptResult:
        if self._should_recycle_before_next_order():
            self._recycle_session()
        session = self._ensure_session()
        result = session.process_order_result(order_id)
        self._completed_since_recycle += 1
        if result.status is ExecutionStatus.FAILED and bool(result.metadata.get("retryable")):
            self._consecutive_retryable_failures += 1
        else:
            self._consecutive_retryable_failures = 0
        return result

    def close(self) -> None:
        self._recycle_session()

    def _ensure_session(self) -> Any:
        if self._session is None:
            self._open_session()
        return self._session

    def _open_session(self) -> None:
        self._session_context = self.session_factory(
            use_saved_state=self.use_saved_state,
            settings=self.settings,
            paths=self.paths,
        )
        self._session = self._session_context.__enter__()
        self._completed_since_recycle = 0
        self._consecutive_retryable_failures = 0

    def _recycle_session(self) -> None:
        if self._session_context is None:
            return
        self._session_context.__exit__(None, None, None)
        self._session_context = None
        self._session = None
        self._completed_since_recycle = 0
        self._consecutive_retryable_failures = 0

    def _should_recycle_before_next_order(self) -> bool:
        if self._session is None:
            return False
        if self.recycle_every_orders > 0 and self._completed_since_recycle >= self.recycle_every_orders:
            return True
        if (
            self.recycle_after_retryable_failures > 0
            and self._consecutive_retryable_failures >= self.recycle_after_retryable_failures
        ):
            return True
        return False


class SessionManager:
    def __init__(
        self,
        use_saved_state: bool = True,
        settings: Optional[AppSettings] = None,
        paths: Optional[RuntimePaths] = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.paths = (paths or RuntimePaths.from_settings(self.settings)).ensure()
        self.selectors = ReceiptSelectors()
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.adapter: Optional[PlaywrightAdapter] = None
        self.login_flow: Optional[LoginFlow] = None
        self.receipt_flow: Optional[ReceiptFlow] = None
        self.inspector = DevToolsInspector()
        self.pdf_flow = PdfFlow(min_bytes=self.settings.min_pdf_bytes)
        self.use_saved_state = use_saved_state
        self.current_receipt_result: Optional[ReceiptResult] = None
        self.attached_over_cdp = False
        self.resumed_from_expanded_form = False
        self.resume_search_probe_pending = True

    def __enter__(self) -> "SessionManager":
        try:
            self.playwright = sync_playwright().start()
            self.browser = self._connect_browser()
            self._initialize_browser_session()
            self.inspector.attach(self.page)
            self.adapter = PlaywrightAdapter(self.page, self.paths.screenshots_dir)
            self.login_flow = LoginFlow(adapter=self.adapter, selectors=self.selectors)
            self.receipt_flow = ReceiptFlow(adapter=self.adapter, selectors=self.selectors)

            self._prepare_browser_session()
            return self
        except Exception:
            self._close_resources(persist_storage_state=False)
            raise

    def _connect_browser(self) -> Browser:
        assert self.playwright is not None

        if self.settings.browser_cdp_url:
            self.attached_over_cdp = True
            logger.info(f"通过 CDP 连接现有浏览器: {self.settings.browser_cdp_url}")
            return self.playwright.chromium.connect_over_cdp(self.settings.browser_cdp_url)

        self.attached_over_cdp = False
        return self._launch_browser()

    def _initialize_browser_session(self) -> None:
        assert self.browser is not None

        if self.attached_over_cdp:
            self.context, self.page = self._resolve_attached_context_page()
            return

        storage_state_path = self.paths.session_state_file
        context_kwargs: dict[str, Any] = {"accept_downloads": True}
        if self.use_saved_state and storage_state_path.exists():
            logger.info(f"加载已保存的会话状态: {storage_state_path}")
            context_kwargs["storage_state"] = str(storage_state_path)
        elif not self.use_saved_state:
            logger.info("已禁用使用保存的会话状态，创建新会话")
        else:
            logger.info("未找到已保存的会话状态，创建新会话")

        self.context = self.browser.new_context(**context_kwargs)
        self.page = self.context.new_page()

    def _resolve_attached_context_page(self) -> tuple[BrowserContext, Page]:
        assert self.browser is not None

        contexts = list(self.browser.contexts)
        if not contexts:
            raise RuntimeError(
                "Connected CDP browser exposes no contexts. Open Chrome with the target profile before attaching."
            )

        preferred_app_match: tuple[BrowserContext, Page] | None = None
        preferred_match: tuple[BrowserContext, Page] | None = None
        for context in contexts:
            for page in reversed(list(context.pages)):
                current_url = getattr(page, "url", "")
                if self._matches_app_host(current_url) and not self._is_pdf_like_url(current_url):
                    logger.info(f"复用现有页面: {current_url}")
                    return context, page
                if preferred_app_match is None and self._matches_app_host(current_url):
                    preferred_app_match = (context, page)
                if preferred_match is None and self._is_reusable_attached_page(current_url):
                    preferred_match = (context, page)

        if preferred_app_match is not None:
            logger.info(f"复用最近的应用页面: {preferred_app_match[1].url}")
            return preferred_app_match

        if preferred_match is not None:
            logger.info(f"复用最近的现有页面: {preferred_match[1].url}")
            return preferred_match

        context = contexts[0]
        logger.info("未找到现有页面，在默认上下文中新建标签页")
        return context, context.new_page()

    def _prepare_browser_session(self) -> None:
        assert self.adapter is not None
        assert self.page is not None

        if self.attached_over_cdp:
            if self._receipt_page_ready():
                if self._receipt_form_expanded():
                    self.resumed_from_expanded_form = True
                logger.info(f"已连接到可用收据页面: {self.page.url}")
                return

            if "/ERV/ERVQ1020" in self.page.url:
                if self._receipt_form_expanded():
                    self.resumed_from_expanded_form = True
                    logger.info(f"附加页面已处于展开表单状态: {self.page.url}")
                    return
                logger.info(f"附加页面已位于收据入口页，继续准备表单: {self.page.url}")
                self._fill_tax_information()
                return

            if self.page.url in ("", "about:blank"):
                logger.info(f"附加页面为空，打开目标网址: {self.settings.login_url}")
                self.adapter.goto(self.settings.login_url)
            elif self._is_browser_internal_url(self.page.url):
                logger.info(f"附加页面为浏览器内部页面，打开目标网址: {self.settings.login_url}")
                self.adapter.goto(self.settings.login_url)
            else:
                logger.info(f"附加页面尚未就绪，尝试从当前页面继续: {self.page.url}")

            self._ensure_ready_for_receipt_search()
            return

        logger.info(f"打开目标网址: {self.settings.login_url}")
        self.adapter.goto(self.settings.login_url)
        self._ensure_ready_for_receipt_search()

    def _matches_app_host(self, url: str) -> bool:
        host = urlparse(self.settings.login_url).netloc
        return bool(host and host in url)

    def _is_browser_internal_url(self, url: str) -> bool:
        lowered = url.lower()
        return lowered.startswith(
            (
                "chrome://",
                "chrome-untrusted://",
                "devtools://",
                "edge://",
                "about:",
                "view-source:",
                "extension://",
            )
        )

    def _is_reusable_attached_page(self, url: str) -> bool:
        return bool(url and url != "about:blank" and not self._is_browser_internal_url(url))

    def _is_pdf_like_url(self, url: str) -> bool:
        lowered = url.lower()
        return lowered.startswith("blob:") or "pdf" in lowered

    def _launch_browser(self) -> Browser:
        assert self.playwright is not None

        attempts: list[dict[str, object]] = []
        if self.settings.browser_channel:
            attempts.append(
                {
                    "headless": self.settings.browser_headless,
                    "channel": self.settings.browser_channel,
                }
            )
        attempts.append({"headless": self.settings.browser_headless})
        if self.settings.browser_channel != "chrome":
            attempts.append({"headless": self.settings.browser_headless, "channel": "chrome"})

        last_error: Exception | None = None
        for options in attempts:
            try:
                logger.info(f"启动浏览器: {options}")
                return self.playwright.chromium.launch(**options)
            except Exception as error:
                last_error = error
                logger.warning(f"浏览器启动失败 {options}: {error}")

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unable to launch browser")

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._close_resources(persist_storage_state=True)
        logger.info("浏览器已关闭")

    def _close_resources(self, persist_storage_state: bool) -> None:
        if persist_storage_state and self.context and not self.attached_over_cdp:
            storage_state_path = self.paths.session_state_file
            storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"保存会话状态到: {storage_state_path}")
            self.context.storage_state(path=str(storage_state_path))

        if self.page and not self.attached_over_cdp:
            self.page.close()
        if self.context and not self.attached_over_cdp:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        self.adapter = None
        self.login_flow = None
        self.receipt_flow = None

    def _retry_action(self, action: Callable[[], T], max_retries: int = 3, delay: float = 0.5) -> T:
        last_exception: Exception | None = None
        for attempt in range(max_retries):
            try:
                return action()
            except Exception as error:
                last_exception = error
                logger.warning(f"操作失败，尝试重试 ({attempt + 1}/{max_retries}): {error}")
                time.sleep(delay)
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("未知错误")

    def _record_result(
        self,
        order_id: str,
        status: ExecutionStatus,
        reason: str = "",
        screenshot_path: str | Path | None = None,
        retryable: bool = False,
    ) -> ReceiptResult:
        metadata = self.inspector.snapshot(
            current_url=self.page.url if self.page else "",
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )
        metadata["retryable"] = retryable
        self.current_receipt_result = ReceiptResult(
            order_id=order_id,
            status=status,
            reason=reason,
            screenshot_path=Path(screenshot_path) if screenshot_path else None,
            metadata=metadata,
        )
        return self.current_receipt_result

    def _capture_screenshot(self, name: str, page: Page | None = None) -> str | None:
        target_page = page or self.page
        if target_page is None:
            return None
        self.paths.screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = self.paths.screenshots_dir / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.png"
        target_page.screenshot(path=str(path), full_page=True)
        return str(path)

    def _ensure_ready_for_receipt_search(self) -> None:
        assert self.page is not None
        assert self.login_flow is not None

        if self.page.query_selector(self.selectors.receipt_menu_items[0]):
            self.login_flow.navigate_to_receipt_page()
        elif self.page.query_selector(self.selectors.policy_accept_labels[0]):
            self.login_flow.accept_policy()
            self.login_flow.navigate_to_receipt_page()
        elif self.page.query_selector(self.selectors.epayment_tiles[0]):
            self.login_flow.navigate_to_receipt_page()

        self._fill_tax_information()

    def _wait_for_first_visible(
        self,
        candidates: tuple[str, ...],
        timeout_ms: int | None = None,
    ) -> str:
        assert self.page is not None
        last_error: Exception | None = None
        for selector in candidates:
            try:
                self.page.wait_for_selector(
                    selector,
                    timeout=timeout_ms or self.settings.browser_timeout_ms,
                    state="visible",
                )
                return selector
            except Exception as error:
                last_error = error
        raise LookupError(f"Unable to resolve selector from {candidates}") from last_error

    def _fill_first_visible(self, candidates: tuple[str, ...], value: str) -> None:
        assert self.page is not None
        selector = self._wait_for_first_visible(candidates)
        locator = self.page.locator(selector).first
        try:
            current_value = locator.input_value()
            if current_value == value:
                logger.info(f"输入框值已正确，跳过填充: {selector}")
                return
            if locator.is_disabled():
                if current_value == value:
                    logger.info(f"输入框已禁用且值已正确，跳过填充: {selector}")
                    return
                raise RuntimeError(f"input is disabled before fill: {selector}")
        except AttributeError:
            pass

        locator.fill("")
        locator.fill(value)

    def _click_first_visible(self, candidates: tuple[str, ...]) -> None:
        assert self.page is not None
        selector = self._wait_for_first_visible(candidates)
        self.page.locator(selector).first.click()

    def _fill_tax_information(self) -> None:
        assert self.page is not None

        if not self.settings.tax_id or not self.settings.branch_id:
            logger.warning("未配置税号或分支号，跳过纳税人信息填充")
            return

        if self._receipt_form_expanded():
            logger.info("收据表单已展开，跳过纳税人信息重复填充")
            return

        try:
            self._fill_first_visible(self.selectors.tax_id_inputs, self.settings.tax_id)
            self._fill_first_visible(self.selectors.branch_id_inputs, self.settings.branch_id)
            self._click_first_visible(self.selectors.taxpayer_validate_buttons)
            time.sleep(1)
        except Exception as error:
            screenshot = self._capture_screenshot("taxpayer_info_error")
            logger.warning(f"填充纳税人信息失败，将继续流程: {error}")
            self._record_result(
                order_id="SYSTEM",
                status=ExecutionStatus.NEEDS_HUMAN_REVIEW,
                reason=f"taxpayer information validation failed: {error}",
                screenshot_path=screenshot,
                retryable=False,
            )

    def _fill_printer_info(self) -> None:
        assert self.page is not None

        if self.settings.printer_card_number:
            logger.info("填写打印人证件号")
            self._fill_first_visible(self.selectors.printer_card_inputs, self.settings.printer_card_number)
        if self.settings.printer_phone_number:
            logger.info("填写打印人手机号")
            self._fill_first_visible(self.selectors.printer_phone_inputs, self.settings.printer_phone_number)

    def _resolve_pdf_page(self) -> Page:
        assert self.page is not None
        assert self.context is not None

        original_url = self.page.url
        original_pages = list(self.context.pages)
        deadline = time.time() + 20

        while time.time() < deadline:
            new_pages = [page for page in self.context.pages if page not in original_pages]
            if new_pages:
                return new_pages[-1]
            current_url = self.page.url
            if current_url != original_url and ("blob:" in current_url or "pdf" in current_url.lower()):
                return self.page
            time.sleep(0.5)

        return self.page

    def _observe_search_state(self, order_id: str) -> dict[str, object]:
        assert self.page is not None

        state = self.page.evaluate(
            """({ orderId }) => {
                const normalize = (value) => (value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
                const target = normalize(orderId);
                const bodyText = document.body ? document.body.innerText || '' : '';
                const rowSelectors = [
                    '.InovuaReactDataGrid__row-cell-wrap',
                    '.InovuaReactDataGrid__row',
                    'table tbody tr',
                    'tbody tr',
                    'tr',
                    '[role="row"]'
                ];

                let match = null;
                for (const selector of rowSelectors) {
                    const rows = Array.from(document.querySelectorAll(selector));
                    for (let index = 0; index < rows.length; index += 1) {
                        const normalizedText = normalize(rows[index].innerText || '');
                        if (normalizedText && normalizedText.includes(target)) {
                            match = { selector, index };
                            break;
                        }
                    }
                    if (match) {
                        break;
                    }
                }

                return {
                    match,
                    noResults: bodyText.includes('ไม่พบข้อมูล'),
                    loadingVisible: bodyText.includes('Loading'),
                };
            }""",
            {"orderId": order_id},
        )
        if not isinstance(state, dict):
            return {"match": None, "noResults": False, "loadingVisible": False}
        return state

    def _wait_for_search_results(self, order_id: str) -> None:
        assert self.receipt_flow is not None

        self.receipt_flow.search()
        state = self._poll_search_state(order_id, timeout_seconds=3)
        if not (state["match"] or state["noResults"] or state["loadingVisible"]):
            logger.info("首次搜索未见明显反馈，重试一次")
            self.receipt_flow.search()

        state = self._poll_search_state(order_id, timeout_seconds=20)
        if state["match"]:
            return
        if state["noResults"]:
            raise LookupError(f"未找到订单 {order_id} 的搜索结果")
        raise RuntimeError(f"搜索订单 {order_id} 超时，未观察到结果行或明确的无结果状态")

    def _poll_search_state(self, order_id: str, timeout_seconds: float) -> dict[str, object]:
        deadline = time.time() + timeout_seconds
        last_state = {"match": None, "noResults": False, "loadingVisible": False}
        while time.time() < deadline:
            last_state = self._observe_search_state(order_id)
            if last_state["match"] or last_state["noResults"]:
                return last_state
            time.sleep(0.5)
        return last_state

    def _find_matching_result_row(self, order_id: str) -> tuple[str, int]:
        state = self._observe_search_state(order_id)
        match = state.get("match")
        if not isinstance(match, dict):
            raise LookupError(f"未能定位订单 {order_id} 的结果行")
        selector = match.get("selector")
        index = match.get("index")
        if not isinstance(selector, str) or not isinstance(index, int):
            raise LookupError(f"搜索结果行定位信息无效: {match}")
        return selector, index

    def _click_print_icon_for_order(self, order_id: str) -> None:
        assert self.page is not None

        selector, index = self._find_matching_result_row(order_id)
        row = self.page.locator(selector).nth(index)

        last_error: Exception | None = None
        seen: set[str] = set()
        for candidate in self.selectors.printer_buttons:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                target = row.locator(candidate)
                if target.count() > 0:
                    target.last.click()
                    return
            except Exception as error:
                last_error = error

        if last_error is not None:
            raise LookupError(f"未找到订单 {order_id} 结果行内的打印图标") from last_error
        raise LookupError(f"未找到订单 {order_id} 结果行内的打印图标")

    def _wait_for_pdf_capture_ready(self, pdf_page: Page) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            current_url = getattr(pdf_page, "url", "")
            if current_url.startswith("blob:"):
                return
            try:
                viewer_ready = pdf_page.evaluate(
                    """() => {
                        const selectors = [
                            'embed[src^="blob:"]',
                            'iframe[src^="blob:"]',
                            'object[data^="blob:"]',
                            'a[href^="blob:"]',
                        ];
                        return {
                            hasBlobSource: selectors.some((selector) => document.querySelector(selector)),
                            readyState: document.readyState,
                        };
                    }"""
                )
                if isinstance(viewer_ready, dict) and viewer_ready.get("hasBlobSource"):
                    return
            except Exception:
                pass
            time.sleep(0.25)

        raise RuntimeError(f"PDF capture source did not become ready for page: {getattr(pdf_page, 'url', '')}")

    def _open_pdf_page_for_order(self, order_id: str) -> Page:
        assert self.context is not None

        try:
            with self.context.expect_page(timeout=15000) as popup_info:
                self._click_print_icon_for_order(order_id)
            pdf_page = popup_info.value
        except PlaywrightTimeoutError:
            logger.info(f"未观察到订单 {order_id} 的 popup，回退到现有页面解析")
            pdf_page = self._resolve_pdf_page()

        if pdf_page is not self.page:
            self.inspector.attach(pdf_page)

        self._wait_for_pdf_capture_ready(pdf_page)
        return pdf_page

    def _close_pdf_popup(self, pdf_page: Page) -> None:
        if pdf_page is self.page:
            return
        try:
            pdf_page.close()
        except Exception as error:
            logger.warning(f"关闭 PDF popup 失败: {error}")

    def _try_direct_blob_fetch(self, pdf_page: Page) -> bytes | None:
        try:
            return pdf_page.evaluate(
                """async () => {
                    const candidates = [];
                    if (window.location.href.startsWith('blob:')) {
                        candidates.push(window.location.href);
                    }
                    for (const selector of ['embed[src^="blob:"]', 'iframe[src^="blob:"]', 'object[data^="blob:"]', 'a[href^="blob:"]']) {
                        for (const element of document.querySelectorAll(selector)) {
                            candidates.push(element.src || element.data || element.href);
                        }
                    }
                    for (const blobUrl of candidates) {
                        try {
                            const response = await fetch(blobUrl);
                            if (!response.ok) continue;
                            const buffer = await response.arrayBuffer();
                            const bytes = Array.from(new Uint8Array(buffer));
                            if (bytes.length >= 4 && bytes[0] === 37 && bytes[1] === 80 && bytes[2] === 68 && bytes[3] === 70) {
                                return bytes;
                            }
                        } catch (error) {
                            console.error('blob fetch failed', error);
                        }
                    }
                    return null;
                }"""
            )
        except Exception as error:
            logger.warning(f"直接抓取 blob/pdf 失败: {error}")
            return None

    def _try_browser_download(self, pdf_page: Page) -> bytes | None:
        try:
            with pdf_page.expect_download(timeout=5000) as download_info:
                clicked = pdf_page.evaluate(
                    """() => {
                        const selectors = [
                            'viewer-download-controls',
                            'cr-icon-button[iron-icon="cr:file-download"]',
                            'button[title*="Download"]',
                            'button[aria-label*="Download"]'
                        ];
                        for (const selector of selectors) {
                            const node = document.querySelector(selector);
                            if (node) {
                                node.click();
                                return true;
                            }
                        }
                        return false;
                    }"""
                )
                if not clicked:
                    return None
            download: Download = download_info.value
            target = self.paths.downloads_dir / download.suggested_filename
            download.save_as(str(target))
            return target.read_bytes() if target.exists() else None
        except PlaywrightTimeoutError:
            return None
        except Exception as error:
            logger.warning(f"浏览器下载 PDF 失败: {error}")
            return None

    def _try_page_export(self, pdf_page: Page) -> bytes | None:
        try:
            return pdf_page.pdf()
        except Exception as error:
            logger.warning(f"受控导出 PDF 失败: {error}")
            return None

    def process_single_order(self, order_id: str) -> bool:
        assert self.page is not None
        assert self.receipt_flow is not None

        pdf_page: Page | None = None
        try:
            logger.info(f"开始处理订单流程: {order_id}")
            should_probe_existing_state = self.attached_over_cdp and self.resume_search_probe_pending
            existing_state = (
                self._poll_search_state(
                    order_id,
                    timeout_seconds=self.settings.batch_resume_probe_timeout_seconds,
                )
                if should_probe_existing_state
                else {"match": None}
            )
            if should_probe_existing_state:
                self.resume_search_probe_pending = False
            if existing_state.get("match"):
                logger.info(f"附加页面已存在订单结果行，直接进入打印步骤: {order_id}")
            else:
                if self.resumed_from_expanded_form:
                    logger.info("当前为预展开恢复页面，跳过打印人信息重填")
                else:
                    self._fill_printer_info()
                logger.info(f"填写订单号: {order_id}")
                self.receipt_flow.input_order_id(order_id)
                logger.info(f"等待搜索结果: {order_id}")
                self._wait_for_search_results(order_id)
            logger.info(f"等待打印 popup/pdf viewer: {order_id}")
            pdf_page = self._open_pdf_page_for_order(order_id)
            screenshot = (
                self._capture_screenshot(f"pdf_page_{order_id}", page=pdf_page)
                if self.settings.batch_capture_pdf_viewer_screenshot
                else None
            )
            pdf_path = self.paths.receipts_dir / f"{order_id}_{datetime.now():%Y%m%d}.pdf"

            logger.info(f"开始抓取 PDF 工件: {order_id}")
            result = self.pdf_flow.acquire(
                order_id=order_id,
                pdf_path=pdf_path,
                direct_fetch=lambda: self._try_direct_blob_fetch(pdf_page),
                browser_download=lambda: self._try_browser_download(pdf_page),
                export_pdf=lambda: self._try_page_export(pdf_page),
                screenshot_path=screenshot,
                source="playwright",
            )
            result.metadata.update(
                self.inspector.snapshot(
                    current_url=pdf_page.url,
                    screenshot_path=screenshot,
                )
            )
            result.metadata.setdefault("retryable", False)
            self.current_receipt_result = result
            return result.status is ExecutionStatus.SUCCEEDED
        except PlaywrightTimeoutError as error:
            screenshot = self._capture_screenshot(f"transient_error_{order_id}")
            self._record_result(
                order_id=order_id,
                status=ExecutionStatus.FAILED,
                reason=f"temporary browser timeout: {error}",
                screenshot_path=screenshot,
                retryable=True,
            )
            return False
        except Exception as error:
            screenshot = self._capture_screenshot(f"order_error_{order_id}")
            logger.exception(f"处理订单 {order_id} 时出错: {error}")
            self._record_result(
                order_id=order_id,
                status=ExecutionStatus.FAILED,
                reason=str(error),
                screenshot_path=screenshot,
                retryable=False,
            )
            return False
        finally:
            if pdf_page is not None:
                self._close_pdf_popup(pdf_page)

    def process_order_result(self, order_id: str) -> ReceiptResult:
        self.current_receipt_result = None
        success = self.process_single_order(order_id)
        if self.current_receipt_result is not None:
            return self.current_receipt_result
        return ReceiptResult(
            order_id=order_id,
            status=ExecutionStatus.SUCCEEDED if success else ExecutionStatus.FAILED,
        )

    def smoke_status(self) -> dict[str, object]:
        assert self.page is not None

        order_inputs_ready = self._any_visible(self.selectors.order_prefix_inputs) and self._any_visible(
            self.selectors.order_suffix_inputs
        )
        printer_inputs_ready = self._any_visible(self.selectors.printer_card_inputs) and self._any_visible(
            self.selectors.printer_phone_inputs
        )

        return {
            "ready": order_inputs_ready and printer_inputs_ready,
            "current_url": self.page.url,
            "order_inputs_ready": order_inputs_ready,
            "printer_inputs_ready": printer_inputs_ready,
        }

    def _any_visible(self, candidates: tuple[str, ...], timeout_ms: int = 1000) -> bool:
        assert self.page is not None

        for selector in candidates:
            locator = self.page.locator(selector).first
            try:
                if locator.is_visible(timeout=timeout_ms):
                    return True
            except Exception:
                continue
        return False

    def _receipt_page_ready(self) -> bool:
        return self._any_visible(self.selectors.order_prefix_inputs, timeout_ms=250) and self._any_visible(
            self.selectors.order_suffix_inputs,
            timeout_ms=250,
        )

    def _receipt_form_expanded(self) -> bool:
        return self._any_visible(self.selectors.printer_card_inputs, timeout_ms=250) and self._any_visible(
            self.selectors.printer_phone_inputs,
            timeout_ms=250,
        )

    def batch_fullflow_download(
        self,
        excel_path: Optional[str] = None,
        sheet_name: Optional[str] = None,
    ) -> dict[str, int]:
        excel_reader = ExcelReader(excel_path, settings=self.settings)
        order_ids = excel_reader.get_order_ids(sheet_name)

        success_count = 0
        failed_count = 0
        human_review_count = 0
        for order_id in order_ids:
            result = self.process_order_result(order_id)
            if result.status is ExecutionStatus.SUCCEEDED:
                success_count += 1
            elif result.status is ExecutionStatus.NEEDS_HUMAN_REVIEW:
                human_review_count += 1
            else:
                failed_count += 1

        return {
            "total": len(order_ids),
            "success": success_count,
            "failed": failed_count,
            "needs_human_review": human_review_count,
        }
