from __future__ import annotations

from pathlib import Path

from loguru import logger
from playwright.sync_api import Page


class PlaywrightAdapter:
    def __init__(self, page: Page, screenshot_dir: Path) -> None:
        self.page = page
        self.screenshot_dir = screenshot_dir

    def goto(self, url: str) -> None:
        logger.info(f"浏览器跳转开始: {url}")
        self.page.goto(url)
        logger.info(f"浏览器跳转完成: {self.page.url}")

    def wait_visible(self, selector: str, timeout_ms: int = 0) -> None:
        timeout = timeout_ms if timeout_ms > 0 else 30000
        self.page.wait_for_selector(selector, timeout=timeout, state="visible")

    def click(self, selector: str) -> None:
        self.page.click(selector)

    def fill(self, selector: str, value: str) -> None:
        self.page.fill(selector, value)

    def text_snapshot(self) -> str:
        return self.page.locator("body").inner_text()

    def screenshot(self, name: str) -> str:
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.screenshot_dir / f"{name}.png"
        self.page.screenshot(path=str(path))
        return str(path)
