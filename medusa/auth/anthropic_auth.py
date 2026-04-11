from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_DIR = REPO_ROOT / ".credentials"
ANTHROPIC_CREDENTIAL_FILE = CREDENTIALS_DIR / "anthropic.json"
CLAUDE_CREDENTIALS_RELATIVE_PATH = Path(".claude/.credentials.json")


@dataclass(slots=True)
class ResolvedAnthropicAuth:
    api_key: str | None = None
    auth_token: str | None = None
    source: str | None = None
    expires_at: int | None = None
    credential_path: str | None = None


def _clean_secret(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _normalize_token(value: Any) -> str | None:
    cleaned = _clean_secret(value)
    if not cleaned:
        return None
    # Setup tokens are often pasted with line breaks or spaces.
    return "".join(cleaned.split())


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _coerce_host_path(raw_path: str) -> Path:
    if len(raw_path) >= 3 and raw_path[1:3] == ":\\":
        drive = raw_path[0].lower()
        suffix = raw_path[3:].replace("\\", "/")
        return Path(f"/mnt/{drive}/{suffix}")
    return Path(raw_path)


def _resolve_home_candidates() -> list[Path]:
    candidates: list[Path] = []

    # Unix/WSL home (HOME env var — set in Linux and WSL environments)
    unix_home = _clean_secret(os.getenv("HOME"))
    if unix_home:
        candidates.append(Path(unix_home))

    # Windows home paths
    for env_name in ("USERPROFILE",):
        env_value = _clean_secret(os.getenv(env_name))
        if env_value:
            candidates.append(_coerce_host_path(env_value))

    home = Path.home()
    candidates.append(home)

    username = _clean_secret(os.getenv("USERNAME")) or _clean_secret(os.getenv("USER")) or home.name

    # WSL root user (common default WSL user)
    candidates.append(Path("/root"))

    # WSL /home/<username>
    if username:
        candidates.append(Path(f"/home/{username}"))

    # Windows drives mounted in WSL
    for drive in ("c", "d"):
        candidates.append(Path(f"/mnt/{drive}/Users/{username}"))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _resolve_claude_credential_paths() -> list[Path]:
    return [home_dir / CLAUDE_CREDENTIALS_RELATIVE_PATH for home_dir in _resolve_home_candidates()]


def _resolve_api_key(explicit_api_key: str | None = None) -> tuple[str | None, str | None]:
    for source_name, candidate in (
        ("explicit api_key", explicit_api_key),
        ("CLAUDE_API_KEY", os.getenv("CLAUDE_API_KEY")),
        ("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY")),
    ):
        cleaned = _clean_secret(candidate)
        if cleaned:
            return cleaned, source_name
    return None, None


def load_persisted_anthropic_token() -> ResolvedAnthropicAuth | None:
    payload = _load_json_file(ANTHROPIC_CREDENTIAL_FILE)
    if not payload:
        return None

    token = _normalize_token(payload.get("token"))
    if not token:
        return None

    expires_at_raw = payload.get("expires_at")
    expires_at = expires_at_raw if isinstance(expires_at_raw, int) else None
    now_ms = int(time.time() * 1000)
    if expires_at is not None and expires_at <= now_ms:
        return None

    return ResolvedAnthropicAuth(
        auth_token=token,
        source="repo persisted token",
        expires_at=expires_at,
        credential_path=str(ANTHROPIC_CREDENTIAL_FILE),
    )


def load_claude_cli_token() -> ResolvedAnthropicAuth | None:
    now_ms = int(time.time() * 1000)

    for candidate in _resolve_claude_credential_paths():
        payload = _load_json_file(candidate)
        if not payload:
            continue

        oauth_payload = payload.get("claudeAiOauth")
        if not isinstance(oauth_payload, dict):
            continue

        access_token = _normalize_token(oauth_payload.get("accessToken"))
        if not access_token:
            continue

        expires_at_raw = oauth_payload.get("expiresAt")
        expires_at = expires_at_raw if isinstance(expires_at_raw, int) else None
        if expires_at is not None and expires_at <= now_ms:
            continue

        refresh_token = _clean_secret(oauth_payload.get("refreshToken"))
        return ResolvedAnthropicAuth(
            auth_token=access_token,
            source="Claude Code oauth" if refresh_token else "Claude Code token",
            expires_at=expires_at,
            credential_path=str(candidate),
        )

    return None


def resolve_anthropic_auth(
    explicit_auth_token: str | None = None,
    explicit_api_key: str | None = None,
) -> ResolvedAnthropicAuth:
    api_key, api_key_source = _resolve_api_key(explicit_api_key)

    explicit_token = _normalize_token(explicit_auth_token)
    if explicit_token:
        return ResolvedAnthropicAuth(
            api_key=api_key,
            auth_token=explicit_token,
            source="explicit auth_token",
        )

    env_token = _normalize_token(os.getenv("ANTHROPIC_AUTH_TOKEN"))
    if env_token:
        return ResolvedAnthropicAuth(
            api_key=api_key,
            auth_token=env_token,
            source="ANTHROPIC_AUTH_TOKEN",
        )

    persisted = load_persisted_anthropic_token()
    if persisted:
        persisted.api_key = api_key
        return persisted

    claude_cli = load_claude_cli_token()
    if claude_cli:
        claude_cli.api_key = api_key
        return claude_cli

    return ResolvedAnthropicAuth(
        api_key=api_key,
        source=api_key_source,
    )


def save_anthropic_setup_token(token: str, expires_at: int | None = None) -> Path:
    normalized = _normalize_token(token)
    if not normalized:
        raise ValueError("Anthropic setup token cannot be empty.")

    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "provider": "anthropic",
        "type": "token",
        "token": normalized,
        "source": "setup-token",
        "updated_at": int(time.time() * 1000),
    }
    if expires_at is not None:
        payload["expires_at"] = expires_at

    ANTHROPIC_CREDENTIAL_FILE.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return ANTHROPIC_CREDENTIAL_FILE


def clear_persisted_anthropic_token() -> bool:
    try:
        ANTHROPIC_CREDENTIAL_FILE.unlink()
    except FileNotFoundError:
        return False
    return True
