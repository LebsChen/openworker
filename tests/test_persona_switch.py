from __future__ import annotations

from coworker.engine import TurnEngine
from coworker.permissions import Mode
from coworker.providers import AssistantTurn, ProviderClient
from coworker.server import SessionManager
from coworker.server import create_app
from fastapi.testclient import TestClient


class ScriptedProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="ok", finish_reason="stop")

    def capabilities(self, model):
        from coworker.providers import ModelCapabilities

        return ModelCapabilities()


def _manager(tmp_path):
    return SessionManager(workspace=tmp_path, provider=ScriptedProvider())


def test_switch_persona_rebuilds_prompt_preserves_history_todo_and_filters_grants(tmp_path):
    manager = _manager(tmp_path)
    engine = manager.get_engine("switch", workspace=str(tmp_path), agent="code")
    assert engine is not None
    engine.messages.append({"role": "user", "content": "keep this"})
    engine.todo.items = [{"content": "finish", "status": "in_progress"}]
    engine.permissions.allow_tool_for_session("git_status")
    engine.permissions.allow_tool_for_session("run_shell")
    manager.save("switch", engine)
    prior_history = engine.messages[1:].copy()

    replacement, notice, error = manager.switch_persona("switch", "ops")

    assert error is None and replacement is not None
    assert notice == "Persona switched to Ops Coworker"
    assert replacement is manager._engines["switch"]
    assert replacement is not engine
    assert replacement.executor is engine.executor
    assert replacement.remote_target is engine.remote_target
    assert replacement.messages[0]["role"] == "system"
    assert "operations engineer" in replacement.messages[0]["content"]
    assert replacement.messages[1:-1] == prior_history
    assert replacement.todo is engine.todo
    assert replacement.todo.items == [{"content": "finish", "status": "in_progress"}]
    assert "run_shell" in replacement.permissions.session_allow_tools
    assert "git_status" not in replacement.permissions.session_allow_tools
    assert replacement.messages[-1] == {
        "role": "notice",
        "kind": "persona_switch",
        "text": notice,
        "ts": replacement.messages[-1]["ts"],
    }
    assert all(m.get("role") != "notice" for m in replacement._outbound_messages())
    persisted = manager.session_store.load("switch")
    assert persisted.agent == "ops"
    assert persisted.messages[0]["content"] == replacement.messages[0]["content"]


def test_switch_persona_rejects_running_and_pending_sessions(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    engine = manager.get_engine("guarded", workspace=str(tmp_path), agent="code")
    assert engine is not None

    manager.mark_running("guarded")
    _, _, error = manager.switch_persona("guarded", "ops")
    assert "running" in error.lower()
    manager.mark_idle("guarded")

    monkeypatch.setattr(manager.inbox, "pending", lambda session_id: [object()])
    _, _, error = manager.switch_persona("guarded", "ops")
    assert "pending" in error.lower()


def test_switch_persona_rejects_workspace_requirement_mismatch(tmp_path):
    manager = _manager(tmp_path)
    engine = manager.get_engine("chat-session", agent="chat")
    assert engine is not None

    _, _, error = manager.switch_persona("chat-session", "fullstack")

    assert error is not None
    assert "start a new session" in error.lower()
    assert manager._engines["chat-session"] is engine


def test_switch_persona_does_not_materialize_unknown_session(tmp_path):
    manager = _manager(tmp_path)

    replacement, notice, error = manager.switch_persona("missing", "fullstack")

    assert replacement is None and notice is None
    assert error == "unknown session"
    assert manager.session_store.load("missing") is None


def test_switch_persona_accepts_cross_family_with_same_workspace_requirement(tmp_path):
    manager = _manager(tmp_path)
    engine = manager.get_engine("cross-family", workspace=str(tmp_path), agent="code")
    assert engine is not None

    replacement, _, error = manager.switch_persona("cross-family", "ops")

    assert error is None
    assert replacement is not None
    assert replacement.agent_name == "ops"
    assert replacement.permissions.mode is Mode.INTERACTIVE


def test_ws_persona_switch_broadcasts_transition(tmp_path):
    manager = _manager(tmp_path)
    client = TestClient(create_app(manager))

    with client.websocket_connect(
        f"/ws/session/ws-switch?workspace={tmp_path}&agent=code"
    ) as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "set_persona", "persona": "fullstack"})
        changed = ws.receive_json()

    assert changed["type"] == "persona_changed"
    assert changed["data"]["persona"] == "fullstack"
    assert manager.session_store.load("ws-switch").agent == "fullstack"


def test_persona_switch_notice_does_not_block_retry(tmp_path):
    manager = _manager(tmp_path)
    engine = manager.get_engine("retry-switch", workspace=str(tmp_path), agent="code")
    assert engine is not None
    engine._append_notice("error", "provider failed")
    engine._append_notice("persona_switch", "Persona switched to Ops Coworker")
    assert engine._tail_is_retriable_error()
