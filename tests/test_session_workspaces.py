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


def test_archived_repository_session_reuses_branch(tmp_path: Path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )

    manager = SessionWorkspaceManager(tmp_path / "host")
    first = manager.create("session-reused", repository=repo)
    branch = first.branch
    manager.archive("session-reused")
    second = manager.create("session-reused", repository=repo)

    assert second.branch == branch
    assert second.path.exists()
    assert second.worktree


def test_session_manager_wires_workspace_into_tool_boundary(tmp_path: Path):
    import subprocess

    from coworker.server.manager import SessionManager

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    manager = SessionManager(data_dir=tmp_path / "data")
    engine_a = manager.get_engine("session-a", workspace=str(repo), agent="code", isolate=True)
    engine_b = manager.get_engine("session-b", workspace=str(repo), agent="code", isolate=True)

    assert engine_a is not None and engine_b is not None
    assert engine_a.permissions.workspace_root != engine_b.permissions.workspace_root
    assert engine_a.registry.execute("read_file", {"path": str(outside)}) == {
        "error": "path escapes the workspace"
    }
    assert engine_a.registry.execute(
        "read_file", {"path": str(engine_b.permissions.workspace_root / "README.md")}
    ) == {"error": "path escapes the workspace"}


def test_isolation_is_opt_in_and_non_git_targets_get_private_directories(tmp_path: Path):
    from coworker.server.manager import SessionManager

    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "marker.txt").write_text("selected", encoding="utf-8")
    manager = SessionManager(data_dir=tmp_path / "data")

    legacy = manager.get_engine("legacy", workspace=str(selected), agent="code")
    assert legacy is not None
    assert legacy.permissions.workspace_root == selected.resolve()

    isolated = manager.get_engine(
        "isolated", workspace=str(selected), agent="code", isolate=True
    )
    assert isolated is not None
    assert isolated.permissions.workspace_root != selected.resolve()
    assert isolated.permissions.workspace_root.is_relative_to(
        (tmp_path / "data" / "session-workspaces" / "sessions").resolve()
    )
