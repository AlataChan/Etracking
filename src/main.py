"""
主模块，程序入口。
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import signal
import sys
import time
from pathlib import Path

from loguru import logger

from src.core.config import AppSettings, load_settings, with_settings_overrides
from src.core.models import BatchRunResult, ExecutionStatus, ReceiptJob, ReceiptResult
from src.core.paths import RuntimePaths
from src.core.results import build_run_id, latest_results_by_order, load_results_jsonl, run_id_from_results_path
from src.integrations.run_ledger import RunLedger
from src.integrations.report_writer import ReportWriter
from src.session_manager import BatchSessionProcessor, SessionManager
from src.support.logging import setup_logger
from src.workflow.batch_runner import BatchRunner


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
    resume_results_path: str | Path | None = None,
    use_saved_state: bool = True,
    settings: AppSettings | None = None,
    paths: RuntimePaths | None = None,
) -> BatchRunResult:
    resolved_settings = settings or load_settings()
    resolved_paths = paths or build_paths(resolved_settings)
    start_time = time.time()
    started_at = datetime.now(UTC)
    logger.info("\n===== 开始批量处理订单 =====")

    runner = BatchRunner()
    resume_path = Path(resume_results_path) if resume_results_path else None
    run_id = run_id_from_results_path(resume_path) if resume_path else None
    job = ReceiptJob(
        order_ids=[],
        excel_path=Path(excel_path) if excel_path else resolved_settings.excel_path,
        sheet_name=sheet_name or resolved_settings.excel_sheet_name,
        use_saved_state=use_saved_state,
        output_dir=resolved_paths.receipts_dir,
        run_id=run_id,
        max_retries=resolved_settings.max_retries,
        min_artifact_bytes=resolved_settings.min_pdf_bytes,
        resume_results_path=resume_path,
    )
    job.order_ids = runner.load_order_ids(job)
    if not job.run_id:
        job.run_id = build_run_id(started_at)

    writer = ReportWriter(resolved_paths)
    previous_results = load_results_jsonl(resume_path) if resume_path else []
    effective_results = latest_results_by_order(previous_results)
    ledger = RunLedger(resolved_paths.report_paths_for(job.run_id))
    stop_controller = _StopController()
    stop_controller.install()
    processor = BatchSessionProcessor(
        use_saved_state=use_saved_state,
        settings=resolved_settings,
        paths=resolved_paths,
    )

    def snapshot_report(finished_at: datetime | None = None) -> BatchRunResult:
        ordered_results = [effective_results[order_id] for order_id in job.order_ids if order_id in effective_results]
        return BatchRunResult(
            job=job,
            run_id=job.run_id or "",
            results=ordered_results,
            started_at=started_at,
            finished_at=finished_at,
            planned_total=len(job.order_ids),
            stopped_early=stop_controller.should_stop(),
        )

    def on_result(result: ReceiptResult) -> None:
        effective_results[result.order_id] = result
        ledger.append_result(result)
        ledger.write_summary_snapshot(snapshot_report())

    ledger.write_summary_snapshot(snapshot_report())

    try:
        report = runner.run(
            job=job,
            process_order=processor.process_order_result,
            previous_results=previous_results,
            on_result=on_result,
            should_stop=stop_controller.should_stop,
        )
    finally:
        processor.close()
        stop_controller.restore()

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
            resume_results_path=args.resume_results,
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
