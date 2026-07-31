from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from coworker.server import app as app_module
from coworker.remote.hosts import RvmHost
from coworker.sessions import SessionRecord
from coworker.server.app import create_app
from coworker.server.manager import SessionManager


class FakeAsyncClient:
    requests: list[str] = []

    def __init__(self, *args, **kwargs):
        self.redirects = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.requests.append(url)
        if self.redirects == 0:
            self.redirects += 1
            return httpx.Response(
                302,
                headers={
                    "location": "/ide/",
                    "set-cookie": "rvm_ide_tkn=agent-cookie; Path=/, vscode-tkn=serve-cookie; Path=/",
                },
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>IDE</html>")

    def build_request(self, method, url, **kwargs):
        self.requests.append(url)
        return httpx.Request(method, url, **kwargs)

    async def send(self, request, **kwargs):
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "application/javascript"},
            content=b"asset",
        )

    async def aclose(self):
        return None


def test_ide_bootstrap_keeps_rvm_token_server_side(monkeypatch, tmp_path):
    manager = SessionManager(data_dir=tmp_path)
    target = SimpleNamespace(
        host=SimpleNamespace(id="rvm"),
        workspace=r"C:\Users\Team",
        client=SimpleNamespace(base_url="https://rvm.example", close=lambda: None),
    )
    manager.rvm_hosts.put(
        RvmHost("rvm", "Remote", "https://rvm.example", workspace=r"C:\Users\Team"),
        "server-token",
    )
    manager.session_store.save(
        SessionRecord(
            "session-1",
            r"C:\Users\Team",
            "test",
            "auto",
            host_id="rvm",
        )
    )
    monkeypatch.setattr(manager, "resolve_remote_target", lambda _session_id: target)
    monkeypatch.setattr(manager.rvm_hosts, "token", lambda _host_id: "server-token")
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.requests.clear()

    with TestClient(create_app(manager)) as client:
        response = client.get("/v1/sessions/session-1/ide/")
        assert response.status_code == 200
        assert "folder=C%3A%5CUsers%5CTeam" in str(response.request.url)
        assert response.text == "<html>IDE</html>"
        assert "server-token" not in response.text
        assert "server-token" not in response.headers.get("location", "")
        client.cookies.set("openworker_ide_key", response.cookies["openworker_ide_key"])
        asset = client.get("/out/static.js")
        assert asset.status_code == 200
        assert asset.content == b"asset"
        assert client.get("/ide/static/remoteEntry.js").status_code == 200
        assert client.get("/ide/%2E%2E/secret").status_code == 400
        assert client.get("/out/..%2f..%2fetc/passwd").status_code == 400
        assert (
            client.get("/out/%252e%252e%252f%252e%252e%252fetc/passwd").status_code
            == 400
        )

    assert any("tkn=server-token" in url for url in FakeAsyncClient.requests)
    assert any("folder=C%3A%5CUsers%5CTeam" in url for url in FakeAsyncClient.requests)


def test_ide_bootstrap_reuses_valid_key(monkeypatch, tmp_path):
    manager = SessionManager(data_dir=tmp_path)
    target = SimpleNamespace(
        host=SimpleNamespace(id="rvm"),
        workspace=r"C:\Users\Team",
        client=SimpleNamespace(base_url="https://rvm.example", close=lambda: None),
    )
    manager.rvm_hosts.put(
        RvmHost("rvm", "Remote", "https://rvm.example", workspace=r"C:\Users\Team"),
        "server-token",
    )
    manager.session_store.save(
        SessionRecord("session-1", r"C:\Users\Team", "test", "auto", host_id="rvm")
    )
    monkeypatch.setattr(manager, "resolve_remote_target", lambda _session_id: target)
    monkeypatch.setattr(manager.rvm_hosts, "token", lambda _host_id: "server-token")
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(create_app(manager)) as client:
        redirect = client.get(
            "/v1/sessions/session-1/ide/", follow_redirects=False
        )
        assert redirect.status_code == 307
        assert redirect.headers["location"] == (
            "/v1/sessions/session-1/ide/?folder=C%3A%5CUsers%5CTeam"
        )
        assert "set-cookie" not in redirect.headers

        first = client.get(redirect.headers["location"])
        first_key = first.cookies["openworker_ide_key"]
        client.cookies.set("openworker_ide_key", first_key)
        second = client.get(redirect.headers["location"])
        second_key = second.cookies["openworker_ide_key"]

        assert first.status_code == second.status_code == 200
        assert first_key
        assert second_key == first_key
        set_cookie = second.headers["set-cookie"]
        assert "SameSite=none" in set_cookie
        assert "Secure" in set_cookie
        assert "Partitioned" in set_cookie


def test_ide_proxy_requires_random_key_for_http_and_root_websocket(monkeypatch, tmp_path):
    monkeypatch.setenv("COWORKER_API_TOKEN", "sidecar-token")
    manager = SessionManager(data_dir=tmp_path)
    app = create_app(manager)
    with TestClient(app) as client:
        assert client.get("/v1/sessions/session-1/ide/").status_code == 401
        assert client.get("/vscode-remote-resource").status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/?reconnectionToken=probe"):
                pass


def test_ide_root_websocket_accepts_without_openworker_subprotocol(
    monkeypatch, tmp_path
):
    class FakeUpstream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    manager = SessionManager(data_dir=tmp_path)
    target = SimpleNamespace(
        host=SimpleNamespace(id="rvm"),
        workspace=r"C:\Users\Team",
        client=SimpleNamespace(base_url="https://rvm.example", close=lambda: None),
    )
    manager.rvm_hosts.put(
        RvmHost("rvm", "Remote", "https://rvm.example", workspace=r"C:\Users\Team"),
        "server-token",
    )
    manager.session_store.save(
        SessionRecord("session-1", r"C:\Users\Team", "test", "auto", host_id="rvm")
    )
    monkeypatch.setenv("COWORKER_API_TOKEN", "sidecar-token")
    monkeypatch.setattr(manager, "resolve_remote_target", lambda _session_id: target)
    monkeypatch.setattr(manager.rvm_hosts, "token", lambda _host_id: "server-token")
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(app_module, "rvm_ws_connect", lambda *args, **kwargs: FakeUpstream())

    with TestClient(create_app(manager)) as client:
        bootstrap = client.get(
            "/v1/sessions/session-1/ide/",
            headers={"x-openworker-token": "sidecar-token"},
        )
        assert bootstrap.status_code == 200
        client.cookies.set("openworker_ide_key", bootstrap.cookies["openworker_ide_key"])
        with client.websocket_connect("/?reconnectionToken=probe") as websocket:
            assert websocket.accepted_subprotocol is None
