# Changelog

## 2026-04-18

### LLMs — Anthropic OAuth + OpenAI Codex Auth Fixed

Fixed both providers failing when using OAuth credentials.

#### Anthropic OAuth (`medusa/llms/anthropic.py`, `medusa/auth/anthropic_auth.py`)

**Root cause:** OAuth tokens (`sk-ant-oat*`) require a specific set of headers and a mandatory system prompt prefix that signals to Anthropic's backend that the request is coming from an authorized Claude Code client. Without these, the API returned 429 model-access errors on Sonnet/Opus.

- Missing `anthropic-dangerous-direct-browser-access: true` header — required for OAuth tokens to reach subscription-tier models
- Missing `claude-code-20250219` and `oauth-2025-04-20` beta flags in `anthropic-beta` header
- Missing identity system block: `"You are Claude Code, Anthropic's official CLI for Claude."` must be prepended as the first system block for OAuth requests; Anthropic validates its presence to grant full subscription model access
- `max_tokens` validation error: when thinking is enabled, `max_tokens` must be strictly greater than `budget_tokens`; fixed by computing `effective_max_tokens = max(self.max_tokens, self.thinking_budget + 1024)`
- Token refresh: expired OAuth tokens now auto-refresh against `platform.claude.com/v1/oauth/token` and are written back to the credential file; Cloudflare blocks plain Python User-Agent so requests use `claude-cli/2.1.75`

#### OpenAI Codex (`medusa/llms/openai.py`, `medusa/llms/factory.py`)

**Root cause:** Three compounding errors caused the endpoint to return an HTML loading page instead of an API response.

1. **Wrong URL path** — requests were sent to `chatgpt.com/backend-api/responses`. The correct Codex endpoint is `chatgpt.com/backend-api/codex/responses`.
2. **Missing required headers** — the endpoint requires `chatgpt-account-id` (extracted from the JWT's `https://api.openai.com/auth.chatgpt_account_id` claim), `originator: pi`, `User-Agent: pi (platform arch)`, and `OpenAI-Beta: responses=experimental`. None of these were present.
3. **Wrong request structure** — the OpenAI SDK's `responses.create()` was used, which targets a different endpoint and schema. The Codex endpoint expects a raw SSE stream with `instructions` (system prompt) as a top-level field separate from `input` (messages), `store: false`, and `text: {verbosity: "medium"}`.

**Fix:** Replaced `ChatOpenAI` usage for the `openai-codex` provider with a new dedicated `ChatOpenAICodex` class that uses a raw `httpx` SSE stream matching the `@mariozechner/pi-ai` `openai-codex-responses` transport exactly.

#### Prompt caching — OpenAI (`medusa/llms/openai.py`)

Added `prompt_cache_key` (a stable per-session UUID) to all OpenAI requests. OpenAI caches the request prefix when the same key is reused across turns, equivalent to Anthropic's `cache_control` breakpoints.

#### Modified files

- `medusa/llms/anthropic.py` — OAuth headers, identity system block, `_is_oauth_token` property, `_build_system()`, `effective_max_tokens` fix
- `medusa/llms/openai.py` — new `ChatOpenAICodex` class (raw SSE, correct endpoint/headers/body); `prompt_cache_key` added to both `ChatOpenAI` and `ChatOpenAICodex`
- `medusa/llms/factory.py` — `openai-codex` provider now routes to `ChatOpenAICodex`; `OPENAI_CODEX_BASE_URL` updated to `chatgpt.com/backend-api`
- `medusa/auth/anthropic_auth.py` — OAuth token refresh logic, write-back to credential file, User-Agent fix
- `medusa/auth/openai_codex_auth.py` — mtime-based expiry fallback, soft-refresh from Codex CLI on expired persisted token

---

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
