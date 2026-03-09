from __future__ import annotations

import json

from src.core.models import BatchRunResult, ReceiptResult
from src.core.paths import ReportPaths


class RunLedger:
    def __init__(self, paths: ReportPaths) -> None:
        self.paths = paths
        self.paths.report_dir.mkdir(parents=True, exist_ok=True)

    def append_result(self, result: ReceiptResult) -> None:
        with self.paths.results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.to_dict(), ensure_ascii=False))
            handle.write("\n")

    def write_summary_snapshot(self, report: BatchRunResult) -> None:
        self.paths.summary_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
