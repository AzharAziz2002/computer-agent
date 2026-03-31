from medusa.orchestrator.desktop.state import DesktopState
from medusa.orchestrator.desktop.controller import Desktop
from importlib.resources import files
from datetime import datetime
from getpass import getuser
from pathlib import Path
import pyautogui as pg

INCLUDE_SOUL = False

class Prompt:
    @staticmethod
    def system_prompt(desktop:Desktop, language: str, instructions: list[str]=[]) -> str:
        """Build system prompt (tools are now passed via API, not in prompt)."""
        width, height = pg.size()
        format_vars = {
            'datetime': datetime.now().strftime('%A, %B %d, %Y'),
            'instructions': '\n'.join(instructions),
            'download_directory': Path.home().joinpath('Downloads').as_posix(),
            'os': desktop.get_windows_version(),
            'language': language,
            'home_dir': Path.home().as_posix(),
            'user': f"{getuser()} ({desktop.get_user_account_type()})",
            'resolution': f'Primary Monitor ({width}x{height}) with DPI Scale: {desktop.get_dpi_scaling()}',
        }
        parts = []
        if INCLUDE_SOUL:
            soul = Path(files('medusa.orchestrator.prompts').joinpath('soul.md')).read_text(encoding='utf-8')
            parts.append(soul.format(**format_vars))
        template = Path(files('medusa.orchestrator.prompts').joinpath('system.md')).read_text(encoding='utf-8')
        parts.append(template.format(**format_vars))
        return '\n\n'.join(parts)

    @staticmethod
    def screenshot_observation(desktop_state: DesktopState) -> str:
        """Build accessibility tree observation from desktop state."""
        cursor_location = pg.position()
        tree_state = desktop_state.tree_state
        template = Path(files('medusa.orchestrator.prompts').joinpath('observation.md')).read_text(encoding='utf-8')
        active_app_name = desktop_state.active_app.name if desktop_state.active_app else ''
        return template.format(**{
            'cursor_location': f'({cursor_location.x},{cursor_location.y})',
            'active_app': desktop_state.active_app_to_string(),
            'apps': desktop_state.apps_to_string(),
            'interactive_elements': tree_state.interactive_elements_to_string(active_app_name) or 'No interactive elements found',
            'scrollable_elements': tree_state.scrollable_elements_to_string(active_app_name) or 'No scrollable elements found',
        })
