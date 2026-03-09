from src.browser.devtools_inspector import DevToolsInspector


def test_devtools_snapshot_shape_is_stable() -> None:
    inspector = DevToolsInspector(max_entries=5)
    inspector.record_console("error", "Failed to render PDF")
    inspector.record_request(
        url="https://example.invalid/api/receipt/A017X680406286",
        method="GET",
        resource_type="xhr",
        status=500,
    )
    inspector.record_request(
        url="blob:https://example.invalid/123",
        method="GET",
        resource_type="document",
        status=200,
    )

    payload = inspector.snapshot(current_url="https://example.invalid/receipt", screenshot_path="runtime/logs/s1.png")

    assert payload["currentUrl"] == "https://example.invalid/receipt"
    assert payload["screenshotPath"] == "runtime/logs/s1.png"
    assert payload["consoleErrors"][0]["message"] == "Failed to render PDF"
    assert payload["networkRequests"][0]["url"].startswith("https://example.invalid/api/receipt")
    assert payload["networkRequests"][1]["url"].startswith("blob:")


def test_devtools_snapshot_filters_uninteresting_requests() -> None:
    inspector = DevToolsInspector(max_entries=5)
    inspector.record_request(
        url="https://example.invalid/static/app.js",
        method="GET",
        resource_type="script",
        status=200,
    )
    inspector.record_request(
        url="https://example.invalid/api/search",
        method="POST",
        resource_type="fetch",
        status=200,
    )

    payload = inspector.snapshot(current_url="https://example.invalid")

    assert len(payload["networkRequests"]) == 1
    assert payload["networkRequests"][0]["url"].endswith("/api/search")
