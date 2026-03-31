"""Persistent Playwright browser manager for Medusa agent sessions.

All public methods are async — called from the async agent loop via
the async browser tool function. Playwright async API runs directly
in the same event loop.
"""

import asyncio
import re
import uuid
import logging
from pathlib import Path
from io import BytesIO
from PIL import Image

from medusa.orchestrator.browser.config import BrowserConfig, default_user_data_dir
from medusa.orchestrator.browser.snapshot import SnapshotParser, AiSnapshotParser
from medusa.orchestrator.browser.constants import (
    DEFAULT_AI_SNAPSHOT_MAX_CHARS,
    DEFAULT_AI_SNAPSHOT_EFFICIENT_MAX_CHARS,
    DEFAULT_AI_SNAPSHOT_EFFICIENT_DEPTH,
)

logger = logging.getLogger(__name__)

# Normalise modifier key names the LLM might pass → Playwright expected strings
_MODIFIER_MAP = {
    'ctrl': 'Control', 'control': 'Control',
    'shift': 'Shift',
    'alt': 'Alt',
    'meta': 'Meta', 'win': 'Meta', 'cmd': 'Meta',
}


class BrowserController:
    """Manages a persistent Playwright browser instance across tool calls."""

    RENDER_W = 1280
    RENDER_H = 720

    def __init__(self, config: BrowserConfig | None = None):
        self.config = config or BrowserConfig()
        self._playwright = None
        self._browser = None             # only used in relay mode (connect_over_cdp)
        self._context = None
        self._current_page = None
        self._snapshot_parser = SnapshotParser()
        self._ai_snapshot_parser = AiSnapshotParser()
        self._refs_mode: str = 'role'      # 'role' or 'aria' (ai snapshot)
        self._ai_available: bool | None = None  # cache _snapshot_for_ai probe result
        self._is_running = False
        self._is_relay_mode = False        # True when connected via extension relay
        self._relay = None                 # ExtensionRelay instance
        self._console_messages: list[dict] = []
        # Stable tab IDs: t0, t1, t2... — never shift when tabs open/close
        self._page_ids: dict[str, object] = {}       # tab_id → Page
        self._page_id_reverse: dict[int, str] = {}   # id(Page) → tab_id
        self._next_tab_id: int = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def _assign_tab_id(self, page) -> str:
        """Assign a stable ID (t0, t1, ...) to a page and register cleanup."""
        tab_id = f't{self._next_tab_id}'
        self._next_tab_id += 1
        self._page_ids[tab_id] = page
        self._page_id_reverse[id(page)] = tab_id

        def _on_close(_page=page, _tab_id=tab_id):
            self._page_ids.pop(_tab_id, None)
            self._page_id_reverse.pop(id(_page), None)

        page.on('close', lambda _: _on_close())
        return tab_id

    async def start(self, channel: str | None = None, user_data_dir: str | None = None,
                    headless: bool | None = None, profile: str | None = None) -> str:
        if self._is_running:
            return 'Browser is already running.'

        from playwright.async_api import async_playwright

        # Resolve profile: explicit arg > config default > None (local mode)
        profile = profile or self.config.default_profile

        # ── Relay mode: connect to user's real browser via extension ──
        if profile in ('chrome', 'edge'):
            from medusa.orchestrator.browser.relay import ExtensionRelay
            from medusa.orchestrator.browser.constants import RELAY_AUTH_HEADER

            # Clean up leftover relay from a failed previous start attempt
            if self._relay is not None:
                try:
                    await self._relay.stop()
                except Exception:
                    pass
                self._relay = None

            self._relay = ExtensionRelay(
                host=self.config.relay_host,
                port=self.config.relay_port,
            )
            await self._relay.start()

            # Wait for the Chrome extension to connect (up to 30 s)
            print('[Browser] Waiting for Medusa extension to connect to relay...')
            for _ in range(300):
                if self._relay.extension_connected():
                    break
                await asyncio.sleep(0.1)
            if not self._relay.extension_connected():
                await self._relay.stop()
                self._relay = None
                raise RuntimeError(
                    'Chrome extension did not connect after 30 s. '
                    'Make sure the Medusa Browser Relay extension is installed '
                    'and active in the Chrome/Edge profile you are using.'
                )

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._relay.cdp_ws_url,
                headers={RELAY_AUTH_HEADER: self._relay.auth_token},
            )

            # Get the default context (or create one)
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = await self._browser.new_context()

            self._context.on('page', self._on_page_created)
            self._is_relay_mode = True
            self._is_running = True

            # Create agent's first tab (goes through CDP → extension → grouped tab)
            self._current_page = await self._context.new_page()
            self._assign_tab_id(self._current_page)
            self._setup_console_listener(self._current_page)

            return (
                f'Browser connected via extension relay ({profile}). '
                f'Agent tab opened in your browser under the "Medusa" tab group. '
                f'Using your saved logins and cookies.'
            )

        # ── Local mode: launch isolated browser ──────────────────────
        ch = channel or self.config.channel
        udd = user_data_dir or self.config.user_data_dir or default_user_data_dir()
        hl = headless if headless is not None else self.config.headless

        Path(udd).mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=udd,
            channel=ch,
            headless=hl,
            no_viewport=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-sync',
                '--start-maximized',
                *self.config.extra_args,
            ],
            ignore_default_args=['--enable-automation'],
        )

        if self._context.pages:
            self._current_page = self._context.pages[-1]
        else:
            self._current_page = await self._context.new_page()

        self._assign_tab_id(self._current_page)
        self._setup_console_listener(self._current_page)
        self._context.on('page', self._on_page_created)
        self._is_running = True
        return f'Browser started ({ch}).'

    async def stop(self) -> str:
        if not self._is_running:
            return 'Browser is not running.'
        was_relay = self._is_relay_mode
        try:
            if self._is_relay_mode:
                # Relay mode: disconnect browser, then stop relay
                if self._browser:
                    await self._browser.close()
            else:
                # Local mode: close persistent context
                if self._context:
                    await self._context.close()
            if self._playwright:
                await self._playwright.stop()
            if self._relay:
                await self._relay.stop()
        except Exception as e:
            logger.warning(f'Error stopping browser: {e}')
        finally:
            self._browser = None
            self._context = None
            self._playwright = None
            self._relay = None
            self._current_page = None
            self._is_running = False
            self._is_relay_mode = False
            self._snapshot_parser = SnapshotParser()
            self._console_messages = []
            self._page_ids.clear()
            self._page_id_reverse.clear()
        return 'Browser stopped.' + (' (relay disconnected)' if was_relay else '')

    async def _ensure_running(self):
        if not self._is_running or not self._context:
            await self.start()

    async def _ensure_page(self):
        await self._ensure_running()
        if self._current_page is None or self._current_page.is_closed():
            pages = self._context.pages
            if pages:
                self._current_page = pages[-1]
            else:
                # Both modes: create a new page.
                # In relay mode this goes through CDP → extension → new grouped tab.
                self._current_page = await self._context.new_page()
        return self._current_page

    def _on_page_created(self, page):
        self._current_page = page
        self._assign_tab_id(page)
        self._setup_console_listener(page)

    def _setup_console_listener(self, page):
        """Attach console message collector to a page."""
        def _on_console(msg):
            self._console_messages.append({
                'level': msg.type,
                'text': msg.text,
            })
        page.on('console', _on_console)

    def _invalidate_refs(self):
        self._snapshot_parser = SnapshotParser()
        self._ai_snapshot_parser = AiSnapshotParser()
        self._refs_mode = 'role'

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    async def status(self) -> str:
        if not self._is_running:
            return 'Browser is not running.'
        mode = 'relay' if self._is_relay_mode else 'local'
        pages = self._context.pages if self._context else []
        if not pages:
            return f'Browser running ({mode}). No agent tabs open.'
        page = await self._ensure_page()
        title = await page.title()
        relay_info = ''
        if self._is_relay_mode and self._relay:
            ext_ok = self._relay.extension_connected()
            relay_info = f' Extension: {"connected" if ext_ok else "disconnected"}.'
        tab_count = len(pages)
        return f'Browser running ({mode}, {tab_count} agent tab(s)). Current: {title} ({page.url}).{relay_info}'

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    async def navigate(self, url: str, timeout_ms: int | None = None) -> str:
        page = await self._ensure_page()
        if not url.startswith(('http://', 'https://', 'file://')):
            url = 'https://' + url
        await page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms or 30000)
        self._invalidate_refs()
        title = await page.title()
        return f'Navigated to {page.url} — "{title}"'

    async def go_back(self) -> str:
        page = await self._ensure_page()
        await page.go_back(timeout=10000)
        self._invalidate_refs()
        return f'Went back to {page.url}'

    # ------------------------------------------------------------------ #
    # Observation
    # ------------------------------------------------------------------ #

    async def _try_snapshot_for_ai(self, page, timeout_ms: int = 5000) -> str | None:
        """Attempt Playwright's private _snapshotForAI method. Returns None if unavailable."""
        if self._ai_available is False:
            return None
        try:
            # Python Playwright maps camelCase → snake_case for private attrs
            fn = getattr(page, '_snapshot_for_ai', None)
            if fn is None:
                # Try through the internal impl object
                fn = getattr(getattr(page, '_impl_obj', None), '_snapshot_for_ai', None)
            if fn is None:
                # Method genuinely missing — lock out permanently
                self._ai_available = False
                return None
            result = await fn(timeout=timeout_ms, track='response')
            text = str(result.get('full', '') if isinstance(result, dict) else result or '')
            self._ai_available = True
            return text
        except Exception:
            # Transient error (page crash, timeout, etc.) — don't lock out,
            # just return None so next call can retry
            return None

    async def snapshot(
        self,
        depth: int | None = None,
        selector: str | None = None,
        interactive: bool = False,
        compact: bool = False,
        limit: int | None = None,
        max_chars: int | None = None,
        snapshot_format: str | None = None,
        mode: str | None = None,
    ) -> str:
        page = await self._ensure_page()
        is_efficient = mode != 'deep'  # default is efficient

        if max_chars is not None:
            char_limit = max_chars
        elif is_efficient:
            char_limit = DEFAULT_AI_SNAPSHOT_EFFICIENT_MAX_CHARS
        else:
            char_limit = DEFAULT_AI_SNAPSHOT_MAX_CHARS

        # Efficient mode caps depth unless explicitly overridden
        if depth is None and is_efficient:
            depth = DEFAULT_AI_SNAPSHOT_EFFICIENT_DEPTH

        opts = {'depth': depth, 'interactive': interactive, 'compact': compact}

        # ── AI format (uses Playwright's private _snapshotForAI) ──────────────
        # Default (None) = try AI first, fall back to role. 'aria' = skip AI entirely.
        if snapshot_format != 'aria':
            ai_text = await self._try_snapshot_for_ai(page)
            if ai_text is not None:
                formatted, _ = self._ai_snapshot_parser.parse(ai_text, opts)
                self._refs_mode = 'aria'

                if limit is not None:
                    lines = formatted.splitlines()
                    count, result_lines = 0, []
                    for line in lines:
                        if re.search(r'\[ref=e\d+\]', line):
                            count += 1
                            if count > limit:
                                result_lines.append(f'... (limited to {limit} elements)')
                                break
                        result_lines.append(line)
                    formatted = '\n'.join(result_lines)

                if len(formatted) > char_limit:
                    formatted = formatted[:char_limit] + '\n... (snapshot truncated)'

                title = await page.title()
                tabs_info = await self._tabs_summary()
                return f'Page: {title} ({page.url})\n{tabs_info}\n\n{formatted}'

            # AI not available — fall through to role format

        # ── Role format (ariaSnapshot() YAML) ────────────────────────────────
        root = page.locator(selector) if selector else page.locator(':root')
        raw_yaml = await root.aria_snapshot()

        formatted, _ = self._snapshot_parser.parse(raw_yaml, opts)
        self._refs_mode = 'role'

        # Limit: cap at N interactive elements
        if limit is not None:
            lines = formatted.splitlines()
            count, result_lines = 0, []
            for line in lines:
                if re.search(r'\[ref=e\d+\]', line):
                    count += 1
                    if count > limit:
                        result_lines.append(f'... (limited to {limit} elements)')
                        break
                result_lines.append(line)
            formatted = '\n'.join(result_lines)

        if len(formatted) > char_limit:
            formatted = formatted[:char_limit] + '\n... (snapshot truncated)'

        title = await page.title()
        tabs_info = await self._tabs_summary()
        return f'Page: {title} ({page.url})\n{tabs_info}\n\n{formatted}'

    async def screenshot(
        self,
        full_page: bool = False,
        ref: str | None = None,
        element: str | None = None,
        img_type: str = 'jpeg',
    ) -> Image.Image:
        page = await self._ensure_page()
        fmt = 'jpeg' if img_type == 'jpeg' else 'png'

        # Guard: no_viewport=True mode or minimized window can leave the
        # viewport at 0×0, which causes CDP "Cannot take screenshot with 0 width".
        vp = page.viewport_size
        if not vp or vp.get('width', 0) == 0:
            await page.set_viewport_size({'width': self.RENDER_W, 'height': self.RENDER_H})

        if ref:
            locator, _ = self._resolve_locator(page, ref, None)
            screenshot_bytes = await locator.screenshot(type=fmt)
        elif element:
            screenshot_bytes = await page.locator(element).screenshot(type=fmt)
        else:
            screenshot_bytes = await page.screenshot(type=fmt, full_page=full_page)

        image = Image.open(BytesIO(screenshot_bytes))
        if image.width > self.RENDER_W or image.height > self.RENDER_H:
            image = image.resize((self.RENDER_W, self.RENDER_H), Image.LANCZOS)
        return image

    # ------------------------------------------------------------------ #
    # Element interactions
    # ------------------------------------------------------------------ #

    def _resolve_locator(self, page, ref: str | None, element: str | None):
        """Resolve a ref or CSS element selector to a Playwright locator + description."""
        if ref:
            if self._refs_mode == 'aria':
                # AI snapshot: Playwright aria-ref selector (most stable)
                locator = self._ai_snapshot_parser.resolve_ref(page, ref)
                elem = self._ai_snapshot_parser._ref_map.get(ref)
                desc = f'[{ref}] {elem.role} "{elem.name}"' if elem else f'[{ref}]'
                return locator, desc
            else:
                # Role snapshot: get_by_role resolution
                locator = self._snapshot_parser.resolve_ref(page, ref)
                elem = self._snapshot_parser._ref_map[ref]
                return locator, f'[{ref}] {elem.role} "{elem.name}"'
        if element:
            return page.locator(element), f'CSS "{element}"'
        return None, None

    async def click(
        self,
        ref: str | None = None,
        button: str = 'left',
        double_click: bool = False,
        modifiers: list[str] | None = None,
        element: str | None = None,
    ) -> str:
        page = await self._ensure_page()
        locator, desc = self._resolve_locator(page, ref, element)
        if locator is None:
            raise ValueError('ref or element required for click.')

        pw_mods = [_MODIFIER_MAP.get(m.lower(), m) for m in modifiers] if modifiers else None

        if double_click:
            await locator.dblclick(button=button, modifiers=pw_mods, timeout=5000)
        else:
            await locator.click(button=button, modifiers=pw_mods, timeout=5000)

        action = 'Double-clicked' if double_click else 'Clicked'
        mod_str = f' with {"+".join(modifiers)}' if modifiers else ''
        return f'{action} {desc}{mod_str}'

    async def type_text(
        self,
        text: str,
        ref: str | None = None,
        submit: bool = False,
        slowly: bool = False,
        element: str | None = None,
    ) -> str:
        page = await self._ensure_page()
        locator, desc = self._resolve_locator(page, ref, element)
        if locator is None:
            raise ValueError('ref or element required for type.')

        if slowly:
            await locator.press_sequentially(text, timeout=10000)
        else:
            await locator.fill(text, timeout=5000)
        if submit:
            await locator.press('Enter', timeout=5000)

        suffix = ' and submitted' if submit else ''
        return f'Typed "{text}" into {desc}{suffix}'

    async def hover(self, ref: str | None = None, element: str | None = None) -> str:
        page = await self._ensure_page()
        locator, desc = self._resolve_locator(page, ref, element)
        if locator is None:
            raise ValueError('ref or element required for hover.')
        await locator.hover(timeout=5000)
        return f'Hovered over {desc}'

    async def select_option(self, ref: str, values: list[str]) -> str:
        page = await self._ensure_page()
        locator, desc = self._resolve_locator(page, ref, None)
        await locator.select_option(values, timeout=5000)
        return f'Selected {values} in {desc}'

    async def press_key(self, key: str) -> str:
        page = await self._ensure_page()
        await page.keyboard.press(key)
        return f'Pressed key: {key}'

    async def scroll_to(self, ref: str) -> str:
        page = await self._ensure_page()
        locator, desc = self._resolve_locator(page, ref, None)
        await locator.scroll_into_view_if_needed(timeout=5000)
        return f'Scrolled {desc} into view'

    async def drag(self, start_ref: str, end_ref: str) -> str:
        page = await self._ensure_page()
        source, src_desc = self._resolve_locator(page, start_ref, None)
        target, tgt_desc = self._resolve_locator(page, end_ref, None)
        await source.drag_to(target)
        return f'Dragged {src_desc} → {tgt_desc}'

    async def fill_fields(self, fields: list[dict]) -> str:
        page = await self._ensure_page()
        filled = []
        for field in fields:
            ref = field.get('ref')
            value = str(field.get('value', ''))
            if not ref:
                raise ValueError(f'each field must have a "ref". Got: {field}')
            locator, desc = self._resolve_locator(page, ref, None)
            await locator.fill(value, timeout=5000)
            filled.append(f'{desc}={value!r}')
        return f'Filled {len(filled)} field(s): {", ".join(filled)}'

    # ------------------------------------------------------------------ #
    # JavaScript
    # ------------------------------------------------------------------ #

    async def evaluate(self, js: str) -> str:
        page = await self._ensure_page()
        result = await page.evaluate(js)
        return f'Result: {result}'

    # ------------------------------------------------------------------ #
    # Tab management
    # ------------------------------------------------------------------ #

    async def tabs(self) -> str:
        await self._ensure_running()
        return await self._tabs_summary()

    async def _tabs_summary(self) -> str:
        lines = ['Tabs:']
        for page in self._context.pages:
            tab_id = self._page_id_reverse.get(id(page), '?')
            title = await page.title()
            marker = ' (current)' if page == self._current_page else ''
            lines.append(f'  [{tab_id}] {title} — {page.url}{marker}')
        return '\n'.join(lines)

    async def open_tab(self, url: str | None = None) -> str:
        await self._ensure_running()
        page = await self._context.new_page()
        self._current_page = page
        # tab ID assigned automatically by _on_page_created listener
        if url:
            if not url.startswith(('http://', 'https://', 'file://')):
                url = 'https://' + url
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        self._invalidate_refs()
        tab_id = self._page_id_reverse.get(id(page), '?')
        tabs = await self._tabs_summary()
        return f'Opened new tab [{tab_id}]. {tabs}'

    async def focus_tab(self, tab_id: str) -> str:
        await self._ensure_running()
        page = self._page_ids.get(tab_id)
        if page is None:
            available = ', '.join(sorted(self._page_ids.keys(), key=lambda k: int(k[1:])))
            raise ValueError(f'Tab "{tab_id}" not found. Available tabs: {available or "none"}')
        self._current_page = page
        await self._current_page.bring_to_front()
        self._invalidate_refs()
        title = await self._current_page.title()
        return f'Focused tab [{tab_id}]: {title}'

    async def close_tab(self, tab_id: str | None = None) -> str:
        await self._ensure_running()
        if tab_id is not None:
            target = self._page_ids.get(tab_id)
            if target is None:
                available = ', '.join(sorted(self._page_ids.keys(), key=lambda k: int(k[1:])))
                raise ValueError(f'Tab "{tab_id}" not found. Available tabs: {available or "none"}')
        else:
            target = self._current_page

        closed_id = self._page_id_reverse.get(id(target), tab_id or '?')
        url = target.url
        await target.close()
        # page.on('close') listener auto-cleans _page_ids and _page_id_reverse

        remaining = self._context.pages
        self._current_page = remaining[-1] if remaining else None
        self._invalidate_refs()
        if remaining:
            tabs = await self._tabs_summary()
            return f'Closed tab [{closed_id}] ({url}). {tabs}'
        return f'Closed tab [{closed_id}] ({url}). No tabs open.'

    # ------------------------------------------------------------------ #
    # Wait / PDF
    # ------------------------------------------------------------------ #

    async def wait(
        self,
        time_ms: int = 1000,
        wait_text: str | None = None,
        wait_text_gone: str | None = None,
    ) -> str:
        page = await self._ensure_page()
        timeout = time_ms or 30000

        if wait_text:
            await page.get_by_text(wait_text).first.wait_for(state='visible', timeout=timeout)
            return f'Text "{wait_text}" appeared on page.'

        if wait_text_gone:
            await page.get_by_text(wait_text_gone).first.wait_for(state='hidden', timeout=timeout)
            return f'Text "{wait_text_gone}" disappeared from page.'

        await page.wait_for_timeout(time_ms)
        return f'Waited {time_ms}ms'

    async def pdf(self) -> str:
        page = await self._ensure_page()
        title = await page.title() or 'page'
        safe_title = ''.join(c for c in title[:30] if c.isalnum() or c in ' _-').strip() or 'page'
        uid = uuid.uuid4().hex[:8]
        output_path = Path.home() / '.medusa' / 'media' / f'{safe_title}---{uid}.pdf'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = await page.pdf()
        output_path.write_bytes(pdf_bytes)
        output_path.chmod(0o600)
        return f'PDF saved to {output_path}'

    # ------------------------------------------------------------------ #
    # Dialog
    # ------------------------------------------------------------------ #

    async def dialog(
        self,
        accept: bool = True,
        prompt_text: str | None = None,
    ) -> str:
        page = await self._ensure_page()

        async def _handle(dlg):
            if accept:
                await dlg.accept(prompt_text or '')
            else:
                await dlg.dismiss()

        page.once('dialog', _handle)
        action = 'accept' if accept else 'dismiss'
        prompt_note = f' (prompt text: "{prompt_text}")' if prompt_text else ''
        return f'Dialog handler armed — will {action} next dialog{prompt_note}. Now trigger the action that opens it.'

    # ------------------------------------------------------------------ #
    # Upload
    # ------------------------------------------------------------------ #

    def _validate_upload_paths(self, paths: list[str]) -> list[str]:
        """Validate all upload paths are within the configured upload root directory."""
        root = Path(self.config.upload_root or (Path.home() / '.medusa' / 'uploads')).resolve()
        root.mkdir(parents=True, exist_ok=True)
        validated = []
        for p in paths:
            resolved = (root / p).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                raise ValueError(
                    f'Upload path "{p}" escapes the allowed upload directory ({root}). '
                    f'All upload files must be placed inside {root}.'
                )
            if not resolved.exists():
                raise ValueError(f'Upload file not found: {resolved}')
            validated.append(str(resolved))
        return validated

    async def upload(
        self,
        paths: list[str],
        ref: str | None = None,
        element: str | None = None,
        timeout_ms: int = 30000,
    ) -> str:
        if not paths:
            raise ValueError('paths required for upload.')
        validated_paths = self._validate_upload_paths(paths)
        page = await self._ensure_page()

        locator, desc = self._resolve_locator(page, ref, element)
        if locator is None:
            raise ValueError('ref or element required to identify the file input for upload.')

        async with page.expect_file_chooser(timeout=timeout_ms) as fc_info:
            await locator.click()

        file_chooser = await fc_info.value
        await file_chooser.set_files(validated_paths)
        return f'Uploaded {len(validated_paths)} file(s) via {desc}: {", ".join(paths)}'

    # ------------------------------------------------------------------ #
    # Console
    # ------------------------------------------------------------------ #

    async def console(self, level: str | None = None) -> str:
        messages = self._console_messages
        if level:
            # Normalise 'warn' → 'warning' to match Playwright type strings
            norm = 'warning' if level == 'warn' else level
            messages = [m for m in messages if m['level'] == norm]
        if not messages:
            return 'No console messages captured.' + (f' (filter: {level})' if level else '')
        lines = [f'[{m["level"]}] {m["text"]}' for m in messages]
        return f'Console ({len(lines)} messages):\n' + '\n'.join(lines)

    # ------------------------------------------------------------------ #
    # Resize
    # ------------------------------------------------------------------ #

    async def resize(self, width: int, height: int) -> str:
        page = await self._ensure_page()
        await page.set_viewport_size({'width': width, 'height': height})
        return f'Viewport resized to {width}×{height}'
