from __future__ import annotations

import csv
import json

from src.core.models import BatchRunResult
from src.core.paths import RuntimePaths


class ReportWriter:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def write(self, report: BatchRunResult) -> BatchRunResult:
        report_dir = self.paths.report_dir_for(report.run_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        summary_path = report_dir / "summary.json"
        results_path = report_dir / "results.jsonl"
        csv_path = report_dir / "results.csv"

        summary_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with results_path.open("w", encoding="utf-8") as handle:
            for result in report.results:
                handle.write(json.dumps(result.to_dict(), ensure_ascii=False))
                handle.write("\n")
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["orderId", "status", "reason", "attempts", "artifactPath", "screenshotPath"],
            )
            writer.writeheader()
            for result in report.results:
                writer.writerow(
                    {
                        "orderId": result.order_id,
                        "status": result.status.value,
                        "reason": result.reason,
                        "attempts": result.attempts,
                        "artifactPath": str(result.artifact.path) if result.artifact else "",
                        "screenshotPath": str(result.screenshot_path) if result.screenshot_path else "",
                    }
                )

        report.report_dir = report_dir
        report.summary_path = summary_path
        report.results_path = results_path
        report.csv_path = csv_path
        return report
