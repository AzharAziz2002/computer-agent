from __future__ import annotations

import os

from medusa.auth.anthropic_auth import (
    clear_persisted_anthropic_token,
    load_claude_cli_token,
    resolve_anthropic_auth,
    save_anthropic_setup_token,
)
from medusa.auth.catalog import (
    PROVIDERS,
    AuthMethod,
    ProviderSpec,
    get_provider,
)
from medusa.auth.llm_config import load_llm_config, save_llm_config
from medusa.auth.openai_codex_auth import (
    clear_persisted_openai_codex_auth,
    import_codex_cli_credentials,
    resolve_openai_codex_auth,
    run_codex_login,
    save_openai_codex_oauth,
)
from medusa.cli.display import (
    confirm,
    console,
    error,
    info,
    select_menu,
    status_table,
    success,
    text_input,
)


def _cancelled() -> int:
    info("Cancelled.")
    return 0


def _probe_provider_auth(provider: ProviderSpec) -> dict:
    """Probe whether a provider has working credentials."""
    status: dict = {
        "id": provider.id,
        "label": provider.label,
        "authenticated": False,
        "source": None,
        "expires_at": None,
    }
    if provider.id == "anthropic":
        auth = resolve_anthropic_auth()
        if auth.auth_token or auth.api_key:
            status["authenticated"] = True
            status["source"] = auth.source
            status["expires_at"] = auth.expires_at
    elif provider.id == "openai-codex":
        auth = resolve_openai_codex_auth()
        if auth.access_token:
            status["authenticated"] = True
            status["source"] = auth.source
            status["expires_at"] = auth.expires_at
    return status


def _provider_menu() -> ProviderSpec | None:
    choices = [
        {"name": f"{p.label}  ({p.id})", "value": p}
        for p in PROVIDERS
    ]
    return select_menu("Select provider", choices)


def _model_menu(provider: ProviderSpec) -> str | None:
    choices = [
        {
            "name": f"{m.label}  ({m.id})" + ("  [default]" if m.is_default else ""),
            "value": m.id,
        }
        for m in provider.models
    ]
    return select_menu("Select model", choices)


def _reasoning_menu(provider: ProviderSpec, model_id: str) -> str | None:
    """Show reasoning level menu if the model supports it. Returns level or None."""
    model_spec = next((m for m in provider.models if m.id == model_id), None)
    if not model_spec or not model_spec.reasoning_levels:
        return None

    choices = [
        {"name": level.capitalize(), "value": level}
        for level in model_spec.reasoning_levels
    ]
    return select_menu("Select reasoning level", choices)


def _select_model_and_save(provider: ProviderSpec) -> int:
    """Shared model + reasoning selection and save. Returns 0 on success."""
    model_id = _model_menu(provider)
    if model_id is None:
        return _cancelled()

    reasoning_level = _reasoning_menu(provider, model_id)
    # reasoning_level=None is valid (esc on reasoning = skip, or model has no levels)

    path = save_llm_config(provider.id, model_id, reasoning_level)
    label = f"{provider.id} / {model_id}"
    if reasoning_level:
        label += f" / reasoning={reasoning_level}"
    success(f"Active config saved: {label} -> {path}")
    return 0


# ── Setup Flow ────────────────────────────────────────────────────────

def _execute_anthropic_auth(method: AuthMethod) -> bool | None:
    """Returns True on success, False on failure, None if user pressed Escape."""
    if method == AuthMethod.SETUP_TOKEN:
        token = text_input("Paste your Anthropic setup/OAuth token:", password=True)
        if token is None:
            return None
        if not token.strip():
            error("Token cannot be empty.")
            return False
        path = save_anthropic_setup_token(token)
        success(f"Token saved to {path}")
        return True

    if method == AuthMethod.CLI_IMPORT:
        cli_token = load_claude_cli_token()
        if not cli_token or not cli_token.auth_token:
            error("No Claude Code CLI credentials found in ~/.claude/.credentials.json")
            return False
        path = save_anthropic_setup_token(cli_token.auth_token, cli_token.expires_at)
        success(f"Imported Claude Code credentials to {path}")
        return True

    if method == AuthMethod.API_KEY:
        key = text_input("Paste your Anthropic API key:", password=True)
        if key is None:
            return None
        if not key.strip():
            error("API key cannot be empty.")
            return False
        info(
            "API keys are resolved from environment variables (ANTHROPIC_API_KEY or CLAUDE_API_KEY).\n"
            "  Add this to your .env file:\n"
            f"  ANTHROPIC_API_KEY={key.strip()}"
        )
        return True

    if method == AuthMethod.ENV_VAR:
        val = os.getenv("ANTHROPIC_AUTH_TOKEN")
        if val and val.strip():
            success("ANTHROPIC_AUTH_TOKEN is set in the environment.")
            return True
        error("ANTHROPIC_AUTH_TOKEN is not set. Export it in your shell or .env file.")
        return False

    return False


def _execute_codex_auth(method: AuthMethod) -> bool:
    if method == AuthMethod.OAUTH_LOGIN:
        try:
            run_codex_login()
        except FileNotFoundError as exc:
            error(str(exc))
            return False
        except Exception as exc:
            error(f"codex login failed: {exc}")
            return False
        try:
            path = import_codex_cli_credentials()
            success(f"Imported OAuth credentials to {path}")
            return True
        except ValueError as exc:
            error(str(exc))
            return False

    if method == AuthMethod.CLI_IMPORT:
        try:
            path = import_codex_cli_credentials()
            success(f"Imported Codex CLI credentials to {path}")
            return True
        except ValueError as exc:
            error(str(exc))
            return False

    if method == AuthMethod.ENV_VAR:
        val = os.getenv("OPENAI_CODEX_ACCESS_TOKEN")
        if val and val.strip():
            success("OPENAI_CODEX_ACCESS_TOKEN is set in the environment.")
            return True
        error("OPENAI_CODEX_ACCESS_TOKEN is not set. Export it in your shell or .env file.")
        return False

    return False


def setup_flow() -> int:
    provider = _provider_menu()
    if provider is None:
        return _cancelled()

    auth_choices = [
        {"name": f"{am.label}  -  {am.description}", "value": am.method}
        for am in provider.auth_methods
    ]
    method = select_menu("Select auth method", auth_choices)
    if method is None:
        return _cancelled()

    if provider.id == "anthropic":
        ok = _execute_anthropic_auth(method)
    elif provider.id == "openai-codex":
        ok = _execute_codex_auth(method)
    else:
        error(f"Unknown provider: {provider.id}")
        return 1

    if ok is None:
        return _cancelled()
    if not ok:
        return 1

    should_set = confirm("Set this as your active provider?", default=True)
    if should_set is None:
        return _cancelled()
    if should_set:
        return _select_model_and_save(provider)

    return 0


# ── Select Flow ───────────────────────────────────────────────────────

def select_flow() -> int:
    # Probe all providers for working credentials.
    authenticated = []
    for provider in PROVIDERS:
        status = _probe_provider_auth(provider)
        if status["authenticated"]:
            authenticated.append(provider)

    if not authenticated:
        error("No providers have valid credentials. Run 'setup' first.")
        return 1

    if len(authenticated) == 1:
        provider = authenticated[0]
        info(f"Only one authenticated provider: {provider.label}")
    else:
        choices = [
            {"name": f"{p.label}  ({p.id})", "value": p}
            for p in authenticated
        ]
        provider = select_menu("Select provider", choices)
        if provider is None:
            return _cancelled()

    return _select_model_and_save(provider)


# ── Show Flow ─────────────────────────────────────────────────────────

def show_flow() -> int:
    config = load_llm_config()
    active_provider = config.provider if config else None
    active_model = config.model if config else None
    active_reasoning = config.reasoning_level if config else None
    config_path = config.path if config else None

    provider_statuses = [_probe_provider_auth(p) for p in PROVIDERS]

    status_table(
        active_provider=active_provider,
        active_model=active_model,
        active_reasoning=active_reasoning,
        config_path=config_path,
        provider_statuses=provider_statuses,
    )
    return 0


# ── Clear Flow ────────────────────────────────────────────────────────

def clear_flow() -> int:
    provider = _provider_menu()
    if provider is None:
        return _cancelled()

    should_clear = confirm(f"Remove stored credentials for {provider.label}?")
    if should_clear is None or not should_clear:
        info("Cancelled.")
        return 0

    if provider.id == "anthropic":
        removed = clear_persisted_anthropic_token()
    elif provider.id == "openai-codex":
        removed = clear_persisted_openai_codex_auth()
    else:
        error(f"Unknown provider: {provider.id}")
        return 1

    if removed:
        success(f"Removed credentials for {provider.label}.")
    else:
        info(f"No persisted credentials found for {provider.label}.")
    return 0
