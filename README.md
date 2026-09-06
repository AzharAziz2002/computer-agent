# Medusa

Medusa is an AI agent that controls your Windows computer the way a human would — it looks at the screen, clicks, types, opens apps, browses the web, and works inside any application. You give it a task, it figures out the rest.

## Frontend

Medusa's desktop UI lives in a separate repository:

**https://github.com/mhuzaifashah/computer-ui**

It is a Node.js project (Electron + React + TypeScript), so it is kept apart from this
Python backend. Setup and usage instructions are in that repository's own README.

The UI talks to the API server in this repo, so start the backend first:

```bash
uv run python server.py
```

Then follow the frontend repo's instructions to launch the UI.

---

## Quick Start

```bash
uv sync
```

**Run the CLI agent:**
```bash
uv run python main.py
```

**Start the API server** (for frontend — does not start automatically):
```bash
uv run python server.py
```

The server runs at `http://127.0.0.1:8000`.

---

## Auth Setup

Before running, configure a provider and credentials:

```bash
uv run python -m medusa.cli
```

This opens an interactive menu. Use the sub-commands below to go directly to a specific flow:

| Command | What it does |
|---|---|
| `uv run python -m medusa.cli setup` | Set up a provider (API key or OAuth token) |
| `uv run python -m medusa.cli select` | Switch the active provider/model |
| `uv run python -m medusa.cli show` | Show current config and auth status |
| `uv run python -m medusa.cli clear` | Remove stored credentials for a provider |

---

## Provider Auth Details

### Anthropic

Three auth methods are available during `setup`:

- **OAuth/setup token** — paste a token starting with `sk-ant-oat*`. Saved to `.credentials/anthropic.json`.
- **Import Claude Code CLI** — imports credentials from `~/.claude/.credentials.json` if you are already logged into Claude Code CLI.
- **API key** — paste your `ANTHROPIC_API_KEY`. The CLI will tell you to add it to your `.env` file (keys are read from env, not stored directly).

`.env` file for API key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### OpenAI Codex

Three auth methods are available during `setup`:

- **OAuth login** — runs the Codex CLI browser login flow and imports the result to `.credentials/openai_codex.json`.
- **Import Codex CLI** — imports an existing `~/.codex/auth.json` without re-running browser auth.
- **Env var** — set `OPENAI_CODEX_ACCESS_TOKEN` in your shell or `.env` file.

`.env` file for env var method:
```
OPENAI_CODEX_ACCESS_TOKEN=...
```

---

## Credential Files

| File | Contents |
|---|---|
| `.credentials/llm_config.json` | Active provider + model selection |
| `.credentials/anthropic.json` | Anthropic OAuth token (auto-refreshed on expiry) |
| `.credentials/openai_codex.json` | OpenAI Codex JWT token |
| `.credentials/connectors.enc` | Encrypted MCP connector credentials |
| `.env` | API keys read at runtime (never committed) |

---


