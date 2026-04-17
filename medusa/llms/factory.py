from __future__ import annotations

from dataclasses import dataclass

from medusa.auth import load_llm_config, resolve_anthropic_auth, resolve_openai_codex_auth
from medusa.llms.anthropic import ChatAnthropic
from medusa.llms.openai import ChatOpenAI

# Codex CLI OAuth tokens work against the ChatGPT backend Responses API.
# The correct base URL is chatgpt.com/backend-api (NO /v1 suffix) — the SDK
# appends /responses making the full path chatgpt.com/backend-api/responses.
# Using /v1 → HTML (that path doesn't exist).
# Using api.openai.com → 401 missing api.responses.write scope (Codex JWT
# doesn't carry that scope; chatgpt.com endpoint doesn't require it).
OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"

# Anthropic thinking-budget mapping (token count per reasoning level).
ANTHROPIC_THINKING_BUDGETS: dict[str, int] = {
    "low": 2048,
    "medium": 10240,
    "high": 32768,
}


@dataclass(slots=True)
class ResolvedLLMRuntime:
    llm: object
    provider: str
    model: str
    reasoning_level: str | None = None
    auth_source: str | None = None


def build_runtime_llm(
    *,
    model_override: str | None,
    default_provider: str,
    default_model: str,
    anthropic_thinking_budget: int = -1,
) -> ResolvedLLMRuntime:
    config = load_llm_config()
    provider = (config.provider if config else default_provider).strip()
    configured_model = config.model if config else None
    configured_reasoning = config.reasoning_level if config else None
    normalized_override = model_override.strip() if isinstance(model_override, str) and model_override.strip() else None
    effective_model = (normalized_override or configured_model or default_model).strip()

    if provider == "openai-codex":
        auth = resolve_openai_codex_auth()
        if not auth.access_token:
            raise RuntimeError(
                "OpenAI Codex is selected but no valid ChatGPT OAuth credentials were found. "
                "Run `python -m medusa.cli setup` to configure credentials."
            )
        # Map reasoning level to OpenAI effort string.
        reasoning_effort = configured_reasoning if configured_reasoning in ("low", "medium", "high") else "medium"
        llm = ChatOpenAI(
            model=effective_model,
            api_key=auth.access_token,
            base_url=OPENAI_CODEX_BASE_URL,
            provider_name="openai-codex",
            reasoning_effort=reasoning_effort,
            account_id=auth.account_id,
        )
        return ResolvedLLMRuntime(
            llm=llm,
            provider=provider,
            model=effective_model,
            reasoning_level=configured_reasoning,
            auth_source=auth.source,
        )

    if provider != "anthropic":
        raise RuntimeError(f"Unsupported LLM provider in .credentials/llm_config.json: {provider}")

    auth = resolve_anthropic_auth()
    if not auth.auth_token and not auth.api_key:
        raise RuntimeError(
            "Anthropic is selected but no valid credentials were found. "
            "Set `CLAUDE_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, "
            "or run `python -m medusa.cli setup` to configure credentials."
        )

    # Map reasoning level to Anthropic thinking budget (token count).
    # Explicit budget from caller takes precedence; otherwise use configured level.
    if anthropic_thinking_budget > -1:
        effective_budget = anthropic_thinking_budget
    elif configured_reasoning and configured_reasoning in ANTHROPIC_THINKING_BUDGETS:
        effective_budget = ANTHROPIC_THINKING_BUDGETS[configured_reasoning]
    else:
        effective_budget = -1  # disabled

    llm = ChatAnthropic(
        model=effective_model,
        api_key=auth.api_key,
        auth_token=auth.auth_token,
        thinking_budget=effective_budget,
    )
    return ResolvedLLMRuntime(
        llm=llm,
        provider=provider,
        model=effective_model,
        reasoning_level=configured_reasoning,
        auth_source=auth.source,
    )
