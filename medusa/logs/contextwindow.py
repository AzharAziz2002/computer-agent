from medusa.messages import SystemMessage, HumanMessage, AIMessage, ToolCallMessage, ToolResultMessage

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from textwrap import shorten

CONTEXT_LOG_DIR = Path(__file__).parent.parent.parent / "LOGS" / "context"


class ContextLogger:
    """Async logger that dumps context snapshots to markdown after each turn."""

    def __init__(self):
        CONTEXT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = CONTEXT_LOG_DIR / f"context_{timestamp}.md"
        self.log_path.write_text(
            f"# Context Snapshots\n\n"
            f"**Started:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n",
            encoding="utf-8",
        )
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def log_snapshot(self, turn_number: int, messages: list):
        """Schedule an async write of the full context snapshot."""
        snapshot = self._build_snapshot(turn_number, messages)
        try:
            asyncio.run_coroutine_threadsafe(self._write(snapshot), self._loop)
        except Exception:
            self._sync_write(snapshot)

    async def _write(self, content: str):
        self._sync_write(content)

    def _sync_write(self, content: str):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(content)

    def _build_snapshot(self, turn_number: int, messages: list) -> str:
        parts = [
            f"## After Turn {turn_number}\n\n",
            f"**Messages: {len(messages)}** · "
            f"**Time:** {datetime.now().strftime('%H:%M:%S')}\n\n",
        ]

        for i, msg in enumerate(messages):
            parts.append(f"### [{i}] {type(msg).__name__}\n\n")

            if isinstance(msg, SystemMessage):
                preview = shorten(msg.content, width=200, placeholder="...")
                parts.append(f"```\n{preview}\n```\n\n")

            elif isinstance(msg, HumanMessage):
                parts.append(f"{msg.content}\n\n")

            elif isinstance(msg, AIMessage):
                parts.append(f"{msg.content}\n\n")

            elif isinstance(msg, ToolCallMessage):
                parts.append(
                    f"**Tool:** `{msg.tool_name}` · **ID:** `{msg.tool_call_id}`\n\n"
                )
                if msg.content:
                    parts.append(f"> {shorten(msg.content, width=300, placeholder='...')}\n\n")
                parts.append(f"**Input:** `{msg.tool_input}`\n\n")

            elif isinstance(msg, ToolResultMessage):
                has_image = "Yes" if msg.image is not None else "No"
                parts.append(
                    f"**Tool:** `{msg.tool_name}` · **ID:** `{msg.tool_call_id}` · **Image:** {has_image}\n\n"
                )
                content = msg.content
                if content.startswith('<desktop_state>'):
                    lines = content.count('\n') + 1
                    preview = shorten(content, width=300, placeholder="...")
                    parts.append(f"`<desktop_state>` ({lines} lines)\n\n```\n{preview}\n```\n\n")
                elif content in ("[screenshot expired]", "[trimmed]"):
                    parts.append(f"**`{content}`**\n\n")
                else:
                    parts.append(f"```\n{shorten(content, width=500, placeholder='...')}\n```\n\n")

            else:
                parts.append(f"_{type(msg).__name__}: {shorten(str(msg), width=200, placeholder='...')}_\n\n")

        parts.append("---\n\n")
        return "".join(parts)

    def stop(self):
        """Stop the background loop."""
        try:
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=3)
        except Exception:
            pass
