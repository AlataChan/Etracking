from pathlib import Path

from src.core.config import load_settings
from src.core.paths import RuntimePaths


def test_runtime_paths_are_scoped_under_runtime(tmp_path: Path) -> None:
    paths = RuntimePaths.from_project_root(tmp_path)
    paths.ensure()
    report_paths = paths.report_paths_for("job_20260309_120000")
    report_paths.report_dir.mkdir(parents=True, exist_ok=True)

    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.logs_dir == tmp_path / "runtime" / "logs"
    assert paths.receipts_dir == tmp_path / "runtime" / "receipts"
    assert paths.reports_dir == tmp_path / "runtime" / "reports"
    assert paths.session_state_file == tmp_path / "runtime" / "session" / "state.json"
    assert paths.screenshots_dir.is_dir()
    assert report_paths.report_dir == tmp_path / "runtime" / "reports" / "job_20260309_120000"
    assert report_paths.summary_path == report_paths.report_dir / "summary.json"
    assert report_paths.results_path == report_paths.report_dir / "results.jsonl"
    assert report_paths.csv_path == report_paths.report_dir / "results.csv"


def test_load_settings_merges_example_local_and_env(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.example.yaml").write_text(
        """
login:
  login_url: https://example.invalid
  tax_id: EXAMPLE
file:
  output_dir: runtime/receipts
excel:
  path: data/orders.xlsx
""".strip(),
        encoding="utf-8",
    )
    (config_dir / "settings.local.yaml").write_text(
        """
login:
  tax_id: LOCAL
  branch_id: "1"
file:
  output_dir: runtime/custom-receipts
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("ETRACKING_BRANCH_ID", "99")
    monkeypatch.setenv("ETRACKING_BROWSER_CDP_URL", "http://127.0.0.1:9222")

    settings = load_settings(project_root=tmp_path)

    assert settings.login_url == "https://example.invalid"
    assert settings.tax_id == "LOCAL"
    assert settings.branch_id == "99"
    assert settings.browser_cdp_url == "http://127.0.0.1:9222"
    assert settings.output_dir == Path("runtime/custom-receipts")
    assert settings.excel_path == Path("data/orders.xlsx")
