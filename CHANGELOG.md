# Changelog

## 2026-03-20

### Agent — Dead Variables Removed

Removed four unused or vestigial variables from `Agent.__init__` and their propagation through the codebase.

#### What was removed and where

- **`name` / `description`** (`medusa/orchestrator/core.py`) — hardcoded strings `'Medusa'` and `'An agent that can interact with GUI elements on Windows OS'` assigned in `__init__` but never read anywhere
- **`use_vision: bool`** (`medusa/orchestrator/core.py`, `main.py`, `medusa/telemetry/views.py`) — parameter documented as abandoned in CLAUDE.md; vision is always screenshot-based; the flag only tagged telemetry events with no behavioral effect
- **`browser_choice: Browser`** (`medusa/orchestrator/core.py`, `medusa/orchestrator/prompts/generator.py`) — `Browser` enum value was passed to `Prompt.system_prompt()` solely to interpolate `browser.value` into `soul.md`; `soul.md` is never rendered (`INCLUDE_SOUL = False`); actual browser control is done by `self.browser_controller` which is unaffected; `Browser` import also removed from both files

#### Modified files

- **`medusa/orchestrator/core.py`** — removed `browser_choice`, `use_vision` params and `self.name`, `self.description`, `self.browser`, `self.use_vision` assignments; removed `Browser` import; removed `use_vision` from both `AgentTelemetryEvent` calls; removed `browser=` arg from `Prompt.system_prompt()` call
- **`medusa/orchestrator/prompts/generator.py`** — removed `browser: Browser` param, `Browser` import, and `'browser': browser.value` from format vars
- **`medusa/telemetry/views.py`** — removed `use_vision: bool` field from `AgentTelemetryEvent`
- **`main.py`** — removed `use_vision=False` from `Agent(...)` call

---

## 2026-03-12

### API — `use_vision` Removed

The `use_vision` field added to `StartTaskRequest` was a dead parameter — it reached `Agent(use_vision=...)` but the feature it controls (`desktop.get_state(use_vision=True)`, annotated screenshots) is abandoned and not called anywhere in the active agent loop. The parameter only affected telemetry event tags with no behavioral effect.

#### Modified Files

- **`api/models.py`** — removed `use_vision: bool` from `StartTaskRequest`
- **`api/routers/tasks.py`** — removed `use_vision` from `_run_agent` signature, `Agent(...)` instantiation, and `run_in_executor` call
