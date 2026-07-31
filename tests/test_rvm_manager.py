from types import SimpleNamespace

from coworker.remote.executor import RvmExecutor
from coworker.remote.hosts import RvmHost
from coworker.server import manager as manager_module
from coworker.server.manager import SessionManager
from coworker.sessions import SessionRecord
from coworker.tools.shell import LocalExecutor


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
        return SimpleNamespace(
            model="model",
            mode=SimpleNamespace(value="interactive"),
            permissions=SimpleNamespace(
                mode=SimpleNamespace(value="interactive"),
                session_allow_tools=set(),
                session_allow_commands=set(),
            ),
            messages=[],
            executor=SimpleNamespace(cwd=kwargs["remote_target"].workspace),
            remote_target=kwargs["remote_target"],
            agent_name="code",
        )

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
    assert manager.session_store.load("selected-session").host_id == "rvm"


def test_remote_session_rejects_local_workspace_for_windows_host(monkeypatch, tmp_path):
    class Client:
        def health(self):
            return {"platform": "windows"}

        def mkdir(self, path):
            return {"ok": True}

        def close(self):
            pass

    manager = SessionManager(data_dir=tmp_path)
    manager.rvm_hosts.put(
        RvmHost("winrvm", "Windows", "http://rvm", platform="windows", workspace=r"C:\Users\Team"),
        "token",
    )
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: Client())
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

    engine = manager.get_engine(
        "windows-session",
        agent="code",
        host_id="winrvm",
        workspace="/home/ubuntu/OpenWorker/windows-session",
    )

    assert engine.remote_target.workspace.startswith(r"C:\Users\Team\.coworker\sessions")
    assert not engine.remote_target.workspace.startswith("/home/")
    assert manager.session_store.load("windows-session").workspace == engine.remote_target.workspace


def test_windows_host_never_accepts_posix_persisted_workspace(monkeypatch, tmp_path):
    class Client:
        def health(self):
            return {"platform": "windows"}

        def mkdir(self, path):
            return {"ok": True}

        def close(self):
            pass

    manager = SessionManager(data_dir=tmp_path)
    manager.rvm_hosts.put(
        RvmHost("winrvm", "Windows", "http://rvm", platform="windows", workspace=r"C:\Users\Team"),
        "token",
    )
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: Client())
    manager.session_store.save(
        SessionRecord(
            session_id="bad-workspace",
            workspace="/home/ubuntu/OpenWorker/bad-workspace",
            model="m",
            mode="interactive",
            host_id="winrvm",
        )
    )
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

    engine = manager.get_engine("bad-workspace", agent="code")

    assert engine.remote_target.workspace.startswith(r"C:\Users\Team\.coworker\sessions")
    assert manager.session_store.load("bad-workspace").workspace == engine.remote_target.workspace


def test_stale_local_engine_is_rebuilt_for_requested_remote_host(monkeypatch, tmp_path):
    class Client:
        def health(self):
            return {"platform": "linux"}

        def mkdir(self, path):
            return {"ok": True}

        def close(self):
            pass

    manager = SessionManager(data_dir=tmp_path)
    manager.rvm_hosts.put(
        RvmHost("rvm", "Remote", "http://rvm", platform="linux", workspace="/remote"),
        "token",
    )
    client = Client()
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: client)
    closed = []
    manager._engines["bound"] = SimpleNamespace(
        remote_target=None,
        executor=SimpleNamespace(close=lambda: closed.append(True)),
    )
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
    engine = manager.get_engine("bound", agent="code", host_id="rvm")
    assert engine.remote_target.host.id == "rvm"
    assert closed == [True]


def test_remote_roots_use_remote_existence_check(monkeypatch, tmp_path):
    class Client:
        def health(self):
            return {"platform": "windows"}

        def exists(self, path):
            return {"exists": True}

        def close(self):
            pass

    manager = SessionManager(data_dir=tmp_path)
    host = RvmHost("winrvm", "Antec", "http://rvm", platform="windows", workspace=r"C:\Users\Team")
    manager.rvm_hosts.put(host, "token")
    client = Client()
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: client)
    manager.session_store.save(
        SessionRecord(
            session_id="remote-roots",
            workspace=r"C:\Users\Team\.coworker\sessions\remote-roots",
            model="m",
            mode="interactive",
            host_id="winrvm",
        )
    )
    roots = manager.get_roots("remote-roots")
    assert roots[0]["path"].startswith(r"C:\Users\Team")
    assert roots[0]["exists"] is True


def test_remote_artifacts_use_rvm_listing(monkeypatch, tmp_path):
    class Client:
        def health(self):
            return {"platform": "windows"}

        def ls(self, path):
            if path.endswith("remote-artifacts"):
                return {"items": [{"name": "report.txt", "dir": False}]}
            return {"items": []}

        def stat(self, path):
            return {"size": 7, "modified_at": 12.5}

        def close(self):
            pass

    manager = SessionManager(data_dir=tmp_path)
    manager.rvm_hosts.put(
        RvmHost("winrvm", "Windows", "http://rvm", platform="windows", workspace=r"C:\Users\Team"),
        "token",
    )
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: Client())
    manager.session_store.save(
        SessionRecord(
            session_id="remote-artifacts",
            workspace=r"C:\Users\Team\.coworker\sessions\remote-artifacts",
            model="m",
            mode="interactive",
            host_id="winrvm",
        )
    )

    artifacts = manager.list_artifacts("remote-artifacts")

    assert artifacts[0]["path"] == "report.txt"
    assert artifacts[0]["abs_path"].endswith(r"\report.txt")


def test_cached_remote_session_rejects_host_marked_offline(tmp_path):
    manager = SessionManager(data_dir=tmp_path)
    host = RvmHost("rvm", "Remote", "http://rvm", platform="linux", workspace="/remote")
    manager.rvm_hosts.put(host, "token")
    manager.session_store.save(
        SessionRecord(
            session_id="offline",
            workspace="/remote/.coworker/sessions/offline",
            model="m",
            mode="interactive",
            host_id="rvm",
        )
    )
    manager.rvm_hosts.set_offline("rvm", True)
    import pytest

    with pytest.raises(manager_module.RvmHostOfflineError, match="marked offline"):
        manager.ensure_remote_available("offline")


def test_remote_session_persists_binding_and_executes_after_reload(monkeypatch, tmp_path):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))

    class Client:
        host_label = "Antec"

        def __init__(self):
            self.files = set()
            self.commands = []

        def health(self):
            return {"platform": "windows", "workspace": r"C:\Users\Team"}

        def info(self):
            return {"hostname": "Antec", "platform": "windows", "arch": "x64", "cpus": 4}

        def read(self, path):
            return {"path": path, "content": ""}

        def mkdir(self, path):
            return {"ok": True}

        def exec_sync(self, command, *, cwd=None, timeout=None, session=None):
            import re

            self.commands.append(command)
            marker = re.search(r"(__COWORKER_RVM_[0-9a-f]+__)", command).group(1)
            if "Set-Content" in command:
                self.files.add(r"C:\Users\Team\.coworker\remote-proof.txt")
                output = ""
            elif "hostname" in command:
                output = "Antec\r\n"
            else:
                output = ""
            return {
                "result": {
                    "stdout": f"{output}{marker}\r\n0\r\n{cwd or r'C:\\Users\\Team'}\r\n",
                    "stderr": "",
                    "exit_code": 0,
                }
            }

        def close(self):
            pass

    class Provider:
        def capabilities(self, model):
            return SimpleNamespace()

    client = Client()
    host = RvmHost(
        "winrvm",
        "Antec",
        "http://rvm",
        platform="windows",
        workspace=r"C:\Users\Team",
    )
    manager = SessionManager(data_dir=tmp_path, provider=Provider())
    manager.rvm_hosts.put(host, "token")
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: client)

    engine = manager.get_engine("remote-proof", agent="code", host_id="winrvm")
    record = manager.session_store.load("remote-proof")
    assert record is not None
    assert record.host_id == "winrvm"
    assert isinstance(engine.executor, RvmExecutor)
    assert not isinstance(engine.executor, LocalExecutor)
    assert engine.remote_target.host.id == "winrvm"

    hostname = engine.executor.run("hostname")
    remote_file = r"C:\Users\Team\.coworker\remote-proof.txt"
    engine.executor.run(f"Set-Content -Path '{remote_file}' -Value 'remote'")
    assert hostname["output"].strip() == "Antec"
    assert remote_file in client.files
    assert not (tmp_path / "remote-proof.txt").exists()

    reloaded = SessionManager(data_dir=tmp_path, provider=Provider())
    reloaded.rvm_hosts.put(host, "token")
    monkeypatch.setattr(reloaded.rvm_hosts, "client", lambda _host_id: client)
    restored = reloaded.get_engine("remote-proof", agent="code")
    assert restored.remote_target.host.id == "winrvm"
    assert isinstance(restored.executor, RvmExecutor)
    assert not isinstance(restored.executor, LocalExecutor)
