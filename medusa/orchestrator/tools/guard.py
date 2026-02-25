"""Command safety guard that classifies shell commands before execution."""

import re
import ctypes
from typing import Literal

class CommandGuard:
    """Classifies shell commands as safe, requiring confirmation, or blocked."""

    BLOCKED: list[tuple[re.Pattern, str]] = [
        (re.compile(r'\bshutdown\b', re.IGNORECASE),          'System shutdown is not permitted'),
        (re.compile(r'\bStop-Computer\b', re.IGNORECASE),     'System shutdown is not permitted'),
        (re.compile(r'\bRestart-Computer\b', re.IGNORECASE),  'System restart is not permitted'),
        (re.compile(r'\bformat\s+[a-zA-Z]:', re.IGNORECASE), 'Disk formatting is not permitted'),
        (re.compile(r'\bFormat-Volume\b', re.IGNORECASE),     'Disk formatting is not permitted'),
        (re.compile(r'\bdiskpart\b', re.IGNORECASE),          'Disk partitioning is not permitted'),
        (re.compile(r'\bbcdedit\b', re.IGNORECASE),           'Boot configuration changes are not permitted'),
        (re.compile(r'\bcipher\s+/w', re.IGNORECASE),         'Disk wiping is not permitted'),
        (re.compile(r'\bsdelete\b', re.IGNORECASE),           'Secure delete utility is not permitted'),
        (re.compile(r'\brd\s+/s\s+/q\s+[a-zA-Z]:\\', re.IGNORECASE), 'Recursive drive deletion is not permitted'),
        (re.compile(r'Remove-Item.{0,60}-Recurse.{0,60}-Force\s+[a-zA-Z]:\\(?:Windows|System32|Program)', re.IGNORECASE), 'Deleting system directories is not permitted'),
        (re.compile(r'\brm\s+-[^\s]*r[^\s]*f\s+/', re.IGNORECASE), 'Recursive force-delete on root paths is not permitted'),
        (re.compile(r'\bnet\s+user\s+administrator\b', re.IGNORECASE), 'Modifying the administrator account is not permitted'),
    ]

    CONFIRM: list[tuple[re.Pattern, str]] = [
        (re.compile(r'\bRemove-Item\b', re.IGNORECASE),        'Remove-Item (file/dir deletion)'),
        (re.compile(r'\brm\b', re.IGNORECASE),                 'rm (file/dir deletion)'),
        (re.compile(r'\bdel\b', re.IGNORECASE),                'del (file deletion)'),
        (re.compile(r'\brmdir\b', re.IGNORECASE),              'rmdir (directory removal)'),
        (re.compile(r'\brd\b', re.IGNORECASE),                 'rd (directory removal)'),
        (re.compile(r'\breg\s+(add|delete)\b', re.IGNORECASE), 'registry modification'),
        (re.compile(r'\bnet\s+user\b', re.IGNORECASE),         'user account modification'),
        (re.compile(r'\bSet-ExecutionPolicy\b', re.IGNORECASE),'execution policy change'),
        (re.compile(r'\bInvoke-Expression\b', re.IGNORECASE),  'dynamic code execution (iex)'),
        (re.compile(r'\biex\b', re.IGNORECASE),                'dynamic code execution (iex)'),
        (re.compile(r'\bRunAs\b', re.IGNORECASE),              'elevated process launch'),
    ]

    @classmethod
    def classify(cls, command: str) -> tuple[Literal['allow', 'confirm', 'block'], str]:
        """Return (verdict, reason). Reason is empty string for 'allow'."""
        for pattern, reason in cls.BLOCKED:
            if pattern.search(command):
                return 'block', reason
        for pattern, reason in cls.CONFIRM:
            if pattern.search(command):
                return 'confirm', reason
        return 'allow', ''

    @classmethod
    def ask_user(cls, command: str, reason: str) -> bool:
        """Show a Windows MessageBox asking whether to run the command."""
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        MB_TOPMOST = 0x40000
        IDYES = 6
        msg = (
            f"The agent wants to run a potentially destructive command:\n\n"
            f"{command}\n\n"
            f"Reason flagged: {reason}\n\n"
            f"Allow execution?"
        )
        result = ctypes.windll.user32.MessageBoxW(
            0, msg, "Medusa \u2014 Command Confirmation",
            MB_YESNO | MB_ICONWARNING | MB_TOPMOST
        )
        return result == IDYES
