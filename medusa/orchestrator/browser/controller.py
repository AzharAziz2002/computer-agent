"""Persistent Playwright browser manager for Medusa agent sessions."""

import logging
from pathlib import Path
from io import BytesIO
from PIL import Image
from playwright.sync_api import sync_playwright, Playwright, BrowserContext, Page

from medusa.orchestrator.browser.config import BrowserConfig, default_user_data_dir
from medusa.orchestrator.browser.snapshot import SnapshotParser

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_CHARS = 8000


class BrowserController:
    """Manages a persistent Playwright browser instance across tool calls."""

    RENDER_W = 1280
    RENDER_H = 720

    def __init__(self, config: BrowserConfig | None = None):
        self.config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._current_page: Page | None = None
        self._snapshot_parser = SnapshotParser()
        self._is_running = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def start(self, channel: str | None = None, user_data_dir: str | None = None,
              headless: bool | None = None) -> str:
        """Launch browser with persistent context."""
        if self._is_running:
            return 'Browser is already running.'

        ch = channel or self.config.channel
        udd = user_data_dir or self.config.user_data_dir or default_user_data_dir()
        hl = headless if headless is not None else self.config.headless

        Path(udd).mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=udd,
            channel=ch,
            headless=hl,
            viewport={'width': self.config.viewport_width, 'height': self.config.viewport_height},
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-sync',
                *self.config.extra_args,
            ],
            ignore_default_args=['--enable-automation'],
        )

        if self._context.pages:
            self._current_page = self._context.pages[-1]
        else:
            self._current_page = self._context.new_page()

        self._context.on('page', self._on_page_created)
        self._is_running = True
        return f'Browser started ({ch}).'

    def stop(self) -> str:
        """Close browser and cleanup. Idempotent."""
        if not self._is_running:
            return 'Browser is not running.'
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning(f'Error stopping browser: {e}')
        finally:
            self._context = None
            self._playwright = None
            self._current_page = None
            self._is_running = False
            self._snapshot_parser = SnapshotParser()
        return 'Browser stopped.'

    def _ensure_running(self):
        """Auto-start browser if not running."""
        if not self._is_running or not self._context:
            self.start()

    def _ensure_page(self) -> Page:
        """Ensure we have a valid current page."""
        self._ensure_running()
        if self._current_page is None or self._current_page.is_closed():
            pages = self._context.pages
            if pages:
                self._current_page = pages[-1]
            else:
                self._current_page = self._context.new_page()
        return self._current_page

    def _on_page_created(self, page: Page):
        """Track new tabs/popups."""
        self._current_page = page

    def _invalidate_refs(self):
        """Reset snapshot parser — refs become stale after navigation or tab switch."""
        self._snapshot_parser = SnapshotParser()

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self) -> str:
        if not self._is_running:
            return 'Browser is not running.'
        page = self._ensure_page()
        return f'Browser running. Current page: {page.title} ({page.url})'

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    def navigate(self, url: str) -> str:
        page = self._ensure_page()
        if not url.startswith(('http://', 'https://', 'file://')):
            url = 'https://' + url
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        self._invalidate_refs()
        return f'Navigated to {page.url} — "{page.title}"'

    def go_back(self) -> str:
        page = self._ensure_page()
        page.go_back(timeout=10000)
        self._invalidate_refs()
        return f'Went back to {page.url}'

    # ------------------------------------------------------------------ #
    # Observation
    # ------------------------------------------------------------------ #

    def snapshot(self) -> str:
        page = self._ensure_page()
        raw_yaml = page.locator('body').aria_snapshot()
        formatted, _ = self._snapshot_parser.parse(raw_yaml)

        if len(formatted) > MAX_SNAPSHOT_CHARS:
            formatted = formatted[:MAX_SNAPSHOT_CHARS] + '\n... (snapshot truncated)'

        page_info = f'Page: {page.title} ({page.url})'
        tabs_info = self._tabs_summary()
        return f'{page_info}\n{tabs_info}\n\n{formatted}'

    def screenshot(self, full_page: bool = False) -> Image.Image:
        page = self._ensure_page()
        screenshot_bytes = page.screenshot(type='png', full_page=full_page)
        image = Image.open(BytesIO(screenshot_bytes))
        if image.width > self.RENDER_W or image.height > self.RENDER_H:
            image = image.resize((self.RENDER_W, self.RENDER_H), Image.LANCZOS)
        return image

    # ------------------------------------------------------------------ #
    # Element interactions
    # ------------------------------------------------------------------ #

    def click(self, ref: str, button: str = 'left', double_click: bool = False) -> str:
        page = self._ensure_page()
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        if double_click:
            locator.dblclick(button=button, timeout=5000)
        else:
            locator.click(button=button, timeout=5000)
        action = 'Double-clicked' if double_click else 'Clicked'
        return f'{action} [{ref}] {elem.role} "{elem.name}"'

    def type_text(self, ref: str, text: str, submit: bool = False,
                  slowly: bool = False) -> str:
        page = self._ensure_page()
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        if slowly:
            locator.press_sequentially(text, timeout=10000)
        else:
            locator.fill(text, timeout=5000)
        if submit:
            locator.press('Enter', timeout=5000)
        suffix = ' and submitted' if submit else ''
        return f'Typed "{text}" into [{ref}] {elem.role} "{elem.name}"{suffix}'

    def hover(self, ref: str) -> str:
        page = self._ensure_page()
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        locator.hover(timeout=5000)
        return f'Hovered over [{ref}] {elem.role} "{elem.name}"'

    def select_option(self, ref: str, values: list[str]) -> str:
        page = self._ensure_page()
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        locator.select_option(values, timeout=5000)
        return f'Selected {values} in [{ref}] {elem.role} "{elem.name}"'

    def press_key(self, key: str) -> str:
        page = self._ensure_page()
        page.keyboard.press(key)
        return f'Pressed key: {key}'

    def scroll_to(self, ref: str) -> str:
        page = self._ensure_page()
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        locator.scroll_into_view_if_needed(timeout=5000)
        return f'Scrolled [{ref}] {elem.role} "{elem.name}" into view'

    # ------------------------------------------------------------------ #
    # JavaScript
    # ------------------------------------------------------------------ #

    def evaluate(self, js: str) -> str:
        page = self._ensure_page()
        result = page.evaluate(js)
        return f'Result: {result}'

    # ------------------------------------------------------------------ #
    # Tab management
    # ------------------------------------------------------------------ #

    def tabs(self) -> str:
        self._ensure_running()
        return self._tabs_summary()

    def _tabs_summary(self) -> str:
        lines = ['Tabs:']
        for i, page in enumerate(self._context.pages):
            marker = ' (current)' if page == self._current_page else ''
            lines.append(f'  [{i}] {page.title} — {page.url}{marker}')
        return '\n'.join(lines)

    def open_tab(self, url: str | None = None) -> str:
        self._ensure_running()
        page = self._context.new_page()
        self._current_page = page
        if url:
            if not url.startswith(('http://', 'https://', 'file://')):
                url = 'https://' + url
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
        self._invalidate_refs()
        return f'Opened new tab. {self._tabs_summary()}'

    def focus_tab(self, index: int) -> str:
        self._ensure_running()
        pages = self._context.pages
        if index < 0 or index >= len(pages):
            raise ValueError(f'Tab index {index} out of range (0-{len(pages) - 1})')
        self._current_page = pages[index]
        self._current_page.bring_to_front()
        self._invalidate_refs()
        return f'Focused tab [{index}]: {self._current_page.title}'

    def close_tab(self, index: int | None = None) -> str:
        self._ensure_running()
        pages = self._context.pages
        if index is not None:
            if index < 0 or index >= len(pages):
                raise ValueError(f'Tab index {index} out of range (0-{len(pages) - 1})')
            target = pages[index]
        else:
            target = self._current_page

        url = target.url
        target.close()

        remaining = self._context.pages
        self._current_page = remaining[-1] if remaining else None
        self._invalidate_refs()
        return f'Closed tab ({url}). {self._tabs_summary() if remaining else "No tabs open."}'

    # ------------------------------------------------------------------ #
    # Wait / PDF
    # ------------------------------------------------------------------ #

    def wait(self, time_ms: int = 1000) -> str:
        page = self._ensure_page()
        page.wait_for_timeout(time_ms)
        return f'Waited {time_ms}ms'

    def pdf(self) -> str:
        page = self._ensure_page()
        title = page.title or 'page'
        safe_title = ''.join(c for c in title[:30] if c.isalnum() or c in ' _-')
        output_path = Path.home() / '.medusa' / 'downloads' / f'{safe_title}.pdf'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = page.pdf()
        output_path.write_bytes(pdf_bytes)
        return f'PDF saved to {output_path}'
