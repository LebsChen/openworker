from types import SimpleNamespace

from coworker.remote.hosts import RvmHost
from coworker.server import manager as manager_module
from coworker.server.manager import SessionManager


def test_remote_sessions_get_distinct_scratch_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))

    class Client:
        host_label = "host"

        def __init__(self):
            self.created = []

        def health(self):
            return {"platform": "linux"}

        def mkdir(self, path):
            self.created.append(path)
            return {"ok": True}

    client = Client()
    manager = SessionManager(data_dir=tmp_path, host_id="rvm")
    manager.rvm_hosts.put(
        RvmHost("rvm", "Remote", "http://rvm", platform="linux", workspace="/remote"),
        "token",
    )
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda host_id: client)

    captured = []

    def fake_build_engine(**kwargs):
        captured.append(kwargs["remote_target"].workspace)
        return SimpleNamespace()

    monkeypatch.setattr(manager_module, "build_engine", fake_build_engine)
    manager.get_engine("one", agent="code")
    manager.get_engine("two", agent="code")

    assert captured == [
        "/remote/.coworker/sessions/one",
        "/remote/.coworker/sessions/two",
    ]
    assert client.created == captured


def test_new_session_host_can_be_selected_per_connection(monkeypatch, tmp_path):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))

    class Client:
        host_label = "selected"

        def health(self):
            return {"platform": "linux"}

        def mkdir(self, path):
            return {"ok": True}

    client = Client()
    manager = SessionManager(data_dir=tmp_path)
    manager.rvm_hosts.put(
        RvmHost("rvm", "Selected", "http://rvm", platform="linux", workspace="/remote"),
        "token",
    )
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: client)
    monkeypatch.setattr(
        manager_module,
        "build_engine",
        lambda **kwargs: SimpleNamespace(
            model="m",
            permissions=SimpleNamespace(mode=SimpleNamespace(value="interactive")),
            messages=[],
            executor=SimpleNamespace(cwd=kwargs["remote_target"].workspace),
            remote_target=kwargs["remote_target"],
            agent_name="code",
        ),
    )

    engine = manager.get_engine("selected-session", agent="code", host_id="rvm")

    assert engine.remote_target.host.id == "rvm"
    assert manager.session_store.load("selected-session") is None
    manager.save("selected-session", engine)
    assert manager.session_store.load("selected-session").host_id == "rvm"


def test_existing_engine_cannot_cross_local_and_remote_host_bindings(tmp_path):
    manager = SessionManager(data_dir=tmp_path)
    manager._engines["bound"] = SimpleNamespace(remote_target=None)
    with __import__("pytest").raises(ValueError, match="bound to rvm"):
        manager.get_engine("bound", host_id="rvm")
