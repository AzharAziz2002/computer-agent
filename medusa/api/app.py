from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from medusa.api.routers import tasks, screenshot, sessions, connectors
from medusa.plugins.manager import MCPManager
from medusa.plugins.credentials import CredentialStore

# Singleton — shared by connectors router and tasks router.
mcp_manager = MCPManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle for the MCP plugin system."""
    # ── Startup ──────────────────────────────────────────────────
    cred_store = CredentialStore()
    connectors.mcp_manager = mcp_manager
    connectors.cred_store = cred_store

    # Auto-reconnect connectors that were connected in a previous session.
    for conn_id in cred_store.list_connected():
        try:
            await mcp_manager.connect(conn_id)
            print(f"[Plugins] Reconnected '{conn_id}'")
        except Exception as exc:
            print(f"[Plugins] Could not reconnect '{conn_id}': {exc}")

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    await mcp_manager.shutdown()


app = FastAPI(title="Medusa API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router)
app.include_router(screenshot.router)
app.include_router(sessions.router)
app.include_router(connectors.router)
