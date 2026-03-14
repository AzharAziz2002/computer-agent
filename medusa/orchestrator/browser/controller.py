"""Persistent Playwright browser manager for Medusa agent sessions.

Uses async Playwright running in a dedicated background thread to avoid
conflicts with asyncio event loops from LLM SDKs. Public methods are
synchronous — they dispatch coroutines to the background loop and block
until complete.
"""

import asyncio
import logging
import threading
from pathlib import Path
from io import BytesIO
from PIL import Image

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
        self._playwright = None
        self._context = None
        self._current_page = None
        self._snapshot_parser = SnapshotParser()
        self._is_running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Background event loop
    # ------------------------------------------------------------------ #

    def _start_loop(self):
        """Run a new asyncio event loop in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_loop(self):
        """Start background thread + event loop if not running."""
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._start_loop, daemon=True)
            self._thread.start()
            while self._loop is None or not self._loop.is_running():
                pass

    def _run(self, coro):
        """Dispatch async coroutine to background loop, block for result."""
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=60)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def start(self, channel: str | None = None, user_data_dir: str | None = None,
              headless: bool | None = None) -> str:
        if self._is_running:
            return 'Browser is already running.'
        return self._run(self._start_async(channel, user_data_dir, headless))

    async def _start_async(self, channel, user_data_dir, headless):
        from playwright.async_api import async_playwright

        ch = channel or self.config.channel
        udd = user_data_dir or self.config.user_data_dir or default_user_data_dir()
        hl = headless if headless is not None else self.config.headless

        Path(udd).mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
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
            self._current_page = await self._context.new_page()

        self._context.on('page', self._on_page_created)
        self._is_running = True
        return f'Browser started ({ch}).'

    def stop(self) -> str:
        if not self._is_running:
            return 'Browser is not running.'
        try:
            self._run(self._stop_async())
        except Exception as e:
            logger.warning(f'Error stopping browser: {e}')
        finally:
            self._context = None
            self._playwright = None
            self._current_page = None
            self._is_running = False
            self._snapshot_parser = SnapshotParser()
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
            self._loop = None
            self._thread = None
        return 'Browser stopped.'

    async def _stop_async(self):
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()

    def _ensure_running(self):
        if not self._is_running or not self._context:
            self.start()

    def _ensure_page(self):
        self._ensure_running()
        if self._current_page is None or self._current_page.is_closed():
            pages = self._context.pages
            if pages:
                self._current_page = pages[-1]
            else:
                self._current_page = self._run(self._context.new_page())
        return self._current_page

    def _on_page_created(self, page):
        self._current_page = page

    def _invalidate_refs(self):
        self._snapshot_parser = SnapshotParser()

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self) -> str:
        if not self._is_running:
            return 'Browser is not running.'
        self._ensure_page()
        return self._run(self._status_async())

    async def _status_async(self):
        page = self._current_page
        title = await page.title()
        return f'Browser running. Current page: {title} ({page.url})'

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    def navigate(self, url: str) -> str:
        self._ensure_page()
        return self._run(self._navigate_async(url))

    async def _navigate_async(self, url):
        page = self._current_page
        if not url.startswith(('http://', 'https://', 'file://')):
            url = 'https://' + url
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        self._invalidate_refs()
        title = await page.title()
        return f'Navigated to {page.url} — "{title}"'

    def go_back(self) -> str:
        self._ensure_page()
        return self._run(self._go_back_async())

    async def _go_back_async(self):
        page = self._current_page
        await page.go_back(timeout=10000)
        self._invalidate_refs()
        return f'Went back to {page.url}'

    # ------------------------------------------------------------------ #
    # Observation
    # ------------------------------------------------------------------ #

    def snapshot(self) -> str:
        self._ensure_page()
        return self._run(self._snapshot_async())

    async def _snapshot_async(self):
        page = self._current_page
        raw_yaml = await page.locator('body').aria_snapshot()
        formatted, _ = self._snapshot_parser.parse(raw_yaml)

        if len(formatted) > MAX_SNAPSHOT_CHARS:
            formatted = formatted[:MAX_SNAPSHOT_CHARS] + '\n... (snapshot truncated)'

        title = await page.title()
        page_info = f'Page: {title} ({page.url})'
        tabs_info = await self._tabs_summary_async()
        return f'{page_info}\n{tabs_info}\n\n{formatted}'

    def screenshot(self, full_page: bool = False) -> Image.Image:
        self._ensure_page()
        return self._run(self._screenshot_async(full_page))

    async def _screenshot_async(self, full_page):
        page = self._current_page
        screenshot_bytes = await page.screenshot(type='png', full_page=full_page)
        image = Image.open(BytesIO(screenshot_bytes))
        if image.width > self.RENDER_W or image.height > self.RENDER_H:
            image = image.resize((self.RENDER_W, self.RENDER_H), Image.LANCZOS)
        return image

    # ------------------------------------------------------------------ #
    # Element interactions
    # ------------------------------------------------------------------ #

    def click(self, ref: str, button: str = 'left', double_click: bool = False) -> str:
        self._ensure_page()
        return self._run(self._click_async(ref, button, double_click))

    async def _click_async(self, ref, button, double_click):
        page = self._current_page
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        if double_click:
            await locator.dblclick(button=button, timeout=5000)
        else:
            await locator.click(button=button, timeout=5000)
        action = 'Double-clicked' if double_click else 'Clicked'
        return f'{action} [{ref}] {elem.role} "{elem.name}"'

    def type_text(self, ref: str, text: str, submit: bool = False,
                  slowly: bool = False) -> str:
        self._ensure_page()
        return self._run(self._type_text_async(ref, text, submit, slowly))

    async def _type_text_async(self, ref, text, submit, slowly):
        page = self._current_page
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        if slowly:
            await locator.press_sequentially(text, timeout=10000)
        else:
            await locator.fill(text, timeout=5000)
        if submit:
            await locator.press('Enter', timeout=5000)
        suffix = ' and submitted' if submit else ''
        return f'Typed "{text}" into [{ref}] {elem.role} "{elem.name}"{suffix}'

    def hover(self, ref: str) -> str:
        self._ensure_page()
        return self._run(self._hover_async(ref))

    async def _hover_async(self, ref):
        page = self._current_page
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        await locator.hover(timeout=5000)
        return f'Hovered over [{ref}] {elem.role} "{elem.name}"'

    def select_option(self, ref: str, values: list[str]) -> str:
        self._ensure_page()
        return self._run(self._select_option_async(ref, values))

    async def _select_option_async(self, ref, values):
        page = self._current_page
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        await locator.select_option(values, timeout=5000)
        return f'Selected {values} in [{ref}] {elem.role} "{elem.name}"'

    def press_key(self, key: str) -> str:
        self._ensure_page()
        return self._run(self._press_key_async(key))

    async def _press_key_async(self, key):
        page = self._current_page
        await page.keyboard.press(key)
        return f'Pressed key: {key}'

    def scroll_to(self, ref: str) -> str:
        self._ensure_page()
        return self._run(self._scroll_to_async(ref))

    async def _scroll_to_async(self, ref):
        page = self._current_page
        locator = self._snapshot_parser.resolve_ref(page, ref)
        elem = self._snapshot_parser._ref_map[ref]
        await locator.scroll_into_view_if_needed(timeout=5000)
        return f'Scrolled [{ref}] {elem.role} "{elem.name}" into view'

    # ------------------------------------------------------------------ #
    # JavaScript
    # ------------------------------------------------------------------ #

    def evaluate(self, js: str) -> str:
        self._ensure_page()
        return self._run(self._evaluate_async(js))

    async def _evaluate_async(self, js):
        page = self._current_page
        result = await page.evaluate(js)
        return f'Result: {result}'

    # ------------------------------------------------------------------ #
    # Tab management
    # ------------------------------------------------------------------ #

    def tabs(self) -> str:
        self._ensure_running()
        return self._run(self._tabs_summary_async())

    async def _tabs_summary_async(self) -> str:
        lines = ['Tabs:']
        for i, page in enumerate(self._context.pages):
            title = await page.title()
            marker = ' (current)' if page == self._current_page else ''
            lines.append(f'  [{i}] {title} — {page.url}{marker}')
        return '\n'.join(lines)

    def open_tab(self, url: str | None = None) -> str:
        self._ensure_running()
        return self._run(self._open_tab_async(url))

    async def _open_tab_async(self, url):
        page = await self._context.new_page()
        self._current_page = page
        if url:
            if not url.startswith(('http://', 'https://', 'file://')):
                url = 'https://' + url
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        self._invalidate_refs()
        tabs = await self._tabs_summary_async()
        return f'Opened new tab. {tabs}'

    def focus_tab(self, index: int) -> str:
        self._ensure_running()
        return self._run(self._focus_tab_async(index))

    async def _focus_tab_async(self, index):
        pages = self._context.pages
        if index < 0 or index >= len(pages):
            raise ValueError(f'Tab index {index} out of range (0-{len(pages) - 1})')
        self._current_page = pages[index]
        await self._current_page.bring_to_front()
        self._invalidate_refs()
        title = await self._current_page.title()
        return f'Focused tab [{index}]: {title}'

    def close_tab(self, index: int | None = None) -> str:
        self._ensure_running()
        return self._run(self._close_tab_async(index))

    async def _close_tab_async(self, index):
        pages = self._context.pages
        if index is not None:
            if index < 0 or index >= len(pages):
                raise ValueError(f'Tab index {index} out of range (0-{len(pages) - 1})')
            target = pages[index]
        else:
            target = self._current_page

        url = target.url
        await target.close()

        remaining = self._context.pages
        self._current_page = remaining[-1] if remaining else None
        self._invalidate_refs()
        if remaining:
            tabs = await self._tabs_summary_async()
            return f'Closed tab ({url}). {tabs}'
        return f'Closed tab ({url}). No tabs open.'

    # ------------------------------------------------------------------ #
    # Wait / PDF
    # ------------------------------------------------------------------ #

    def wait(self, time_ms: int = 1000) -> str:
        self._ensure_page()
        return self._run(self._wait_async(time_ms))

    async def _wait_async(self, time_ms):
        page = self._current_page
        await page.wait_for_timeout(time_ms)
        return f'Waited {time_ms}ms'

    def pdf(self) -> str:
        self._ensure_page()
        return self._run(self._pdf_async())

    async def _pdf_async(self):
        page = self._current_page
        title = await page.title() or 'page'
        safe_title = ''.join(c for c in title[:30] if c.isalnum() or c in ' _-')
        output_path = Path.home() / '.medusa' / 'downloads' / f'{safe_title}.pdf'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = await page.pdf()
        output_path.write_bytes(pdf_bytes)
        return f'PDF saved to {output_path}'
