from medusa.messages import SystemMessage, HumanMessage, ToolCallMessage, ToolResultMessage
from medusa.logs.contextwindow import ContextLogger
from medusa.orchestrator.context.constants import (
    BLOCK_REMOVE, BLOCK_LIMIT,
    SCREENSHOT_REMOVE, SCREENSHOT_LIMIT,
    SCREENSHOT_CACHE, SCREENSHOT_CACHE_SLOTS,
)

class ContextManager:
    """Manages message context — removes old turns, expires old screenshots,
    and assigns sticky cache marks to screenshots within the available budget."""

    def __init__(self):
        self._pinned = []    # SystemMessage + HumanMessage(query) — never removed
        self._turns = []     # list of lists — each turn = [msg, msg, ...]
        self._current_turn = []
        self._turn_count = 0
        self._logger = ContextLogger()

    def append(self, message):
        """Append a message to context."""
        if isinstance(message, (SystemMessage, HumanMessage)) and not self._turns and not self._current_turn:
            self._pinned.append(message)
        else:
            self._current_turn.append(message)

    def end_turn(self):
        """Finalize the current turn and trim context."""
        if self._current_turn:
            self._turns.append(self._current_turn)
            self._current_turn = []
            self._trim()
            self._mark_screenshots_cached()
            self._turn_count += 1
            self._logger.log_snapshot(self._turn_count, self.messages)

    # ── Trimming ──

    def _trim(self):
        """Remove old turns and expire old screenshots."""
        # 1. Remove entire turns beyond block_limit
        if BLOCK_REMOVE and len(self._turns) > BLOCK_LIMIT:
            self._turns = self._turns[-BLOCK_LIMIT:]

        # 2. Remove screenshot pairs (ToolCall + ToolResult) older than screenshot_limit turns
        if SCREENSHOT_REMOVE:
            last_turn_idx = len(self._turns) - 1
            for ti, turn in enumerate(self._turns):
                age = last_turn_idx - ti
                if age >= SCREENSHOT_LIMIT:
                    expired_ids = {msg.tool_call_id for msg in turn if self._is_screenshot(msg)}
                    if expired_ids:
                        self._turns[ti] = [
                            msg for msg in turn
                            if not (self._is_screenshot(msg) or
                                    (isinstance(msg, ToolCallMessage) and msg.tool_call_id in expired_ids))
                        ]

            # Drop turns that became fully empty after screenshot removal
            self._turns = [turn for turn in self._turns if turn]

    # ── Screenshot detection ──

    def _is_screenshot(self, msg) -> bool:
        """Check if a message is a screenshot or snapshot ToolResultMessage."""
        if not isinstance(msg, ToolResultMessage):
            return False
        if msg.tool_name == 'desktop':
            return msg.image is not None or msg.content.startswith('<desktop_state>')
        if msg.tool_name == 'browser':
            return msg.image is not None or msg.content.startswith('Page:')
        return False

    # ── Sticky cache marking ──

    def _mark_screenshots_cached(self):
        """Assign cache_control=ephemeral to screenshots using sticky slot-based marking.

        Marks are sticky — once a screenshot gets cache_control it keeps it for
        its entire lifetime in context. New screenshots only get marked when a
        slot is available. When a marked screenshot is trimmed out, the freed
        slot goes to the newest unmarked screenshot (longest remaining lifetime
        → most cache hits).
        """
        if not SCREENSHOT_CACHE:
            return

        # Count how many screenshots in context already have a cache mark
        marked = 0
        for turn in self._turns:
            for msg in turn:
                if self._is_screenshot(msg) and msg.cache_control:
                    marked += 1

        slots_remaining = SCREENSHOT_CACHE_SLOTS - marked
        if slots_remaining <= 0:
            return

        # Fill free slots: scan newest-first (longest remaining lifetime)
        for turn in reversed(self._turns):
            for msg in reversed(turn):
                if slots_remaining <= 0:
                    return
                if self._is_screenshot(msg) and not msg.cache_control:
                    msg.cache_control = {'type': 'ephemeral'}
                    slots_remaining -= 1

    # ── Public API ──

    @property
    def messages(self) -> list:
        """Return full message list for LLM invocation."""
        result = list(self._pinned)
        for turn in self._turns:
            result.extend(turn)
        if self._current_turn:
            result.extend(self._current_turn)
        return result
