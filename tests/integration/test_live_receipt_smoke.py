from __future__ import annotations

import os

import pytest

from src.core.config import load_settings, with_settings_overrides
from src.core.models import ExecutionStatus
from src.core.paths import RuntimePaths
from src.session_manager import SessionManager


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("ETRACKING_RUN_LIVE") != "1",
        reason="set ETRACKING_RUN_LIVE=1 to run live browser smoke tests",
    ),
]


def test_live_receipt_search_page_is_ready() -> None:
    settings = load_settings()
    paths = RuntimePaths.from_settings(settings).ensure()

    with SessionManager(use_saved_state=True, settings=settings, paths=paths) as session:
        status = session.smoke_status()

    assert status["ready"] is True
    assert status["current_url"]
    assert status["order_inputs_ready"] is True
    assert status["printer_inputs_ready"] is True


@pytest.mark.skipif(
    not os.getenv("ETRACKING_LIVE_ORDER_ID"),
    reason="set ETRACKING_LIVE_ORDER_ID to run the live blob-popup receipt download test",
)
def test_live_receipt_download_via_blob_popup() -> None:
    settings = load_settings()
    cdp_url = os.getenv("ETRACKING_BROWSER_CDP_URL")
    if cdp_url:
        settings = with_settings_overrides(
            settings,
            {"login": {"browser": {"cdp_url": cdp_url}}},
        )
    paths = RuntimePaths.from_settings(settings).ensure()

    with SessionManager(use_saved_state=True, settings=settings, paths=paths) as session:
        result = session.process_order_result(os.environ["ETRACKING_LIVE_ORDER_ID"])

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.metadata["currentUrl"].startswith("blob:")
