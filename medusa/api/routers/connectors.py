"""REST API for managing MCP connectors.

Endpoints
---------
GET    /api/connectors                  — list all connectors with status
POST   /api/connectors/{id}/connect     — initiate connection (OAuth or API key)
DELETE /api/connectors/{id}             — disconnect and remove credentials
GET    /api/connectors/{id}/tools       — list tools from a connected MCP server
"""

from __future__ import annotations

import os
import urllib.parse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from medusa.plugins.catalog import ConnectorDef, get_connector, list_connectors
from medusa.plugins.credentials import CredentialStore
from medusa.plugins.manager import MCPManager
from medusa.plugins.oauth import OAuthCallbackServer

router = APIRouter(prefix="/api/connectors", tags=["connectors"])

# Singleton instances — injected by app.py at startup.
mcp_manager: MCPManager | None = None
cred_store: CredentialStore | None = None

# Active OAuth flows keyed by connector_id.
_pending_oauth: dict[str, OAuthCallbackServer] = {}


# ── Request / response models ───────────────────────────────────────

class ConnectRequest(BaseModel):
    api_key: str | None = None


class ConnectorStatus(BaseModel):
    id: str
    name: str
    auth_type: str
    connected: bool
    tools: list[dict] = []


class ConnectResponse(BaseModel):
    connected: bool = False
    auth_url: str | None = None
    tools: list[dict] = []


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/", response_model=list[ConnectorStatus])
async def list_all_connectors():
    """Return every catalog entry with its current connection status."""
    results: list[ConnectorStatus] = []
    for cdef in list_connectors():
        connected = mcp_manager.is_connected(cdef.id) if mcp_manager else False
        tools = []
        if connected and mcp_manager:
            conn = mcp_manager._connections.get(cdef.id)
            if conn:
                tools = conn.tools
        results.append(ConnectorStatus(
            id=cdef.id,
            name=cdef.name,
            auth_type=cdef.auth_type,
            connected=connected,
            tools=tools,
        ))
    return results


@router.post("/{connector_id}/connect", response_model=ConnectResponse)
async def connect_connector(connector_id: str, body: ConnectRequest | None = None):
    """Initiate a connection for *connector_id*.

    - **api_key** auth: send ``{api_key: "..."}`` in the body.  Stores the key,
      spawns the MCP server, and returns ``{connected: true, tools: [...]}``.
    - **oauth** auth: returns ``{auth_url: "https://..."}``  — the frontend
      should open this URL in the system browser.  After the user authenticates,
      the backend captures the callback, stores tokens, and spawns the MCP
      server.  Frontend should poll ``GET /api/connectors`` until status
      shows ``connected: true``.
    - **none** auth: just spawns the MCP server directly.
    """
    cdef = get_connector(connector_id)
    if cdef is None:
        raise HTTPException(404, f"Connector '{connector_id}' not found in catalog")
    if mcp_manager is None or cred_store is None:
        raise HTTPException(503, "Plugin system not initialized")

    # ── No auth required (MCP server may handle its own OAuth) ──
    if cdef.auth_type == "none":
        tools = await mcp_manager.connect(connector_id)
        # Store a marker so auto-reconnect works on restart
        cred_store.set(connector_id, {"_marker": True})
        return ConnectResponse(connected=True, tools=tools)

    # ── API key ──────────────────────────────────────────────────
    if cdef.auth_type == "api_key":
        api_key = body.api_key if body else None
        if not api_key:
            raise HTTPException(400, f"This connector requires an API key ({cdef.api_key_label})")
        cred_store.set(connector_id, {"api_key": api_key})
        try:
            tools = await mcp_manager.connect(connector_id)
        except Exception as exc:
            cred_store.delete(connector_id)
            raise HTTPException(502, f"MCP server failed to start: {exc}")
        return ConnectResponse(connected=True, tools=tools)

    # ── OAuth ────────────────────────────────────────────────────
    if cdef.auth_type == "oauth":
        callback_server = OAuthCallbackServer()
        await callback_server.start()
        _pending_oauth[connector_id] = callback_server

        # Build authorize URL
        client_id = os.environ.get(cdef.oauth_client_id_env, "")
        if not client_id:
            await callback_server.stop()
            _pending_oauth.pop(connector_id, None)
            raise HTTPException(
                500,
                f"OAuth client ID not configured — set {cdef.oauth_client_id_env} in .env",
            )

        params = {
            "client_id": client_id,
            "redirect_uri": callback_server.redirect_uri,
            "response_type": "code",
            "scope": " ".join(cdef.oauth_scopes),
            "state": callback_server.state,
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{cdef.oauth_authorize_url}?{urllib.parse.urlencode(params)}"

        # Launch background task to wait for callback
        import asyncio
        asyncio.create_task(
            _complete_oauth(connector_id, cdef, callback_server)
        )

        return ConnectResponse(auth_url=auth_url)

    raise HTTPException(400, f"Unknown auth_type '{cdef.auth_type}'")


async def _complete_oauth(
    connector_id: str,
    cdef: ConnectorDef,
    callback_server: OAuthCallbackServer,
) -> None:
    """Background task: wait for OAuth callback, exchange code, store tokens, connect."""
    try:
        code = await callback_server.wait_for_code(timeout=300)
        if code is None:
            return

        client_id = os.environ.get(cdef.oauth_client_id_env, "")
        client_secret = os.environ.get(cdef.oauth_client_secret_env, "")

        tokens = await OAuthCallbackServer.exchange_code(
            token_url=cdef.oauth_token_url,
            code=code,
            redirect_uri=callback_server.redirect_uri,
            client_id=client_id,
            client_secret=client_secret,
        )

        cred_store.set(connector_id, {
            "access_token": tokens.get("access_token", ""),
            "refresh_token": tokens.get("refresh_token", ""),
            "token_type": tokens.get("token_type", "Bearer"),
        })

        await mcp_manager.connect(connector_id)
    except Exception as exc:
        print(f"[Connectors] OAuth flow failed for {connector_id}: {exc}")
    finally:
        await callback_server.stop()
        _pending_oauth.pop(connector_id, None)


@router.delete("/{connector_id}")
async def disconnect_connector(connector_id: str):
    """Disconnect and remove stored credentials."""
    if mcp_manager is None or cred_store is None:
        raise HTTPException(503, "Plugin system not initialized")

    await mcp_manager.disconnect(connector_id)
    cred_store.delete(connector_id)
    return {"disconnected": True}


@router.get("/{connector_id}/tools")
async def list_connector_tools(connector_id: str):
    """List tools exposed by a connected MCP server."""
    if mcp_manager is None:
        raise HTTPException(503, "Plugin system not initialized")
    if not mcp_manager.is_connected(connector_id):
        raise HTTPException(404, f"Connector '{connector_id}' is not connected")

    conn = mcp_manager._connections.get(connector_id)
    return conn.tools if conn else []
