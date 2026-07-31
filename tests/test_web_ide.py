from types import SimpleNamespace
import time

import httpx
import websockets
from fastapi.testclient import TestClient

from coworker.remote.hosts import RvmHost
from coworker.server import app as app_module
from coworker.server.app import create_app
from coworker.server.manager import SessionManager
from coworker.server.web_ide import IdeProxyRegistry, IdeTarget
from coworker.server import web_ide as web_ide_module
from coworker.sessions import SessionRecord


class FakeAsyncClient:
    requests: list[httpx.Request] = []

    def __init__(self, *args, **kwargs):
        self.redirects = 0

    async def get(self, url, **kwargs):
        request = httpx.Request("GET", url, headers=kwargs.get("headers"))
        self.requests.append(request)
        if self.redirects == 0:
            self.redirects += 1
            return httpx.Response(
                302,
                request=request,
                headers={
                    "location": "/ide/",
                    "set-cookie": (
                        "rvm_ide_tkn=agent-cookie; Path=/, "
                        "vscode-tkn=serve-cookie; Path=/"
                    ),
                },
            )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            content=b'<meta id="vscode-workbench-web-configuration">',
        )

    def build_request(self, method, url, **kwargs):
        request = httpx.Request(method, url, **kwargs)
        self.requests.append(request)
        return request

    async def send(self, request, **kwargs):
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "application/javascript"},
            content=b"asset",
        )

    async def aclose(self):
        return None


class FailingAsyncClient(FakeAsyncClient):
    async def get(self, url, **kwargs):
        request = httpx.Request("GET", url, headers=kwargs.get("headers"))
        self.requests.append(request)
        return httpx.Response(
            401,
            request=request,
            headers={"content-type": "text/plain"},
            content=b"RVM authorization required",
        )


def _manager(tmp_path, sessions: dict[str, tuple[str, str]]):
    manager = SessionManager(data_dir=tmp_path)
    targets = {}
    for session_id, (host_id, base_url) in sessions.items():
        workspace = rf"C:\Users\{host_id}"
        manager.rvm_hosts.put(
            RvmHost(host_id, host_id, base_url, workspace=workspace),
            f"{host_id}-server-token",
        )
        manager.session_store.save(
            SessionRecord(session_id, workspace, "test", "auto", host_id=host_id)
        )
        targets[session_id] = SimpleNamespace(
            host=SimpleNamespace(id=host_id),
            workspace=workspace,
            client=SimpleNamespace(base_url=base_url, close=lambda: None),
        )
    manager.resolve_remote_target = lambda session_id: targets[session_id]
    manager.rvm_hosts.token = lambda host_id: f"{host_id}-server-token"
    return manager


def test_ide_session_replays_rvm_cookies_and_returns_opaque_url(monkeypatch, tmp_path):
    manager = _manager(tmp_path, {"session-1": ("rvm-a", "https://rvm.example")})
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.requests.clear()

    with TestClient(create_app(manager)) as client:
        result = client.post("/v1/sessions/session-1/ide/session")
        assert result.status_code == 200
        url = result.json()["url"]
        assert url.startswith("http://127.0.0.1:")
        assert "key=" in url
        assert "server-token" not in url

        first, second = FakeAsyncClient.requests[:2]
        assert "cookie" not in first.headers
        assert "rvm_ide_tkn=agent-cookie" in second.headers["cookie"]
        assert "vscode-tkn=serve-cookie" in second.headers["cookie"]

        document = httpx.get(url)
        assert document.status_code == 200
        assert "vscode-workbench-web-configuration" in document.text


def test_ide_ports_isolate_bound_hosts(monkeypatch, tmp_path):
    manager = _manager(
        tmp_path,
        {
            "session-a": ("rvm-a", "https://rvm-a.example"),
            "session-b": ("rvm-b", "https://rvm-b.example"),
        },
    )
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(create_app(manager)) as client:
        first = client.post("/v1/sessions/session-a/ide/session").json()["url"]
        second = client.post("/v1/sessions/session-b/ide/session").json()["url"]
        first_port = first.split("/", 3)[2]
        second_port = second.split("/", 3)[2]
        assert first_port != second_port

        httpx.get(
            f"http://{first_port}/out/vs/code.js",
            headers={"sec-fetch-site": "same-origin"},
        )
        assert any(
            request.url.host == "rvm-a.example"
            for request in FakeAsyncClient.requests
            if request.url.path.endswith("/ide/static/out/vs/code.js")
        )
        httpx.get(
            f"http://{first_port}/extensions/git-base/dist/browser/extension.js?tkn=",
            headers={"sec-fetch-site": "same-origin"},
        )
        assert any(
            request.url.host == "rvm-a.example"
            and request.url.params.get("tkn") == "rvm-a-server-token"
            for request in FakeAsyncClient.requests
            if request.url.path.endswith("/ide/static/extensions/git-base/dist/browser/extension.js")
        )
        assert not any(
            request.url.host == "rvm-b.example"
            and request.url.path.endswith("/ide/static/out/vs/code.js")
            for request in FakeAsyncClient.requests
        )


def test_ide_document_requires_key_and_traversal_is_rejected(monkeypatch, tmp_path):
    manager = _manager(tmp_path, {"session-1": ("rvm-a", "https://rvm.example")})
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(create_app(manager)) as client:
        result = client.post("/v1/sessions/session-1/ide/session").json()
        origin = result["url"].split("/ide/", 1)[0]
        assert httpx.get(f"{origin}/ide/").status_code == 401
        assert (
            httpx.get(
                f"{origin}/out/%252e%252e%252f%252e%252e%252fetc/passwd",
                headers={"sec-fetch-site": "same-origin"},
            ).status_code
            == 400
        )


def test_ide_bootstrap_failure_surfaces_upstream_reason(monkeypatch, tmp_path):
    manager = _manager(tmp_path, {"session-1": ("rvm-a", "https://rvm.example")})
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FailingAsyncClient)

    with TestClient(create_app(manager)) as client:
        result = client.post("/v1/sessions/session-1/ide/session")
        assert result.status_code == 503
        assert result.json() == {
            "status": "offline",
            "error": (
                "Remote Web IDE bootstrap failed (HTTP 401): "
                "RVM authorization required"
            ),
        }
        assert "Unable to start the Web IDE proxy" not in result.text


async def test_registry_replaces_host_binding_and_closes_all():
    class Client:
        async def get(self, url, **kwargs):
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok")

        async def aclose(self):
            pass

        def build_request(self, method, url, **kwargs):
            return httpx.Request(method, url, **kwargs)

        async def send(self, request, **kwargs):
            return httpx.Response(200, request=request, content=b"ok")

    registry = IdeProxyRegistry(Client())
    first = await registry.get_or_create(
        IdeTarget("session", "host-a", "https://a.example", "C:\\a", "token-a")
    )
    second = await registry.get_or_create(
        IdeTarget("session", "host-b", "https://b.example", "C:\\b", "token-b")
    )
    assert first.port != second.port
    second.last_used = time.monotonic() - second.ttl - 1
    third = await registry.get_or_create(
        IdeTarget("other-session", "host-c", "https://c.example", "C:\\c", "token-c")
    )
    assert third.port != second.port
    await registry.close_all()
    assert not registry.proxies


async def test_proxy_websocket_accepts_without_openworker_subprotocol(monkeypatch):
    class Upstream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send(self, message):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    monkeypatch.setattr(web_ide_module, "rvm_ws_connect", lambda *args, **kwargs: Upstream())

    class Client:
        async def get(self, url, **kwargs):
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok")

        async def aclose(self):
            pass

    registry = IdeProxyRegistry(Client())
    proxy = await registry.get_or_create(
        IdeTarget("session", "host", "https://rvm.example", "C:\\workspace", "token")
    )
    try:
        async with websockets.asyncio.client.connect(
            f"ws://127.0.0.1:{proxy.port}/?reconnectionToken=probe",
            origin=f"http://127.0.0.1:{proxy.port}",
        ) as websocket:
            assert websocket.subprotocol is None
    finally:
        await registry.close_all()
