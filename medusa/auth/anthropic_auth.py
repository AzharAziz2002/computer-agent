from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_DIR = REPO_ROOT / ".credentials"
ANTHROPIC_CREDENTIAL_FILE = CREDENTIALS_DIR / "anthropic.json"
CLAUDE_CREDENTIALS_RELATIVE_PATH = Path(".claude/.credentials.json")

# --- Anthropic OAuth refresh constants ---
# Sourced from OpenClaw's pi-ai OAuth module (anthropic.js).
# Used to refresh expired OAuth tokens (sk-ant-oat*) via the "shared write-back"
# approach: refresh the token, then write new access + refresh tokens back to the
# SAME credential file so both Medusa and Claude Code CLI stay in sync.
ANTHROPIC_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
ANTHROPIC_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


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


# ---------------------------------------------------------------------------
# OAuth token refresh  (shared write-back)
# ---------------------------------------------------------------------------

def _refresh_oauth_token(refresh_token: str) -> dict[str, Any] | None:
    """Exchange a single-use refresh token for a new access + refresh pair.

    Calls Anthropic's OAuth token endpoint with grant_type=refresh_token.
    Returns dict with ``access_token``, ``refresh_token``, ``expires_at`` (ms)
    on success, or ``None`` on any failure.

    IMPORTANT: Refresh tokens are **single-use**.  After a successful call the
    old refresh_token is permanently invalidated — the caller MUST persist the
    new refresh_token returned here.
    """
    body = json.dumps({
        "grant_type": "refresh_token",
        "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
        "refresh_token": refresh_token,
    }).encode("utf-8")

    # User-Agent must look like a real client — Cloudflare blocks the default
    # Python-urllib UA with a 1010 "browser signature ban".  We send the same
    # user-agent string that Claude CLI uses for API requests.
    req = urllib.request.Request(
        ANTHROPIC_TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "claude-cli/2.1.75",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None

    access_token = data.get("access_token")
    new_refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")

    if not access_token or not new_refresh or not isinstance(expires_in, (int, float)):
        return None

    # 5-minute safety margin — matches OpenClaw's expiry calculation:
    # Date.now() + expires_in * 1000 - 5 * 60 * 1000
    expires_at = int(time.time() * 1000) + int(expires_in * 1000) - 5 * 60 * 1000

    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "expires_at": expires_at,
    }


def _write_back_cli_credentials(credential_path: Path, refreshed: dict[str, Any]) -> bool:
    """Write refreshed tokens back to a Claude Code CLI credential file.

    Preserves all existing fields (scopes, subscriptionType, rateLimitTier,
    etc.) and only updates accessToken, refreshToken, expiresAt.  This is the
    "shared write-back" mechanism: after Medusa refreshes, Claude Code CLI
    picks up the new tokens on its next read.
    """
    try:
        raw = credential_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False

    oauth = payload.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return False

    # Only touch the three token-related fields; leave everything else intact.
    oauth["accessToken"] = refreshed["access_token"]
    oauth["refreshToken"] = refreshed["refresh_token"]
    oauth["expiresAt"] = refreshed["expires_at"]

    try:
        credential_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return False

    return True


def _coerce_host_path(raw_path: str) -> Path:
    if len(raw_path) >= 3 and raw_path[1:3] == ":\\":
        drive = raw_path[0].lower()
        suffix = raw_path[3:].replace("\\", "/")
        return Path(f"/mnt/{drive}/{suffix}")
    return Path(raw_path)


@lru_cache(maxsize=1)
def _resolve_wsl_home_unc() -> Path | None:
    """Get the default WSL distro's home as a Windows UNC path.

    Returns e.g. ``\\\\wsl.localhost\\Ubuntu\\home\\huzaifa`` when WSL is
    available, or ``None`` otherwise.  Result is cached for the process
    lifetime.
    """
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if not wsl:
        return None
    try:
        # Distro name — first non-empty line from `wsl -l -q`.
        distro_result = subprocess.run(
            [wsl, "-l", "-q"],
            capture_output=True, timeout=5,
        )
        raw = distro_result.stdout.decode("utf-16-le", errors="ignore")
        distro = next(
            (line for line in (l.strip("\r\n\x00 ") for l in raw.splitlines()) if line),
            None,
        )
        if not distro:
            return None

        # WSL $HOME (e.g. /home/huzaifa).
        home_result = subprocess.run(
            [wsl, "bash", "-c", "printenv HOME"],
            capture_output=True, text=True, timeout=5,
        )
        wsl_home = home_result.stdout.strip()
        if not wsl_home or not wsl_home.startswith("/"):
            return None

        return Path(f"\\\\wsl.localhost\\{distro}{wsl_home}")
    except (subprocess.TimeoutExpired, OSError):
        return None


@lru_cache(maxsize=8)
def _resolve_wsl_env(var_name: str) -> str | None:
    """Read an environment variable from the default WSL distro."""
    wsl = shutil.which("wsl") or shutil.which("wsl.exe")
    if not wsl:
        return None
    try:
        # Use printenv — avoids shell-escaping issues with $VAR from Windows.
        result = subprocess.run(
            [wsl, "bash", "-lic", f"printenv {var_name}"],
            capture_output=True, text=True, timeout=5,
        )
        value = result.stdout.strip()
        return value or None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _wsl_path_to_windows(wsl_path: str) -> Path | None:
    """Convert a WSL-internal path to a Windows-accessible path.

    Paths starting with ``/mnt/<drive>/`` are mapped to ``<DRIVE>:\\``.
    Other absolute paths are accessed via ``\\\\wsl.localhost\\<distro>\\``.
    """
    # /mnt/d/foo -> D:\foo  (drive letter at index 5, slash at index 6)
    if wsl_path.startswith("/mnt/") and len(wsl_path) >= 7 and wsl_path[5].isalpha() and wsl_path[6] == "/":
        drive_letter = wsl_path[5].upper()
        rest = wsl_path[7:].replace("/", "\\")
        return Path(f"{drive_letter}:\\{rest}")

    # Absolute WSL filesystem path — needs UNC via distro name.
    wsl_home_unc = _resolve_wsl_home_unc()
    if wsl_home_unc and wsl_path.startswith("/"):
        # Extract \\wsl.localhost\<distro> prefix from the home UNC.
        # e.g. \\wsl.localhost\Ubuntu\home\huzaifa -> \\wsl.localhost\Ubuntu
        parts = str(wsl_home_unc).split("\\")
        # ['', '', 'wsl.localhost', 'Ubuntu', 'home', 'huzaifa']
        if len(parts) >= 4:
            unc_root = "\\".join(parts[:4])  # \\wsl.localhost\Ubuntu
            return Path(unc_root + wsl_path.replace("/", "\\"))
    return None


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

    # WSL filesystem via UNC path (\\wsl.localhost\<distro>\home\<user>).
    # Needed when Windows Python must read files written by WSL tools.
    wsl_home_unc = _resolve_wsl_home_unc()
    if wsl_home_unc:
        candidates.append(wsl_home_unc)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _resolve_claude_credential_paths() -> list[Path]:
    paths: list[Path] = []

    # --- CLAUDE_CONFIG_DIR override ---
    # When set, Claude Code stores config (including .credentials.json) in this
    # directory instead of ~/.claude/.  The credentials file sits directly inside
    # the config dir (no .claude/ subdirectory).
    config_dir = _clean_secret(os.getenv("CLAUDE_CONFIG_DIR"))
    if config_dir:
        paths.append(_coerce_host_path(config_dir) / ".credentials.json")

    # --- Well-known non-default config locations ---
    # Claude Code desktop/CLI may write credentials to a separate data directory
    # (e.g. D:\Software\...\claude_code).  Include both WSL and Windows forms so
    # resolution works regardless of which Python interpreter is running.
    for extra in (
        Path("/mnt/d/Software/SoftwareFiles/claude_code"),       # WSL Python
        Path(r"D:\Software\SoftwareFiles\claude_code"),           # Windows Python
    ):
        cred = extra / ".credentials.json"
        if cred not in paths:
            paths.append(cred)

    # --- Default: ~/.claude/.credentials.json under each home candidate ---
    paths.extend(home_dir / CLAUDE_CREDENTIALS_RELATIVE_PATH for home_dir in _resolve_home_candidates())

    return paths


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
        # --- Auto-refresh for persisted OAuth tokens ---
        # If the token is expired but we have a refresh_token stored alongside
        # it, attempt to refresh.  On success, update the persisted file with
        # both the new access and refresh tokens.
        refresh_token = _clean_secret(payload.get("refresh_token"))
        if refresh_token:
            refreshed = _refresh_oauth_token(refresh_token)
            if refreshed:
                # Write new tokens back to .credentials/anthropic.json
                payload["token"] = refreshed["access_token"]
                payload["refresh_token"] = refreshed["refresh_token"]
                payload["expires_at"] = refreshed["expires_at"]
                payload["updated_at"] = int(time.time() * 1000)
                try:
                    ANTHROPIC_CREDENTIAL_FILE.write_text(
                        json.dumps(payload, indent=2) + "\n",
                        encoding="utf-8",
                    )
                except OSError:
                    pass  # Token is still usable even if persist fails
                return ResolvedAnthropicAuth(
                    auth_token=refreshed["access_token"],
                    source="repo persisted token (refreshed)",
                    expires_at=refreshed["expires_at"],
                    credential_path=str(ANTHROPIC_CREDENTIAL_FILE),
                )
        # Expired and no refresh token (or refresh failed) — skip
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
            # --- Shared write-back refresh ---
            # Access token is expired.  If a refresh token is available, use it
            # to obtain fresh tokens and write them BACK to this same credential
            # file.  This keeps Claude Code CLI in sync — it will read the new
            # tokens on its next startup/refresh cycle.
            refresh_token = _clean_secret(oauth_payload.get("refreshToken"))
            if refresh_token:
                refreshed = _refresh_oauth_token(refresh_token)
                if refreshed and _write_back_cli_credentials(candidate, refreshed):
                    return ResolvedAnthropicAuth(
                        auth_token=refreshed["access_token"],
                        source="Claude Code oauth (refreshed)",
                        expires_at=refreshed["expires_at"],
                        credential_path=str(candidate),
                    )
            # Refresh failed or no refresh token — try next candidate file
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


def save_anthropic_setup_token(
    token: str,
    expires_at: int | None = None,
    refresh_token: str | None = None,
) -> Path:
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
    # Store refresh_token alongside the access token so auto-refresh can work
    # for persisted tokens (not just CLI-imported ones).
    if refresh_token:
        payload["refresh_token"] = _normalize_token(refresh_token)

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
