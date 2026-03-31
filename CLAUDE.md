# Agents

This repository defines one primary coding/runtime agent: **Medusa**.

Medusa is a Windows computer-use agent that can:
- observe desktop state through screenshots,
- invoke structured tools,
- execute shell commands (with safety guardrails),
- and iterate until a task is complete.

This document is for coding agents that need to understand project structure, module ownership, and where to make changes safely.

## Project Snapshot

- Name: `computer` (Medusa runtime)
- Platform: Windows only
- Python: `>=3.13` (managed with `uv`)
- Entry flow: `main.py` -> `medusa.orchestrator.core.Agent`
- API entry: `server.py` -> `medusa.api.app` (FastAPI, port 8000)


## Runtime Architecture

1. `main.py` reads user prompt, loads environment variables, creates LLM client, then calls `Agent.print_response`.
2. `medusa.orchestrator.core.Agent` builds a tool registry and desktop controller, creates prompts, and runs the action loop.
3. The chosen LLM adapter (`medusa.llms.*`) receives serialized messages + tool schemas and returns tool calls.
4. `Registry.execute()` validates tool args (Pydantic), executes tool function, and returns a `ToolResult`.
5. Desktop/tool outcomes are injected back into messages until `done_tool` is called.


## Module Responsibilities

### `medusa/orchestrator`
- `core.py`: Main autonomous loop (LLM call, tool execution, retries, termination). Also filters screenshot tool calls from batches that contain a shell call.
- `views.py`: Core agent data models (`AgentStep`, `AgentResult`, `Action`, `AgentData`).
- `registry/`: Tool registration, schema emission, execution + validation.
- `tools/`: Modular tool system (each tool has its own implementation + schema files).
  - `base.py`: `SharedBaseModel` base class for all tool schemas.
  - `{tool}_tool.py`: Tool implementations (`desktop_tool`, `shell_tool`, `memory_tool`, `browser_tool`, `general_tool` for `done`/`app`/`scrape`).
  - `{tool}_schema.py`: Tool argument schemas (Pydantic models).
  - `service.py`: Re-exports for backward compatibility.
  - `views.py`: Re-exports for backward compatibility.
- `browser/`: Browser automation and snapshot capture via Playwright.
  - `controller.py`: Async Playwright browser control (navigation, interaction, screenshot).
  - `relay.py`: Extension relay for accessing Chrome user profiles.
  - `snapshot.py`: Browser page state capture (DOM, loaded resources, page metrics).
  - `config.py`: Browser configuration (profiles, launch args, timeouts).
  - `constants.py`: Browser-related constants.
  - `state.py`: Browser state dataclass.
- `shellmiddleware/command_safety.py`: Shell command safety classification (`allow`, `confirm`, `block`). Replaces old `tools/guard.py`.
- `shellmiddleware/search_rules.py`: File-search validation and consecutive-failure tracking. Blocks extension-only searches, bad search patterns (GCI -Recurse, where.exe wildcards), and stops the agent after 2 consecutive empty results.
- `desktop/controller.py`: OS and GUI interactions (apps, click/type/scroll/drag, shell execution, screenshots).
- `desktop/state.py`: App and desktop state dataclasses/enums.
- `tree/inspector.py`: Accessibility tree traversal. **Used only by `scrape_tool`** for browser DOM content extraction — not used for general desktop perception.
- `tree/state.py`: Node/state models for interactive/scroll/text elements.
- `watchdog/observer.py`: UIA event thread (focus, structure, property change listeners).
- `prompts/`: Prompt templates + generator for system and observation messages.
- `context/`: Context window management package.
  - `constants.py`: Toggleable settings (block removal, screenshot removal, cache breakpoints).
  - `manager.py`: `ContextManager` — block trimming, screenshot expiry, sticky cache marking.

### `medusa/api` — FastAPI backend for frontend integration
- `app.py`: FastAPI app with CORS middleware, lifespan (startup/shutdown for MCP plugin system), mounts all routers. Creates singleton `MCPManager` shared by connectors + tasks routers.
- `routers/tasks.py`: REST + WebSocket endpoints.
  - `POST /api/tasks` — start a new agent task (runs `Agent.invoke` in a thread pool). Passes `mcp_manager` to Agent.
  - `DELETE /api/tasks/{task_id}` — stop a running task.
  - `WS /api/ws/{task_id}` — stream step updates to frontend as JSON frames (`TaskUpdateFrame`).
- `routers/screenshot.py`: `GET /api/screenshot` — returns a live JPEG screenshot of the desktop.
- `routers/sessions.py`: Session CRUD (list, get, delete).
- `routers/connectors.py`: MCP connector management.
  - `GET /api/connectors` — list all connectors with connection status.
  - `POST /api/connectors/{id}/connect` — initiate connection (OAuth or API key).
  - `DELETE /api/connectors/{id}` — disconnect + remove credentials.
  - `GET /api/connectors/{id}/tools` — list tools from connected MCP server.
- `models.py`: Pydantic request/response models (`StartTaskRequest`, `StartTaskResponse`, `AgentStepModel`, `TaskUpdateFrame`).
- `state.py`: In-memory task store (task status, steps, queues for WS broadcast).
- `server.py` (project root): `uvicorn` entry point — `python server.py` starts on `http://127.0.0.1:8000`.

### `medusa/llms`
- Common contract:
  - `base.py`: `BaseChatLLM` protocol.
  - `views.py`: `ChatLLMResponse`, usage model, tool call model.
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

### `medusa/logs`
- `logger.py`: Async session markdown logging into `LOGS/session_*.md`.
- `contextwindow.py`: Context window tracking helpers.

### `medusa/tool`
- Tool decorator and schema preprocessing.
- Converts Pydantic models into provider-agnostic JSON schema consumed by registry and LLM adapters.

### `medusa/plugins` — MCP connector system
- `catalog.py`: Static registry of supported connectors (`ConnectorDef` dataclass, `CATALOG` dict). Each entry maps a frontend connector ID to its auth type, MCP server command, and env variable mapping. Add new connectors by adding entries to `CATALOG`.
- `credentials.py`: Encrypted credential storage. Master key in OS keyring (Windows Credential Manager via `keyring`), credentials encrypted with Fernet (AES-128-CBC + HMAC) to `.credentials/connectors.enc`. Never stores credentials in plaintext on disk.
- `oauth.py`: Ephemeral OAuth callback server. Starts on random port, captures authorization code, exchanges for tokens. Validates CSRF state parameter.
- `manager.py`: MCP server lifecycle manager (`MCPManager`). Spawns MCP server subprocesses via Python MCP SDK (`stdio_client`), maintains persistent `ClientSession` connections, exposes merged tool list. Tool names prefixed with `{connector_id}__` to avoid collisions.

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

Registered in `Agent.registry` (built-in tools):
- `desktop`: unified desktop actions (`click`, `type`, `scroll`, `drag`, `move`, `shortcut`, `hold_key`, `wait`, `multi_select`, `multi_edit`, `screenshot`) via pyautogui
- `browser`: browser automation via Playwright (navigate, click, type, screenshot)
- `app`: app launch/switch/resize
- `shell`: PowerShell execution (guarded by `CommandGuard` + `SearchValidator`)
- `memory`: persistent markdown memory files in `.memories`
- `scrape`: visible browser page content via accessibility tree
- `done`: terminal tool to finalize answer

**MCP connector tools** (dynamic, from connected MCP servers):
- When connectors are connected via the Connectors page, their MCP tools are merged into the agent's tool schema at task start.
- MCP tool names are prefixed: `{connector_id}__{tool_name}` (e.g. `github__list_repos`).
- In the agent loop (`core.py`), tool calls with `__` in the name are routed to `MCPManager.call_tool()` instead of the built-in registry.


## Abandoned / Dormant Concepts

These modules exist in the codebase but are **not active** in the current agent perception pipeline:

- **`desktop.get_state(use_vision=False)`** — previously used to generate text-based desktop observations from the UI accessibility tree. Abandoned; the agent now observes exclusively via screenshots.
- **`Prompt.screenshot_observation()`** — observation text generated from desktop state. Commented out in `service.py` screenshot case; not called anywhere active.
- **`use_vision` flag on `Agent`** — the parameter still exists but has no effect; vision is always screenshot-based.
- **Inspect mode** — was removed; there is no non-screenshot observation mode.
- **`tree/inspector.py` for desktop perception** — the UI tree is still traversed, but **only** to serve `scrape_tool` (browser DOM extraction). It is not used to describe general desktop state to the agent.
- **`tools/guard.py`** — deleted; replaced by `shellmiddleware/command_safety.py`.


## Configuration and Environment

- `.env` is expected for API credentials (for example `CLAUDE_API_KEY`). Also holds OAuth client IDs/secrets for MCP connectors (e.g. `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`).
- `.credentials/connectors.enc` — encrypted connector credentials (Fernet). Master key stored in OS keyring. **Never committed** (in `.gitignore`).
- Core dependencies in `pyproject.toml` include:
  - desktop automation (`pyautogui`, `pywin32`, `uiautomation`, `comtypes`),
  - LLM SDKs (Anthropic, Google, OpenAI, Groq, Ollama, Mistral, Cerebras),
  - API server (`fastapi`, `uvicorn`),
  - MCP connector system (`mcp`, `cryptography`, `keyring`, `httpx`),
  - infra (`pydantic`, `rapidfuzz`, `markdownify`, `posthog`).


## Common Dev Commands

```bash
uv sync
uv run python main.py          # CLI agent
python server.py               # API server on :8000
uv run python tests/test_tool_schemas.py
tree /f /a
```


## Where To Change Code

- **Add or modify a tool:**
  - schema: `medusa/orchestrator/tools/{tool}_schema.py`
  - implementation: `medusa/orchestrator/tools/{tool}_tool.py`
  - registration: `medusa/orchestrator/core.py` (tool list in `Registry([...])`)
  - backward compatibility: optionally update `service.py` and `views.py` re-exports

- **Add/modify shell safety rules:**
  - destructive command blocking/confirmation: `medusa/orchestrator/shellmiddleware/command_safety.py`
  - search pattern enforcement + failure tracking: `medusa/orchestrator/shellmiddleware/search_rules.py`

- **Add/modify provider support:**
  - new adapter in `medusa/llms/`
  - ensure `invoke()` returns `ChatLLMResponse`
  - implement message serializer + tool schema formatter

- **Change prompt behavior:**
  - templates in `medusa/orchestrator/prompts/*.md`
  - assembly logic in `medusa/orchestrator/prompts/generator.py`

- **Change desktop action behavior:**
  - `medusa/orchestrator/desktop/controller.py`

- **Change browser automation behavior:**
  - Playwright control: `medusa/orchestrator/browser/controller.py`
  - Browser snapshots: `medusa/orchestrator/browser/snapshot.py`
  - Profile management: `medusa/orchestrator/browser/relay.py` + `config.py`

- **Change browser scraping behavior:**
  - `medusa/orchestrator/tree/inspector.py`

- **Add API endpoints for the frontend:**
  - add router in `medusa/api/routers/`
  - register in `medusa/api/app.py`
  - add models in `medusa/api/models.py`

- **Add a new MCP connector:**
  - Add entry to `CATALOG` in `medusa/plugins/catalog.py` with auth type, MCP command, env mapping
  - If OAuth: set `oauth_client_id_env` / `oauth_client_secret_env` and add client ID/secret to `.env`
  - No other code changes needed — the connector appears in `GET /api/connectors` automatically


## API Contract (for frontend)

Base URL: `http://127.0.0.1:8000`

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tasks` | Start agent task. Body: `{query, model, session_id?}`. Returns `{task_id, session_id}`. |
| `DELETE` | `/api/tasks/{task_id}` | Stop a running task. |
| `WS` | `/api/ws/{task_id}` | Stream step updates. Each frame is a `TaskUpdateFrame` JSON object. |
| `GET` | `/api/screenshot` | Returns live desktop screenshot as JPEG. |
| `GET` | `/api/sessions` | List all sessions. |
| `GET` | `/api/sessions/{id}` | Get session metadata + transcript. |
| `DELETE` | `/api/sessions/{id}` | Delete session. |
| `GET` | `/api/connectors` | List all connectors with connection status + tools. |
| `POST` | `/api/connectors/{id}/connect` | Connect (API key in body, or returns OAuth URL). |
| `DELETE` | `/api/connectors/{id}` | Disconnect + remove credentials. |
| `GET` | `/api/connectors/{id}/tools` | List tools from connected MCP server. |

`TaskUpdateFrame` shape:
```json
{
  "task_id": "...",
  "type": "delta | step | done",
  "status": "running | done | failed",
  "delta": "...",
  "step": {
    "id": "...",
    "stepNumber": 1,
    "action": { "name": "shell", "params": {} },
    "observation": "...",
    "isError": false
  },
  "result": "...",
  "error": "..."
}
```


## Safety Notes

- This agent operates with the same OS privileges as the running user.
- `shell_tool` has guardrails via `CommandGuard` (block/confirm/allow) and `SearchValidator` (search pattern enforcement), but not full sandboxing.
- Desktop actions and shell commands can affect local files/apps; validate changes during development.
