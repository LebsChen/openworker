from __future__ import annotations

import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient

from coworker.remote.paths import RemotePathStyle
from coworker.remote.tools import RemoteTarget
from coworker.server import SessionManager, create_app
from coworker.server.manager import RvmHostOfflineError
from coworker.sessions import SessionRecord


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_local_status_and_diff_include_unicode_and_untracked(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "app.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    (tmp_path / "app.txt").write_text("one\ntwo\n", encoding="utf-8")
    unicode_name = "说明.txt"
    (tmp_path / unicode_name).write_text("新增\n", encoding="utf-8")

    manager = SessionManager(workspace=tmp_path, data_dir=tmp_path.parent / "coworker-data")
    client = TestClient(create_app(manager))
    status = client.get("/v1/sessions/unknown/git/status").json()
    assert status["repository"] is True
    assert status["dirty"] is True
    assert {item["path"] for item in status["files"]} == {"app.txt", unicode_name}
    diff = client.get("/v1/sessions/unknown/git/diff", params={"path": "app.txt"}).json()
    assert diff["ok"] is True
    assert "+two" in diff["diff"]


def test_non_repo_is_explicit_empty_state(tmp_path):
    client = TestClient(create_app(SessionManager(workspace=tmp_path, data_dir=tmp_path.parent / "coworker-data")))
    body = client.get("/v1/sessions/unknown/git/status").json()
    assert body == {
        "repository": False,
        "branch": None,
        "upstream": None,
        "sync": None,
        "dirty": False,
        "untracked": False,
        "files": [],
    }


def test_local_diff_rejects_workspace_escape(tmp_path):
    client = TestClient(create_app(SessionManager(workspace=tmp_path)))
    body = client.get("/v1/sessions/unknown/git/diff", params={"path": "../outside.txt"}).json()
    assert body["ok"] is False
    assert "escapes" in body["error"]


def test_local_status_uses_new_path_for_renames(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "old.txt").write_text("same\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    _git(tmp_path, "mv", "old.txt", "new.txt")

    manager = SessionManager(
        workspace=tmp_path,
        data_dir=tmp_path.parent / "coworker-data",
    )
    status = TestClient(create_app(manager)).get("/v1/sessions/unknown/git/status").json()
    assert len(status["files"]) == 1
    assert status["files"][0]["path"] == "new.txt"
    assert status["files"][0]["status"] == "R"


class FakeGitClient:
    def git_status(self):
        return {
            "branch": "master",
            "has_uncommitted": True,
            "has_untracked": True,
            "in_sync": True,
            "files": [{"status": "??", "path": "demo-中文说明.txt"}],
        }

    def git_changes(self):
        return {
            "branch": "master",
            "files": [{"path": "demo-中文说明.txt", "changeType": "added", "additions": 1, "deletions": 0}],
        }

    def git_file_diff(self, path):
        assert path == "demo-中文说明.txt"
        return {"diff": "+新增\n"}

    def close(self):
        pass


def test_remote_status_and_diff_use_windows_remote_paths(tmp_path):
    manager = SessionManager(data_dir=tmp_path)
    manager.session_store.save(
        SessionRecord(
            session_id="remote",
            workspace=r"C:\Users\Team",
            model="test",
            mode="auto",
            host_id="rvm",
        )
    )
    target = RemoteTarget(
        host=SimpleNamespace(name="Windows"),
        client=FakeGitClient(),
        style=RemotePathStyle("windows"),
        workspace=r"C:\Users\Team",
    )
    manager.resolve_remote_target = lambda *_args, **_kwargs: target
    client = TestClient(create_app(manager))
    status = client.get("/v1/sessions/remote/git/status").json()
    assert status["files"][0]["path"] == "demo-中文说明.txt"
    diff = client.get("/v1/sessions/remote/git/diff", params={"path": "demo-中文说明.txt"}).json()
    assert diff["diff"] == "+新增\n"
    escaped = client.get("/v1/sessions/remote/git/diff", params={"path": r"..\outside.txt"}).json()
    assert escaped["ok"] is False
    assert "escapes" in escaped["error"]


def test_remote_git_offline_returns_explicit_503(tmp_path):
    manager = SessionManager(data_dir=tmp_path)
    manager.session_store.save(
        SessionRecord(
            session_id="offline",
            workspace=r"C:\Users\Team",
            model="test",
            mode="auto",
            host_id="rvm",
        )
    )
    manager.resolve_remote_target = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RvmHostOfflineError("RVM host offline or unreachable")
    )
    client = TestClient(create_app(manager))
    response = client.get("/v1/sessions/offline/git/status")
    assert response.status_code == 503
    assert response.json()["status"] == "offline"
