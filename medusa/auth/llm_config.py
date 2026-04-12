from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_DIR = REPO_ROOT / ".credentials"
LLM_CONFIG_FILE = CREDENTIALS_DIR / "llm_config.json"


@dataclass(slots=True)
class ResolvedLLMConfig:
    provider: str = "anthropic"
    model: str | None = None
    reasoning_level: str | None = None
    source: str | None = None
    path: str | None = None


def load_llm_config() -> ResolvedLLMConfig | None:
    try:
        payload = json.loads(LLM_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict):
        return None

    provider = payload.get("provider")
    model = payload.get("model")
    if not isinstance(provider, str) or not provider.strip():
        return None

    normalized_model = model.strip() if isinstance(model, str) and model.strip() else None
    reasoning_level_raw = payload.get("reasoning_level")
    reasoning_level = (
        reasoning_level_raw.strip()
        if isinstance(reasoning_level_raw, str) and reasoning_level_raw.strip()
        else None
    )
    return ResolvedLLMConfig(
        provider=provider.strip(),
        model=normalized_model,
        reasoning_level=reasoning_level,
        source="repo llm config",
        path=str(LLM_CONFIG_FILE),
    )


def save_llm_config(
    provider: str,
    model: str | None = None,
    reasoning_level: str | None = None,
) -> Path:
    normalized_provider = provider.strip()
    if not normalized_provider:
        raise ValueError("Provider cannot be empty.")

    normalized_model = model.strip() if isinstance(model, str) and model.strip() else None
    normalized_level = (
        reasoning_level.strip()
        if isinstance(reasoning_level, str) and reasoning_level.strip()
        else None
    )
    payload: dict[str, Any] = {"provider": normalized_provider}
    if normalized_model:
        payload["model"] = normalized_model
    if normalized_level:
        payload["reasoning_level"] = normalized_level

    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    LLM_CONFIG_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return LLM_CONFIG_FILE
