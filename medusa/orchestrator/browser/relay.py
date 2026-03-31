"""CDP relay server bridging Playwright ↔ Chrome Extension.

Architecture:
    Extension connects to  ws://host:port/extension  (single connection)
    Playwright connects to  ws://host:port/cdp        (multiple connections)
    HTTP endpoints serve CDP metadata (/json/version, /json/list, etc.)

The relay forwards CDP commands from /cdp clients to the extension, which
executes them via chrome.debugger.sendCommand(), and returns results.  CDP
events emitted by the extension are broadcast to all /cdp clients.

Certain CDP commands (Browser.getVersion, Target.* management) are handled
locally by the relay without forwarding.

Based on OpenClaw's extension-relay.ts — ported to Python/FastAPI.
"""

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field
from ipaddress import ip_address

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.websockets import WebSocketState

from medusa.orchestrator.browser.constants import DEFAULT_RELAY_PORT, RELAY_AUTH_HEADER

logger = logging.getLogger(__name__)


# ── Data models ──────────────────────────────────────────────────────

@dataclass
class ConnectedTarget:
    session_id: str
    target_id: str
    target_info: dict = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────

def _is_loopback(addr: str | None) -> bool:
    """Check if an IP address is loopback."""
    if not addr:
        return False
    try:
        return ip_address(addr).is_loopback
    except ValueError:
        return addr in ('127.0.0.1', '::1', 'localhost')


# ── Relay Server ─────────────────────────────────────────────────────

class ExtensionRelay:
    """WebSocket relay between Chrome extension and Playwright/CDP consumers.

    Usage:
        relay = ExtensionRelay(port=18792)
        await relay.start()
        # ... use relay.cdp_ws_url to connect Playwright ...
        await relay.stop()
    """

    def __init__(self, host: str = '127.0.0.1', port: int = DEFAULT_RELAY_PORT):
        self.host = host
        self.port = port
        self.auth_token = secrets.token_urlsafe(32)
        self.cdp_ws_url = f'ws://{host}:{port}/cdp'

        # Extension WebSocket (single connection)
        self._extension_ws: WebSocket | None = None

        # CDP consumer WebSockets (multiple — Playwright etc.)
        self._cdp_clients: set[WebSocket] = set()

        # Attached browser targets (keyed by sessionId)
        self._connected_targets: dict[str, ConnectedTarget] = {}

        # Pending requests to extension (id → Future)
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1

        # Ping task
        self._ping_task: asyncio.Task | None = None

        # Server
        self._app = self._build_app()
        self._server_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

    # ── Public API ───────────────────────────────────────────────────

    def extension_connected(self) -> bool:
        return (
            self._extension_ws is not None
            and self._extension_ws.client_state == WebSocketState.CONNECTED
        )

    async def start(self):
        """Start the relay server in a background asyncio task."""
        import uvicorn

        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level='warning',
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server
        self._bind_error: Exception | None = None

        # Wrap serve() so SystemExit from a port-bind failure doesn't kill the
        # main server process (uvicorn calls sys.exit(1) on startup failure).
        async def _run():
            try:
                await server.serve()
            except SystemExit as exc:
                self._bind_error = OSError(
                    f'Extension relay cannot bind port {self.port} — '
                    'a previous relay may still be running. '
                    f'Kill the process holding port {self.port} and retry.'
                )
            except Exception as exc:
                self._bind_error = exc

        self._server_task = asyncio.create_task(_run())

        # Wait up to 5 s for the server to start (or fail to bind)
        for _ in range(50):
            if server.started:
                break
            if self._bind_error:
                self._server_task.cancel()
                raise self._bind_error
            await asyncio.sleep(0.1)

        if not server.started:
            if self._bind_error:
                raise self._bind_error
            raise OSError(f'Extension relay failed to start on port {self.port} (timeout)')

        logger.info(f'Extension relay started on {self.host}:{self.port}')

    async def stop(self):
        """Shut down the relay server gracefully."""
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            self._ping_task = None

        # Close extension WS
        if self._extension_ws:
            try:
                await self._extension_ws.close(1001, 'server stopping')
            except Exception:
                pass
            self._extension_ws = None

        # Close CDP clients
        for ws in list(self._cdp_clients):
            try:
                await ws.close(1001, 'server stopping')
            except Exception:
                pass
        self._cdp_clients.clear()

        # Cancel pending
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(Exception('relay stopping'))
        self._pending.clear()

        # Stop uvicorn and release the port
        if hasattr(self, '_uvicorn_server'):
            self._uvicorn_server.should_exit = True
            # Force-close the listening sockets so the port is freed immediately.
            # uvicorn stores asyncio.Server objects in .servers — closing them
            # releases the bound port without waiting for TIME_WAIT.
            for srv in getattr(self._uvicorn_server, 'servers', []) or []:
                srv.close()
        if self._server_task:
            try:
                await asyncio.wait_for(self._server_task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._server_task.cancel()
                try:
                    await self._server_task
                except (asyncio.CancelledError, Exception):
                    pass
            self._server_task = None

        logger.info('Extension relay stopped')

    # ── FastAPI app builder ──────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        # ── HTTP routes ──────────────────────────────────────────────

        @app.head('/')
        async def health_head():
            return Response(status_code=200)

        @app.get('/')
        async def health_get():
            return PlainTextResponse('OK')

        @app.get('/extension/status')
        async def extension_status():
            return JSONResponse({'connected': self.extension_connected()})

        @app.get('/json/version')
        @app.put('/json/version')
        async def json_version(request: Request):
            if not self._check_auth(request):
                return Response(status_code=401, content='Unauthorized')
            payload = {
                'Browser': 'Medusa/extension-relay',
                'Protocol-Version': '1.3',
            }
            if self.extension_connected():
                payload['webSocketDebuggerUrl'] = self.cdp_ws_url
            return JSONResponse(payload)

        @app.get('/json/list')
        @app.get('/json')
        @app.put('/json/list')
        @app.put('/json')
        async def json_list(request: Request):
            if not self._check_auth(request):
                return Response(status_code=401, content='Unauthorized')
            targets = []
            for t in self._connected_targets.values():
                info = t.target_info
                targets.append({
                    'id': t.target_id,
                    'type': info.get('type', 'page'),
                    'title': info.get('title', ''),
                    'description': info.get('title', ''),
                    'url': info.get('url', ''),
                    'webSocketDebuggerUrl': self.cdp_ws_url,
                })
            return JSONResponse(targets)

        @app.api_route('/json/activate/{target_id:path}', methods=['GET', 'PUT'])
        async def json_activate(target_id: str, request: Request):
            if not self._check_auth(request):
                return Response(status_code=401, content='Unauthorized')
            target_id = target_id.strip()
            if not target_id:
                return Response(status_code=400, content='targetId required')
            asyncio.create_task(self._forward_fire_and_forget(
                'Target.activateTarget', {'targetId': target_id}
            ))
            return PlainTextResponse('OK')

        @app.api_route('/json/close/{target_id:path}', methods=['GET', 'PUT'])
        async def json_close(target_id: str, request: Request):
            if not self._check_auth(request):
                return Response(status_code=401, content='Unauthorized')
            target_id = target_id.strip()
            if not target_id:
                return Response(status_code=400, content='targetId required')
            asyncio.create_task(self._forward_fire_and_forget(
                'Target.closeTarget', {'targetId': target_id}
            ))
            return PlainTextResponse('OK')

        # ── WebSocket: Extension ─────────────────────────────────────

        @app.websocket('/extension')
        async def ws_extension(websocket: WebSocket):
            # Only allow one extension connection at a time
            if self._extension_ws is not None:
                await websocket.close(4009, 'Extension already connected')
                return

            await websocket.accept()
            self._extension_ws = websocket
            logger.info('Chrome extension connected')

            # Start ping keepalive
            self._ping_task = asyncio.create_task(self._ping_loop())

            try:
                while True:
                    text = await websocket.receive_text()
                    await self._on_extension_message(text)
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.warning(f'Extension WS error: {e}')
            finally:
                self._on_extension_closed()

        # ── WebSocket: CDP consumers (Playwright) ────────────────────

        @app.websocket('/cdp')
        async def ws_cdp(websocket: WebSocket):
            # Auth check via query param or header
            token = (
                websocket.headers.get(RELAY_AUTH_HEADER)
                or websocket.query_params.get('token')
            )
            if token != self.auth_token:
                await websocket.close(4001, 'Unauthorized')
                return

            if not self.extension_connected():
                await websocket.close(4003, 'Extension not connected')
                return

            await websocket.accept()
            self._cdp_clients.add(websocket)
            logger.info(f'CDP client connected (total: {len(self._cdp_clients)})')

            try:
                while True:
                    text = await websocket.receive_text()
                    await self._on_cdp_message(websocket, text)
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.warning(f'CDP WS error: {e}')
            finally:
                self._cdp_clients.discard(websocket)
                logger.info(f'CDP client disconnected (total: {len(self._cdp_clients)})')

        return app

    # ── Auth helper ──────────────────────────────────────────────────

    def _check_auth(self, request: Request) -> bool:
        token = request.headers.get(RELAY_AUTH_HEADER)
        return token == self.auth_token

    # ── Extension message handling ───────────────────────────────────

    async def _on_extension_message(self, text: str):
        try:
            msg = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return

        if not isinstance(msg, dict):
            return

        # Pong response to our ping
        if msg.get('method') == 'pong':
            return

        # Response to a forwarded command (id + result/error)
        msg_id = msg.get('id')
        if isinstance(msg_id, int) and (msg.get('result') is not None or msg.get('error') is not None):
            fut = self._pending.pop(msg_id, None)
            if fut and not fut.done():
                if msg.get('error'):
                    fut.set_exception(Exception(str(msg['error'])))
                else:
                    fut.set_result(msg.get('result'))
            return

        # CDP event forwarded from extension
        method = msg.get('method')
        if method == 'forwardCDPEvent':
            params = msg.get('params', {})
            cdp_method = params.get('method', '')
            cdp_params = params.get('params')
            session_id = params.get('sessionId')

            if not cdp_method:
                return

            # Track attached/detached targets
            if cdp_method == 'Target.attachedToTarget':
                self._handle_target_attached(cdp_params)

            elif cdp_method == 'Target.detachedFromTarget':
                self._handle_target_detached(cdp_params)

            elif cdp_method == 'Target.targetInfoChanged':
                self._handle_target_info_changed(cdp_params)

            # Broadcast to all CDP clients
            self._broadcast_to_cdp({
                'method': cdp_method,
                'params': cdp_params,
                'sessionId': session_id,
            })

    def _handle_target_attached(self, params: dict | None):
        if not params:
            return
        session_id = params.get('sessionId')
        target_info = params.get('targetInfo', {})
        target_type = target_info.get('type', 'page')
        target_id = target_info.get('targetId')

        # Only track page targets
        if target_type != 'page':
            return
        if not session_id or not target_id:
            return

        prev = self._connected_targets.get(session_id)
        prev_target_id = prev.target_id if prev else None
        changed_target = prev is not None and prev_target_id and prev_target_id != target_id

        self._connected_targets[session_id] = ConnectedTarget(
            session_id=session_id,
            target_id=target_id,
            target_info=target_info,
        )

        if changed_target and prev_target_id:
            # Synthetic detach for old target
            self._broadcast_to_cdp({
                'method': 'Target.detachedFromTarget',
                'params': {'sessionId': session_id, 'targetId': prev_target_id},
                'sessionId': session_id,
            })

    def _handle_target_detached(self, params: dict | None):
        if not params:
            return
        session_id = params.get('sessionId')
        if session_id:
            self._connected_targets.pop(session_id, None)

    def _handle_target_info_changed(self, params: dict | None):
        if not params:
            return
        target_info = params.get('targetInfo', {})
        target_id = target_info.get('targetId')
        if not target_id:
            return
        target_type = target_info.get('type', 'page')
        if target_type != 'page':
            return
        for sid, target in self._connected_targets.items():
            if target.target_id == target_id:
                target.target_info = {**target.target_info, **target_info}

    def _on_extension_closed(self):
        logger.info('Chrome extension disconnected')
        self._extension_ws = None

        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            self._ping_task = None

        # Reject all pending
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(Exception('extension disconnected'))
        self._pending.clear()
        self._connected_targets.clear()

        # Close all CDP clients
        for ws in list(self._cdp_clients):
            asyncio.create_task(self._safe_close(ws, 1011, 'extension disconnected'))
        self._cdp_clients.clear()

    # ── CDP client message handling ──────────────────────────────────

    async def _on_cdp_message(self, ws: WebSocket, text: str):
        try:
            cmd = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return

        if not isinstance(cmd, dict):
            return

        cmd_id = cmd.get('id')
        method = cmd.get('method', '')
        params = cmd.get('params')
        session_id = cmd.get('sessionId')

        if not isinstance(cmd_id, int) or not isinstance(method, str):
            return

        if not self.extension_connected():
            await self._send_cdp_response(ws, cmd_id, session_id,
                                          error='Extension not connected')
            return

        try:
            result = await self._route_cdp_command(method, params, session_id)

            # After certain commands, replay target state to the client
            if method == 'Target.setAutoAttach' and not session_id:
                self._replay_targets_to_client(ws, 'autoAttach')
            if method == 'Target.setDiscoverTargets':
                discover = (params or {}).get('discover', False)
                if discover:
                    self._replay_targets_to_client(ws, 'discover')
            if method == 'Target.attachToTarget':
                target_id = (params or {}).get('targetId')
                if target_id:
                    for t in self._connected_targets.values():
                        if t.target_id == target_id:
                            self._send_cdp_event(ws, {
                                'method': 'Target.attachedToTarget',
                                'params': {
                                    'sessionId': t.session_id,
                                    'targetInfo': {**t.target_info, 'attached': True},
                                    'waitingForDebugger': False,
                                },
                            })
                            break

            await self._send_cdp_response(ws, cmd_id, session_id, result=result)

        except Exception as e:
            await self._send_cdp_response(ws, cmd_id, session_id, error=str(e))

    async def _route_cdp_command(self, method: str, params: dict | None, session_id: str | None):
        """Handle a CDP command — either locally or by forwarding to extension."""
        match method:
            case 'Browser.getVersion':
                return {
                    'protocolVersion': '1.3',
                    'product': 'Chrome/Medusa-Extension-Relay',
                    'revision': '0',
                    'userAgent': 'Medusa-Extension-Relay',
                    'jsVersion': 'V8',
                }
            case 'Browser.setDownloadBehavior':
                return {}
            case 'Target.setAutoAttach' | 'Target.setDiscoverTargets':
                return {}
            case 'Target.getTargets':
                return {
                    'targetInfos': [
                        {**t.target_info, 'attached': True}
                        for t in self._connected_targets.values()
                    ]
                }
            case 'Target.getTargetInfo':
                target_id = (params or {}).get('targetId') if params else None
                if target_id:
                    for t in self._connected_targets.values():
                        if t.target_id == target_id:
                            return {'targetInfo': t.target_info}
                if session_id and session_id in self._connected_targets:
                    t = self._connected_targets[session_id]
                    return {'targetInfo': t.target_info}
                # Return first target as fallback
                first = next(iter(self._connected_targets.values()), None)
                return {'targetInfo': first.target_info if first else {}}
            case 'Target.attachToTarget':
                target_id = (params or {}).get('targetId')
                if not target_id:
                    raise ValueError('targetId required')
                for t in self._connected_targets.values():
                    if t.target_id == target_id:
                        return {'sessionId': t.session_id}
                raise ValueError('target not found')
            case _:
                # Forward to extension
                return await self._send_to_extension(method, params, session_id)

    # ── Extension communication ──────────────────────────────────────

    async def _send_to_extension(
        self,
        method: str,
        params: dict | None = None,
        session_id: str | None = None,
        timeout: float = 30.0,
    ) -> dict | None:
        """Send a CDP command to the extension and wait for the response."""
        ws = self._extension_ws
        if ws is None or ws.client_state != WebSocketState.CONNECTED:
            raise Exception('Chrome extension not connected')

        cmd_id = self._next_id
        self._next_id += 1

        payload = {
            'id': cmd_id,
            'method': 'forwardCDPCommand',
            'params': {
                'method': method,
            },
        }
        if params is not None:
            payload['params']['params'] = params
        if session_id is not None:
            payload['params']['sessionId'] = session_id

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = fut

        try:
            await ws.send_text(json.dumps(payload))
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            raise Exception(f'Extension request timeout: {method}')
        except Exception:
            self._pending.pop(cmd_id, None)
            raise

    async def _forward_fire_and_forget(self, method: str, params: dict | None = None):
        """Fire-and-forget command to extension (for HTTP activate/close endpoints)."""
        try:
            await self._send_to_extension(method, params, timeout=10.0)
        except Exception:
            pass

    # ── CDP client communication ─────────────────────────────────────

    def _broadcast_to_cdp(self, event: dict):
        """Send a CDP event to all connected /cdp clients."""
        # Filter out None values
        msg = {k: v for k, v in event.items() if v is not None}
        text = json.dumps(msg)
        for ws in list(self._cdp_clients):
            if ws.client_state == WebSocketState.CONNECTED:
                asyncio.create_task(self._safe_send(ws, text))

    def _send_cdp_event(self, ws: WebSocket, event: dict):
        """Send a CDP event to a specific client."""
        msg = {k: v for k, v in event.items() if v is not None}
        if ws.client_state == WebSocketState.CONNECTED:
            asyncio.create_task(self._safe_send(ws, json.dumps(msg)))

    async def _send_cdp_response(
        self,
        ws: WebSocket,
        cmd_id: int,
        session_id: str | None = None,
        result=None,
        error: str | None = None,
    ):
        if ws.client_state != WebSocketState.CONNECTED:
            return
        resp: dict = {'id': cmd_id}
        if session_id is not None:
            resp['sessionId'] = session_id
        if error is not None:
            resp['error'] = {'message': error}
        else:
            resp['result'] = result if result is not None else {}
        await self._safe_send(ws, json.dumps(resp))

    def _replay_targets_to_client(self, ws: WebSocket, mode: str):
        """Replay all connected targets to a new/reconnecting CDP client."""
        for target in self._connected_targets.values():
            if mode == 'autoAttach':
                event = {
                    'method': 'Target.attachedToTarget',
                    'params': {
                        'sessionId': target.session_id,
                        'targetInfo': {**target.target_info, 'attached': True},
                        'waitingForDebugger': False,
                    },
                }
            else:
                event = {
                    'method': 'Target.targetCreated',
                    'params': {
                        'targetInfo': {**target.target_info, 'attached': True},
                    },
                }
            self._send_cdp_event(ws, event)

    # ── Keepalive ────────────────────────────────────────────────────

    async def _ping_loop(self):
        """Send periodic pings to the extension to keep the connection alive."""
        try:
            while True:
                await asyncio.sleep(5)
                ws = self._extension_ws
                if ws and ws.client_state == WebSocketState.CONNECTED:
                    try:
                        await ws.send_text(json.dumps({'method': 'ping'}))
                    except Exception:
                        break
                else:
                    break
        except asyncio.CancelledError:
            pass

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    async def _safe_send(ws: WebSocket, text: str):
        try:
            await ws.send_text(text)
        except Exception:
            pass

    @staticmethod
    async def _safe_close(ws: WebSocket, code: int = 1000, reason: str = ''):
        try:
            await ws.close(code, reason)
        except Exception:
            pass
