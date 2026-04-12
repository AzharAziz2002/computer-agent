from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from medusa.auth.anthropic_auth import (
    _clean_secret,
    _coerce_host_path,
    _resolve_home_candidates,
    _resolve_wsl_env,
    _resolve_wsl_home_unc,
    _wsl_path_to_windows,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_DIR = REPO_ROOT / ".credentials"
OPENAI_CODEX_CREDENTIAL_FILE = CREDENTIALS_DIR / "openai_codex.json"
CODEX_CLI_AUTH_RELATIVE_PATH = Path(".codex/auth.json")
DEFAULT_OPENAI_CODEX_MODEL = "gpt-5.4"


@dataclass(slots=True)
class ResolvedOpenAICodexAuth:
    access_token: str | None = None
    refresh_token: str | None = None
    account_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    source: str | None = None
    expires_at: int | None = None
    credential_path: str | None = None


def _normalize_secret(value: Any) -> str | None:
    cleaned = _clean_secret(value)
    return "".join(cleaned.split()) if cleaned else None


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        import base64

        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        parsed = json.loads(payload)
    except (ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _resolve_codex_access_token_expiry(access_token: str) -> int | None:
    payload = _decode_jwt_payload(access_token)
    exp = payload.get("exp") if isinstance(payload, dict) else None
    if isinstance(exp, int) and exp > 0:
        return exp * 1000
    if isinstance(exp, str) and exp.isdigit():
        return int(exp) * 1000
    return None


def _resolve_codex_identity(access_token: str) -> tuple[str | None, str | None]:
    payload = _decode_jwt_payload(access_token)
    if not payload:
        return None, None

    profile = payload.get("https://api.openai.com/profile")
    if isinstance(profile, dict):
        email = _clean_secret(profile.get("email"))
        if email:
            return email, email

    auth = payload.get("https://api.openai.com/auth")
    stable_id = None
    if isinstance(auth, dict):
        stable_id = (
            _clean_secret(auth.get("chatgpt_account_user_id"))
            or _clean_secret(auth.get("chatgpt_user_id"))
            or _clean_secret(auth.get("user_id"))
        )
    if not stable_id:
        stable_id = _clean_secret(payload.get("sub"))
    if stable_id:
        return None, f"id-{stable_id}"
    return None, None


def _candidate_codex_homes() -> list[Path]:
    candidates: list[Path] = []

    # Native CODEX_HOME (set in the current process environment).
    configured = _clean_secret(os.getenv("CODEX_HOME"))
    if configured:
        expanded = configured
        if configured == "~":
            expanded = str(Path.home())
        elif configured.startswith("~/"):
            expanded = str(Path.home() / configured[2:])
        candidates.append(_coerce_host_path(expanded))

    # WSL CODEX_HOME (set inside the default WSL distro — e.g. via .bashrc).
    wsl_codex_home = _resolve_wsl_env("CODEX_HOME")
    if wsl_codex_home:
        win_path = _wsl_path_to_windows(wsl_codex_home)
        if win_path:
            candidates.append(win_path)

    for home_dir in _resolve_home_candidates():
        candidates.append(home_dir / ".codex")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _resolve_codex_cli_auth_paths() -> list[Path]:
    return [candidate / "auth.json" for candidate in _candidate_codex_homes()]


def _get_file_mtime_ms(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        return None


ONE_HOUR_MS = 3_600_000


def _resolve_from_payload(
    payload: dict[str, Any],
    *,
    source: str,
    credential_path: Path,
    credential_mtime_ms: int | None = None,
) -> ResolvedOpenAICodexAuth | None:
    access_token = None
    refresh_token = None
    account_id = None
    email = None
    display_name = None

    if payload.get("auth_mode") == "chatgpt":
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            return None
        access_token = _normalize_secret(tokens.get("access_token"))
        refresh_token = _normalize_secret(tokens.get("refresh_token"))
        account_id = _clean_secret(tokens.get("account_id"))
    else:
        access_token = _normalize_secret(payload.get("access_token"))
        refresh_token = _normalize_secret(payload.get("refresh_token"))
        account_id = _clean_secret(payload.get("account_id"))
        email = _clean_secret(payload.get("email"))
        display_name = _clean_secret(payload.get("display_name"))

    if not access_token:
        return None

    expires_at = _resolve_codex_access_token_expiry(access_token)
    # Mtime-based expiry fallback (matches OpenClaw's readCodexCliCredentials)
    if expires_at is None:
        base_ms = credential_mtime_ms if credential_mtime_ms is not None else int(time.time() * 1000)
        expires_at = base_ms + ONE_HOUR_MS

    now_ms = int(time.time() * 1000)
    if expires_at <= now_ms:
        return None

    jwt_email, jwt_display_name = _resolve_codex_identity(access_token)
    return ResolvedOpenAICodexAuth(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=account_id,
        email=email or jwt_email,
        display_name=display_name or jwt_display_name,
        source=source,
        expires_at=expires_at,
        credential_path=str(credential_path),
    )


def load_persisted_openai_codex_auth() -> ResolvedOpenAICodexAuth | None:
    payload = _load_json_file(OPENAI_CODEX_CREDENTIAL_FILE)
    if not payload:
        return None
    return _resolve_from_payload(
        payload,
        source="repo persisted oauth",
        credential_path=OPENAI_CODEX_CREDENTIAL_FILE,
        credential_mtime_ms=_get_file_mtime_ms(OPENAI_CODEX_CREDENTIAL_FILE),
    )


def load_codex_cli_auth() -> ResolvedOpenAICodexAuth | None:
    for candidate in _resolve_codex_cli_auth_paths():
        payload = _load_json_file(candidate)
        if not payload:
            continue
        resolved = _resolve_from_payload(
            payload,
            source="Codex CLI chatgpt oauth",
            credential_path=candidate,
            credential_mtime_ms=_get_file_mtime_ms(candidate),
        )
        if resolved:
            return resolved
    return None


def _try_soft_refresh() -> ResolvedOpenAICodexAuth | None:
    """Re-read from Codex CLI auth.json in case it was refreshed externally."""
    cli_auth = load_codex_cli_auth()
    if not cli_auth or not cli_auth.access_token:
        return None
    # Re-persist the fresh token locally so we don't hit the CLI file every time.
    save_openai_codex_oauth(
        access_token=cli_auth.access_token,
        refresh_token=cli_auth.refresh_token,
        account_id=cli_auth.account_id,
        email=cli_auth.email,
        display_name=cli_auth.display_name,
        source="soft-refresh-from-codex-cli",
    )
    return cli_auth


def resolve_openai_codex_auth(
    explicit_access_token: str | None = None,
) -> ResolvedOpenAICodexAuth:
    explicit_token = _normalize_secret(explicit_access_token)
    if explicit_token:
        expires_at = _resolve_codex_access_token_expiry(explicit_token)
        email, display_name = _resolve_codex_identity(explicit_token)
        return ResolvedOpenAICodexAuth(
            access_token=explicit_token,
            email=email,
            display_name=display_name,
            expires_at=expires_at,
            source="explicit access_token",
        )

    env_token = _normalize_secret(os.getenv("OPENAI_CODEX_ACCESS_TOKEN"))
    if env_token:
        expires_at = _resolve_codex_access_token_expiry(env_token)
        email, display_name = _resolve_codex_identity(env_token)
        return ResolvedOpenAICodexAuth(
            access_token=env_token,
            email=email,
            display_name=display_name,
            expires_at=expires_at,
            source="OPENAI_CODEX_ACCESS_TOKEN",
        )

    persisted = load_persisted_openai_codex_auth()
    if persisted:
        return persisted

    # Persisted token expired or missing — try soft refresh from Codex CLI.
    refreshed = _try_soft_refresh()
    if refreshed:
        return refreshed

    cli_auth = load_codex_cli_auth()
    if cli_auth:
        return cli_auth

    return ResolvedOpenAICodexAuth(source=None)


def save_openai_codex_oauth(
    *,
    access_token: str,
    refresh_token: str | None = None,
    account_id: str | None = None,
    email: str | None = None,
    display_name: str | None = None,
    source: str = "chatgpt-oauth",
) -> Path:
    normalized_access = _normalize_secret(access_token)
    if not normalized_access:
        raise ValueError("OpenAI Codex access token cannot be empty.")

    normalized_refresh = _normalize_secret(refresh_token)
    expires_at = _resolve_codex_access_token_expiry(normalized_access)
    jwt_email, jwt_display_name = _resolve_codex_identity(normalized_access)

    payload: dict[str, Any] = {
        "provider": "openai-codex",
        "type": "oauth",
        "access_token": normalized_access,
        "source": source,
        "updated_at": int(time.time() * 1000),
    }
    if normalized_refresh:
        payload["refresh_token"] = normalized_refresh
    if account_id:
        payload["account_id"] = account_id
    if email or jwt_email:
        payload["email"] = email or jwt_email
    if display_name or jwt_display_name:
        payload["display_name"] = display_name or jwt_display_name
    if expires_at is not None:
        payload["expires_at"] = expires_at

    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    OPENAI_CODEX_CREDENTIAL_FILE.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return OPENAI_CODEX_CREDENTIAL_FILE


def import_codex_cli_credentials() -> Path:
    resolved = load_codex_cli_auth()
    if not resolved or not resolved.access_token:
        raise ValueError("No valid Codex CLI credentials were found.")

    return save_openai_codex_oauth(
        access_token=resolved.access_token,
        refresh_token=resolved.refresh_token,
        account_id=resolved.account_id,
        email=resolved.email,
        display_name=resolved.display_name,
        source="codex-cli-import",
    )


def clear_persisted_openai_codex_auth() -> bool:
    try:
        OPENAI_CODEX_CREDENTIAL_FILE.unlink()
    except FileNotFoundError:
        return False
    return True


def resolve_codex_login_command() -> list[str]:
    codex_executable = shutil.which("codex")
    if codex_executable:
        return [codex_executable, "login"]

    # Codex CLI might be installed inside WSL (e.g. via nvm).
    # Use a login shell so nvm/fnm/etc. are sourced.
    wsl_executable = shutil.which("wsl") or shutil.which("wsl.exe")
    if wsl_executable:
        return [wsl_executable, "bash", "-lic", "codex login"]

    raise FileNotFoundError(
        "codex CLI was not found on PATH (checked native and WSL). "
        "Install it first, or use 'Import from Codex CLI' if credentials already exist."
    )


def run_codex_login() -> None:
    command = resolve_codex_login_command()
    subprocess.run(command, check=True)
