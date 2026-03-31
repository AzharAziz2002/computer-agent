"""Ephemeral OAuth callback server.

When a connector requires OAuth, the backend:
  1. Starts a tiny HTTP server on a random port.
  2. Builds the authorize URL with ``redirect_uri = http://localhost:{port}/callback``.
  3. Returns the URL to the frontend, which opens it in the system browser.
  4. After the user authenticates, the provider redirects back to this server.
  5. The server captures the authorization code and exchanges it for tokens.
  6. The server shuts down automatically.

Security:
  - CSRF ``state`` parameter is generated and validated.
  - The callback server binds only to 127.0.0.1 (never externally reachable).
  - The server is ephemeral — lives only for the duration of the OAuth flow.
"""

import asyncio
import secrets

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse


_SUCCESS_HTML = """\
<html>
<head><style>
  body { font-family: system-ui, sans-serif; display: flex;
         align-items: center; justify-content: center; height: 100vh;
         margin: 0; background: #fafafa; color: #222; }
</style></head>
<body><h2>Connected!  You can close this tab.</h2></body>
</html>
"""

_FAILURE_HTML = """\
<html>
<head><style>
  body { font-family: system-ui, sans-serif; display: flex;
         align-items: center; justify-content: center; height: 100vh;
         margin: 0; background: #fafafa; color: #c00; }
</style></head>
<body><h2>Authentication failed — please try again.</h2></body>
</html>
"""


class OAuthCallbackServer:
    """Ephemeral HTTP server to capture an OAuth authorization code."""

    def __init__(self):
        self.port: int = 0
        self.code: str | None = None
        self.state: str = secrets.token_urlsafe(32)
        self._received_state: str | None = None
        self._event = asyncio.Event()
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self.port}/callback"

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> int:
        """Start the callback server and return the assigned port."""
        app = FastAPI()

        @app.get("/callback")
        async def _callback(request: Request):
            self.code = request.query_params.get("code")
            self._received_state = request.query_params.get("state")
            self._event.set()
            if self.code and self._received_state == self.state:
                return HTMLResponse(_SUCCESS_HTML)
            return HTMLResponse(_FAILURE_HTML, status_code=400)

        config = uvicorn.Config(
            app, host="127.0.0.1", port=0, log_level="warning", access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())

        # Wait for the server to bind and extract the assigned port.
        for _ in range(50):
            if self._server.started:
                for srv in self._server.servers:
                    for sock in srv.sockets:
                        self.port = sock.getsockname()[1]
                break
            await asyncio.sleep(0.1)
        else:
            raise OSError("OAuth callback server failed to start (timeout)")

        return self.port

    async def wait_for_code(self, timeout: float = 300) -> str | None:
        """Block until the callback arrives (up to *timeout* seconds)."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        # Validate CSRF state
        if self._received_state != self.state:
            return None
        return self.code

    async def stop(self) -> None:
        """Shut down the callback server."""
        if self._server:
            self._server.should_exit = True
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    # ── Token exchange ───────────────────────────────────────────────

    @staticmethod
    async def exchange_code(
        token_url: str,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
    ) -> dict:
        """Exchange an authorization code for access + refresh tokens."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            resp.raise_for_status()
            return resp.json()
