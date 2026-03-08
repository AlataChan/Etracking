"""
测试批量下载功能
"""
import os
import sys
from loguru import logger
from src.session_manager import SessionManager
from src.excel_reader import ExcelReader

def setup_logger():
    """
    设置日志记录器
    """
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    log_file = os.path.join(logs_dir, 'batch_test.log')
    
    # 添加控制台输出
    logger.remove()  # 移除默认处理器
    logger.add(sys.stderr, level="INFO", colorize=True)
    
    # 添加文件输出
    logger.add(
        log_file, 
        rotation="10 MB", 
        level="DEBUG", 
        compression="zip", 
        encoding="utf-8"
    )

def create_test_excel():
    """
    创建测试用的Excel文件，如果不存在的话
    """
    import pandas as pd
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
    os.makedirs(data_dir, exist_ok=True)
    
    excel_path = os.path.join(data_dir, 'test_orders.xlsx')
    
    # 如果文件已存在，不创建
    if os.path.exists(excel_path):
        logger.info(f"测试Excel文件已存在: {excel_path}")
        return excel_path

    # 创建测试数据
    df = pd.DataFrame({
        'A': ['订单号', '', '备注'],
        'B': ['备注1', '', '备注2'], 
        'C': ['备注3', '', '备注4'],
        'D': ['备注5', '', '备注6'],
        'E': ['备注7', '', '备注8'],
        'F': ['A017X680406284', 'A017X680406285', 'A017X680406286']  # 测试订单号，使用相似但不同的号码
    })
    
    # 保存到Excel
    df.to_excel(excel_path, index=False)
    logger.info(f"已创建测试Excel文件: {excel_path}")
    
    return excel_path

def test_with_test_data():
    """
    使用硬编码的测试数据进行测试
    """
    # 测试用的订单号列表
    test_orders = [
        'A017X680406284',
        'A017X680406285'
    ]
    
    logger.info(f"使用硬编码测试数据: {test_orders}")
    
    # 使用会话管理器处理
    with SessionManager() as session:
        for order_id in test_orders:
            logger.info(f"\n===== 处理订单: {order_id} =====")
            result = session.process_single_order(order_id)
            logger.info(f"处理结果: {'成功' if result else '失败'}")
            
def test_with_excel_data():
    """
    使用Excel文件中的数据进行测试
    """
    # 创建测试Excel文件
    excel_path = create_test_excel()
    
    # 读取Excel中的订单号
    reader = ExcelReader(excel_path)
    order_ids = reader.get_order_ids()
    
    if not order_ids:
        logger.error("未从Excel中读取到订单号，退出测试")
        return
    
    logger.info(f"从Excel读取到 {len(order_ids)} 个订单号: {order_ids}")
    
    # 使用会话管理器进行批量处理
    with SessionManager() as session:
        session.batch_fullflow_download()

def main():
    """
    主函数
    """
    setup_logger()
    logger.info("===== 开始批量下载测试 =====")
    
    # 选择一种测试方式
    # test_with_test_data()  # 使用硬编码数据
    test_with_excel_data()   # 使用Excel数据
    
    logger.info("===== 批量下载测试完成 =====")

if __name__ == "__main__":
    main() 