import json

import httpx
import pytest

from coworker.remote.client import (
    RvmClient,
    RvmMalformedResponseError,
    RvmTimeoutError,
    RvmUnauthorizedError,
    RvmUnreachableError,
)


def test_client_maps_routes_and_never_exposes_token():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"platform": "linux"})
        if request.url.path == "/api/exec-sync":
            return httpx.Response(200, json={"status": "completed", "result": {"stdout": "", "stderr": "", "exit_code": 0}})
        return httpx.Response(200, json={})

    client = RvmClient("http://rvm.example/", "secret-token", host_label="DevBox", transport=httpx.MockTransport(handler))
    assert client.health()["platform"] == "linux"
    client.exec_sync("pwd", cwd="/workspace", timeout=3, session="s", env={"A": "b"})
    request = seen[-1]
    assert request.method == "POST"
    assert request.url.path == "/api/exec-sync"
    assert request.headers["authorization"] == "Bearer secret-token"
    import json
    assert json.loads(request.content)["session"] == "s"
    assert "secret-token" not in repr(client)


def test_client_distinguishes_auth_and_network_errors():
    auth = RvmClient("http://rvm", "secret", host_label="DevBox", transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "unauthorized"})))
    with pytest.raises(RvmUnauthorizedError) as exc:
        auth.info()
    assert "secret" not in str(exc.value)

    def fail(request):
        raise httpx.ConnectError("no route", request=request)

    offline = RvmClient("http://rvm", "secret", host_label="DevBox", transport=httpx.MockTransport(fail))
    with pytest.raises(RvmUnreachableError, match="DevBox"):
        offline.info()


def test_client_maps_all_routes_and_storage_payloads():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"stdout": "", "stderr": "", "exit_code": 0}})

    client = RvmClient("http://rvm", "secret", transport=httpx.MockTransport(handler))
    client.info()
    client.read("/a")
    client.write("/a", "body")
    client.ls("/a")
    client.stat("/a")
    client.mkdir("/a")
    client.exists("/a")
    client.delete("/a", recursive=False)
    client.rename("/a", "/b")
    expected = [
        ("GET", "/api/info", {}),
        ("POST", "/api/read", {"path": "/a"}),
        ("POST", "/api/write", {"path": "/a", "content": "body"}),
        ("POST", "/api/ls", {"path": "/a"}),
        ("POST", "/api/storage/stat", {"path": "/a"}),
        ("POST", "/api/storage/mkdir", {"path": "/a"}),
        ("POST", "/api/storage/exists", {"path": "/a"}),
        ("POST", "/api/storage/delete", {"path": "/a", "recursive": False}),
        ("POST", "/api/storage/rename", {"from": "/a", "to": "/b"}),
    ]
    for request, (method, path, body) in zip(seen, expected):
        assert (request.method, request.url.path) == (method, path)
        if body:
            import json
            assert json.loads(request.content) == body
        assert "secret" not in repr(request)


def test_client_maps_screenshot_and_computer_routes():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/screenshot":
            return httpx.Response(200, json={"image": "abc", "format": "png"})
        if request.url.path == "/mcp":
            body = json.loads(request.content)
            name = body["params"]["name"]
            if name == "browser_navigate":
                result = {"url": body["params"]["arguments"]["url"], "result": {}}
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": json.dumps(result)}]}})
            if name == "browser_eval":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": '{"result":{"value":"Example"}}'}]}})
            if name == "browser_screenshot":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "image", "data": "png-data", "mimeType": "image/png"}]}})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": "Browser closed"}]}})
        return httpx.Response(200, json={"ok": True})

    client = RvmClient(
        "http://rvm", "secret", transport=httpx.MockTransport(handler)
    )
    assert client.screenshot() == {"image": "abc", "format": "png"}
    assert client.computer(action="left_click", coordinate=[1, 2]) == {"ok": True}
    assert client.computer(
        actions=[{"action": "mouse_move", "coordinate": [1, 2]}]
    ) == {"ok": True}
    assert client.browser_navigate("https://example.com")["url"] == "https://example.com"
    assert client.browser_eval("document.title")["result"]["value"] == "Example"
    assert client.browser_screenshot() == {"image": "png-data", "format": "png"}
    assert client.browser_close()["ok"] is True
    assert seen[0].content == b"{}"
    assert seen[1].content == b'{"action":"left_click","coordinate":[1,2]}'
    assert seen[2].content == b'{"actions":[{"action":"mouse_move","coordinate":[1,2]}]}'
    assert all(request.headers["authorization"] == "Bearer secret" for request in seen)
    mcp = [request for request in seen if request.url.path == "/mcp"]
    assert all(request.headers["authorization"] == "Bearer secret" for request in mcp)
    assert all("secret" not in repr(request) for request in mcp)


def test_client_classifies_timeout_and_malformed_json_without_token():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    timed = RvmClient("http://rvm", "top-secret", transport=httpx.MockTransport(timeout))
    with pytest.raises(RvmTimeoutError) as exc:
        timed.info()
    assert "top-secret" not in str(exc.value)

    malformed = RvmClient(
        "http://rvm",
        "top-secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="no json")),
    )
    with pytest.raises(RvmMalformedResponseError) as exc:
        malformed.info()
    assert "top-secret" not in str(exc.value)
