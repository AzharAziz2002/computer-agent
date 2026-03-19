from medusa.messages import SystemMessage, HumanMessage, ToolCallMessage, ToolResultMessage
from medusa.logs.contextwindow import ContextLogger

class ContextManager:
    """Manages message context — removes old turns, expires old screenshots."""

    def __init__(self, block_limit: int = 4, screenshot_limit: int = 2, cache_query: bool = True,
                 cache_screenshot: bool = True):
        self._pinned = []    # SystemMessage + HumanMessage(query) — never removed
        self._turns = []     # list of lists — each turn = [msg, msg, ...]
        self.block_limit = block_limit
        self.screenshot_limit = screenshot_limit
        self.cache_query = cache_query
        self.cache_screenshot = cache_screenshot  # mark latest screenshot ephemeral for prompt caching
        self._current_turn = []
        self._turn_count = 0
        self._logger = ContextLogger()

    def append(self, message):
        """Append a message to context."""
        # Pinned messages: system + query (before any tool activity)
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
            if self.cache_screenshot:
                self._mark_latest_screenshot()
            self._turn_count += 1
            self._logger.log_snapshot(self._turn_count, self.messages)

    def _trim(self):
        """Remove old turns and expire old screenshots."""
        # 1. Remove entire turns beyond block_limit
        if len(self._turns) > self.block_limit:
            self._turns = self._turns[-self.block_limit:]

        # 2. Remove screenshot pairs (ToolCall + ToolResult) older than screenshot_limit turns.
        #    age = how many turns ago (0 = current, 1 = previous, ...).
        last_turn_idx = len(self._turns) - 1
        for ti, turn in enumerate(self._turns):
            age = last_turn_idx - ti
            if age >= self.screenshot_limit:
                expired_ids = {msg.tool_call_id for msg in turn if self._is_screenshot(msg)}
                if expired_ids:
                    self._turns[ti] = [
                        msg for msg in turn
                        if not (self._is_screenshot(msg) or
                                (isinstance(msg, ToolCallMessage) and msg.tool_call_id in expired_ids))
                    ]

        # 3. Drop turns that became fully empty after screenshot removal
        self._turns = [turn for turn in self._turns if turn]

    def _is_screenshot(self, msg) -> bool:
        """Check if a message is a screenshot or snapshot ToolResultMessage."""
        if not isinstance(msg, ToolResultMessage):
            return False
        if msg.tool_name == 'desktop':
            return msg.image is not None or msg.content.startswith('<desktop_state>')
        if msg.tool_name == 'browser':
            return msg.image is not None or msg.content.startswith('Page:')
        return False

    def _mark_latest_screenshot(self):
        """Set cache_control=ephemeral on every screenshot currently in context.

        With screenshot_limit=2 there are at most 2 screenshots alive at once.
        System prompt and tools schema each use 1 of the 4 allowed Anthropic cache
        breakpoints, leaving exactly 2 for screenshots — so both can be marked.

        Keeping A cached when B arrives means the next request still gets a cache
        hit on A's prefix before processing B, then a cache hit on B's prefix on
        the turn after. Clearing A would throw that hit away for no benefit.
        """
        for turn in self._turns:
            for msg in turn:
                if self._is_screenshot(msg):
                    msg.cache_control = {'type': 'ephemeral'}

    @property
    def messages(self) -> list:
        """Return full message list for LLM invocation."""
        result = list(self._pinned)
        for turn in self._turns:
            result.extend(turn)
        # Include any in-progress turn
        if self._current_turn:
            result.extend(self._current_turn)
        return result
