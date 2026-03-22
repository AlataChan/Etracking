"""
CLI adapter — thin wrapper over ReceiptApplicationService.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from loguru import logger

from src.application.receipt_service import ReceiptApplicationService
from src.core.config import AppSettings, load_settings, with_settings_overrides
from src.core.models import BatchRunResult, ExecutionStatus
from src.core.paths import RuntimePaths
from src.support.logging import setup_logger


class _StopController:
    def __init__(self) -> None:
        self.stop_requested = False
        self._previous_handlers: dict[int, object] = {}

    def install(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self._handle_signal)

    def restore(self) -> None:
        for sig, handler in self._previous_handlers.items():
            signal.signal(sig, handler)
        self._previous_handlers.clear()

    def should_stop(self) -> bool:
        return self.stop_requested

    def _handle_signal(self, signum, frame) -> None:  # type: ignore[no-untyped-def]
        logger.warning(f"收到停止信号 {signum}，当前订单完成后停止批处理")
        self.stop_requested = True


def build_paths(
    settings: AppSettings,
    output_dir: str | None = None,
) -> RuntimePaths:
    return RuntimePaths.from_settings(settings, receipts_dir=output_dir).ensure()


def _log_batch_summary(report: BatchRunResult) -> None:
    elapsed = 0.0
    if report.started_at and report.finished_at:
        elapsed = (report.finished_at - report.started_at).total_seconds()
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)

    logger.info("\n===== 批量处理完成 =====")
    logger.info(f"总共处理: {report.total} 个订单")
    logger.info(f"成功处理: {report.succeeded} 个订单")
    logger.info(f"失败处理: {report.failed} 个订单")
    logger.info(f"需要人工复核: {report.needs_human_review} 个订单")
    logger.info(f"处理用时: {int(hours)}小时 {int(minutes)}分钟 {int(seconds)}秒")
    logger.info(f"报告目录: {report.report_dir}")


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
        "--resume-results",
        type=str,
        help="从已有 results.jsonl 恢复整批任务，成功且工件有效的订单将被跳过",
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

    service = ReceiptApplicationService(settings=settings, paths=paths)
    use_saved_state = not args.no_saved_state

    if args.no_saved_state:
        logger.info("已禁用使用保存的会话状态")

    if args.order_id:
        report = service.run_single(args.order_id, use_saved_state=use_saved_state)
        result = report.results[0] if report.results else None
        sys.exit(0 if result and result.status is ExecutionStatus.SUCCEEDED else 1)

    if args.batch or args.excel:
        stop_controller = _StopController()
        stop_controller.install()
        try:
            report = service.run_batch(
                excel_path=args.excel,
                sheet_name=args.sheet,
                resume_results_path=args.resume_results,
                use_saved_state=use_saved_state,
                should_stop=stop_controller.should_stop,
            )
        finally:
            stop_controller.restore()

        _log_batch_summary(report)
        exit_code = 0 if report.failed == 0 and report.needs_human_review == 0 else 1
        sys.exit(exit_code)

    if args.retry_failed_from:
        report = service.retry_failed(
            results_path=args.retry_failed_from,
            use_saved_state=use_saved_state,
        )
        _log_batch_summary(report)
        exit_code = 0 if report.failed == 0 and report.needs_human_review == 0 else 1
        sys.exit(exit_code)

    build_parser().print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
