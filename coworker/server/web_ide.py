"""Per-session loopback Web IDE proxies.

Each proxy has one bound RVM target. The loopback port is an origin-level routing
key, not a security boundary: any local process that discovers the port can reach
the proxied ``/vscode-remote-resource`` endpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import secrets
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect as rvm_ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus


@dataclass
class IdeTarget:
    session_id: str
    host_id: str
    base_url: str
    workspace: str
    token: str


def _error(message: str, status_code: int = 503) -> JSONResponse:
    return JSONResponse({"status": "offline", "error": message}, status_code=status_code)


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _capture_cookies(response: httpx.Response, cookies: dict[str, str]) -> None:
    headers: list[str] = []
    for header in response.headers.get_list("set-cookie"):
        headers.extend(re.split(r",\s*(?=[^;,=\s]+=[^;,]*)", header))
    for header in headers:
        first = header.split(";", 1)[0]
        if "=" not in first:
            continue
        name, value = first.split("=", 1)
        if not name:
            continue
        if "max-age=0" in header.lower():
            cookies.pop(name, None)
        else:
            cookies[name] = value


def _decoded_path(path: str) -> str:
    decoded = path
    for _ in range(5):
        next_path = unquote(decoded)
        if next_path == decoded:
            break
        decoded = next_path
    if any(segment == ".." for segment in re.split(r"[/\\]", decoded)):
        raise ValueError("traversal")
    return decoded


def _replace_connection_token(query: str, token: str) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode(
        [(name, token if name.lower() in {"tkn", "token"} else value) for name, value in pairs]
    )


class _EmbeddedUvicornServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.ready = asyncio.Event()

    @contextlib.contextmanager
    def capture_signals(self):
        yield

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        self.ready.set()


class SessionIdeProxy:
    ttl = 3600.0

    def __init__(self, target: IdeTarget, http_client: httpx.AsyncClient) -> None:
        self.target = target
        self.http_client = http_client
        self.document_key = secrets.token_urlsafe(32)
        self.cookies: dict[str, str] = {}
        self.last_used = time.monotonic()
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_socket.bind(("127.0.0.1", 0))
        self.listen_socket.listen(socket.SOMAXCONN)
        self.listen_socket.setblocking(False)
        self.port = int(self.listen_socket.getsockname()[1])
        self.server = _EmbeddedUvicornServer(
            uvicorn.Config(
                self._build_app(),
                log_level="error",
                access_log=False,
            )
        )
        self.task: asyncio.Task[None] | None = None

    def matches(self, target: IdeTarget) -> bool:
        return (
            self.target.session_id == target.session_id
            and self.target.host_id == target.host_id
            and self.target.base_url == target.base_url
        )

    def expired(self) -> bool:
        return time.monotonic() - self.last_used > self.ttl

    async def start(self) -> None:
        self.task = asyncio.create_task(self.server.serve(sockets=[self.listen_socket]))
        ready = asyncio.create_task(self.server.ready.wait())
        done, _ = await asyncio.wait(
            {self.task, ready},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if self.task in done:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)
            await self.task
        await ready

    async def stop(self) -> None:
        self.server.should_exit = True
        try:
            if self.task is not None:
                await self.task
        finally:
            self.task = None
            if self.listen_socket is not None:
                self.listen_socket.close()
                self.listen_socket = None

    def url(self) -> str:
        assert self.port is not None
        return (
            f"http://127.0.0.1:{self.port}/ide/?"
            + urlencode({"folder": self.target.workspace, "key": self.document_key})
        )

    def _origin(self, request: Request) -> str:
        return f"http://{request.url.hostname}:{request.url.port}"

    def _request_is_workbench(self, request: Request) -> bool:
        # This is hardening only; a local process that finds the port can still reach it.
        origin = self._origin(request)
        if request.headers.get("sec-fetch-site") == "same-origin":
            return True
        referer = request.headers.get("referer", "")
        request_origin = request.headers.get("origin", "")
        return referer.startswith(origin + "/") or request_origin == origin

    def _upstream_url(self, path: str, query: str) -> str:
        path = path.lstrip("/")
        if path == "ide":
            path = ""
        return f"{self.target.base_url}/ide/{path}" + (f"?{query}" if query else "")

    async def _send(
        self,
        request: Request,
        upstream_path: str,
        *,
        query: str | None = None,
    ) -> Response:
        query = _replace_connection_token(
            request.url.query if query is None else query, self.target.token
        )
        url = self._upstream_url(upstream_path, query)
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower()
            not in {"host", "content-length", "cookie", "authorization", "accept-encoding"}
        }
        headers["Authorization"] = f"Bearer {self.target.token}"
        headers["Accept-Encoding"] = "identity"
        if self.cookies:
            headers["Cookie"] = _cookie_header(self.cookies)
        body = await request.body()
        try:
            response = await self.http_client.send(
                self.http_client.build_request(
                    request.method, url, headers=headers, content=body
                ),
                stream=True,
            )
        except httpx.TimeoutException:
            return _error("Remote Web IDE request timed out", 503)
        except httpx.HTTPError:
            return _error("Remote Web IDE is offline or unreachable", 503)
        _capture_cookies(response, self.cookies)
        excluded = {
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection",
            "set-cookie",
        }
        response_headers = {
            key: value for key, value in response.headers.items() if key.lower() not in excluded
        }

        async def stream() -> Any:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(
            stream(),
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type"),
        )

    async def document(self, request: Request) -> Response:
        if request.query_params.get("key") != self.document_key:
            return _error("Invalid or expired Web IDE session key", 401)
        self.last_used = time.monotonic()
        response = await self._bootstrap()
        if isinstance(response, JSONResponse):
            return response
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )

    async def _bootstrap(self) -> httpx.Response | JSONResponse:
        query = [
            ("folder", self.target.workspace),
            ("tkn", self.target.token),
        ]
        url = self._upstream_url("", urlencode(query))
        for _ in range(4):
            headers = {
                "Authorization": f"Bearer {self.target.token}",
                "Accept": "text/html",
                "Accept-Encoding": "identity",
            }
            if self.cookies:
                headers["Cookie"] = _cookie_header(self.cookies)
            response = await self.http_client.get(url, headers=headers)
            _capture_cookies(response, self.cookies)
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("location")
            if not location:
                break
            parts = urlsplit(urljoin(url, location))
            redirect_query = [
                (name, value)
                for name, value in parse_qsl(parts.query, keep_blank_values=True)
                if name.lower() not in {"key", "tkn", "token", "folder"}
            ]
            redirect_query.append(("folder", self.target.workspace))
            url = parts._replace(query=urlencode(redirect_query), fragment="").geturl()
        if response.status_code < 200 or response.status_code >= 300:
            detail = response.text.strip()
            message = f"Remote Web IDE bootstrap failed (HTTP {response.status_code})"
            if detail:
                message += f": {detail}"
            return _error(message, 502)
        return response

    async def prepare(self) -> None:
        response = await self._bootstrap()
        if isinstance(response, JSONResponse):
            detail = response.body.decode("utf-8", errors="replace")
            raise RuntimeError(detail)
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError("Remote Web IDE bootstrap failed")

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/ide/")
        async def ide_document(request: Request) -> Response:
            return await self.document(request)

        @app.api_route(
            "/ide/{path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        )
        async def ide_path(request: Request, path: str) -> Response:
            if not self._request_is_workbench(request):
                return _error("Web IDE request origin is not allowed", 403)
            try:
                _decoded_path(path)
            except ValueError:
                return _error("Invalid Web IDE path", 400)
            self.last_used = time.monotonic()
            return await self._send(request, path)

        @app.api_route(
            "/{asset_root}/{path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        )
        async def root_asset(request: Request, asset_root: str, path: str) -> Response:
            if asset_root not in {"out", "resources", "extensions", "node_modules"}:
                return _error("Not found", 404)
            if not self._request_is_workbench(request):
                return _error("Web IDE request origin is not allowed", 403)
            try:
                _decoded_path(path)
            except ValueError:
                return _error("Invalid Web IDE path", 400)
            self.last_used = time.monotonic()
            return await self._send(request, f"static/{asset_root}/{path}")

        @app.api_route(
            "/vscode-remote-resource",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        )
        async def remote_resource(request: Request) -> Response:
            if not self._request_is_workbench(request):
                return _error("Web IDE request origin is not allowed", 403)
            self.last_used = time.monotonic()
            return await self._send(request, "vscode-remote-resource")

        @app.websocket("/")
        async def management_socket(ws: WebSocket) -> None:
            origin = f"http://{ws.url.hostname}:{ws.url.port}"
            if ws.headers.get("origin") != origin:
                await ws.close(code=1008, reason="Web IDE origin is not allowed")
                return
            await ws.accept()
            query = _replace_connection_token(str(ws.query_params), self.target.token)
            upstream_url = self.target.base_url.replace("https://", "wss://", 1).replace(
                "http://", "ws://", 1
            ) + "/ide/?" + query
            try:
                async with rvm_ws_connect(
                    upstream_url,
                    additional_headers={
                        "Authorization": f"Bearer {self.target.token}",
                        **({"Cookie": _cookie_header(self.cookies)} if self.cookies else {}),
                    },
                    max_size=None,
                    ping_interval=None,
                ) as upstream:
                    async def client_to_rvm() -> None:
                        while True:
                            message = await ws.receive()
                            if message["type"] == "websocket.disconnect":
                                return
                            await upstream.send(message.get("bytes") or message.get("text") or "")

                    async def rvm_to_client() -> None:
                        async for message in upstream:
                            if isinstance(message, bytes):
                                await ws.send_bytes(message)
                            else:
                                await ws.send_text(message)

                    client_task = asyncio.create_task(client_to_rvm())
                    rvm_task = asyncio.create_task(rvm_to_client())
                    done, pending = await asyncio.wait(
                        {client_task, rvm_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    for task in done:
                        if not task.cancelled() and task.exception() is not None:
                            raise task.exception()
            except (WebSocketDisconnect, ConnectionClosed):
                pass
            except InvalidStatus:
                if ws.client_state.name == "CONNECTED":
                    await ws.close(code=1011, reason="Remote Web IDE unavailable")
            except Exception:
                if ws.client_state.name == "CONNECTED":
                    await ws.close(code=1011, reason="Remote Web IDE disconnected")

        return app


class IdeProxyRegistry:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client
        self.proxies: dict[str, SessionIdeProxy] = {}

    async def get_or_create(self, target: IdeTarget) -> SessionIdeProxy:
        await self.sweep()
        current = self.proxies.get(target.session_id)
        if current is not None and current.matches(target):
            current.last_used = time.monotonic()
            return current
        if current is not None:
            await current.stop()
        proxy = SessionIdeProxy(target, self.http_client)
        await proxy.start()
        try:
            await proxy.prepare()
        except Exception:
            await proxy.stop()
            raise
        self.proxies[target.session_id] = proxy
        return proxy

    async def sweep(self) -> None:
        for session_id, proxy in list(self.proxies.items()):
            if proxy.expired():
                await proxy.stop()
                self.proxies.pop(session_id, None)

    async def close(self, session_id: str) -> None:
        proxy = self.proxies.pop(session_id, None)
        if proxy is not None:
            await proxy.stop()

    async def close_all(self) -> None:
        for session_id in list(self.proxies):
            await self.close(session_id)
