from __future__ import annotations

import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from coworker.remote.hosts import RvmHost
from coworker.remote.paths import RemotePathStyle
from coworker.remote.tools import RemoteTarget
from coworker.server import SessionManager, create_app
from coworker.server.manager import (
    RvmHostOfflineError,
    RvmHostUnauthorizedError,
)
from coworker.sessions import SessionRecord


class FakeUpstream:
    def __init__(self) -> None:
        self.sent: list[bytes | str] = []
        self.history: list[bytes | str] = []
        self.ready = asyncio.Event()
        self.yielded = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def send(self, message):
        self.sent.append(message)
        self.history.append(message)
        if len(self.sent) >= 2:
            self.ready.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.ready.wait()
        if self.sent and not self.yielded:
            self.yielded = True
            self.sent.clear()
            return b"remote-output"
        raise StopAsyncIteration


def _manager(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_API_TOKEN", "browser-secret")
    manager = SessionManager(data_dir=tmp_path)
    host = RvmHost("rvm-1", "Linux RVM", "http://rvm.example", "posix", "/workspace")
    manager.rvm_hosts.put(host, "rvm-secret")
    client = SimpleNamespace(base_url=host.base_url)
    target = RemoteTarget(
        host=host,
        client=client,
        style=RemotePathStyle("posix"),
        workspace="/workspace/session-1",
    )
    manager.resolve_remote_target = lambda *_args, **_kwargs: target
    return manager


def test_pty_proxy_auth_and_transparent_framing(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    upstream = FakeUpstream()
    observed = {}

    def connect(url, **kwargs):
        observed["url"] = url
        observed["headers"] = kwargs["additional_headers"]
        observed["ping_interval"] = kwargs["ping_interval"]
        return upstream

    monkeypatch.setattr("coworker.server.app.rvm_ws_connect", connect)
    with TestClient(create_app(manager)) as client:
        with client.websocket_connect(
            "/ws/rvm/pty/session-1?cols=120&rows=40",
            subprotocols=["openworker", "browser-secret"],
        ) as socket:
            socket.send_bytes(b"stdin")
            socket.send_text('{"type":"resize","cols":120,"rows":40}')
            assert socket.receive_bytes() == b"remote-output"

    query = parse_qs(urlsplit(observed["url"]).query)
    assert query == {"cols": ["120"], "rows": ["40"], "cwd": ["/workspace/session-1"]}
    assert observed["headers"] == {"Authorization": "Bearer rvm-secret"}
    assert observed["ping_interval"] is None
    assert "rvm-secret" not in observed["url"]
    assert upstream.history == [b"stdin", '{"type":"resize","cols":120,"rows":40}']


def test_pty_proxy_rejects_browser_auth(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    with TestClient(create_app(manager)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/rvm/pty/session-1",
                subprotocols=["openworker", "wrong"],
            ):
                pass


def test_pty_proxy_unknown_host_never_creates_local_shell(tmp_path, monkeypatch):
    manager = SessionManager(data_dir=tmp_path)
    manager.session_store.save(
        SessionRecord(
            session_id="s",
            workspace="/workspace",
            model="test",
            mode="auto",
            host_id="missing",
        )
    )
    with TestClient(create_app(manager)) as client:
        with client.websocket_connect("/ws/rvm/pty/s?agent=cowork") as socket:
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_text()
    assert error.value.reason == "Unknown RVM host"
    assert manager.session_store.load("stray") is None


def test_pty_proxy_unknown_session_never_materializes_session(tmp_path):
    manager = SessionManager(data_dir=tmp_path)
    with TestClient(create_app(manager)) as client:
        with client.websocket_connect("/ws/rvm/pty/not-created?agent=cowork") as socket:
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_text()
    assert error.value.reason == "Unknown session"
    assert manager.session_store.load("not-created") is None


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("RVM host Linux RVM is offline or unreachable", "RVM host offline or unreachable"),
        ("RVM host Linux RVM is unauthorized", "RVM host unauthorized"),
    ],
)
def test_pty_proxy_host_health_failures_are_explicit(
    tmp_path, monkeypatch, message, reason
):
    manager = SessionManager(data_dir=tmp_path)
    failure = (
        RvmHostOfflineError(message)
        if "offline" in message
        else RvmHostUnauthorizedError(message)
    )
    manager.resolve_remote_target = lambda *_args, **_kwargs: (_ for _ in ()).throw(failure)
    with TestClient(create_app(manager)) as client:
        with client.websocket_connect("/ws/rvm/pty/s") as socket:
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_text()
    assert error.value.reason == reason
