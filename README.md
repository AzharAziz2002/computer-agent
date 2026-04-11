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
