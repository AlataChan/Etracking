"""
收据打印模块，负责搜索和下载收据PDF
"""

from typing import Optional, Dict, Any, List
from playwright.sync_api import Page, ElementHandle, BrowserContext
from loguru import logger
import os
import time
import random
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'settings.yaml')

class ReceiptPrinter:
    """
    收据打印器，负责搜索订单号并下载PDF
    """
    def __init__(self, page: Page, context: BrowserContext) -> None:
        """
        初始化收据打印器
        
        Args:
            page: Playwright页面对象
            context: Playwright浏览器上下文
        """
        self.page = page
        self.context = context
        self.config = self._load_config()
        self.download_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 
            self.config.get('file', {}).get('output_dir', 'downloads')
        )
        os.makedirs(self.download_path, exist_ok=True)
        
        # 设置PDF下载事件监听
        self._setup_download_handlers()
        
    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        if not os.path.exists(CONFIG_PATH):
            logger.warning(f"未找到配置文件: {CONFIG_PATH}，使用默认配置")
            return {}
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
            
    def _setup_download_handlers(self) -> None:
        """
        设置下载事件处理器
        """
        if not self.context:
            return
            
        # 监听新页面打开事件，通常是PDF预览页
        self.context.on("page", self._handle_new_page)
        
    def _handle_new_page(self, new_page: Page) -> None:
        """
        处理新打开的页面，通常是PDF预览
        
        Args:
            new_page: 新打开的页面对象
        """
        logger.info("检测到新页面打开，可能是PDF预览")
        
        try:
            # 等待页面加载完成
            new_page.wait_for_load_state("networkidle", timeout=30000)
            logger.info("PDF页面加载完成，准备下载")
            
            # 执行PDF下载
            self._download_pdf(new_page)
        except Exception as e:
            logger.error(f"处理PDF页面时出错: {e}")
            new_page.screenshot(path=os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "logs", "screenshots", f"pdf_error_{time.strftime('%Y%m%d_%H%M%S')}.png"
            ))
        finally:
            # 关闭PDF页面
            try:
                new_page.close()
            except Exception:
                pass
                
    def _download_pdf(self, pdf_page: Page) -> Optional[bytes]:
        """
        从PDF页面下载PDF文件
        
        Args:
            pdf_page: PDF预览页面
            
        Returns:
            Optional[bytes]: PDF二进制数据，失败则返回None
        """
        try:
            # 获取当前URL中的订单号参数
            url = pdf_page.url
            receipt_id = self._extract_receipt_id(url)
            
            if not receipt_id:
                logger.warning(f"无法从URL提取订单号: {url}")
                receipt_id = f"unknown_{time.strftime('%Y%m%d_%H%M%S')}"
                
            # 构建PDF文件名
            filename = self.config.get('file', {}).get('name_format', '{receipt_id}.pdf').format(receipt_id=receipt_id)
            filepath = os.path.join(self.download_path, filename)
            
            # 使用Playwright保存PDF
            logger.info(f"开始下载PDF，保存为: {filepath}")
            pdf_data = pdf_page.pdf(
                path=filepath,
                format="A4",
                print_background=True
            )
            
            logger.info(f"PDF下载成功: {filepath}")
            return pdf_data
        except Exception as e:
            logger.error(f"下载PDF时出错: {e}")
            return None
            
    def _extract_receipt_id(self, url: str) -> Optional[str]:
        """
        从URL中提取订单号
        
        Args:
            url: 页面URL
            
        Returns:
            Optional[str]: 提取的订单号，如果未找到则返回None
        """
        # 实现从URL中提取订单号的逻辑
        # 这里仅为示例，需要根据实际URL格式调整
        import re
        match = re.search(r'receiptId=([^&]+)', url)
        if match:
            return match.group(1)
        return None
        
    def search_receipt(self, receipt_id: str) -> bool:
        """
        搜索并打印指定订单号的收据
        
        Args:
            receipt_id: 订单号
            
        Returns:
            bool: 搜索成功返回True，否则False
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
            
        try:
            logger.info(f"开始搜索订单号: {receipt_id}")
            
            # 等待搜索框出现
            logger.info("等待搜索框出现...")
            search_input = self.page.wait_for_selector('input[type="text"].MuiInputBase-input.MuiOutlinedInput-input', timeout=30000)
            if not search_input:
                raise RuntimeError("未找到订单号搜索框")
                
            # 清空搜索框并输入订单号
            search_input.click()
            search_input.fill("")
            time.sleep(0.3)
            search_input.fill(receipt_id)
            logger.info(f"已输入订单号: {receipt_id}")
            
            # 点击搜索按钮
            logger.info("点击搜索按钮...")
            search_btn = self.page.wait_for_selector('button:has-text("ค้นหา")', timeout=10000)
            if search_btn:
                search_btn.click()
            else:
                self.page.click('button:has-text("ค้นหา")')
                
            # 等待搜索结果加载
            try:
                self.page.wait_for_selector('.MuiCircularProgress-root', state='hidden', timeout=20000)
            except Exception:
                pass  # 忽略loading动画可能不存在的情况
                
            # 检查是否有搜索结果
            logger.info("检查搜索结果...")
            time.sleep(2)  # 确保结果已加载
            
            # 检查是否有"ไม่พบข้อมูล"消息(未找到结果)
            no_results = self.page.query_selector('div:has-text("ไม่พบข้อมูล")')
            if no_results:
                logger.warning(f"未找到订单号 {receipt_id} 的结果")
                return False
                
            # 点击查看PDF图标
            logger.info("查找并点击查看PDF图标...")
            view_icon = self.page.query_selector('button svg.MuiSvgIcon-root[data-testid="VisibilityIcon"]')
            if not view_icon:
                logger.warning("未找到查看PDF图标")
                return False
                
            # 点击父级按钮元素
            view_btn = view_icon.evaluate('node => node.closest("button")')
            if view_btn:
                self.page.evaluate('btn => btn.click()', view_btn)
                logger.info("已点击查看PDF按钮，等待PDF页面打开...")
            else:
                logger.warning("无法获取查看PDF的按钮元素")
                return False
                
            # 等待PDF页面事件处理
            logger.info("等待PDF处理完成...")
            time.sleep(5)  # 给_handle_new_page回调足够的时间处理
            
            return True
        except Exception as e:
            logger.error(f"搜索订单号 {receipt_id} 时出错: {e}")
            if self.page:
                self.page.screenshot(path=os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "logs", "screenshots", f"search_error_{receipt_id}_{time.strftime('%Y%m%d_%H%M%S')}.png"
                ))
            return False
            
    def print_multiple_receipts(self, receipt_ids: List[str]) -> Dict[str, bool]:
        """
        批量打印多个订单号的收据
        
        Args:
            receipt_ids: 订单号列表
            
        Returns:
            Dict[str, bool]: 每个订单号的处理结果，成功为True，失败为False
        """
        results = {}
        
        for receipt_id in receipt_ids:
            # 随机延迟，模拟人类行为
            delay = random.uniform(1.5, 3.0)
            logger.info(f"等待 {delay:.2f} 秒后处理下一个订单...")
            time.sleep(delay)
            
            # 搜索并下载收据
            success = self.search_receipt(receipt_id)
            results[receipt_id] = success
            
            # 记录处理结果
            if success:
                logger.info(f"订单 {receipt_id} 处理成功")
            else:
                logger.warning(f"订单 {receipt_id} 处理失败")
                
        # 输出处理摘要
        total = len(receipt_ids)
        successful = sum(1 for success in results.values() if success)
        logger.info(f"批量处理完成: 总共 {total} 个订单，成功 {successful} 个，失败 {total - successful} 个")
        
        return results 