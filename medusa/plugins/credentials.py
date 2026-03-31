"""Encrypted credential storage for MCP connectors.

Security layers:
  1. Master key lives in the OS credential manager (Windows Credential Manager
     on Windows, Keychain on macOS) via the ``keyring`` library — never on disk.
  2. All connector credentials are serialized to JSON, encrypted with Fernet
     (AES-128-CBC + HMAC-SHA256), and written to ``.credentials/connectors.enc``.
  3. The ``.credentials/`` directory is in ``.gitignore``.
  4. Credentials are decrypted only when needed and passed to MCP subprocesses
     as environment variables — never logged.
"""

import json
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken

SERVICE_NAME = "medusa-connectors"
KEY_NAME = "master-key"
CRED_DIR = Path(__file__).parent.parent.parent / ".credentials"
CRED_FILE = CRED_DIR / "connectors.enc"


class CredentialStore:
    """Encrypted credential storage backed by the OS keyring for the master key."""

    def __init__(self):
        self._fernet = Fernet(self._get_or_create_master_key())

    # ── Master key management ────────────────────────────────────────

    @staticmethod
    def _get_or_create_master_key() -> bytes:
        """Retrieve the Fernet master key from the OS keyring, creating one if absent."""
        stored = keyring.get_password(SERVICE_NAME, KEY_NAME)
        if stored is None:
            stored = Fernet.generate_key().decode()
            keyring.set_password(SERVICE_NAME, KEY_NAME, stored)
        return stored.encode()

    # ── Low-level I/O ────────────────────────────────────────────────

    def _load(self) -> dict:
        if not CRED_FILE.exists():
            return {}
        try:
            encrypted = CRED_FILE.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted)
        except (InvalidToken, json.JSONDecodeError):
            # Corrupted or re-keyed — start fresh rather than crash
            return {}

    def _save(self, data: dict) -> None:
        CRED_DIR.mkdir(parents=True, exist_ok=True)
        encrypted = self._fernet.encrypt(json.dumps(data).encode())
        CRED_FILE.write_bytes(encrypted)

    # ── Public API ───────────────────────────────────────────────────

    def get(self, connector_id: str) -> dict | None:
        """Return stored credentials for *connector_id*, or ``None``."""
        return self._load().get(connector_id)

    def set(self, connector_id: str, credentials: dict) -> None:
        """Store (overwrite) credentials for *connector_id*."""
        data = self._load()
        data[connector_id] = credentials
        self._save(data)

    def delete(self, connector_id: str) -> None:
        """Remove credentials for *connector_id* (no-op if absent)."""
        data = self._load()
        if data.pop(connector_id, None) is not None:
            self._save(data)

    def list_connected(self) -> list[str]:
        """Return IDs of connectors that have stored credentials."""
        return list(self._load().keys())
