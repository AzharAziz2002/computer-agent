# Agents

This repository defines one primary coding/runtime agent: **Medusa**.

Medusa is a Windows computer-use agent that can:
- observe desktop state through UI Automation and screenshots,
- invoke structured tools,
- execute shell commands (with safety guardrails),
- and iterate until a task is complete.

This document is for coding agents that need to understand project structure, module ownership, and where to make changes safely.

## Project Snapshot

- Name: `computer` (Medusa runtime)
- Platform: Windows only
- Python: `>=3.13` (managed with `uv`)
- Entry flow: `main.py` -> `medusa.orchestrator.core.Agent`

## WSL Execution Note

- When working from WSL in this repository, do not assume `uv` or `python` is available in the Linux environment.
- Use the Windows virtualenv interpreter directly: `./.venv/Scripts/python.exe`
- Prefer commands such as `./.venv/Scripts/python.exe main.py` and `./.venv/Scripts/python.exe tests/test_tool_schemas.py`
- Anthropic auth supports repo-local token storage in `.credentials/anthropic.json` and automatic Claude Code credential reuse from `~/.claude/.credentials.json`.
- OpenAI Codex auth supports repo-local OAuth storage in `.credentials/openai_codex.json` and automatic Codex CLI credential reuse from `~/.codex/auth.json`. Expired tokens are soft-refreshed from Codex CLI auth.json when available.
- Runtime provider/model selection lives in `.credentials/llm_config.json`.
- Use `python -m medusa.cli` (or `./.venv/Scripts/python.exe -m medusa.cli`) for interactive provider/model configuration.


## Runtime Architecture

1. `main.py` reads user prompt, loads environment variables, creates LLM client, then calls `Agent.print_response`.
2. `medusa.orchestrator.core.Agent` builds a tool registry and desktop controller, creates prompts, and runs the action loop.
3. The chosen LLM adapter (`medusa.llms.*`) receives serialized messages + tool schemas and returns tool calls.
4. `Registry.execute()` validates tool args (Pydantic), executes tool function, and returns a `ToolResult`.
5. Desktop/tool outcomes are injected back into messages until `done_tool` is called.

## Module Responsibilities

### `medusa/orchestrator`
- `core.py`: Main autonomous loop (LLM call, tool execution, retries, termination).
- `views.py`: Core agent data models (`AgentStep`, `AgentResult`, `Action`, `AgentData`).
- `logger.py`: Async session markdown logging into `LOGS/session_*.md`.
- `registry/`: Tool registration, schema emission, execution + validation.
- `tools/service.py`: Concrete tool implementations.
- `tools/views.py`: Tool argument schemas (Pydantic models).
- `tools/guard.py`: Shell command classification (`allow`, `confirm`, `block`).
- `desktop/controller.py`: OS and GUI interactions (apps, click/type/scroll/drag, shell execution).
- `desktop/state.py`: App and desktop state dataclasses/enums.
- `tree/inspector.py`: Accessibility tree traversal + filtering + DOM-aware extraction for browser content.
- `tree/state.py`: Node/state models for interactive/scroll/text elements.
- `watchdog/observer.py`: UIA event thread (focus, structure, property change listeners).
- `prompts/`: Prompt templates + generator for system and observation messages.

### `medusa/auth`
- `anthropic_auth.py`: Anthropic credential resolver (setup token, Claude Code CLI, API key, env vars).
- `openai_codex_auth.py`: OpenAI Codex credential resolver (OAuth, Codex CLI, env vars). Includes soft-refresh and mtime-based expiry fallback.
- `llm_config.py`: Active provider + model persistence (`llm_config.json`).
- `catalog.py`: Provider catalog (frozen dataclasses) defining available providers, auth methods, and models.

### `medusa/cli`
- Interactive CLI for provider/model configuration. Invoke via `python -m medusa.cli`.
- `app.py`: Argparse dispatch + interactive top-level menu.
- `flows.py`: Setup, select, show, clear flows.
- `display.py`: InquirerPy + rich formatting helpers.

### `medusa/llms`
- Common contract:
  - `base.py`: `BaseChatLLM` protocol.
  - `views.py`: `ChatLLMResponse`, usage model, tool call model.
- `factory.py`: `build_runtime_llm()` — reads config, resolves auth, instantiates LLM adapter.
- Provider adapters:
  - `anthropic.py`, `google.py`, `openai.py`, `azure_openai.py`, `open_router.py`, `groq.py`, `cerebras.py`, `mistral.py`, `ollama.py`
  - Each adapter handles:
    - message serialization,
    - provider-specific tool schema formatting,
    - response parsing into common `ChatLLMResponse`.

### `medusa/messages`
- Unified internal message types used across providers:
  - `SystemMessage`, `HumanMessage`, `AIMessage`,
  - `ImageMessage`,
  - `ToolCallMessage`, `ToolResultMessage`.

### `medusa/tool`
- Tool decorator and schema preprocessing.
- Converts Pydantic models into provider-agnostic JSON schema consumed by registry and LLM adapters.

### `medusa/telemetry`
- Optional PostHog integration.
- Controlled by `ANONYMIZED_TELEMETRY` env setting.

### `medusa/uia`
- Local vendored/forked UI Automation layer used by desktop and tree modules.
- Provides controls, patterns, enums, events, and Win32/UIA helpers.

### `tests`
- `test_tool_schemas.py`: Runtime schema generation/inspection for all registered tools and providers.
- Outputs markdown report in same folder (`tool_schemas_report.md`).

## Tooling Surface (Agent-Visible)

Registered in `Agent.registry`:
- `desktop_tool`: unified desktop actions (`click`, `type`, `scroll`, `drag`, `move`, `shortcut`, `wait`, `multi_select`, `multi_edit`)
- `app_tool`: app launch/switch/resize
- `shell_tool`: PowerShell execution (guarded by `CommandGuard`)
- `memory_tool`: persistent markdown memory files in `.memories`
- `scrape_tool`: visible page content extraction via current accessibility tree state
- `done_tool`: terminal tool to finalize answer

## Configuration and Environment

- `.env` is expected for API credentials (for example `CLAUDE_API_KEY`).
- Core dependencies in `pyproject.toml` include:
  - desktop automation (`pyautogui`, `pywin32`, `uiautomation`, `comtypes`),
  - LLM SDKs (Anthropic, Google, OpenAI, Groq, Ollama, Mistral, Cerebras),
  - infra (`pydantic`, `rapidfuzz`, `markdownify`, `posthog`).

## Common Dev Commands

```bash
uv sync
uv run python main.py
uv run python tests/test_tool_schemas.py
tree /f /a
```

From WSL, use:

```bash
./.venv/Scripts/python.exe main.py
./.venv/Scripts/python.exe tests/test_tool_schemas.py
./.venv/Scripts/python.exe -m medusa.cli            # Interactive provider/model config
./.venv/Scripts/python.exe -m medusa.cli setup       # Set up a provider
./.venv/Scripts/python.exe -m medusa.cli select      # Switch active model
./.venv/Scripts/python.exe -m medusa.cli show        # Show current config & auth status
./.venv/Scripts/python.exe -m medusa.cli clear       # Clear stored credentials
```

## Where To Change Code

- Add or modify a tool:
  - schema: `medusa/orchestrator/tools/views.py`
  - implementation: `medusa/orchestrator/tools/service.py`
  - registration: `medusa/orchestrator/core.py` (tool list in `Registry([...])`)

- Add/modify provider support:
  - new adapter in `medusa/llms/`
  - ensure `invoke()` returns `ChatLLMResponse`
  - implement message serializer + tool schema formatter

- Change prompt behavior:
  - templates in `medusa/orchestrator/prompts/*.md`
  - assembly logic in `medusa/orchestrator/prompts/generator.py`

- Change desktop perception or action behavior:
  - `medusa/orchestrator/desktop/controller.py`
  - `medusa/orchestrator/tree/inspector.py`
  - `medusa/orchestrator/watchdog/observer.py`

## Safety Notes

- This agent operates with the same OS privileges as the running user.
- `shell_tool` has guardrails, but not full sandboxing.
- Desktop actions and shell commands can affect local files/apps; validate changes during development.
