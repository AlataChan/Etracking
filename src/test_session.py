"""
测试模块
"""
import pytest
from src.session_manager import SessionManager
from src.excel_reader import ExcelReader
import os
import time
from loguru import logger

def test_single_receipt():
    """
    测试单个收据下载流程
    """
    with SessionManager() as sm:
        # 测试订单号
        test_order_id = "1234567890"
        logger.info(f"\n===== 测试单个订单下载流程: {test_order_id} =====")
        
        # 执行下载流程
        result = sm.process_single_order(test_order_id)
        
        # 验证结果
        assert result is True, f"订单 {test_order_id} 处理失败"
        
        # 检查PDF文件是否存在
        pdf_path = os.path.join(sm.downloads_dir, f"{test_order_id}_{time.strftime('%Y%m%d')}.pdf")
        assert os.path.exists(pdf_path), f"PDF文件不存在: {pdf_path}"

def test_batch_download():
    """
    测试批量下载功能
    """
    with SessionManager() as sm:
        logger.info("\n===== 测试批量下载功能 =====")
        
        # 获取测试订单号
        excel_reader = ExcelReader()
        order_ids = excel_reader.get_order_ids()
        assert len(order_ids) > 0, "未找到测试订单号"
        
        # 执行批量下载
        sm.batch_fullflow_download()
        
        # 验证下载结果
        today = time.strftime('%Y%m%d')
        for order_id in order_ids:
            pdf_path = os.path.join(sm.downloads_dir, f"{order_id}_{today}.pdf")
            assert os.path.exists(pdf_path), f"PDF文件不存在: {pdf_path}"

if __name__ == "__main__":
    # 设置日志级别
    logger.remove()
    logger.add("logs/test.log", level="INFO", rotation="1 day")
    logger.add(lambda msg: print(msg), level="INFO")
    
    # 运行测试
    pytest.main([__file__, "-v"]) 