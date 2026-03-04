from medusa.messages import SystemMessage, HumanMessage, ToolCallMessage, ToolResultMessage
from medusa.logs.contextwindow import ContextLogger

class ContextManager:
    """Manages message context — removes old turns, expires old screenshots."""

    def __init__(self, block_limit: int = 4, screenshot_limit: int = 2, cache_query: bool = True):
        self._pinned = []    # SystemMessage + HumanMessage(query) — never removed
        self._turns = []     # list of lists — each turn = [msg, msg, ...]
        self.block_limit = block_limit
        self.screenshot_limit = screenshot_limit
        self.cache_query = cache_query
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
            self._turn_count += 1
            self._logger.log_snapshot(self._turn_count, self.messages)

    def _trim(self):
        """Remove old turns and expire old screenshots."""
        # 1. Remove entire turns beyond block_limit
        if len(self._turns) > self.block_limit:
            self._turns = self._turns[-self.block_limit:]

        # 2. Expire screenshots older than screenshot_limit turns.
        #    age = how many turns ago (0 = current, 1 = previous, ...).
        #    Expire when age >= screenshot_limit.
        last_turn_idx = len(self._turns) - 1
        for ti, turn in enumerate(self._turns):
            age = last_turn_idx - ti
            if age >= self.screenshot_limit:
                for mi, msg in enumerate(turn):
                    if self._is_screenshot(msg):
                        self._turns[ti][mi] = ToolResultMessage(
                            content="[screenshot expired]",
                            tool_call_id=msg.tool_call_id,
                            tool_name=msg.tool_name,
                        )

    def _is_screenshot(self, msg) -> bool:
        """Check if a message is a screenshot ToolResultMessage."""
        return (isinstance(msg, ToolResultMessage)
                and msg.tool_name == 'desktop_tool'
                and (msg.image is not None
                     or msg.content.startswith('<desktop_state>')))

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
