# Medusa

Medusa is an AI agent that controls your Windows computer the way a human would — it looks at the screen, clicks, types, opens apps, browses the web, and works inside any application. You give it a task, it figures out the rest.

---

## Project Structure

> **Important:** Medusa ships as **two repositories**. This repo is the backend only.
> To run the full desktop application you must clone **both**.

| Repository | Role | Stack |
|---|---|---|
| **[computer-agent](https://github.com/mhuzaifashah/computer-agent)** *(this repo)* | Agent core, computer-control tools, API server | Python 3.13 + `uv` |
| **[computer-ui](https://github.com/mhuzaifashah/computer-ui)** | Desktop user interface | Node.js — Electron + React + TypeScript |

The two halves are kept in separate repositories because they are different runtimes with
independent dependency managers, build pipelines and tooling. The frontend's own setup,
scripts and build instructions are documented in its repository's README.

The UI is a client of the API server in this repo — it has no agent logic of its own, and
does nothing unless this backend is running.

### Clone both repositories

```bash
git clone https://github.com/mhuzaifashah/computer-agent.git
git clone https://github.com/mhuzaifashah/computer-ui.git
```

Keep them side by side:

```
your-folder/
├── computer-agent/   ← backend (this repo)
└── computer-ui/      ← frontend
```

---

## Quick Start

Complete setup, in order. **Requires Windows** and **Python 3.13+**.

### 1. Backend — install dependencies

```bash
cd computer-agent
uv sync
```

### 2. Backend — configure a provider

Medusa needs an LLM provider before it will run. See [Auth Setup](#auth-setup) below.

```bash
uv run python -m medusa.cli
```

### 3. Backend — start the API server

Does not start automatically. Leave it running.

```bash
uv run python server.py
```

The server runs at `http://127.0.0.1:8000`.

### 4. Frontend — install and run

In a **second terminal**:

```bash
cd computer-ui
npm install
npm run dev
```

The desktop window opens and connects to the backend automatically.

### CLI only (no frontend)

The agent is also fully usable from the terminal, without cloning or installing the UI:

```bash
uv run python main.py
```

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


