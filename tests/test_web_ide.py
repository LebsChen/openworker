from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from coworker.server import app as app_module
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
    monkeypatch.setattr(manager, "resolve_remote_target", lambda _session_id: target)
    monkeypatch.setattr(manager.rvm_hosts, "token", lambda _host_id: "server-token")
    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.requests.clear()

    with TestClient(create_app(manager)) as client:
        response = client.get("/v1/sessions/session-1/ide/")
        assert response.status_code == 200
        assert response.text == "<html>IDE</html>"
        assert "server-token" not in response.text
        assert "server-token" not in response.headers.get("location", "")
        asset = client.get("/out/static.js")
        assert asset.status_code == 200
        assert asset.content == b"asset"
        assert client.get("/ide/static/remoteEntry.js").status_code == 200
        assert client.get("/ide/%2E%2E/secret").status_code == 400

    assert any("tkn=server-token" in url for url in FakeAsyncClient.requests)
