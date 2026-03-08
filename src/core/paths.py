from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.config import AppSettings, load_settings


def _resolve_path(project_root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else project_root / candidate


@dataclass(slots=True, frozen=True)
class RuntimePaths:
    project_root: Path
    runtime_dir: Path
    logs_dir: Path
    downloads_dir: Path
    receipts_dir: Path
    reports_dir: Path
    screenshots_dir: Path
    session_dir: Path
    session_state_file: Path
    inbox_dir: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> "RuntimePaths":
        runtime_dir = project_root / "runtime"
        return cls(
            project_root=project_root,
            runtime_dir=runtime_dir,
            logs_dir=runtime_dir / "logs",
            downloads_dir=runtime_dir / "downloads",
            receipts_dir=runtime_dir / "receipts",
            reports_dir=runtime_dir / "reports",
            screenshots_dir=runtime_dir / "logs" / "screenshots",
            session_dir=runtime_dir / "session",
            session_state_file=runtime_dir / "session" / "state.json",
            inbox_dir=runtime_dir / "inbox",
        )

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings | None = None,
        receipts_dir: str | Path | None = None,
    ) -> "RuntimePaths":
        resolved_settings = settings or load_settings()
        base = cls.from_project_root(resolved_settings.project_root)
        resolved_receipts_dir = _resolve_path(
            resolved_settings.project_root,
            receipts_dir or resolved_settings.output_dir,
        )
        return cls(
            project_root=base.project_root,
            runtime_dir=base.runtime_dir,
            logs_dir=base.logs_dir,
            downloads_dir=base.downloads_dir,
            receipts_dir=resolved_receipts_dir,
            reports_dir=base.reports_dir,
            screenshots_dir=base.screenshots_dir,
            session_dir=base.session_dir,
            session_state_file=base.session_state_file,
            inbox_dir=base.inbox_dir,
        )

    def ensure(self) -> "RuntimePaths":
        for path in (
            self.runtime_dir,
            self.logs_dir,
            self.downloads_dir,
            self.receipts_dir,
            self.reports_dir,
            self.screenshots_dir,
            self.session_dir,
            self.inbox_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def report_dir_for(self, run_id: str) -> Path:
        return self.reports_dir / run_id
