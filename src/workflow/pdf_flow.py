from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.core.models import ReceiptResult
from src.support.validation import PdfValidationPolicy, validate_pdf_artifact


@dataclass(slots=True)
class PdfFlow:
    policy: PdfValidationPolicy = field(default_factory=PdfValidationPolicy)

    def finalize(
        self,
        order_id: str,
        pdf_path: str | Path,
        fallback_path: str | Path | None = None,
        source: str = "browser-download",
    ) -> ReceiptResult:
        return validate_pdf_artifact(
            order_id=order_id,
            pdf_path=Path(pdf_path),
            fallback_path=Path(fallback_path) if fallback_path else None,
            source=source,
            policy=self.policy,
        )
