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
