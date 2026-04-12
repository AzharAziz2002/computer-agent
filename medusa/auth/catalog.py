from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AuthMethod(Enum):
    API_KEY = "api-key"
    SETUP_TOKEN = "setup-token"
    OAUTH_LOGIN = "oauth-login"
    CLI_IMPORT = "cli-import"
    ENV_VAR = "env-var"


@dataclass(frozen=True, slots=True)
class AuthMethodSpec:
    method: AuthMethod
    label: str
    description: str
    env_vars: tuple[str, ...] = ()
    requires_external_cli: str | None = None


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    label: str
    is_default: bool = False
    reasoning_levels: tuple[str, ...] = ()  # e.g. ("low", "medium", "high")


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: str
    label: str
    auth_methods: tuple[AuthMethodSpec, ...]
    models: tuple[ModelSpec, ...]
    base_url: str | None = None
    notes: str | None = None


# ── Provider Definitions ─────────────────────────────────────────────

ANTHROPIC = ProviderSpec(
    id="anthropic",
    label="Anthropic (Claude)",
    auth_methods=(
        AuthMethodSpec(
            method=AuthMethod.SETUP_TOKEN,
            label="Setup token (OAuth)",
            description="Paste an Anthropic setup/OAuth token (sk-ant-oat-...)",
        ),
        AuthMethodSpec(
            method=AuthMethod.CLI_IMPORT,
            label="Import from Claude Code CLI",
            description="Reuse credentials from ~/.claude/.credentials.json",
        ),
        AuthMethodSpec(
            method=AuthMethod.API_KEY,
            label="API key",
            description="Paste an Anthropic API key (sk-ant-api-...)",
            env_vars=("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
        ),
        AuthMethodSpec(
            method=AuthMethod.ENV_VAR,
            label="Environment variable",
            description="Use ANTHROPIC_AUTH_TOKEN from environment",
            env_vars=("ANTHROPIC_AUTH_TOKEN",),
        ),
    ),
    models=(
        ModelSpec(
            id="claude-sonnet-4-6", label="Claude Sonnet 4.6", is_default=True,
            reasoning_levels=("low", "medium", "high"),
        ),
        ModelSpec(id="claude-haiku-4-5-20251001", label="Claude Haiku 4.5"),
        ModelSpec(
            id="claude-opus-4-6", label="Claude Opus 4.6",
            reasoning_levels=("low", "medium", "high"),
        ),
    ),
)

OPENAI_CODEX = ProviderSpec(
    id="openai-codex",
    label="OpenAI Codex (ChatGPT)",
    auth_methods=(
        AuthMethodSpec(
            method=AuthMethod.OAUTH_LOGIN,
            label="Login via Codex CLI",
            description="Run `codex login` and import the resulting OAuth tokens",
            requires_external_cli="codex",
        ),
        AuthMethodSpec(
            method=AuthMethod.CLI_IMPORT,
            label="Import from Codex CLI",
            description="Reuse existing credentials from ~/.codex/auth.json",
        ),
        AuthMethodSpec(
            method=AuthMethod.ENV_VAR,
            label="Environment variable",
            description="Use OPENAI_CODEX_ACCESS_TOKEN from environment",
            env_vars=("OPENAI_CODEX_ACCESS_TOKEN",),
        ),
    ),
    models=(
        ModelSpec(
            id="gpt-5.4", label="GPT-5.4", is_default=True,
            reasoning_levels=("low", "medium", "high"),
        ),
        ModelSpec(
            id="gpt-5.4-mini", label="GPT-5.4 Mini",
            reasoning_levels=("low", "medium", "high"),
        ),
        ModelSpec(
            id="gpt-5.3-codex", label="GPT-5.3 Codex",
            reasoning_levels=("low", "medium", "high"),
        ),
        ModelSpec(
            id="gpt-5.2", label="GPT-5.2",
            reasoning_levels=("low", "medium", "high"),
        ),
    ),
    base_url="https://chatgpt.com/backend-api",
)

# ── Registry ─────────────────────────────────────────────────────────

PROVIDERS: tuple[ProviderSpec, ...] = (ANTHROPIC, OPENAI_CODEX)

PROVIDER_MAP: dict[str, ProviderSpec] = {p.id: p for p in PROVIDERS}


def get_provider(provider_id: str) -> ProviderSpec | None:
    return PROVIDER_MAP.get(provider_id)


def get_default_model(provider_id: str) -> str | None:
    spec = PROVIDER_MAP.get(provider_id)
    if not spec:
        return None
    for m in spec.models:
        if m.is_default:
            return m.id
    return spec.models[0].id if spec.models else None
