"""
会话管理模块。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import random
import re
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, TypeVar

from loguru import logger
from playwright.sync_api import (
    Browser,
    BrowserContext,
    ElementHandle,
    FloatRect,
    Page,
    Playwright,
    sync_playwright,
)

from src.core.config import AppSettings, load_settings
from src.core.models import ExecutionStatus, ReceiptResult
from src.core.paths import RuntimePaths
from src.excel_reader import ExcelReader
from src.support.validation import PdfValidationPolicy, validate_pdf_artifact
T = TypeVar('T')

class SessionManager:
    """
    会话管理器，负责登录、会话持久化等功能
    """
    def __init__(
        self,
        use_saved_state: bool = True,
        settings: Optional[AppSettings] = None,
        paths: Optional[RuntimePaths] = None,
    ) -> None:
        """
        初始化会话管理器
        
        Args:
            use_saved_state: 是否使用已保存的会话状态，默认为True
        """
        self.settings = settings or load_settings()
        self.paths = (paths or RuntimePaths.from_settings(self.settings)).ensure()
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.config: Dict[str, Any] = self._load_config()
        self.url: str = self.settings.login_url
        self.tax_id: str = self.settings.tax_id
        self.branch_id: str = self.settings.branch_id
        self.logs_dir: str = str(self.paths.logs_dir)
        self.downloads_dir: str = str(self.paths.downloads_dir)
        self.receipts_dir: str = str(self.paths.receipts_dir)
        self.validation_policy = PdfValidationPolicy(min_bytes=self.settings.min_pdf_bytes)
        self.use_saved_state: bool = use_saved_state
        self.current_receipt_result: Optional[ReceiptResult] = None
        self.paths.ensure()

    def __enter__(self) -> 'SessionManager':
        """
        上下文管理器入口，初始化浏览器并导航到目标网址
        """
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.settings.browser_headless)
        
        # 检查是否使用已保存的会话状态
        storage_state_path = self.paths.session_state_file
        if self.use_saved_state and storage_state_path.exists():
            logger.info(f"加载已保存的会话状态: {storage_state_path}")
            self.context = self.browser.new_context(storage_state=str(storage_state_path))
        else:
            if not self.use_saved_state:
                logger.info("已禁用使用保存的会话状态，创建新会话")
            else:
                logger.info("未找到已保存的会话状态，创建新会话")
            self.context = self.browser.new_context()
            
        self.page = self.context.new_page()
        logger.info(f"打开目标网址: {self.url}")
        self.page.goto(self.url)
        
        # 尝试登录流程
        try:
            self._accept_policy()
        except Exception as e:
            logger.error(f"登录流程执行失败: {e}")
            self._save_error_screenshot("login_failed")
            raise
            
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        上下文管理器退出，关闭所有资源
        """
        # 保存会话状态
        if self.context:
            storage_state_path = self.paths.session_state_file
            logger.info(f"保存会话状态到: {storage_state_path}")
            storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.context.storage_state(path=str(storage_state_path))
            
        # 关闭资源
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("浏览器已关闭")

    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return self.settings.raw

    def _save_error_screenshot(self, error_name: str) -> None:
        """
        保存错误截图
        
        Args:
            error_name (str): 错误名称
        """
        if not self.page:
            return
            
        screenshots_dir = self.paths.screenshots_dir
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        screenshot_path = screenshots_dir / f"{error_name}_{timestamp}.png"
        self.page.screenshot(path=str(screenshot_path))
        logger.info(f"错误截图已保存: {screenshot_path}")

    def _retry_action(self, action: Callable[[], T], max_retries: int = 3, delay: float = 0.5) -> T:
        """
        重试执行操作
        
        Args:
            action: 要执行的操作函数
            max_retries: 最大重试次数
            delay: 重试延迟时间
            
        Returns:
            操作的返回结果
        """
        last_exception = None
        for i in range(max_retries):
            try:
                return action()
            except Exception as e:
                last_exception = e
                logger.warning(f"操作失败，尝试重试 ({i+1}/{max_retries}): {e}")
                time.sleep(delay)
        if last_exception:
            raise last_exception
        raise RuntimeError("未知错误")

    def _record_result(
        self,
        order_id: str,
        status: ExecutionStatus,
        reason: str = "",
        screenshot_path: str | Path | None = None,
    ) -> ReceiptResult:
        self.current_receipt_result = ReceiptResult(
            order_id=order_id,
            status=status,
            reason=reason,
            screenshot_path=Path(screenshot_path) if screenshot_path else None,
        )
        return self.current_receipt_result

    def process_order_result(self, order_id: str) -> ReceiptResult:
        self.current_receipt_result = None
        succeeded = self.process_single_order(order_id)
        if self.current_receipt_result is not None:
            return self.current_receipt_result
        if succeeded:
            return ReceiptResult(
                order_id=order_id,
                status=ExecutionStatus.SUCCEEDED,
            )
        return ReceiptResult(
            order_id=order_id,
            status=ExecutionStatus.FAILED,
            reason="legacy workflow did not produce a validated PDF artifact",
        )

    def _accept_policy(self) -> None:
        """
        step1: 处理个人信息政策弹窗，下拉、勾选、点击同意
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
            
        try:
            logger.info("等待个人信息政策弹窗出现...")
            policy_visible = self.page.wait_for_selector('span.textTH-ind', timeout=15000, state='visible')
            
            # 如果没有找到政策弹窗，可能已经登录
            if not policy_visible:
                logger.info("未检测到政策弹窗，检查是否已登录...")
                if self._check_already_logged_in():
                    return
            
            # 处理政策弹窗
            self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            time.sleep(0.5)
            self.page.hover('span.textTH-ind')
            time.sleep(0.2)
            self.page.click('span.textTH-ind')
            logger.info("已点击'ยอมรับเงื่อนไขการใช้งาน'元素，尝试勾选checkbox...")

            # 主动点击checkbox，确保被勾选
            self.page.wait_for_selector('input#agree', timeout=5000)
            
            def check_checkbox():
                self.page.click('input#agree')
                return self.page.eval_on_selector('input#agree', 'el => el.checked')
                
            checkbox_checked = self._retry_action(check_checkbox, max_retries=3)
            if not checkbox_checked:
                raise RuntimeError("checkbox未能被勾选，请检查页面结构！")

            # 点击确认按钮
            self.page.wait_for_selector('button#UPDETL0050', timeout=5000)
            self.page.hover('button#UPDETL0050')
            time.sleep(0.2)
            self.page.click('button#UPDETL0050')
            logger.info("已点击'ตกลง'按钮，等待弹窗消失...")
            self.page.wait_for_selector('button#UPDETL0050', state='hidden', timeout=5000)
            logger.info("个人信息政策弹窗已关闭，进入主页面。")
            
            # 继续登录流程
            self._navigate_to_receipt_page()
        except Exception as e:
            logger.error(f"处理个人信息政策弹窗时出错: {e}")
            self._save_error_screenshot("policy_error")
            raise

    def _check_already_logged_in(self) -> bool:
        """
        检查是否已经登录
        
        Returns:
            bool: 如果已登录返回True，否则False
        """
        if not self.page:
            return False
            
        try:
            # 尝试找ERV主页面的特征元素
            receipt_menu = self.page.query_selector("span:has-text('พิมพ์ใบเสร็จรับเงิน กศก.123')")
            if receipt_menu:
                logger.info("检测到已经登录到ERV系统")
                self._navigate_to_receipt_page()
                return True
                
            # 尝试找epayment图片
            epayment_img = self.page.query_selector('img#ePayImg')
            if epayment_img:
                logger.info("检测到已经通过政策页面，存在ePayment图片")
                self._navigate_to_receipt_page()
                return True
                
            return False
        except Exception as e:
            logger.warning(f"检查登录状态时出错: {e}")
            return False

    def _navigate_to_receipt_page(self) -> None:
        """
        导航到收据打印页面，合并了之前的_click_epayment和_click_receipt_menu
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
            
        try:
            # 点击epayment图片
            logger.info("等待epayment图片出现...")
            self.page.wait_for_selector('img#ePayImg', timeout=15000)
            self.page.hover('img#ePayImg')
            time.sleep(0.2)
            self.page.click('img#ePayImg')
            logger.info("已点击epayment图片，等待ERV主页面关键元素出现...")
            
            # 等待收据打印菜单出现
            receipt_selector = "span:has-text('พิมพ์ใบเสร็จรับเงิน')"  # 简化选择器，只匹配部分文本
            self.page.wait_for_selector(receipt_selector, timeout=120000)
            logger.info("页面已切换至ERV主页面，准备点击收据打印菜单")
            
            # 点击收据打印菜单
            for _ in range(10):  # 最多尝试10次
                menu_elements = self.page.query_selector_all(receipt_selector)
                if len(menu_elements) > 0:
                    break
                time.sleep(1)
                
            logger.info(f"检测到 {len(menu_elements)} 个菜单项")
            
            # 尝试点击第一个找到的菜单项
            if len(menu_elements) > 0:
                target = menu_elements[0]  # 使用第一个匹配的元素
                logger.info(f"选择菜单文本: '{target.inner_text().strip()}'")
                
                target.hover()
                time.sleep(0.2)
                target.click()
                logger.info("已点击收据打印菜单，等待收据打印页面加载...")
            else:
                logger.error("未找到任何收据打印相关菜单项！")
                raise RuntimeError("未找到收据打印菜单项")
            
            # 等待loading消失
            try:
                self.page.wait_for_selector('.MuiCircularProgress-root', state='hidden', timeout=10000)
            except Exception:
                pass  # 没有loading动画可忽略

            # 等待关键元素出现
            self.page.wait_for_selector("button:has-text('ผู้ประกอบการที่ลงทะเบียนกับกรมศุลกากร')", timeout=60000)
            logger.info("页面已跳转至收据打印页面")
            
            # 继续登录流程
            self._select_company_role()
        except Exception as e:
            logger.error(f"导航到收据打印页面时出错: {e}")
            self._save_error_screenshot("navigation_error")
            raise

    def _select_company_role(self) -> None:
        """
        选择公司角色（代表法人实体）和进口商角色（进口商/出口商）
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
            
        try:
            # 等待角色选择区域显示
            logger.info("等待角色选择区域出现...")
            self.page.wait_for_selector("h6", timeout=30000)
            time.sleep(1)  # 确保页面完全加载
            
            # ===== 选择公司角色 =====
            logger.info("选择公司角色: กระทำการแทน (สำหรับนิติบุคคล)")
            
            # 定义选择器
            company_input_selector = "input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='2']"
            
            # 直接使用简化的方法选择公司角色
            self._select_company_role_simple(company_input_selector)
            
            # ===== 验证进口商角色是否已选择 =====
            logger.info("验证进口商角色: ผู้นำของเข้า/ผู้ส่งของออก")
            
            # 定义选择器
            importer_input_selector = "input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='1']"
            
            # 只验证进口商角色是否已选中
            importer_selected = self.page.evaluate(f"""
                document.querySelector("{importer_input_selector}").checked
            """)
            
            logger.info(f"进口商角色状态: {importer_selected}")
            
            # 如果进口商角色没有选中，记录警告但不抛出异常（根据用户反馈，这个选项通常是默认选中的）
            if not importer_selected:
                logger.warning("进口商角色未被选中，但继续执行流程")
                # 尝试强制选择进口商角色
                self.page.evaluate(f"""
                    const importerRadio = document.querySelector("{importer_input_selector}");
                    if (importerRadio) {{
                        importerRadio.checked = true;
                        importerRadio.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                """)
                logger.info("已尝试强制选择进口商角色")
            
            # 等待校验按钮出现
            self.page.wait_for_selector("button.MuiButton-contained", timeout=30000)
            logger.info("角色选择完成")
            
            # 填写纳税信息
            self._fill_tax_information()
        except Exception as e:
            logger.error(f"选择公司角色时出错: {e}")
            self._save_error_screenshot("role_selection_error")
            raise

    def _select_company_role_simple(self, input_selector: str) -> None:
        """
        简化版公司角色选择方法，专注于可靠性
        
        Args:
            input_selector (str): 输入框选择器
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
            
        # 检查选择器是否存在
        self.page.wait_for_selector(input_selector, timeout=10000)
        
        # 获取选择前状态
        initial_state = self.page.evaluate(f"""
            document.querySelector("{input_selector}").checked
        """)
        logger.info(f"公司角色选择前状态: {initial_state}")
        
        if initial_state:
            logger.info("公司角色已经被选中，无需操作")
            return
        
        try:
            # 方法1: 尝试直接点击input元素
            element = self.page.query_selector(input_selector)
            if element:
                # 强制点击
                element.click(force=True)
                time.sleep(0.5)
                
                is_checked = self.page.evaluate(f"""
                    document.querySelector("{input_selector}").checked
                """)
                logger.info(f"点击后公司角色状态: {is_checked}")
                
                if is_checked:
                    logger.info("公司角色选择成功")
                    return
        except Exception as e:
            logger.warning(f"直接点击公司角色失败: {e}")
        
        try:
            # 方法2: 使用evaluate强制设置
            logger.info("尝试使用JavaScript强制设置公司角色")
            
            self.page.evaluate(f"""
                const companyRadio = document.querySelector("{input_selector}");
                if (companyRadio) {{
                    companyRadio.checked = true;
                    const event = new Event('change', {{ bubbles: true }});
                    companyRadio.dispatchEvent(event);
                }}
            """)
            
            # 给UI时间响应
            time.sleep(1)
            
            # 再次验证
            is_checked = self.page.evaluate(f"""
                document.querySelector("{input_selector}").checked
            """)
            logger.info(f"强制设置后公司角色状态: {is_checked}")
            
            if is_checked:
                logger.info("公司角色选择成功")
                return
        except Exception as e:
            logger.warning(f"JavaScript强制设置公司角色失败: {e}")
        
        # 如果所有方法都失败，记录错误并保存截图
        logger.error("所有方法都无法选择公司角色")
        self._save_error_screenshot("company_role_selection_failed")

    def _fill_tax_information(self) -> None:
        """
        Step8: 精确填写纳税人识别号和分支号，并完成校验
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
        try:
            logger.info("Step8-1: 填写纳税人识别号和分支号")
            self.page.wait_for_selector('input[type="text"]', timeout=10000)
            inputs = self.page.query_selector_all('input[type="text"]')
            logger.info(f"检测到 {len(inputs)} 个文本输入框")
            if len(inputs) < 2:
                logger.error("未找到足够的输入框")
                self._save_error_screenshot("tax_input_not_found")
                return
            # 填写纳税人识别号
            for _ in range(3):
                inputs[0].click()
                inputs[0].press('Control+A')
                inputs[0].press('Backspace')
                time.sleep(0.1)
                inputs[0].fill(self.tax_id)
                time.sleep(0.2)
                val = inputs[0].input_value()
                logger.info(f"纳税人识别号输入框当前值: {val}")
                if val == self.tax_id:
                    break
            else:
                logger.error("纳税人识别号输入失败")
                self._save_error_screenshot("tax_id_input_failed")
                return
            # 填写分支号
            for _ in range(3):
                inputs[1].click()
                inputs[1].press('Control+A')
                inputs[1].press('Backspace')
                time.sleep(0.1)
                inputs[1].fill(self.branch_id)
                time.sleep(0.2)
                val = inputs[1].input_value()
                logger.info(f"分支号输入框当前值: {val}")
                if val == self.branch_id:
                    break
            else:
                logger.error("分支号输入失败")
                self._save_error_screenshot("branch_id_input_failed")
                return
            # 点击空白处，等待自动补全
            self.page.mouse.click(100, 400)
            time.sleep(1.0)
            # 输出输入框内容到日志
            values = [i.input_value() for i in inputs]
            logger.info(f"输入框内容: {values}")
            # 校验按钮
            check_btn_selector = 'button.MuiButton-containedWarning'
            self.page.wait_for_selector(check_btn_selector, timeout=10000)
            check_btns = self.page.query_selector_all(check_btn_selector)
            logger.info(f"检测到 {len(check_btns)} 个校验按钮")
            # 取第一个可用按钮
            check_btn = None
            for btn in check_btns:
                if btn.is_visible() and not self.page.evaluate('el => el.disabled', btn):
                    check_btn = btn
                    break
            if check_btn:
                check_btn.scroll_into_view_if_needed()
                check_btn.hover()
                time.sleep(1.0)
                check_btn.click()
                logger.info("已点击校验按钮，等待打印卡号输入框出现")
            else:
                logger.error("未找到可用校验按钮")
                self._save_error_screenshot("check_btn_not_found")
                return
            # 新的校验成功标准：等待打印卡号输入框出现
            printer_input_selector = 'div[mask=\"enUpperNumber\"][length=\"17\"] input[type=\"text\"]'
            try:
                self.page.wait_for_selector(printer_input_selector, timeout=20000)
                logger.info("检测到打印卡号输入框，纳税信息校验成功")
            except Exception:
                logger.error("未检测到打印卡号输入框，校验可能失败")
                self._save_error_screenshot("printer_input_not_found")
        except Exception as e:
            logger.error(f"Step8执行出错: {e}")
            self._save_error_screenshot("step8_error")
            raise

    def search_receipt(self, receipt_id: str) -> None:
        """
        搜索并打印收据
        
        Args:
            receipt_id (str): 收据ID
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
            
        try:
            # ===== Step 8: 验证纳税人信息 =====
            logger.info("Step 8: 验证纳税人信息...")
            success_element = "h6.MuiTypography-root:has-text('ประเภทบัตรผู้พิมพ์')"
            # 1. 先检查是否已验证成功
            if self.page.query_selector(success_element):
                logger.info("检测到验证已完成，无需重复验证")
            else:
                # 2. 未验证则只尝试一次点击
                check_button_selector = "button.MuiButton-contained"
                check_btn = self.page.query_selector(check_button_selector)
                if check_btn and not self.page.evaluate(f'document.querySelector("{check_button_selector}").disabled'):
                    logger.info("点击校验按钮...")
                    check_btn.hover()
                    time.sleep(0.3)
                    check_btn.click()
                else:
                    logger.info("校验按钮不可用，可能已验证或页面异常，跳过点击")
                # 3. 等待验证结果
                try:
                    self.page.wait_for_selector(success_element, timeout=10000)
                    logger.info("纳税人信息验证成功")
                except Exception as e:
                    self._save_error_screenshot("tax_verification_failed")
                    logger.error(f"纳税人信息验证失败: {e}")
                    raise RuntimeError("纳税人信息验证失败，未检测到成功元素")
            logger.info("Step 8完成，准备进行下一步操作")
            
            # ===== Step 9: 检查身份证类型是否已选中 =====
            logger.info("Step 9: 检查身份证类型(บัตรประจำตัวประชาชน)是否已选中...")
            id_card_radio_selector = "input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='1']"
            try:
                self.page.wait_for_selector(id_card_radio_selector, timeout=5000)
                is_checked = self.page.evaluate(f'document.querySelector("{id_card_radio_selector}").checked')
                logger.info(f"身份证选项当前状态: {is_checked}")
            except Exception as e:
                logger.warning(f"身份证选项检查时出错: {e}")
                self._save_error_screenshot('id_card_check_error')
            logger.info("Step 9完成，继续后续流程")
            
            # ===== Step 10: 填写打印卡号码和手机号码 =====
            logger.info("Step 10: 填写打印卡号码和手机号码...")

            # Step 10-1: 填写打印卡号码
            try:
                logger.info("Step 10-1: 填写打印卡号码(หมายเลขบัตรผู้พิมพ์)...")
                card_number = "3101400478778"
                card_input_selector = "div[mask='enUpperNumber'][length='17'] input[type='text']"
                self.page.wait_for_selector(card_input_selector, timeout=8000, state='visible')
                card_input = self.page.query_selector(card_input_selector)
                if card_input:
                    # 检查是否可用
                    is_disabled = self.page.evaluate("el => el.disabled", card_input)
                    if is_disabled:
                        logger.warning("打印卡号输入框被禁用，等待激活...")
                        time.sleep(1)
                    card_input.click()
                    time.sleep(0.2)
                    card_input.fill("")
                    time.sleep(0.2)
                    card_input.fill(card_number)
                    logger.info(f"已填写打印卡号码: {card_number}")
                else:
                    logger.warning("未找到打印卡号码输入框")
            except Exception as e:
                logger.error(f"填写打印卡号码时出错: {e}")
                self._save_error_screenshot('card_number_error')

            # Step 10-2: 填写手机号码
            try:
                logger.info("Step 10-2: 填写手机号码(หมายเลขโทรศัพท์)...")
                phone_number = "0927271000"
                phone_input_selector = "div[mask='mobile'][length='12'] input[type='text']"
                self.page.wait_for_selector(phone_input_selector, timeout=8000, state='visible')
                phone_input = self.page.query_selector(phone_input_selector)
                if phone_input:
                    is_disabled = self.page.evaluate("el => el.disabled", phone_input)
                    if is_disabled:
                        logger.warning("手机号码输入框被禁用，等待激活...")
                        time.sleep(1)
                    phone_input.click()
                    time.sleep(0.2)
                    phone_input.fill("")
                    time.sleep(0.2)
                    phone_input.fill(phone_number)
                    logger.info(f"已填写手机号码: {phone_number}")
                else:
                    logger.warning("未找到手机号码输入框")
            except Exception as e:
                logger.error(f"填写手机号码时出错: {e}")
                self._save_error_screenshot('phone_number_error')

            logger.info("Step 10完成，继续后续流程")
            
        except Exception as e:
            logger.error(f"搜索收据过程中出错: {e}")
            self._save_error_screenshot("search_receipt_error")
            raise

    def _random_delay(self, min_seconds: float = 0.5, max_seconds: float = 2.0) -> None:
        """
        随机延迟，模拟人类操作
        
        Args:
            min_seconds (float): 最小延迟秒数
            max_seconds (float): 最大延迟秒数
        """
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def _step10_fill_printer_info(self) -> None:
        """
        自动填写打印卡号和手机号（Step 10）
        """
        if not self.page:
            logger.error("页面未初始化，无法填写打印卡号和手机号")
            return
        card_number = self.config.get('login', {}).get('printer_card_number', '3101400478778')
        phone_number = self.config.get('login', {}).get('printer_phone_number', '0927271000')
        try:
            self.page.wait_for_selector("input[type='text']", timeout=8000)
            inputs = self.page.query_selector_all("input[type='text']")
            logger.info(f"检测到 {len(inputs)} 个文本输入框")
            if len(inputs) < 4:
                logger.error(f"未找到足够的输入框，实际数量: {len(inputs)}")
                logger.debug(self.page.content())
                self._save_error_screenshot('printer_info_input_not_found')
                return
            # 第3个输入框：打印卡号
            inputs[2].click()
            inputs[2].fill("")
            inputs[2].fill(card_number)
            logger.info(f"已填写打印卡号码: {card_number}")
            # 第4个输入框：手机号
            inputs[3].click()
            inputs[3].fill("")
            inputs[3].fill(phone_number)
            logger.info(f"已填写手机号码: {phone_number}")
        except Exception as e:
            logger.error(f"填写打印卡号或手机号时出错: {e}")
            logger.debug(self.page.content())
            self._save_error_screenshot('printer_info_fill_error')

    def _simulate_human_typing(self, element: ElementHandle, text: str) -> bool:
        """
        模拟人类输入文本，每次输入一个字符并添加随机延迟
        
        Args:
            element: 要输入的元素
            text: 要输入的文本
            
        Returns:
            bool: 是否成功输入
        """
        try:
            element.click()
            time.sleep(0.3)
            element.press("Control+a")
            time.sleep(0.1)
            element.press("Backspace")
            time.sleep(0.2)
            
            # 逐个字符输入
            for char in text:
                element.type(char)
                time.sleep(random.uniform(0.1, 0.3))
                
            # 验证输入结果
            actual_value = element.input_value()
            return actual_value == text
        except Exception as e:
            logger.error(f"模拟人类输入失败: {e}")
            return False
            
    def _try_multiple_input_methods(self, element: ElementHandle, text: str) -> bool:
        """
        尝试多种输入方法
        
        Args:
            element: 要输入的元素
            text: 要输入的文本
            
        Returns:
            bool: 是否成功输入
        """
        # 方法1: 使用模拟人类输入
        if self._simulate_human_typing(element, text):
            logger.info(f"使用模拟人类输入成功: {text}")
            return True
            
        # 方法2: 使用press方法输入
        try:
            element.click()
            time.sleep(0.2)
            element.press("Control+a")
            time.sleep(0.1)
            element.press("Backspace")
            time.sleep(0.2)
            
            for char in text:
                if char.isalpha():
                    element.press(char)
                else:
                    element.type(char)
                time.sleep(random.uniform(0.1, 0.2))
                
            actual_value = element.input_value()
            if actual_value == text:
                logger.info(f"使用press方法输入成功: {text}")
                return True
        except Exception as e:
            logger.warning(f"使用press方法输入失败: {e}")
            
        # 方法3: 使用更慢的输入方式
        try:
            element.click()
            time.sleep(0.3)
            element.press("Control+a")
            time.sleep(0.2)
            element.press("Backspace")
            time.sleep(0.3)
            
            # 非常慢速输入，每个字符间有较长延迟
            for char in text:
                element.type(char, delay=150)
                time.sleep(0.25)  # 额外的间隔
            
            time.sleep(0.5)
            actual_value = element.input_value()
            if actual_value == text:
                logger.info(f"使用超慢速输入成功: {text}")
                return True
        except Exception as e:
            logger.warning(f"使用超慢速输入失败: {e}")
            
        logger.error(f"所有输入方法均失败，无法输入: {text}")
        return False

    def process_single_order(self, order_id: str) -> bool:
        """
        处理单个订单的下载流程
        
        Args:
            order_id (str): 订单号
            
        Returns:
            bool: 是否成功处理
        """
        if not self.page:
            logger.error("页面未初始化")
            return False
        try:
            logger.info(f"开始处理订单: {order_id}")
            # step10: 自动填写打印卡号和手机号
            self._step10_fill_printer_info()
            
            # ======= 订单号填写 - 按用户指定的三个步骤实现 =======
            
            # 第一步: 等待订单号输入框加载
            logger.info("第一步: 等待订单号输入框加载...")
            
            # 更精确的CSS选择器，直接使用用户提供的
            order_input_selector = '.MuiInputBase-input.css-1czfed0'
            
            try:
                # 等待订单号输入框出现 - 该输入框应与打印卡号和手机号同时加载
                self.page.wait_for_selector(order_input_selector, timeout=60000, state='visible')
                logger.info("订单号输入框已加载")
                
                input_element = self.page.query_selector(order_input_selector)
                if not input_element:
                    logger.error("找到选择器但无法获取输入元素")
                    self._save_error_screenshot(f"no_input_element_{order_id}")
                    return False
                
                # 检查输入框是否被禁用
                is_disabled = self.page.evaluate("el => el.disabled", input_element)
                logger.info(f"订单号输入框禁用状态: {is_disabled}")
                
                if is_disabled:
                    # 如果输入框被禁用，尝试使用JavaScript启用它
                    logger.info("尝试启用禁用的输入框...")
                    self.page.evaluate("el => { el.disabled = false; }", input_element)
                    time.sleep(0.5)
                    
                    is_still_disabled = self.page.evaluate("el => el.disabled", input_element)
                    if is_still_disabled:
                        logger.warning("无法启用输入框，但将继续尝试输入")
            except Exception as e:
                logger.error(f"等待订单号输入框失败: {e}")
                self._save_error_screenshot(f"wait_input_failed_{order_id}")
                return False
                
            # 第二步: 明确地将订单号拆分为前4位和后10位，分别填入两个不同的输入框
            logger.info("第二步: 拆分并分别填写订单号...")
            
            if len(order_id) >= 14:
                prefix = order_id[:4]  # 前四位，如"A017"
                suffix = order_id[4:]  # 后十位，如"X680406284"
                logger.info(f"订单号已拆分为: 前4位='{prefix}', 后10位='{suffix}'")
                
                try:
                    # 使用JavaScript定位两个输入框并分别填写
                    result = self.page.evaluate("""() => {
                        // 获取所有文本输入框
                        const inputs = document.querySelectorAll('input[type="text"]');
                        
                        // 记录输入框情况
                        return {
                            total: inputs.length,
                            boxStatus: inputs.length > 6 ? {
                                box1Disabled: inputs[4].disabled,
                                box2Disabled: inputs[5].disabled,
                                box1Mask: inputs[4].closest('div').getAttribute('mask') || 'unknown',
                                box2Mask: inputs[5].closest('div').getAttribute('mask') || 'unknown',
                                box1Length: inputs[4].closest('div').getAttribute('length') || 'unknown',
                                box2Length: inputs[5].closest('div').getAttribute('length') || 'unknown'
                            } : 'not enough inputs'
                        };
                    }""")
                    
                    logger.info(f"输入框状态：共{result['total']}个输入框，状态：{result['boxStatus']}")
                    
                    # 填写第一个输入框（前4位）
                    logger.info(f"填写第一个输入框（前4位）：{prefix}")
                    self.page.evaluate("""(value) => {
                        const inputs = document.querySelectorAll('input[type="text"]');
                        if (inputs && inputs.length > 4) {
                            const input = inputs[4]; // 第5个输入框（索引4）
                            // 启用输入框（如果被禁用）
                            if (input.disabled) { input.disabled = false; }
                            // 设置值并触发事件
                            input.value = value;
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                            console.log('已填写前4位：' + value);
                        }
                    }""", prefix)
                    
                    # 等待UI响应
                    time.sleep(1.0)
                    
                    # 填写第二个输入框（后10位）
                    logger.info(f"填写第二个输入框（后10位）：{suffix}")
                    self.page.evaluate("""(value) => {
                        const inputs = document.querySelectorAll('input[type="text"]');
                        if (inputs && inputs.length > 5) {
                            const input = inputs[5]; // 第6个输入框（索引5）
                            // 启用输入框（如果被禁用）
                            if (input.disabled) { input.disabled = false; }
                            // 设置值并触发事件
                            input.value = value;
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                            console.log('已填写后10位：' + value);
                        }
                    }""", suffix)
                    
                    # 再次等待UI响应
                    time.sleep(1.0)
                    
                    # 验证两个输入框的值
                    values = self.page.evaluate("""() => {
                        const inputs = document.querySelectorAll('input[type="text"]');
                        return {
                            box1: inputs.length > 4 ? inputs[4].value : '',
                            box2: inputs.length > 5 ? inputs[5].value : ''
                        };
                    }""")
                    
                    logger.info(f"验证填写结果: 前4位框='{values['box1']}', 后10位框='{values['box2']}'")
                    
                    if values['box1'] != prefix or values['box2'] != suffix:
                        logger.warning(f"订单号填写不完整或不正确: 期望前4位='{prefix}', 实际='{values['box1']}'; 期望后10位='{suffix}', 实际='{values['box2']}'")
                except Exception as e:
                    logger.error(f"填写订单号时出错: {e}")
                    self._save_error_screenshot(f"input_error_{order_id}")
            else:
                logger.error(f"订单号长度异常: {len(order_id)}，应至少为14位")
                return False
            
            # 第三步: 移动鼠标到搜索按钮，悬停，点击，等待结果
            logger.info("第三步: 点击搜索按钮并等待结果...")
            
            # 使用精确的搜索按钮选择器
            search_button_selector = 'button.MuiButton-outlinedWarning svg[data-testid="SearchIcon"]'
            
            try:
                # 等待搜索按钮出现
                self.page.wait_for_selector(search_button_selector, timeout=30000)
                
                # 使用JavaScript点击搜索按钮，避免元素拦截问题
                logger.info("使用JavaScript点击搜索按钮...")
                button_clicked = self.page.evaluate("""() => {
                    // 首先尝试通过SVG图标找到按钮
                    const svgIcons = document.querySelectorAll('svg[data-testid="SearchIcon"]');
                    if (svgIcons && svgIcons.length > 0) {
                        // 获取包含SVG图标的最近的按钮祖先
                        const button = svgIcons[0].closest('button');
                        if (button) {
                            console.log('找到搜索按钮，点击中...');
                            button.click();
                            return true;
                        }
                    }
                    
                    // 备用方案：尝试通过文本内容查找按钮
                    const buttons = document.querySelectorAll('button');
                    for (let btn of buttons) {
                        if (btn.textContent.includes('ค้นหา')) {
                            console.log('通过文本找到搜索按钮，点击中...');
                            btn.click();
                            return true;
                        }
                    }
                    
                    return false;
                }""")
                
                if button_clicked:
                    logger.info("搜索按钮点击成功，等待加载...")
                else:
                    logger.warning("JavaScript无法点击搜索按钮，尝试使用普通点击...")
                    # 备用方案：尝试直接点击元素
                    svg_element = self.page.query_selector(search_button_selector)
                    if svg_element:
                        # 如果找到SVG图标，获取其父按钮元素
                        parent_button = self.page.evaluate("""(element) => {
                            const button = element.closest('button');
                            return button ? true : false;
                        }""", svg_element)
                        
                        if parent_button:
                            # 直接使用CSS选择器点击
                            self.page.click('button.MuiButton-outlinedWarning', force=True)
                            logger.info("已直接点击搜索按钮")
                        else:
                            # 最后尝试：通过文本内容查找按钮并点击
                            self.page.click('button:has-text("ค้นหา")', force=True)
                            logger.info("通过文本内容点击搜索按钮")
                
                # 等待加载指示器消失
                try:
                    loading_selector = '.MuiCircularProgress-root'
                    self.page.wait_for_selector(loading_selector, timeout=5000)
                    logger.info("检测到加载指示器，等待其消失...")
                    self.page.wait_for_selector(loading_selector, state='hidden', timeout=120000) # 2分钟
                    logger.info("加载指示器已消失")
                except Exception:
                    logger.info("未检测到加载指示器或加载已完成")
                
                # 截图记录当前状态
                self._save_error_screenshot(f"after_search_{order_id}")
                
                # 等待搜索结果显示 - 使用更准确的选择器，针对React数据网格
                logger.info("等待搜索结果数据网格显示...")
                try:
                    # 尝试多种可能的结果容器选择器
                    result_selectors = [
                        '.InovuaReactDataGrid__row', 
                        '.InovuaReactDataGrid__cell',
                        'div[class*="DataGrid"]',
                        'div[class*="Grid"]'
                    ]
                    
                    found_results = False
                    for selector in result_selectors:
                        try:
                            # 使用较短的超时时间快速检查
                            self.page.wait_for_selector(selector, timeout=10000)
                            logger.info(f"找到搜索结果容器: {selector}")
                            found_results = True
                            break
                        except Exception:
                            continue
                    
                    if not found_results:
                        logger.warning("未通过选择器找到结果容器，使用JavaScript检查...")
                        
                        # 使用JavaScript检查页面内容
                        results_info = self.page.evaluate("""() => {
                            const gridRows = document.querySelectorAll('div[class*="DataGrid__row"], div[class*="Grid__row"]');
                            const gridCells = document.querySelectorAll('div[class*="DataGrid__cell"], div[class*="Grid__cell"]');
                            const printerIcon = document.querySelector('img[src*="icon_printer_fee"]');
                            
                            return {
                                rowCount: gridRows.length,
                                cellCount: gridCells.length,
                                hasPrinterIcon: !!printerIcon,
                                printerIconSrc: printerIcon ? printerIcon.src : null
                            };
                        }""")
                        
                        logger.info(f"页面检查结果: {results_info}")
                        
                        if results_info['rowCount'] > 0 or results_info['cellCount'] > 0 or results_info['hasPrinterIcon']:
                            found_results = True
                            logger.info("JavaScript确认找到结果数据")
                        else:
                            logger.error("未找到任何搜索结果行或单元格")
                            return False
                    
                    # 等待并点击打印图标
                    return self._click_printer_icon_and_download(order_id)
                    
                except Exception as e:
                    logger.error(f"等待搜索结果时出错: {e}")
                    self._save_error_screenshot(f"search_results_error_{order_id}")
                    return False
                
            except Exception as e:
                logger.error(f"点击搜索按钮过程中出错: {e}")
                self._save_error_screenshot(f"search_button_error_{order_id}")
                return False
            
        except Exception as e:
            logger.error(f"处理订单 {order_id} 时出错: {e}")
            self._save_error_screenshot(f"order_{order_id}_error")
            return False

    def _click_printer_icon_and_download(self, order_id: str) -> bool:
        """
        点击打印图标并下载PDF
        
        Args:
            order_id (str): 订单号
        
        Returns:
            bool: 是否成功下载
        """
        if not self.page:
            logger.error("页面未初始化")
            return False
            
        try:
            # 直接通过精确的图片URL查找打印图标
            logger.info("查找打印图标...")
            
            # 使用精确的图片URL
            printer_icon_selector = 'img[src*="icon_printer_fee"]'
            
            try:
                # 等待打印图标出现
                self.page.wait_for_selector(printer_icon_selector, timeout=30000)
                logger.info("已找到打印图标")
                
                # 截图记录找到图标时的状态
                self._save_error_screenshot(f"found_printer_icon_{order_id}")
                
                # 点击打印图标
                printer_clicked = self.page.evaluate("""() => {
                    // 通过URL查找打印图标
                    const printerIcon = document.querySelector('img[src*="icon_printer_fee"]');
                    if (printerIcon) {
                        // 获取父元素并滚动到视图
                        const cell = printerIcon.closest('div[class*="cell"]') || printerIcon.parentElement;
                        if (cell) cell.scrollIntoView({behavior: 'smooth', block: 'center'});
                        
                        // 点击图标
                        console.log('找到打印图标，点击中...');
                        printerIcon.click();
                        return true;
                    }
                    return false;
                }""")
                
                if printer_clicked:
                    logger.info("JavaScript成功点击打印图标")
                else:
                    # 如果JavaScript点击失败，尝试直接点击
                    logger.info("尝试直接点击打印图标...")
                    printer_icon = self.page.query_selector(printer_icon_selector)
                    if printer_icon:
                        printer_icon.scroll_into_view_if_needed()
                        time.sleep(0.5)
                        printer_icon.click()
                        logger.info("已直接点击打印图标")
                    else:
                        logger.error("未找到打印图标元素")
                        return False
            
                # 等待加载对话框
                logger.info("等待加载对话框...")
                loading_selectors = [
                    'div:has-text("Loading")', 
                    '.MuiCircularProgress-root', 
                    'div[role="progressbar"]'
                ]
                
                loading_found = False
                for selector in loading_selectors:
                    try:
                        self.page.wait_for_selector(selector, timeout=5000)
                        logger.info(f"检测到加载指示器: {selector}")
                        loading_found = True
                        break
                    except Exception:
                        continue
                
                if loading_found:
                    logger.info("等待加载指示器消失...")
                    for selector in loading_selectors:
                        try:
                            self.page.wait_for_selector(selector, state='hidden', timeout=120000)  # 2分钟
                            logger.info(f"加载指示器已消失: {selector}")
                            break
                        except Exception:
                            continue
                else:
                    logger.info("未检测到加载指示器，继续等待新页面...")
                
                # 准备保存PDF的路径
                receipts_dir = self.receipts_dir
                os.makedirs(receipts_dir, exist_ok=True)
                download_date = datetime.now().strftime('%Y%m%d')
                download_path = os.path.join(receipts_dir, f"{order_id}_{download_date}.pdf")
                
                # 记录当前页面信息以便比较
                current_url = self.page.url
                initial_pages_count = len(self.context.pages) if self.context else 0
                logger.info(f"当前URL: {current_url}, 当前页面数: {initial_pages_count}")
                
                # 等待页面变化
                logger.info("等待PDF预览页面出现（当前页面URL变化或新页面打开）...")
                pdf_page = None
                start_time = time.time()
                max_wait_time = 60  # 最多等待60秒
                
                # 等待页面变化循环
                while time.time() - start_time < max_wait_time:
                    time.sleep(1)
                    
                    # 检查方式1: 当前页面URL是否变为blob或包含PDF
                    new_url = self.page.url
                    if new_url != current_url:
                        logger.info(f"检测到当前页面URL已变化: {new_url}")
                        if new_url.startswith("blob:") or "pdf" in new_url.lower():
                            logger.info(f"当前页面已变为PDF预览页面: {new_url}")
                            pdf_page = self.page
                            break
                    
                    # 检查方式2: 页面内容是否包含PDF查看器
                    try:
                        has_pdf_viewer = self.page.evaluate("""() => {
                            return Boolean(
                                document.querySelector('embed[type="application/pdf"]') || 
                                document.querySelector('object[type="application/pdf"]') ||
                                document.querySelector('iframe[src*="pdf"]') ||
                                document.querySelector('embed[src*="blob:"]')
                            );
                        }""")
                        
                        if has_pdf_viewer:
                            logger.info("检测到当前页面已包含PDF查看器")
                            pdf_page = self.page
                            break
                    except Exception as e:
                        logger.warning(f"检查PDF查看器时出错: {e}")
                    
                    # 检查方式3: 是否有新页面打开
                    if self.context:
                        current_pages_count = len(self.context.pages)
                        if current_pages_count > initial_pages_count:
                            logger.info(f"检测到新页面打开，页面数从 {initial_pages_count} 增加到 {current_pages_count}")
                            new_page = self.context.pages[-1]
                            new_page_url = new_page.url
                            
                            if new_page_url.startswith("blob:") or "pdf" in new_page_url.lower():
                                logger.info(f"新打开的页面是PDF预览页面: {new_page_url}")
                                pdf_page = new_page
                                break
                
                # 如果未找到PDF页面，尝试最后一次检查
                if not pdf_page:
                    logger.warning(f"在 {max_wait_time} 秒内未检测到PDF预览页面，尝试最后检查...")
                    
                    # 保存当前页面截图
                    screenshot_path = str(self.paths.screenshots_dir / f"current_page_{order_id}_{download_date}.png")
                    self.page.screenshot(path=screenshot_path)
                    logger.info(f"已保存当前页面截图: {screenshot_path}")
                    
                    # 检查所有打开的页面
                    if self.context:
                        for i, page in enumerate(self.context.pages):
                            page_url = page.url
                            logger.info(f"页面 {i+1}: {page_url}")
                            
                            # 检查页面是否为PDF
                            if page_url.startswith("blob:") or "pdf" in page_url.lower():
                                logger.info(f"找到PDF相关页面: {page_url}")
                                pdf_page = page
                                break
                
                # 如果仍未找到PDF页面，尝试分析当前页面内容
                if not pdf_page:
                    try:
                        logger.info("尝试在当前页面查找iframe或embed元素...")
                        page_elements = self.page.evaluate("""() => {
                            const result = {
                                hasEmbed: false,
                                hasIframe: false,
                                hasPdfObject: false,
                                hasBlob: false,
                                embedSrc: '',
                                iframeSrc: '',
                                objectData: ''
                            };
                            
                            // 检查嵌入元素
                            const embeds = document.querySelectorAll('embed');
                            if (embeds.length > 0) {
                                result.hasEmbed = true;
                                result.embedSrc = embeds[0].src || '';
                            }
                            
                            // 检查iframe
                            const iframes = document.querySelectorAll('iframe');
                            if (iframes.length > 0) {
                                result.hasIframe = true;
                                result.iframeSrc = iframes[0].src || '';
                            }
                            
                            // 检查object元素
                            const objects = document.querySelectorAll('object[type="application/pdf"]');
                            if (objects.length > 0) {
                                result.hasPdfObject = true;
                                result.objectData = objects[0].data || '';
                            }
                            
                            // 检查是否有blob URL
                            result.hasBlob = (result.embedSrc.startsWith('blob:') || 
                                             result.iframeSrc.startsWith('blob:') || 
                                             result.objectData.startsWith('blob:'));
                            
                            return result;
                        }""")
                        
                        logger.info(f"页面元素分析结果: {page_elements}")
                        
                        if page_elements.get('hasBlob'):
                            logger.info(f"当前页面包含blob URL，将使用当前页面")
                            pdf_page = self.page
                    except Exception as e:
                        logger.warning(f"分析页面内容失败: {e}")
                
                # 如果仍未找到PDF页面，尝试强制刷新当前页面
                if not pdf_page:
                    try:
                        logger.info("尝试刷新当前页面，看是否能触发PDF显示...")
                        self.page.reload()
                        time.sleep(3)
                        
                        # 再次检查当前页面
                        refreshed_url = self.page.url
                        if refreshed_url.startswith("blob:") or "pdf" in refreshed_url.lower():
                            logger.info(f"刷新后页面变为PDF页面: {refreshed_url}")
                            pdf_page = self.page
                    except Exception as e:
                        logger.warning(f"刷新页面失败: {e}")
                
                # 如果所有方法都失败，使用当前页面作为最后尝试
                if not pdf_page:
                    logger.warning("所有检测方法均未找到PDF页面，将使用当前页面作为最后尝试")
                    pdf_page = self.page
                
                # 保存PDF页面截图用于调试
                try:
                    screenshot_path = str(self.paths.screenshots_dir / f"pdf_page_{order_id}_{download_date}.png")
                    pdf_page.screenshot(path=screenshot_path)
                    logger.info(f"已保存PDF页面截图: {screenshot_path}")
                except Exception as e:
                    logger.warning(f"保存截图失败: {e}")
                
                # 尝试所有可能的下载方法
                download_success = False
                
                # 方法1: 使用JavaScript直接从blob URL提取PDF内容（更可靠的实现）
                try:
                    logger.info("方法1: 使用改进版Blob URL提取方法获取PDF内容...")
                    
                    # 等待确保PDF内容已加载
                    time.sleep(2)
                    
                    # 提取PDF二进制数据
                    pdf_binary = pdf_page.evaluate("""
                        async () => {
                            try {
                                console.log('开始查找PDF元素...');
                                
                                // 依次检查各种可能包含PDF的元素
                                const elements = [
                                    document.querySelector('embed[type="application/pdf"]'),
                                    document.querySelector('object[type="application/pdf"]'),
                                    document.querySelector('iframe[src*="pdf"]'),
                                    document.querySelector('iframe[src^="blob:"]'),
                                    document.querySelector('embed[src^="blob:"]')
                                ].filter(el => el);
                                
                                // 如果页面URL本身就是blob，也添加到检查列表
                                let blobUrls = [];
                                if (window.location.href.startsWith('blob:')) {
                                    console.log('当前页面本身是blob URL');
                                    blobUrls.push(window.location.href);
                                }
                                
                                // 从找到的元素中提取blob URL
                                for (const el of elements) {
                                    if (el && el.src && el.src.startsWith('blob:')) {
                                        console.log('找到blob URL元素:', el.tagName, el.src);
                                        blobUrls.push(el.src);
                                    } else if (el && el.data && el.data.startsWith('blob:')) {
                                        console.log('找到blob data元素:', el.tagName, el.data);
                                        blobUrls.push(el.data);
                                    }
                                }
                                
                                // 如果没有找到blob URL，尝试在文档中搜索
                                if (blobUrls.length === 0) {
                                    console.log('在DOM中搜索blob URL...');
                                    const allLinks = Array.from(document.querySelectorAll('a[href^="blob:"], link[href^="blob:"]'));
                                    for (const link of allLinks) {
                                        blobUrls.push(link.href);
                                    }
                                    
                                    // 搜索脚本中可能包含的blob URL
                                    const scriptText = Array.from(document.querySelectorAll('script'))
                                        .map(script => script.textContent)
                                        .join(' ');
                                    const blobMatches = scriptText.match(/blob:[^"'\\s]+/g);
                                    if (blobMatches) {
                                        blobUrls.push(...blobMatches);
                                    }
                                }
                                
                                console.log(`找到 ${blobUrls.length} 个blob URL:`, blobUrls);
                                
                                // 如果仍然没有找到blob URL，尝试查找内联PDF数据
                                if (blobUrls.length === 0) {
                                    console.log('尝试查找内联PDF数据...');
                                    const pdfObjects = Array.from(document.querySelectorAll('object[data^="data:application/pdf"]'));
                                    if (pdfObjects.length > 0) {
                                        const dataUrl = pdfObjects[0].data;
                                        console.log('找到内联PDF数据URL');
                                        try {
                                            // 从data URL提取数据
                                            const response = await fetch(dataUrl);
                                            const blob = await response.blob();
                                            const arrayBuffer = await blob.arrayBuffer();
                                            return Array.from(new Uint8Array(arrayBuffer));
                                        } catch (e) {
                                            console.error('处理data URL时出错:', e);
                                        }
                                    }
                                    return null;
                                }
                                
                                // 尝试获取第一个有效的blob URL内容
                                for (const blobUrl of blobUrls) {
                                    try {
                                        console.log('正在获取blob内容:', blobUrl);
                                        const response = await fetch(blobUrl);
                                        if (!response.ok) {
                                            console.log('获取失败, HTTP状态:', response.status);
                                            continue;
                                        }
                                        
                                        const blob = await response.blob();
                                        // 验证是否为PDF (检查魔数)
                                        const firstBytes = await blob.slice(0, 5).arrayBuffer();
                                        const header = new Uint8Array(firstBytes);
                                        const isPdf = header[0] === 37 && header[1] === 80 && 
                                                      header[2] === 68 && header[3] === 70; // %PDF
                                        
                                        if (!isPdf) {
                                            console.log('不是有效的PDF数据，跳过');
                                            continue;
                                        }
                                        
                                        const arrayBuffer = await blob.arrayBuffer();
                                        console.log(`成功获取PDF数据，大小: ${arrayBuffer.byteLength} 字节`);
                                        return Array.from(new Uint8Array(arrayBuffer));
                                    } catch (e) {
                                        console.error('处理blob URL时出错:', e);
                                    }
                                }
                                
                                console.log('所有blob URL都处理失败');
                                return null;
                            } catch (error) {
                                console.error('提取PDF内容时出错:', error);
                                return null;
                            }
                        }
                    """)
                    
                    # 检查是否成功提取PDF二进制数据
                    if pdf_binary and len(pdf_binary) > 1000:  # 确保数据长度合理
                        logger.info(f"成功提取PDF二进制数据，大小: {len(pdf_binary) / 1024:.2f} KB")
                        
                        # 验证PDF头部
                        is_valid_pdf = False
                        if len(pdf_binary) >= 4:
                            # 检查PDF魔数 (%PDF)
                            if pdf_binary[0] == 37 and pdf_binary[1] == 80 and pdf_binary[2] == 68 and pdf_binary[3] == 70:
                                is_valid_pdf = True
                                logger.info("数据包含有效的PDF头部标识")
                            else:
                                logger.warning(f"数据缺少PDF头部标识，前4个字节: {pdf_binary[:4]}")
                        
                        if is_valid_pdf:
                            # 保存为PDF文件
                            with open(download_path, "wb") as f:
                                f.write(bytes(pdf_binary))
                            logger.info(f"已将PDF内容保存到: {download_path}")
                            download_success = True
                        else:
                            logger.warning("提取的数据不是有效的PDF，跳过保存")
                    else:
                        if pdf_binary:
                            logger.warning(f"提取的数据太小 ({len(pdf_binary)} 字节)，可能不是完整PDF")
                        else:
                            logger.warning("未能从页面提取PDF内容")
                except Exception as e:
                    logger.warning(f"提取PDF内容失败: {e}")
                    traceback.print_exc()
                
                # 方法2: 如果方法1失败，尝试使用PDF查看器控件直接下载
                if not download_success:
                    try:
                        logger.info("方法2: 尝试使用PDF查看器的下载控件...")
                        
                        # 设置下载监听
                        download_complete = False
                        
                        def handle_download(download):
                            nonlocal download_complete
                            logger.info(f"检测到下载: {download.suggested_filename}")
                            try:
                                download.save_as(download_path)
                                download_complete = True
                                logger.info(f"下载的文件已保存到: {download_path}")
                            except Exception as save_err:
                                logger.error(f"保存下载的文件时出错: {save_err}")
                        
                        # 添加下载监听器
                        pdf_page.on('download', handle_download)
                        
                        # 确保页面有焦点
                        pdf_page.bring_to_front()
                        time.sleep(1)
                        
                        # 尝试直接使用下载控件
                        logger.info("尝试使用下载控件...")
                        download_clicked = pdf_page.evaluate("""() => {
                            try {
                                // 尝试方法1: 通过ID查找下载控件并点击
                                const downloadControls = document.querySelector('viewer-download-controls');
                                if (downloadControls) {
                                    // 尝试通过查找下载控件中的下载按钮
                                    const downloadButton = downloadControls.shadowRoot ? 
                                        downloadControls.shadowRoot.querySelector('cr-icon-button') : 
                                        downloadControls.querySelector('cr-icon-button');
                                    
                                    if (downloadButton) {
                                        console.log('找到下载按钮，点击中...');
                                        downloadButton.click();
                                        return true;
                                    }
                                    
                                    // 如果没有找到下载按钮，尝试直接点击下载控件
                                    console.log('直接点击下载控件...');
                                    downloadControls.click();
                                    return true;
                                }
                                
                                // 尝试方法2: 查找任何具有下载图标或下载文本的按钮
                                const allButtons = document.querySelectorAll('cr-icon-button, button');
                                for (const button of allButtons) {
                                    if (button.getAttribute('iron-icon') === 'cr:file-download' || 
                                        button.getAttribute('title')?.includes('下载') || 
                                        button.textContent?.includes('下载')) {
                                        console.log('找到下载相关按钮，点击中...');
                                        button.click();
                                        return true;
                                    }
                                }
                                
                                return false;
                            } catch (error) {
                                console.error('点击下载控件失败:', error);
                                return false;
                            }
                        }""")
                        
                        if download_clicked:
                            logger.info("成功点击下载控件或按钮")
                        else:
                            logger.warning("未找到下载控件或点击失败，尝试使用打印按钮...")
                            
                            # 尝试点击打印按钮，然后将其导出为PDF
                            print_clicked = pdf_page.evaluate("""() => {
                                try {
                                    // 查找打印按钮
                                    const printButton = document.querySelector('cr-icon-button#print');
                                    if (printButton) {
                                        console.log('找到打印按钮，点击中...');
                                        printButton.click();
                                        return true;
                                    }
                                    
                                    // 备用：查找任何打印相关按钮
                                    const buttons = document.querySelectorAll('cr-icon-button, button');
                                    for (const button of buttons) {
                                        if (button.getAttribute('iron-icon') === 'pdf-cr23:print' || 
                                            button.getAttribute('title')?.includes('打印') || 
                                            button.textContent?.includes('打印')) {
                                            console.log('找到打印相关按钮，点击中...');
                                            button.click();
                                            return true;
                                        }
                                    }
                                    
                                    return false;
                                } catch (error) {
                                    console.error('点击打印按钮失败:', error);
                                    return false;
                                }
                            }""")
                            
                            if print_clicked:
                                logger.info("成功点击打印按钮，等待打印对话框...")
                                time.sleep(2)  # 等待打印对话框出现
                                
                                # 检查打印预览对话框是否出现
                                has_print_dialog = pdf_page.evaluate("""() => {
                                    return !!document.querySelector('print-preview-app') || 
                                           !!document.querySelector('cr-dialog') ||
                                           !!document.querySelector('[aria-label="打印"]') ||
                                           !!document.querySelector('[aria-label="Print"]');
                                }""")
                                
                                if has_print_dialog:
                                    logger.info("检测到打印预览对话框")
                                    
                                    # 等待打印预览组件加载完成
                                    time.sleep(2)
                                    
                                    # 设置目标为"另存为PDF"
                                    pdf_page.evaluate("""() => {
                                        try {
                                            // 尝试点击目标打印机下拉菜单
                                            const destinationSelect = document.querySelector('print-preview-destination-select');
                                            if (destinationSelect && destinationSelect.shadowRoot) {
                                                const dropdownButton = destinationSelect.shadowRoot.querySelector('cr-button');
                                                if (dropdownButton) {
                                                    console.log('点击目标打印机下拉菜单...');
                                                    dropdownButton.click();
                                                }
                                            }
                                        } catch (error) {
                                            console.error('点击目标下拉菜单失败:', error);
                                        }
                                    }""")
                                    time.sleep(1.5)
                                    
                                    # 选择"另存为PDF"选项
                                    pdf_page.evaluate("""() => {
                                        try {
                                            // 尝试选择"另存为PDF"选项
                                            const menuItems = Array.from(document.querySelectorAll('cr-action-menu cr-button'));
                                            const saveToPdfButton = menuItems.find(item => 
                                                item.textContent.includes('PDF') || 
                                                item.textContent.includes('Save as PDF') ||
                                                item.textContent.includes('另存为PDF'));
                                                
                                            if (saveToPdfButton) {
                                                console.log('点击"另存为PDF"选项...');
                                                saveToPdfButton.click();
                                                return true;
                                            }
                                            
                                            // 备用：尝试找到带有PDF文本的任何元素
                                            const pdfOptions = Array.from(document.querySelectorAll('*')).filter(el => 
                                                el.textContent.includes('PDF') && el.offsetWidth > 0 && el.offsetHeight > 0);
                                                
                                            if (pdfOptions.length > 0) {
                                                console.log('找到可能的PDF选项，点击中...');
                                                pdfOptions[0].click();
                                                return true;
                                            }
                                            
                                            return false;
                                        } catch (error) {
                                            console.error('选择另存为PDF选项失败:', error);
                                            return false;
                                        }
                                    }""")
                                    time.sleep(1.5)
                                    
                                    # 点击"保存"按钮
                                    save_clicked = pdf_page.evaluate("""() => {
                                        try {
                                            // 查找并点击保存按钮 (更完整的选择器)
                                            const saveButton = document.querySelector('print-preview-app')?.shadowRoot
                                                ?.querySelector('print-preview-sidebar')
                                                ?.shadowRoot?.querySelector('print-preview-button-strip')
                                                ?.shadowRoot?.querySelector('cr-button.action-button');
                                                
                                            if (saveButton) {
                                                console.log('找到保存按钮，点击中...');
                                                saveButton.click();
                                                return true;
                                            }
                                            
                                            // 备用：查找任何保存相关按钮
                                            const allButtons = document.querySelectorAll('button, cr-button');
                                            for (const button of allButtons) {
                                                if (button.textContent.includes('保存') || 
                                                    button.textContent.includes('Save') || 
                                                    button.classList.contains('action-button') ||
                                                    button.getAttribute('class')?.includes('primary')) {
                                                    console.log('找到保存相关按钮，点击中...');
                                                    button.click();
                                                    return true;
                                                }
                                            }
                                            
                                            return false;
                                        } catch (error) {
                                            console.error('点击保存按钮失败:', error);
                                            return false;
                                        }
                                    }""")
                                    
                                    if not save_clicked:
                                        logger.warning("未找到或无法点击保存按钮，尝试使用Enter键...")
                                        pdf_page.keyboard.press("Enter")
                            else:
                                # 如果点击打印按钮失败，尝试直接使用键盘快捷键
                                logger.warning("未找到或无法点击打印按钮，尝试使用键盘快捷键Ctrl+S...")
                                pdf_page.keyboard.press("Control+s")
                                time.sleep(1.5)
                                pdf_page.keyboard.press("Enter")  # 尝试确认保存对话框
                        
                        # 等待下载完成
                        start_time = time.time()
                        while not download_complete and time.time() - start_time < 30:  # 最多等待30秒
                            time.sleep(1)
                            if os.path.exists(download_path) and os.path.getsize(download_path) > 0:
                                logger.info(f"检测到文件已保存: {download_path}")
                                download_complete = True
                                break
                        
                        # 移除下载监听器
                        pdf_page.remove_listener('download', handle_download)
                        
                        # 如果打印对话框仍然打开，尝试关闭它
                        try:
                            pdf_page.keyboard.press("Escape")  # 尝试关闭任何打开的对话框
                        except Exception:
                            pass
                        
                        if download_complete:
                            logger.info("使用PDF查看器控件成功下载PDF")
                            download_success = True
                        else:
                            logger.warning("使用PDF查看器控件下载失败或超时")
                    except Exception as e:
                        logger.warning(f"使用PDF查看器控件下载时出错: {e}")
                        traceback.print_exc()
                
                # 方法3: 直接使用page.pdf()方法
                if not download_success:
                    try:
                        logger.info(f"方法3: 尝试使用page.pdf()方法保存...")
                        pdf_page.pdf(path=download_path)
                        
                        # 检查文件是否成功保存
                        if os.path.exists(download_path) and os.path.getsize(download_path) > 0:
                            logger.info(f"使用pdf()方法成功保存PDF: {download_path}")
                            download_success = True
                        else:
                            logger.warning("pdf()方法创建的文件为空或不存在")
                    except Exception as e:
                        logger.warning(f"使用pdf()方法保存失败: {e}")
                
                # 方法4: 如果前三种方法都失败，尝试查找并截取PDF区域
                if not download_success:
                    try:
                        logger.info("方法4: 尝试查找并截取PDF区域...")
                        pdf_area = pdf_page.evaluate("""() => {
                            // 尝试查找可能的PDF容器
                            const pdfElements = [
                                document.querySelector('embed[type="application/pdf"]'),
                                document.querySelector('object[type="application/pdf"]'),
                                document.querySelector('iframe'),
                                document.querySelector('div.pdf-container'),
                                document.querySelector('div[role="document"]')
                            ].filter(el => el);
                            
                            if (pdfElements.length > 0) {
                                const element = pdfElements[0];
                                const rect = element.getBoundingClientRect();
                                return {
                                    found: true,
                                    x: rect.left,
                                    y: rect.top,
                                    width: rect.width,
                                    height: rect.height
                                };
                            }
                            return { found: false };
                        }""")
                        
                        if pdf_area and pdf_area.get('found'):
                            logger.info(f"找到PDF区域: {pdf_area}")
                            
                            # 截取PDF区域 - 修复类型错误
                            clip_options = FloatRect(
                                x=float(pdf_area['x']),
                                y=float(pdf_area['y']),
                                width=float(pdf_area['width']),
                                height=float(pdf_area['height'])
                            )
                            
                            # 截取为PNG
                            png_path = os.path.join(receipts_dir, f"{order_id}_{download_date}.png")
                            pdf_page.screenshot(path=png_path, clip=clip_options)
                            logger.info(f"已保存PDF区域截图: {png_path}")
                            
                            # 创建一个最小的PDF文件作为标记
                            with open(download_path, "wb") as f:
                                f.write(b"%PDF-1.5\n%This is an auto-generated PDF marker, PDF area was saved as PNG\n%EOF\n")
                            logger.info(f"已创建PDF标记文件，实际内容已保存为图片: {png_path}")
                            
                            download_success = True
                        else:
                            logger.warning("未找到PDF区域")
                    except Exception as e:
                        logger.warning(f"截取PDF区域失败: {e}")
                
                # 方法5: 保存为图片作为最终后备
                if not download_success:
                    try:
                        logger.info("方法5: 保存整个页面截图作为最终后备...")
                        
                        # 保存页面截图
                        png_path = os.path.join(receipts_dir, f"{order_id}_{download_date}.png")
                        pdf_page.screenshot(path=png_path, full_page=True)
                        logger.info(f"已保存整个页面截图: {png_path}")
                        
                        # 创建最小PDF文件
                        with open(download_path, "wb") as f:
                            f.write(b"%PDF-1.5\n%This is an auto-generated PDF marker, full page was saved as PNG\n%EOF\n")
                        logger.info(f"已创建最小PDF标记文件: {download_path}")
                        
                        download_success = True
                    except Exception as e:
                        logger.error(f"保存页面截图失败: {e}")
                
                # 关闭PDF页面（如果是新打开的）
                if pdf_page and pdf_page != self.page:
                    try:
                        pdf_page.close()
                        logger.info("已关闭PDF页面")
                    except Exception as e:
                        logger.warning(f"关闭PDF页面失败: {e}")
                
                fallback_png_path = Path(receipts_dir) / f"{order_id}_{download_date}.png"
                validation_result = validate_pdf_artifact(
                    order_id=order_id,
                    pdf_path=Path(download_path),
                    fallback_path=fallback_png_path if fallback_png_path.exists() else None,
                    source="legacy-session-manager",
                    policy=self.validation_policy,
                )
                self.current_receipt_result = validation_result

                if validation_result.status is ExecutionStatus.SUCCEEDED:
                    logger.info(f"订单 {order_id} 的PDF已成功保存并通过校验")
                    return True

                logger.error(
                    f"订单 {order_id} 的输出未通过PDF校验: {validation_result.reason}"
                )
                return False
            except Exception as e:
                logger.error(f"查找或点击打印图标时出错: {e}")
                return False
        except Exception as e:
            logger.error(f"点击打印图标和下载过程中出错: {e}")
            self._save_error_screenshot(f"download_error_{order_id}")
            return False

    def batch_fullflow_download(
        self,
        excel_path: Optional[str] = None,
        sheet_name: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        批量下载所有订单的PDF
        
        Returns:
            Dict[str, int]: 包含处理结果的字典，包括total（总数）、success（成功数）和failed（失败数）
        """
        try:
            # 读取Excel中的订单号
            excel_reader = ExcelReader(excel_path, settings=self.settings)
            order_ids = excel_reader.get_order_ids(sheet_name)
            
            if not order_ids:
                logger.warning("未找到任何订单号")
                return {"total": 0, "success": 0, "failed": 0, "needs_human_review": 0}
                
            logger.info(f"共找到 {len(order_ids)} 个订单")
            
            # 处理每个订单
            success_count = 0
            failed_count = 0
            needs_human_review_count = 0
            
            for index, order_id in enumerate(order_ids, 1):
                logger.info(f"处理第 {index}/{len(order_ids)} 个订单")
                
                result = self.process_order_result(order_id)
                if result.status is ExecutionStatus.SUCCEEDED:
                    success_count += 1
                elif result.status is ExecutionStatus.NEEDS_HUMAN_REVIEW:
                    needs_human_review_count += 1
                else:
                    failed_count += 1
                    
                # 随机延迟，避免操作过快
                self._random_delay(1.0, 3.0)
                
            logger.info(f"批量下载完成，成功: {success_count}/{len(order_ids)}")
            
            # 返回处理结果
            return {
                "total": len(order_ids),
                "success": success_count,
                "failed": failed_count,
                "needs_human_review": needs_human_review_count,
            }
            
        except Exception as e:
            logger.error(f"批量下载过程中出错: {e}")
            self._save_error_screenshot("batch_download_error")
            # 发生异常时返回零结果
            return {"total": 0, "success": 0, "failed": 0, "needs_human_review": 0}
