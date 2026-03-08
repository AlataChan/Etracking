"""
测试角色选择功能
"""
from src.session_manager import SessionManager
from loguru import logger
import os
import sys
import time

# 配置日志
log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(log_path, exist_ok=True)
logger.add(os.path.join(log_path, "test_roles.log"), rotation="10 MB")

def test_role_selection():
    """
    专门测试角色选择功能
    """
    logger.info("开始测试角色选择功能")
    
    # 修改SessionManager的_select_company_role方法
    original_method = SessionManager._select_company_role
    
    def custom_select_company_role(self):
        """
        使用精确的选择器选择正确的角色
        """
        if not self.page:
            raise RuntimeError("页面未初始化")
            
        try:
            # 等待角色选择的区域显示
            logger.info("等待角色选择区域出现...")
            self.page.wait_for_selector("h6", timeout=20000)
            
            # 1. 选择公司角色：代表（法人实体）- กระทำการแทน (สำหรับนิติบุคคล)
            company_selector = "input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='2']"
            logger.info(f"选择公司角色: 代表（法人实体），使用选择器 {company_selector}")
            
            # 直接使用JavaScript选择
            self.page.evaluate("""
                const companyRadio = document.querySelector("input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='2']");
                if (companyRadio) {
                    companyRadio.click();
                    companyRadio.checked = true;
                    companyRadio.dispatchEvent(new Event('change', { bubbles: true }));
                } else {
                    console.error("未找到公司角色单选框");
                }
            """)
            logger.info("通过JavaScript选择了公司角色")
            
            # 等待短暂时间确保UI更新
            time.sleep(1)
            
            # 验证选择是否成功
            is_company_selected = self.page.evaluate("""
                document.querySelector("input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='2']").checked
            """)
            logger.info(f"公司角色选择状态: {is_company_selected}")
            
            # 2. 选择进口商角色：进口商/出口商 - ผู้นำของเข้า/ผู้ส่งของออก
            importer_selector = "input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='1']"
            logger.info(f"选择进口商角色: 进口商/出口商，使用选择器 {importer_selector}")
            
            # 直接使用JavaScript选择
            self.page.evaluate("""
                const importerRadio = document.querySelector("input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='1']");
                if (importerRadio) {
                    importerRadio.click();
                    importerRadio.checked = true;
                    importerRadio.dispatchEvent(new Event('change', { bubbles: true }));
                } else {
                    console.error("未找到进口商角色单选框");
                }
            """)
            logger.info("通过JavaScript选择了进口商角色")
            
            # 等待短暂时间确保UI更新
            time.sleep(1)
            
            # 验证选择是否成功
            is_importer_selected = self.page.evaluate("""
                document.querySelector("input.PrivateSwitchBase-input[name='color-radio-button-demo'][value='1']").checked
            """)
            logger.info(f"进口商角色选择状态: {is_importer_selected}")
            
            # 等待校验按钮出现
            self.page.wait_for_selector("button.MuiButton-contained", timeout=40000)
            logger.info("角色选择完成")
            
            # 填写纳税信息
            self._fill_tax_information()
        except Exception as e:
            logger.error(f"选择公司角色时出错: {e}")
            self._save_error_screenshot("role_selection_error")
            raise
    
    # 临时替换方法
    SessionManager._select_company_role = custom_select_company_role
    
    try:
        # 删除已保存的会话
        storage_path = os.path.join(log_path, 'storage_state.json')
        if os.path.exists(storage_path):
            os.remove(storage_path)
            logger.info(f"已删除旧的会话状态: {storage_path}")
        
        # 运行测试
        with SessionManager() as manager:
            logger.info("会话管理器初始化成功")
            logger.info("登录流程已完成")
    except Exception as e:
        logger.exception(f"测试过程中出现错误: {e}")
        return False
    finally:
        # 恢复原始方法
        SessionManager._select_company_role = original_method
    
    logger.info("测试完成")
    return True

if __name__ == "__main__":
    success = test_role_selection()
    sys.exit(0 if success else 1) 