from pathlib import Path

import pytest

from coworker.session_workspaces import SessionWorkspaceManager


def test_session_workspaces_are_root_scoped(tmp_path: Path):
    manager = SessionWorkspaceManager(tmp_path / "host")
    first = manager.create("session-a")
    second = manager.create("session-b")
    (first.path / "a.txt").write_text("a", encoding="utf-8")
    (second.path / "b.txt").write_text("b", encoding="utf-8")

    assert manager.assert_owned("session-a", "a.txt") == first.path / "a.txt"
    with pytest.raises(PermissionError):
        manager.assert_owned("session-a", second.path / "b.txt")
    with pytest.raises(PermissionError):
        manager.assert_owned("session-a", manager.sessions_root / "session-b")


def test_repository_sessions_use_worktree_and_archive_safely(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
        check=True,
    )

    manager = SessionWorkspaceManager(tmp_path / "host")
    workspace = manager.create("session-git", repository=repo)
    assert workspace.worktree
    assert (workspace.path / ".git").exists()
    assert manager.attach("session-git").path == workspace.path

    manager.archive("session-git")
    assert not workspace.path.exists()
    listed = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(workspace.path) not in listed
