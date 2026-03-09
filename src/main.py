"""
主模块，程序入口。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from loguru import logger

from src.core.config import AppSettings, load_settings, with_settings_overrides
from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
from src.core.paths import RuntimePaths
from src.core.results import load_results_jsonl
from src.integrations.report_writer import ReportWriter
from src.session_manager import SessionManager
from src.support.logging import setup_logger
from src.workflow.batch_runner import BatchRunner


def build_paths(
    settings: AppSettings,
    output_dir: str | Path | None = None,
) -> RuntimePaths:
    return RuntimePaths.from_settings(settings, receipts_dir=output_dir).ensure()


def process_single_order(
    order_id: str,
    use_saved_state: bool = True,
    settings: AppSettings | None = None,
    paths: RuntimePaths | None = None,
) -> ReceiptResult:
    resolved_settings = settings or load_settings()
    resolved_paths = paths or build_paths(resolved_settings)

    logger.info(f"\n===== 处理订单: {order_id} =====")

    for retry in range(3):
        try:
            current_use_saved_state = use_saved_state and retry == 0
            with SessionManager(
                use_saved_state=current_use_saved_state,
                settings=resolved_settings,
                paths=resolved_paths,
            ) as session:
                return session.process_order_result(order_id)
        except Exception as retry_error:
            if retry < 2:
                logger.warning(f"第{retry + 1}次尝试失败，准备重试: {retry_error}")
                time.sleep(1)
                continue
            logger.exception(f"处理订单 {order_id} 时出错: {retry_error}")

    return ReceiptResult(
        order_id=order_id,
        status=ExecutionStatus.FAILED,
        reason="all retries exhausted before a valid PDF was captured",
    )


def process_batch_orders(
    excel_path: str | Path | None = None,
    sheet_name: str | None = None,
    use_saved_state: bool = True,
    settings: AppSettings | None = None,
    paths: RuntimePaths | None = None,
) -> BatchRunResult:
    resolved_settings = settings or load_settings()
    resolved_paths = paths or build_paths(resolved_settings)
    start_time = time.time()
    logger.info("\n===== 开始批量处理订单 =====")

    job = ReceiptJob(
        order_ids=[],
        excel_path=Path(excel_path) if excel_path else resolved_settings.excel_path,
        sheet_name=sheet_name or resolved_settings.excel_sheet_name,
        use_saved_state=use_saved_state,
        output_dir=resolved_paths.receipts_dir,
        max_retries=resolved_settings.max_retries,
    )

    runner = BatchRunner()
    writer = ReportWriter(resolved_paths)

    with SessionManager(
        use_saved_state=use_saved_state,
        settings=resolved_settings,
        paths=resolved_paths,
    ) as session:
        report = runner.run(job=job, process_order=session.process_order_result)

    report = writer.write(report)
    elapsed = time.time() - start_time
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)

    logger.info("\n===== 批量处理完成 =====")
    logger.info(f"总共处理: {report.total} 个订单")
    logger.info(f"成功处理: {report.succeeded} 个订单")
    logger.info(f"失败处理: {report.failed} 个订单")
    logger.info(f"需要人工复核: {report.needs_human_review} 个订单")
    logger.info(f"处理用时: {int(hours)}小时 {int(minutes)}分钟 {int(seconds)}秒")
    logger.info(f"报告目录: {report.report_dir}")

    return report


def retry_failed_orders(
    results_path: str | Path,
    use_saved_state: bool = True,
    settings: AppSettings | None = None,
    paths: RuntimePaths | None = None,
) -> BatchRunResult:
    resolved_settings = settings or load_settings()
    resolved_paths = paths or build_paths(resolved_settings)
    previous_results = load_results_jsonl(results_path)
    runner = BatchRunner()
    retry_job = runner.retry_failed_job(
        previous_results,
        base_job=ReceiptJob(
            order_ids=[],
            use_saved_state=use_saved_state,
            output_dir=resolved_paths.receipts_dir,
            max_retries=resolved_settings.max_retries,
        ),
    )
    writer = ReportWriter(resolved_paths)

    with SessionManager(
        use_saved_state=use_saved_state,
        settings=resolved_settings,
        paths=resolved_paths,
    ) as session:
        report = runner.run(job=retry_job, process_order=session.process_order_result)

    return writer.write(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="下载泰国海关发票PDF")
    parser.add_argument("--order-id", type=str, help="单个订单号")
    parser.add_argument("--batch", action="store_true", help="批量处理Excel中的订单")
    parser.add_argument("--excel", type=str, help="包含订单号的Excel文件路径")
    parser.add_argument("--sheet", type=str, help="Excel中的工作表名称")
    parser.add_argument("--no-saved-state", action="store_true", help="不使用已保存的会话状态")
    parser.add_argument(
        "--retry-failed-from",
        type=str,
        help="从之前的 results.jsonl 只重跑失败订单",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="运行期输出目录，默认使用配置中的 runtime/receipts",
    )
    parser.add_argument(
        "--cdp-url",
        type=str,
        help="连接已启动 Chrome 的 CDP 地址，例如 http://127.0.0.1:9222",
    )
    return parser


def parse_args() -> argparse.Namespace:
    return build_parser().parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    if args.cdp_url:
        settings = with_settings_overrides(
            settings,
            {"login": {"browser": {"cdp_url": args.cdp_url}}},
        )
    paths = build_paths(settings, args.output_dir)
    setup_logger(paths, settings.log_level)

    logger.info("=== 泰国海关E-tracking系统PDF下载工具 ===")

    use_saved_state = not args.no_saved_state
    if args.no_saved_state:
        logger.info("已禁用使用保存的会话状态")

    if args.order_id:
        result = process_single_order(
            args.order_id,
            use_saved_state=use_saved_state,
            settings=settings,
            paths=paths,
        )
        sys.exit(0 if result.status is ExecutionStatus.SUCCEEDED else 1)

    if args.batch or args.excel:
        report = process_batch_orders(
            excel_path=args.excel,
            sheet_name=args.sheet,
            use_saved_state=use_saved_state,
            settings=settings,
            paths=paths,
        )
        exit_code = 0 if report.failed == 0 and report.needs_human_review == 0 else 1
        sys.exit(exit_code)

    if args.retry_failed_from:
        report = retry_failed_orders(
            results_path=args.retry_failed_from,
            use_saved_state=use_saved_state,
            settings=settings,
            paths=paths,
        )
        exit_code = 0 if report.failed == 0 and report.needs_human_review == 0 else 1
        sys.exit(exit_code)

    build_parser().print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
