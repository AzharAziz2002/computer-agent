# Medusa

Medusa is an AI agent that controls your Windows computer the way a human would — it looks at the screen, clicks, types, opens apps, browses the web, and works inside any application. You give it a task, it figures out the rest.

> Project is in early development. More features coming soon.

## Anthropic Auth

Medusa can now run Anthropic without `CLAUDE_API_KEY` if either of these exists:

- a repo-local token file at `.credentials/anthropic.json`
- a Claude Code login at `~/.claude/.credentials.json` or common WSL Windows-home equivalents

To save a setup token locally from WSL:

```bash
./.venv/Scripts/python.exe manage_anthropic_auth.py set-token
```

To inspect which auth source Medusa will use:

```bash
./.venv/Scripts/python.exe manage_anthropic_auth.py show
```

## OpenAI Codex Auth

Medusa can also run with ChatGPT OAuth-backed Codex access.

Supported sources:

- a repo-local credential file at `.credentials/openai_codex.json`
- an existing Codex CLI login at `~/.codex/auth.json`

To run the official Codex login flow and import the result into this repo:

```bash
./.venv/Scripts/python.exe manage_openai_auth.py login
```

To reuse an existing Codex CLI login without re-running browser auth:

```bash
./.venv/Scripts/python.exe manage_openai_auth.py import-cli
```

To inspect which Codex auth source Medusa will use:

```bash
./.venv/Scripts/python.exe manage_openai_auth.py show --include-config
```

To switch the repo-local active provider to Codex:

```bash
./.venv/Scripts/python.exe manage_openai_auth.py use --model gpt-5.4
```

Medusa now reads `.credentials/llm_config.json` to decide whether runtime should use Anthropic or OpenAI Codex.
