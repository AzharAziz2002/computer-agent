"""MCP server lifecycle manager.

Spawns MCP server subprocesses via the Python MCP SDK, maintains persistent
``ClientSession`` connections, and exposes a merged tool list that can be
injected into the agent's tool schema.

Connections are persistent — they stay alive until the user explicitly
disconnects or the application shuts down.
"""

from __future__ import annotations

import json
import os
import re
import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from medusa.plugins.catalog import ConnectorDef, get_connector
from medusa.plugins.credentials import CredentialStore, CRED_DIR


@dataclass
class MCPConnection:
    """A running MCP server connection."""
    connector_id: str
    session: ClientSession
    tools: list[dict] = field(default_factory=list)
    _stack: AsyncExitStack = field(default_factory=AsyncExitStack)


class MCPManager:
    """Manages persistent MCP server connections.

    Typical lifecycle::

        manager = MCPManager()
        tools = await manager.connect("github")     # spawns subprocess
        result = await manager.call_tool("github", "list_repos", {})
        await manager.disconnect("github")           # kills subprocess
        await manager.shutdown()                      # disconnect all
    """

    def __init__(self):
        self._connections: dict[str, MCPConnection] = {}
        self._credentials = CredentialStore()

    # ── Pre-launch helpers ────────────────────────────────────────────

    @staticmethod
    def _resolve_command(args: list[str], env: dict[str, str]) -> list[str]:
        """Replace ``$VAR_NAME`` references in command args with env values."""
        def _replace(match: re.Match) -> str:
            return env.get(match.group(1), match.group(0))
        return [re.sub(r'\$([A-Z_][A-Z0-9_]*)', _replace, a) for a in args]

    @staticmethod
    def _setup_gmail(env: dict[str, str]) -> None:
        """Create gcp-oauth.keys.json from GOOGLE_CLIENT_ID/SECRET env vars."""
        client_id = env.get("GOOGLE_CLIENT_ID", "")
        client_secret = env.get("GOOGLE_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise ValueError(
                "Gmail requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env"
            )
        oauth_path = CRED_DIR / "gmail-oauth.keys.json"
        CRED_DIR.mkdir(parents=True, exist_ok=True)
        oauth_path.write_text(json.dumps({
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost"],
            }
        }, indent=2))
        env["GMAIL_OAUTH_PATH"] = str(oauth_path)

    @staticmethod
    def _validate_spotify(env: dict[str, str]) -> None:
        """Check that SPOTIFY_MCP_DIR is set and the build exists."""
        mcp_dir = env.get("SPOTIFY_MCP_DIR", "")
        if not mcp_dir:
            raise ValueError("Spotify requires SPOTIFY_MCP_DIR in .env (path to cloned repo)")
        entry = Path(mcp_dir) / "build" / "index.js"
        if not entry.exists():
            raise ValueError(
                f"Spotify MCP server not built: {entry} not found. "
                f"Run 'npm install && npm run build' in {mcp_dir}"
            )

    # ── Connect / disconnect ─────────────────────────────────────────

    async def connect(self, connector_id: str) -> list[dict]:
        """Spawn the MCP server for *connector_id*, return its tool list.

        If already connected, returns the cached tool list without respawning.

        Raises ``ValueError`` when the connector is not in the catalog or
        has no stored credentials.
        """
        if connector_id in self._connections:
            return self._connections[connector_id].tools

        connector_def = get_connector(connector_id)
        if connector_def is None:
            raise ValueError(f"Connector '{connector_id}' is not in the catalog")

        creds = self._credentials.get(connector_id)
        if connector_def.auth_type != "none" and not creds:
            raise ValueError(
                f"Connector '{connector_id}' requires credentials but none are stored"
            )

        # Build subprocess environment — inherit current env + inject credentials.
        env = dict(os.environ)
        if creds:
            for cred_field, env_var in connector_def.env_mapping.items():
                value = creds.get(cred_field)
                if value:
                    env[env_var] = value

        # Connector-specific pre-launch setup
        if connector_id == "gmail":
            self._setup_gmail(env)
        elif connector_id == "spotify":
            self._validate_spotify(env)

        # Resolve $ENV_VAR references in command args
        resolved_args = self._resolve_command(connector_def.mcp_command[1:], env)

        server_params = StdioServerParameters(
            command=connector_def.mcp_command[0],
            args=resolved_args,
            env=env,
        )

        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(
                stdio_client(server=server_params)
            )
            session = await stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()

            tools_response = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": (
                        t.inputSchema
                        if hasattr(t, "inputSchema")
                        else {"type": "object", "properties": {}}
                    ),
                }
                for t in tools_response.tools
            ]
        except Exception:
            await stack.aclose()
            raise

        conn = MCPConnection(
            connector_id=connector_id,
            session=session,
            tools=tools,
            _stack=stack,
        )
        self._connections[connector_id] = conn
        return tools

    async def disconnect(self, connector_id: str) -> None:
        """Stop the MCP server subprocess for *connector_id*."""
        conn = self._connections.pop(connector_id, None)
        if conn is not None:
            await conn._stack.aclose()

    # ── Tool invocation ──────────────────────────────────────────────

    async def call_tool(
        self, connector_id: str, tool_name: str, arguments: dict
    ) -> str:
        """Call *tool_name* on a connected MCP server and return the text result."""
        conn = self._connections.get(connector_id)
        if conn is None:
            raise ValueError(f"Connector '{connector_id}' is not connected")

        result = await conn.session.call_tool(tool_name, arguments)
        texts = [
            block.text for block in result.content if hasattr(block, "text")
        ]
        return "\n".join(texts) if texts else ""

    # ── Tool schema helpers ──────────────────────────────────────────

    def get_all_tools(self) -> list[dict]:
        """Return a merged tool list from every connected MCP server.

        Tool names are prefixed with ``{connector_id}__`` to avoid collisions
        with built-in tools or tools from other connectors.
        """
        all_tools: list[dict] = []
        for conn_id, conn in self._connections.items():
            for tool in conn.tools:
                all_tools.append({
                    "name": f"{conn_id}__{tool['name']}",
                    "description": f"[{conn_id}] {tool['description']}",
                    "parameters": tool["inputSchema"],
                    "_connector_id": conn_id,
                    "_original_name": tool["name"],
                })
        return all_tools

    # ── Status helpers ───────────────────────────────────────────────

    def is_connected(self, connector_id: str) -> bool:
        return connector_id in self._connections

    def list_connected(self) -> list[str]:
        return list(self._connections.keys())

    # ── Shutdown ─────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Disconnect all MCP servers (called on application exit)."""
        for conn_id in list(self._connections.keys()):
            try:
                await self.disconnect(conn_id)
            except Exception:
                pass
