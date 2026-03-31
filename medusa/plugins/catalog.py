"""Static registry of supported MCP connectors.

Each ConnectorDef maps a frontend connector ID to its auth requirements
and MCP server launch command. Connectors are registered into CATALOG
as they are wired up — the architecture is ready, entries are added later.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConnectorDef:
    """Definition of a single connector (no credentials stored here)."""

    id: str                           # matches frontend Connector.id  (e.g. "github")
    name: str                         # human-readable name
    auth_type: str                    # "oauth" | "api_key" | "none"
    mcp_command: list[str]            # subprocess command, e.g. ["npx", "@mcp/server-github"]
    env_mapping: dict[str, str] = field(default_factory=dict)
    # credential field name → env var injected into MCP subprocess
    # e.g. {"api_key": "GITHUB_TOKEN"}

    # ── OAuth fields (only when auth_type == "oauth") ────────────────
    oauth_authorize_url: str = ""
    oauth_token_url: str = ""
    oauth_scopes: list[str] = field(default_factory=list)
    oauth_client_id_env: str = ""     # .env var holding client_id
    oauth_client_secret_env: str = "" # .env var holding client_secret

    # ── API-key fields ───────────────────────────────────────────────
    api_key_label: str = ""           # display label, e.g. "Personal Access Token"


# ── Global catalog ───────────────────────────────────────────────────
# Entries are added per-connector as they are implemented.
# Example (uncomment when GitHub connector is ready):
#
# CATALOG["github"] = ConnectorDef(
#     id="github",
#     name="GitHub",
#     auth_type="api_key",
#     mcp_command=["npx", "-y", "@modelcontextprotocol/server-github"],
#     env_mapping={"api_key": "GITHUB_PERSONAL_ACCESS_TOKEN"},
#     api_key_label="Personal Access Token",
# )

CATALOG: dict[str, ConnectorDef] = {}

# ── Gmail ─────────────────────────────────────────────────────────────
# MCP server: @gongrzhe/server-gmail-autoauth-mcp
# Auth: server auto-opens browser for Google OAuth on first run.
# Requires in .env:
#   GOOGLE_CLIENT_ID=…apps.googleusercontent.com
#   GOOGLE_CLIENT_SECRET=…
# The manager creates .credentials/gmail-oauth.keys.json automatically.

CATALOG["gmail"] = ConnectorDef(
    id="gmail",
    name="Gmail",
    auth_type="none",
    mcp_command=["npx", "-y", "@gongrzhe/server-gmail-autoauth-mcp"],
)

# ── Spotify ───────────────────────────────────────────────────────────
# MCP server: marcelmarais/spotify-mcp-server (git clone, not on npm)
# Auth: user must run `npm run auth` once in the cloned repo.
# Requires in .env:
#   SPOTIFY_MCP_DIR=D:/path/to/spotify-mcp-server
# The repo must be cloned and built: npm install && npm run build

CATALOG["spotify"] = ConnectorDef(
    id="spotify",
    name="Spotify",
    auth_type="none",
    mcp_command=["node", "$SPOTIFY_MCP_DIR/build/index.js"],
)


def get_connector(connector_id: str) -> ConnectorDef | None:
    """Look up a connector definition by ID."""
    return CATALOG.get(connector_id)


def list_connectors() -> list[ConnectorDef]:
    """Return all registered connector definitions."""
    return list(CATALOG.values())
