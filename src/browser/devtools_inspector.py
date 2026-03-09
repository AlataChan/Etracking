from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from playwright.sync_api import Page, Request, Response


@dataclass(slots=True)
class ConsoleEntry:
    level: str
    message: str


@dataclass(slots=True)
class NetworkEntry:
    url: str
    method: str
    resource_type: str
    status: int | None = None


def _is_interesting_request(url: str, resource_type: str) -> bool:
    lowered = url.lower()
    return any(
        token in lowered
        for token in ("blob:", "pdf", "receipt", "search", "api", "print")
    ) or resource_type in {"xhr", "fetch", "document"}


class DevToolsInspector:
    def __init__(self, max_entries: int = 50) -> None:
        self.max_entries = max_entries
        self.console_entries: deque[ConsoleEntry] = deque(maxlen=max_entries)
        self.page_errors: deque[str] = deque(maxlen=max_entries)
        self.network_entries: deque[NetworkEntry] = deque(maxlen=max_entries)

    def record_console(self, level: str, message: str) -> None:
        self.console_entries.append(ConsoleEntry(level=level, message=message))

    def record_page_error(self, message: str) -> None:
        self.page_errors.append(message)

    def record_request(
        self,
        url: str,
        method: str,
        resource_type: str,
        status: int | None = None,
    ) -> None:
        if _is_interesting_request(url, resource_type):
            self.network_entries.append(
                NetworkEntry(
                    url=url,
                    method=method,
                    resource_type=resource_type,
                    status=status,
                )
            )

    def attach(self, page: Page) -> None:
        page.on("console", lambda message: self.record_console(message.type, message.text))
        page.on("pageerror", lambda error: self.record_page_error(str(error)))
        page.on("request", self._handle_request)
        page.on("response", self._handle_response)

    def _handle_request(self, request: Request) -> None:
        self.record_request(
            url=request.url,
            method=request.method,
            resource_type=request.resource_type,
        )

    def _handle_response(self, response: Response) -> None:
        request = response.request
        self.record_request(
            url=request.url,
            method=request.method,
            resource_type=request.resource_type,
            status=response.status,
        )

    def snapshot(
        self,
        current_url: str,
        screenshot_path: str | None = None,
    ) -> dict[str, Any]:
        return {
            "currentUrl": current_url,
            "screenshotPath": screenshot_path,
            "consoleErrors": [
                asdict(entry)
                for entry in self.console_entries
                if entry.level in {"error", "warning"}
            ],
            "pageErrors": list(self.page_errors),
            "networkRequests": [asdict(entry) for entry in self.network_entries],
        }
