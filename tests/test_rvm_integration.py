import json
from pathlib import Path
from types import SimpleNamespace

from coworker.agent import build_engine
from coworker.agents.code import code_agent
from coworker.agents.base import AgentContext
from coworker.catalog import expand
from coworker.permissions import Mode, PermissionEngine
from coworker.remote.hosts import RvmHost, RvmHostStore
from coworker.remote.client import RvmUnauthorizedError, RvmUnreachableError
from coworker.remote.paths import RemotePathStyle
from coworker.remote.tools import RemoteTarget
from coworker.secrets import SecretStore


class FakeRemoteClient:
    host_label = "DevBox"

    def health(self):
        return {"platform": "windows", "workspace": r"C:\Workspace"}

    def info(self):
        return {"hostname": "devbox", "platform": "windows", "arch": "x64", "cpus": 4}

    def read(self, path):
        return {"path": path, "content": "remote conventions"}

    def exec_sync(self, *args, **kwargs):
        return {"result": {"stdout": "", "stderr": "", "exit_code": 0}}


def test_remote_permission_scoping_and_local_regression():
    style = RemotePathStyle("windows")
    remote = PermissionEngine(
        workspace_root=r"C:\Work",
        roots=[{"path": r"C:\Work", "writable": True}],
        path_style=style,
        mode=Mode.AUTO,
    )
    assert remote.evaluate("write_file", {"path": r"c:/work\src\a.py"}).allowed
    assert not remote.evaluate("write_file", {"path": r"C:\Other\a.py"}).allowed

    local_root = Path("/tmp")
    local = PermissionEngine(workspace_root=local_root, mode=Mode.AUTO)
    assert local.evaluate("write_file", {"path": "/tmp/rvm-regression.txt"}).allowed
    assert not local.evaluate("write_file", {"path": "/etc/rvm-regression.txt"}).allowed


def test_catalog_remote_surface_matches_code_capability():
    target = RemoteTarget(
        host=SimpleNamespace(name="DevBox"),
        client=FakeRemoteClient(),
        style=RemotePathStyle("windows"),
        workspace=r"C:\Work",
    )
    remote_context = AgentContext(workspace=r"C:\Work", executor=object(), remote_target=target)
    names = {tool.__name__ for tool in expand(["code_files", "git", "search"], remote_context)}
    assert {"read_file", "list_files", "write_file", "replace_in_file", "apply_patch", "grep", "git_status", "git_diff", "git_log"} <= names
    assert "search_files" not in names


def test_build_engine_remote_uses_remote_executor_and_prompt(monkeypatch, tmp_path):
    target = RemoteTarget(
        host=SimpleNamespace(name="DevBox"),
        client=FakeRemoteClient(),
        style=RemotePathStyle("windows"),
        workspace=r"C:\does-not-exist-on-client",
    )

    class Provider:
        def complete(self, **kwargs):
            raise AssertionError("completion should not run")

        def capabilities(self, model):
            return SimpleNamespace()

    engine = build_engine(
        agent=code_agent(),
        workspace=r"C:\does-not-exist-on-client",
        provider=Provider(),
        remote_target=target,
        secrets=SecretStore(tmp_path / "secrets.json"),
    )
    from coworker.remote.executor import RvmExecutor
    from coworker.tools.shell import LocalExecutor

    assert isinstance(engine.executor, RvmExecutor)
    assert not isinstance(engine.executor, LocalExecutor)
    prompt = str(engine.messages[0].get("content", ""))
    assert "DevBox" in prompt
    assert "remote host" in prompt


def test_host_store_keeps_token_private(tmp_path):
    host_file = tmp_path / "rvm-hosts.json"
    secrets = SecretStore(tmp_path / "secrets.json")
    store = RvmHostStore(host_file, secrets=secrets)
    store.put(RvmHost("h", "DevBox", "http://rvm"), "super-secret", "vnc-secret")
    assert "super-secret" not in host_file.read_text()
    assert oct(host_file.stat().st_mode & 0o777) == "0o600"
    assert "super-secret" in json.dumps(secrets.get("rvm:h"))
    assert store.vnc_password("h") == "vnc-secret"
    assert "super-secret" not in repr(store.get("h"))
    assert "super-secret" not in repr(store.client("h"))


def test_host_store_migrates_desktop_profiles_into_secret_store(tmp_path):
    legacy = tmp_path / "remote-hosts.json"
    legacy.write_text(
        json.dumps(
            {
                "hosts": [
                    {
                        "name": "win-antec",
                        "url": "http://rvm.example",
                        "token": "desktop-token",
                        "vncPassword": "vnc-secret",
                        "offline": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    secrets = SecretStore(tmp_path / "secrets.json")
    store = RvmHostStore(tmp_path / "rvm-hosts.json", secrets=secrets)

    assert store.get("win-antec").base_url == "http://rvm.example"
    assert store.token("win-antec") == "desktop-token"
    assert store.vnc_password("win-antec") == "vnc-secret"
    assert store.get("win-antec").offline is True


def test_host_store_offline_toggle_is_persisted(tmp_path):
    store = RvmHostStore(tmp_path / "rvm-hosts.json", secrets=SecretStore(tmp_path / "secrets.json"))
    store.put(RvmHost("h", "DevBox", "http://rvm"), "token")
    assert store.set_offline("h", True)
    reloaded = RvmHostStore(tmp_path / "rvm-hosts.json", secrets=store.secrets)
    assert reloaded.get("h").offline is True
    assert "desktop-token" not in (tmp_path / "rvm-hosts.json").read_text()


def test_unknown_host_is_hard_failure_without_local_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    from coworker.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path, host_id="missing")
    try:
        manager.get_engine("missing-session", agent="code")
    except ValueError as exc:
        assert "unknown RVM host" in str(exc)
    else:
        raise AssertionError("unknown host unexpectedly fell back to Local")


class FailingHealthClient:
    def __init__(self, error):
        self.error = error
        self.closed = False

    def health(self):
        raise self.error

    def close(self):
        self.closed = True


def test_bound_offline_host_is_clear_session_build_error(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    from coworker.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path, host_id="offline")
    manager.rvm_hosts.put(RvmHost("offline", "Offline VM", "http://rvm"), "token")
    client = FailingHealthClient(RvmUnreachableError("offline"))
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: client)
    try:
        manager.get_engine("offline-session", agent="code")
    except ValueError as exc:
        assert "Offline VM" in str(exc)
        assert "offline or unreachable" in str(exc)
    else:
        raise AssertionError("offline host unexpectedly built a session")
    assert client.closed


def test_bound_unauthorized_host_is_clear_session_build_error(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    from coworker.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path, host_id="unauthorized")
    manager.rvm_hosts.put(RvmHost("unauthorized", "Unauthorized VM", "http://rvm"), "token")
    client = FailingHealthClient(RvmUnauthorizedError("unauthorized"))
    monkeypatch.setattr(manager.rvm_hosts, "client", lambda _host_id: client)
    try:
        manager.get_engine("unauthorized-session", agent="code")
    except ValueError as exc:
        assert "Unauthorized VM" in str(exc)
        assert "unauthorized" in str(exc)
    else:
        raise AssertionError("unauthorized host unexpectedly built a session")
    assert client.closed
