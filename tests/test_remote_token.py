from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from coworker.server import SessionManager, create_app
from coworker.server.token import resolve_token, token_matches


def test_cli_token_has_highest_priority(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mutually exclusive"):
        resolve_token(
            cli_token="cli-token",
            token_file=token_file,
            environ={"OPENWORKER_TOKEN": "env-token"},
        )

    selected = resolve_token(
        cli_token=" cli-token ",
        environ={"OPENWORKER_TOKEN": "env-token"},
    )
    assert selected.token == "cli-token"
    assert selected.source == "cli"


def test_token_file_then_environment_then_random(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n", encoding="utf-8")
    selected = resolve_token(
        token_file=token_file,
        environ={"OPENWORKER_TOKEN": "env-token"},
    )
    assert (selected.token, selected.source) == ("file-token", "file")

    selected = resolve_token(environ={"OPENWORKER_TOKEN": "env-token"})
    assert (selected.token, selected.source) == ("env-token", "env:OPENWORKER_TOKEN")

    selected = resolve_token(environ={})
    assert len(selected.token) == 64
    assert selected.source == "random"


def test_token_matching_uses_constant_time_comparison(monkeypatch):
    calls = []

    def compare_digest(left, right):
        calls.append((left, right))
        return left == right

    monkeypatch.setattr("coworker.server.token.secrets.compare_digest", compare_digest)
    assert token_matches("expected", "expected")
    assert not token_matches("wrong", "expected")
    assert calls == [("expected", "expected"), ("wrong", "expected")]


def test_http_and_websocket_require_the_same_token(monkeypatch, tmp_path):
    monkeypatch.setenv("COWORKER_API_TOKEN", "known-token")
    client = TestClient(create_app(SessionManager(workspace=tmp_path)))

    assert client.get("/v1/agents").status_code == 401
    assert client.get(
        "/v1/agents", headers={"X-OpenWorker-Token": "wrong-token"}
    ).status_code == 401
    assert client.get(
        "/v1/agents", headers={"X-OpenWorker-Token": "known-token"}
    ).status_code == 200

    with pytest.raises(Exception):
        with client.websocket_connect(
            "/ws/events", subprotocols=["openworker", "wrong-token"]
        ):
            pass

    with client.websocket_connect(
        "/ws/events", subprotocols=["openworker", "known-token"]
    ) as ws:
        assert ws.accepted_subprotocol == "openworker"
