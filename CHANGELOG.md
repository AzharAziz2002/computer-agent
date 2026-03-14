# Changelog

## 2026-03-12

### API — `use_vision` Removed

The `use_vision` field added to `StartTaskRequest` was a dead parameter — it reached `Agent(use_vision=...)` but the feature it controls (`desktop.get_state(use_vision=True)`, annotated screenshots) is abandoned and not called anywhere in the active agent loop. The parameter only affected telemetry event tags with no behavioral effect.

#### Modified Files

- **`api/models.py`** — removed `use_vision: bool` from `StartTaskRequest`
- **`api/routers/tasks.py`** — removed `use_vision` from `_run_agent` signature, `Agent(...)` instantiation, and `run_in_executor` call
