"""
Excel读取模块，用于从Excel文件中读取订单号。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from src.core.config import AppSettings, load_settings


class ExcelReader:
    """
    Excel读取器，负责从Excel文件中读取订单号。
    """

    def __init__(
        self,
        excel_path: Optional[str | Path] = None,
        settings: Optional[AppSettings] = None,
    ) -> None:
        self.settings = settings or load_settings()
        configured_path = Path(excel_path) if excel_path is not None else self.settings.excel_path
        self.excel_path = (
            configured_path
            if configured_path.is_absolute()
            else self.settings.project_root / configured_path
        )
        self.column = self.settings.excel_column

        logger.info(f"Excel文件路径: {self.excel_path}")
        logger.info(f"订单号列: {self.column}")

    def read_orders(self, sheet_name: Optional[str] = None) -> list[str]:
        """
        读取指定sheet的订单号。
        """
        selected_sheet = sheet_name or self.settings.excel_sheet_name

        if not self.excel_path.exists():
            logger.error(f"Excel文件不存在: {self.excel_path}")
            return []

        try:
            logger.info(f"读取Excel文件: {self.excel_path}")
            orders: list[str] = []

            if selected_sheet:
                logger.info(f"读取工作表: {selected_sheet}")
                frame = pd.read_excel(self.excel_path, sheet_name=selected_sheet)
                sheet_orders = self._extract_orders_from_dataframe(frame)
                orders.extend(sheet_orders)
                logger.info(f"工作表 {selected_sheet} 中找到 {len(sheet_orders)} 个订单号")
            else:
                logger.info("读取所有工作表")
                excel_file = pd.ExcelFile(self.excel_path)
                for current_sheet in excel_file.sheet_names:
                    logger.info(f"读取工作表: {current_sheet}")
                    frame = pd.read_excel(excel_file, sheet_name=current_sheet)
                    sheet_orders = self._extract_orders_from_dataframe(frame)
                    orders.extend(sheet_orders)
                    logger.info(f"工作表 {current_sheet} 中找到 {len(sheet_orders)} 个订单号")

            unique_orders = list(dict.fromkeys(orders))
            logger.info(f"总共找到 {len(unique_orders)} 个唯一订单号")
            return unique_orders
        except Exception as error:
            logger.error(f"读取Excel文件时出错: {error}")
            return []

    def _extract_orders_from_dataframe(self, dataframe: pd.DataFrame) -> list[str]:
        """
        从DataFrame中提取订单号。
        """
        try:
            if self.column in dataframe.columns:
                column_data = dataframe[self.column]
            else:
                column_index = ord(self.column.upper()) - ord("A")
                if column_index >= len(dataframe.columns):
                    logger.warning(f"列索引 {self.column} 超出范围")
                    return []
                column_data = dataframe.iloc[:, column_index]

            orders = [str(order).strip() for order in column_data if pd.notna(order)]
            return [order for order in orders if order]
        except Exception as error:
            logger.error(f"从DataFrame提取订单号时出错: {error}")
            return []

    def get_order_ids(self, sheet_name: Optional[str] = None) -> list[str]:
        return self.read_orders(sheet_name)
