from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.core.models import ExecutionStatus
from src.core.models import ReceiptResult
from src.support.validation import PdfValidationPolicy, validate_pdf_artifact


PdfProducer = Callable[[], bytes | None]


@dataclass(slots=True)
class PdfFlow:
    policy: PdfValidationPolicy = field(default_factory=PdfValidationPolicy)

    def __init__(self, min_bytes: int = 1024) -> None:
        self.policy = PdfValidationPolicy(min_bytes=min_bytes)

    def acquire(
        self,
        order_id: str,
        pdf_path: str | Path,
        direct_fetch: PdfProducer,
        browser_download: PdfProducer,
        export_pdf: PdfProducer,
        screenshot_path: str | Path | None = None,
        source: str = "browser-download",
    ) -> ReceiptResult:
        target_path = Path(pdf_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        for producer in (direct_fetch, browser_download, export_pdf):
            pdf_bytes = self._coerce_pdf_bytes(producer())
            if pdf_bytes:
                target_path.write_bytes(pdf_bytes)
                result = validate_pdf_artifact(
                    order_id=order_id,
                    pdf_path=target_path,
                    fallback_path=Path(screenshot_path) if screenshot_path else None,
                    source=source,
                    policy=self.policy,
                )
                if result.status is ExecutionStatus.SUCCEEDED:
                    return result

        return validate_pdf_artifact(
            order_id=order_id,
            pdf_path=target_path,
            fallback_path=Path(screenshot_path) if screenshot_path else None,
            source=source,
            policy=self.policy,
        )

    def _coerce_pdf_bytes(self, payload: object) -> bytes | None:
        if payload is None:
            return None
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, bytearray):
            return bytes(payload)
        if isinstance(payload, list) and all(isinstance(item, int) for item in payload):
            return bytes(payload)
        return None

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
