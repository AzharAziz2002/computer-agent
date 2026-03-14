import atexit
import asyncio
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from datetime import datetime
from pathlib import Path

from medusa.llms.views import ChatLLMUsage

LOGS_DIR = Path(__file__).parent.parent.parent / "LOGS"

# Official Anthropic pricing per million tokens ($/MTok) — source:
# platform.claude.com/docs/en/about-claude/pricing
# Format: model_id_fragment -> (input, output)
_CLAUDE_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-opus-3": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-sonnet-3-7": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-3-5": (0.80, 4.0),
    "claude-haiku-3": (0.25, 1.25),
}


def _get_claude_pricing(model_id: str) -> tuple[float, float] | None:
    """Return (input_$/MTok, output_$/MTok) for a Claude model, or None if unknown."""
    key = model_id.lower().replace(".", "-")
    if key in _CLAUDE_PRICING:
        return _CLAUDE_PRICING[key]
    matches = [(k, v) for k, v in _CLAUDE_PRICING.items() if k in key]
    if matches:
        return max(matches, key=lambda x: len(x[0]))[1]
    return None


class SessionLogger:
    """Per-session markdown logger for LLM responses, tool results, and billing summary."""

    def __init__(self, query: str, model_name: str = "unknown", start_time: datetime | None = None):
        now = datetime.now()
        self._start_time = start_time or now
        LOGS_DIR.mkdir(exist_ok=True)
        daily_dir = LOGS_DIR / self._format_daily_dir(self._start_time)
        daily_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self._start_time.strftime("%Y%m%d_%H%M%S")
        self.log_path = daily_dir / f"session_{timestamp}.md"
        self._model_name = model_name

        self.log_path.write_text(
            f"# Session Log\n\n"
            f"**Time:** {self._start_time.strftime('%Y-%m-%d %H:%M:%S')}  \n"
            f"**Query:** {query}\n\n"
            f"---\n\n",
            encoding="utf-8",
        )

        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._last_tool_time = self._start_time

        self._finalized = False
        self._pending_futures: list[Future] = []
        self._pending_lock = threading.Lock()

        # Background event loop for non-blocking logging calls.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        # Final safety net: append summary even if caller exits unexpectedly.
        atexit.register(self._finalize_on_exit)

    def mark_ready(self):
        """Reset step timer after initialization so first step excludes init overhead."""
        self._last_tool_time = datetime.now()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_response(
        self,
        step: int,
        content: str | None,
        thinking: str | None,
        tool_calls,
        usage: ChatLLMUsage | None = None,
    ):
        """Schedule LLM response log write and accumulate token usage."""
        if usage:
            self._input_tokens += usage.prompt_tokens or 0
            self._output_tokens += usage.completion_tokens or 0
            self._total_tokens += usage.total_tokens or 0

        if self._finalized:
            self._sync_append(self._build_response_block(step, content, thinking, tool_calls))
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._write_response(step, content, thinking, tool_calls), self._loop
            )
            self._track_future(future)
        except Exception:
            # Loop unavailable during shutdown; write synchronously.
            self._sync_append(self._build_response_block(step, content, thinking, tool_calls))

    def log_tool_result(self, step: int, tool_name: str, result: str):
        """Schedule tool result log write."""
        now = datetime.now()
        step_elapsed = now - self._last_tool_time
        total_elapsed = now - self._start_time
        self._last_tool_time = now

        if self._finalized:
            self._sync_append(
                self._build_tool_result_block(step, tool_name, result, step_elapsed, total_elapsed)
            )
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._write_tool_result(step, tool_name, result, step_elapsed, total_elapsed),
                self._loop,
            )
            self._track_future(future)
        except Exception:
            self._sync_append(
                self._build_tool_result_block(step, tool_name, result, step_elapsed, total_elapsed)
            )

    def finalize(self, model_name: str | None = None):
        """Finalize session file with token and billing summary."""
        if self._finalized:
            return

        self._finalized = True
        if model_name:
            self._model_name = model_name

        try:
            self._drain_pending_writes(timeout_seconds=3.0)
        except Exception:
            pass

        try:
            self._stop_background_loop()
        except Exception:
            pass

        # Always write summary — guaranteed last write
        self._write_summary_sync(self._model_name)

        try:
            atexit.unregister(self._finalize_on_exit)
        except Exception:
            pass

    def close(self):
        """Backwards-compatible alias."""
        self.finalize()

    # ------------------------------------------------------------------
    # Async writers
    # ------------------------------------------------------------------

    async def _write_response(self, step: int, content: str | None, thinking: str | None, tool_calls):
        await self._append(self._build_response_block(step, content, thinking, tool_calls))

    async def _write_tool_result(self, step: int, tool_name: str, result: str, step_elapsed, total_elapsed):
        await self._append(
            self._build_tool_result_block(step, tool_name, result, step_elapsed, total_elapsed)
        )

    async def _append(self, content: str):
        # The loop already runs on a dedicated thread, so direct writes are fine.
        self._sync_append(content)

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_response_block(self, step: int, content: str | None, thinking: str | None, tool_calls) -> str:
        parts = [f"## Step {step}\n\n"]
        if thinking:
            parts += ["### Claude Thinking\n\n", thinking.strip(), "\n\n"]
        if content:
            parts += ["=== Claude Reason ===\n\n", content.strip(), "\n\n"]
        if tool_calls:
            for tc in tool_calls:
                raw_repr = (
                    tc.raw
                    if getattr(tc, "raw", None)
                    else f"ToolCall(id='{tc.id}', name='{tc.name}', arguments={tc.arguments})"
                )
                parts += [
                    "=== Tool Call Detected ===\n\n",
                    f'"{raw_repr}"\n\n',
                ]
        return "".join(parts)

    def _build_tool_result_block(self, step: int, tool_name: str, result: str, step_elapsed, total_elapsed) -> str:
        step_str = str(step_elapsed).split(".")[0]
        total_str = str(total_elapsed).split(".")[0]
        return (
            f"=== Tool Result (`{tool_name}`) ===\n\n"
            f"{result.strip()}\n\n"
            f"`Step: {step_str}` · `Total: {total_str}`\n\n---\n\n"
        )

    def _build_summary_block(self, model_name: str) -> str:
        duration = datetime.now() - self._start_time
        lines = [
            "## Session Summary\n\n",
            f"**Duration:** {str(duration).split('.')[0]}\n\n",
            "### Token Usage\n\n",
            "| | Tokens |\n|---|---|\n",
            f"| Input  | {self._input_tokens:,} |\n",
            f"| Output | {self._output_tokens:,} |\n",
            f"| **Total** | **{self._total_tokens:,}** |\n\n",
        ]

        pricing = _get_claude_pricing(model_name)
        if pricing:
            input_rate, output_rate = pricing
            input_cost = (self._input_tokens / 1_000_000) * input_rate
            output_cost = (self._output_tokens / 1_000_000) * output_rate
            total_cost = input_cost + output_cost
            lines += [
                "### Billing (Claude API)\n\n",
                f"**Model:** `{model_name}`  \n",
                f"**Rates:** ${input_rate}/MTok input · ${output_rate}/MTok output\n\n",
                "| | Cost |\n|---|---|\n",
                f"| Input  | ${input_cost:.6f} |\n",
                f"| Output | ${output_cost:.6f} |\n",
                f"| **Total** | **${total_cost:.6f}** |\n\n",
                "> Pricing source: "
                "[platform.claude.com/docs/en/about-claude/pricing]"
                "(https://platform.claude.com/docs/en/about-claude/pricing)\n",
            ]
        else:
            lines.append(f"> Billing not calculated — `{model_name}` is not a Claude model.\n")

        return "".join(lines)

    @staticmethod
    def _format_daily_dir(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d_%a")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_append(self, content: str):
        with open(self.log_path, "a", encoding="utf-8") as file:
            file.write(content)

    def _write_summary_sync(self, model_name: str):
        # Build first, then write in one shot — minimizes interrupt window
        summary = self._build_summary_block(model_name)
        try:
            self._sync_append(summary)
        except (KeyboardInterrupt, Exception):
            # Last resort: direct write ignoring all errors
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(summary)
            except Exception:
                pass

    def _track_future(self, future: Future):
        with self._pending_lock:
            self._pending_futures.append(future)

        def _remove(done_future: Future):
            with self._pending_lock:
                try:
                    self._pending_futures.remove(done_future)
                except ValueError:
                    pass

        future.add_done_callback(_remove)


    def _drain_pending_writes(self, timeout_seconds: float):
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while time.monotonic() < deadline:
            with self._pending_lock:
                pending = list(self._pending_futures)

            if not pending:
                return

            for future in pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                try:
                    future.result(timeout=min(remaining, 0.2))
                except FutureTimeout:
                    continue
                except Exception:
                    continue

    def _stop_background_loop(self):
        try:
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        except Exception:
            pass

    def _finalize_on_exit(self):
        try:
            self.finalize(self._model_name)
        except Exception:
            pass
