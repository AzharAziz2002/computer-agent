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
    relay_port: int = 18792          # extension relay WebSocket port
    relay_host: str = '127.0.0.1'   # extension relay bind address
    # Default browser profile: 'chrome' or 'edge' = use user's real browser
    # via extension relay.  None = launch isolated Chromium (medusa profile).
    # Reads from env MEDUSA_BROWSER_PROFILE if not set explicitly.
    default_profile: str | None = field(default_factory=lambda: os.getenv('MEDUSA_BROWSER_PROFILE'))
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
