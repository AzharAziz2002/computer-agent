"""Browser configuration and executable discovery for Windows."""

import os
from pathlib import Path
from dataclasses import dataclass, field


DEFAULT_CDP_PORT = 9222


@dataclass
class BrowserConfig:
    channel: str = 'chrome'
    user_data_dir: str | None = None
    headless: bool = False
    viewport_width: int = 1280
    viewport_height: int = 720
    upload_root: str | None = None   # defaults to ~/.medusa/uploads
    extra_args: list[str] = field(default_factory=list)


def discover_chrome_executable() -> str | None:
    """Find Chrome or Edge executable on Windows."""
    candidates = [
        # Edge
        Path(os.environ.get('PROGRAMFILES', '')) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe',
        # Chrome
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
        Path(os.environ.get('PROGRAMFILES', '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def default_user_data_dir() -> str:
    """Return default isolated browser profile directory."""
    return str(Path.home() / '.medusa' / 'browser-profile')
