from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SETTINGS: dict[str, Any] = {
    "login": {
        "login_url": "https://e-tracking.customs.go.th/ETS/",
        "tax_id": "",
        "branch_id": "",
        "printer_card_number": "",
        "printer_phone_number": "",
        "browser": {
            "headless": False,
            "timeout": 120000,
            "channel": "",
            "cdp_url": "",
        },
    },
    "file": {
        "output_dir": "runtime/receipts",
        "name_format": "{receipt_id}.pdf",
        "min_pdf_bytes": 1024,
    },
    "logging": {
        "level": "INFO",
        "log_file": "runtime/logs/etracking.log",
        "screenshot_dir": "runtime/logs/screenshots",
        "session_state_file": "runtime/session/state.json",
    },
    "retry": {
        "max_retries": 3,
        "delay": 0.5,
        "use_exponential_backoff": True,
    },
    "excel": {
        "path": "data/orders.xlsx",
        "sheet_name": None,
        "column": "F",
        "skip_header": True,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    return content if isinstance(content, dict) else {}


def _apply_env_overrides(settings: dict[str, Any]) -> dict[str, Any]:
    env_map = {
        "login.tax_id": os.getenv("ETRACKING_TAX_ID"),
        "login.branch_id": os.getenv("ETRACKING_BRANCH_ID"),
        "login.printer_card_number": os.getenv("ETRACKING_PRINTER_CARD_NUMBER"),
        "login.printer_phone_number": os.getenv("ETRACKING_PRINTER_PHONE_NUMBER"),
        "login.browser.cdp_url": os.getenv("ETRACKING_BROWSER_CDP_URL"),
        "excel.path": os.getenv("ETRACKING_EXCEL_PATH"),
        "file.output_dir": os.getenv("ETRACKING_OUTPUT_DIR"),
    }
    merged = deepcopy(settings)
    for dotted_key, value in env_map.items():
        if value in (None, ""):
            continue
        cursor = merged
        keys = dotted_key.split(".")
        for key in keys[:-1]:
            cursor = cursor.setdefault(key, {})
        cursor[keys[-1]] = value
    return merged


@dataclass(slots=True, frozen=True)
class AppSettings:
    project_root: Path
    raw: dict[str, Any]

    @property
    def login_url(self) -> str:
        return str(self.raw["login"]["login_url"])

    @property
    def tax_id(self) -> str:
        return str(self.raw["login"].get("tax_id", ""))

    @property
    def branch_id(self) -> str:
        return str(self.raw["login"].get("branch_id", ""))

    @property
    def printer_card_number(self) -> str:
        return str(self.raw["login"].get("printer_card_number", ""))

    @property
    def printer_phone_number(self) -> str:
        return str(self.raw["login"].get("printer_phone_number", ""))

    @property
    def browser_headless(self) -> bool:
        return bool(self.raw["login"]["browser"].get("headless", False))

    @property
    def browser_timeout_ms(self) -> int:
        return int(self.raw["login"]["browser"].get("timeout", 120000))

    @property
    def browser_channel(self) -> str | None:
        value = self.raw["login"]["browser"].get("channel")
        if value in (None, ""):
            return None
        return str(value)

    @property
    def browser_cdp_url(self) -> str | None:
        value = self.raw["login"]["browser"].get("cdp_url")
        if value in (None, ""):
            return None
        return str(value)

    @property
    def output_dir(self) -> Path:
        return Path(self.raw["file"].get("output_dir", "runtime/receipts"))

    @property
    def min_pdf_bytes(self) -> int:
        return int(self.raw["file"].get("min_pdf_bytes", 1024))

    @property
    def log_level(self) -> str:
        return str(self.raw["logging"].get("level", "INFO"))

    @property
    def excel_path(self) -> Path:
        return Path(self.raw["excel"].get("path", "data/orders.xlsx"))

    @property
    def excel_sheet_name(self) -> str | None:
        value = self.raw["excel"].get("sheet_name")
        return None if value in (None, "") else str(value)

    @property
    def excel_column(self) -> str:
        return str(self.raw["excel"].get("column", "F"))

    @property
    def max_retries(self) -> int:
        return int(self.raw["retry"].get("max_retries", 3))

    @property
    def retry_delay(self) -> float:
        return float(self.raw["retry"].get("delay", 0.5))


def load_settings(project_root: Path | None = None) -> AppSettings:
    root = project_root or PROJECT_ROOT
    config_dir = root / "config"
    merged = deepcopy(DEFAULT_SETTINGS)
    for filename in ("settings.example.yaml", "settings.local.yaml", "settings.yaml"):
        merged = _deep_merge(merged, _read_yaml(config_dir / filename))
    merged = _apply_env_overrides(merged)
    return AppSettings(project_root=root, raw=merged)


def with_settings_overrides(settings: AppSettings, overrides: dict[str, Any]) -> AppSettings:
    return AppSettings(
        project_root=settings.project_root,
        raw=_deep_merge(settings.raw, overrides),
    )
