"""Per-session host bindings and workspace lifecycle.

The desktop may connect to several OpenWorker hosts at once, but a session has
exactly one host and one workspace on that host.  This module deliberately keeps
the state local to a host's data directory; it does not attempt process or
container isolation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _safe_session_id(session_id: str) -> str:
    value = str(session_id).strip()
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError("invalid session id")
    return value


@dataclass(frozen=True)
class SessionWorkspace:
    session_id: str
    path: Path
    repository: Optional[Path] = None
    worktree: bool = False
    branch: Optional[str] = None
    archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "path": str(self.path),
            "repository": str(self.repository) if self.repository else None,
            "worktree": self.worktree,
            "branch": self.branch,
            "archived": self.archived,
        }


class SessionWorkspaceManager:
    """Own session workspace directories beneath ``root/sessions``.

    All paths are checked against the sessions root before they are returned or
    removed.  Repository sessions use ``git worktree`` so archiving never
    manipulates the repository's internal state with a recursive delete.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.sessions_root = self.root / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self._state_path = self.root / "session-workspaces.json"
        self._state = self._load()

    def _load(self) -> dict[str, SessionWorkspace]:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        values = raw.get("sessions", {}) if isinstance(raw, dict) else {}
        if not isinstance(values, dict):
            return {}
        out: dict[str, SessionWorkspace] = {}
        for sid, item in values.items():
            if not isinstance(item, dict):
                continue
            try:
                safe = _safe_session_id(sid)
                path = Path(str(item["path"])).expanduser().resolve()
                if not _inside(path, self.sessions_root):
                    continue
                repository = item.get("repository")
                out[safe] = SessionWorkspace(
                    session_id=safe,
                    path=path,
                    repository=Path(repository).expanduser().resolve()
                    if repository
                    else None,
                    worktree=bool(item.get("worktree")),
                    branch=item.get("branch"),
                    archived=bool(item.get("archived")),
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def _save(self) -> None:
        payload = json.dumps(
            {"sessions": {sid: ws.to_dict() for sid, ws in self._state.items()}},
            indent=2,
        ).encode()
        tmp = self._state_path.with_name(f".{self._state_path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(payload)
        os.chmod(tmp, 0o600)
        tmp.replace(self._state_path)

    def _path(self, session_id: str) -> Path:
        return self.sessions_root / _safe_session_id(session_id)

    def create(
        self, session_id: str, *, repository: str | Path | None = None
    ) -> SessionWorkspace:
        sid = _safe_session_id(session_id)
        target = self._path(sid)
        if not _inside(target, self.sessions_root):
            raise ValueError("session workspace escapes root")
        if sid in self._state and not self._state[sid].archived:
            return self._state[sid]

        repo = Path(repository).expanduser().resolve() if repository else None
        if repo is not None and not (repo / ".git").exists():
            raise ValueError("repository is not a git checkout")
        branch = f"openworker/session-{sid}"
        if target.exists():
            raise FileExistsError(f"workspace already exists: {target}")
        if repo is None:
            target.mkdir(parents=True)
            workspace = SessionWorkspace(sid, target)
        else:
            try:
                add = subprocess.run(
                    ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(target), "HEAD"],
                    capture_output=True,
                    text=True,
                )
                if add.returncode:
                    # An archived session may be recreated. Its branch is still
                    # useful state, so attach a new worktree to that branch.
                    add = subprocess.run(
                        ["git", "-C", str(repo), "worktree", "add", str(target), branch],
                        capture_output=True,
                        text=True,
                    )
                if add.returncode:
                    raise subprocess.CalledProcessError(
                        add.returncode, add.args, output=add.stdout, stderr=add.stderr
                    )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(exc.stderr.strip() or "git worktree add failed") from exc
            workspace = SessionWorkspace(sid, target, repo, True, branch)
        self._state[sid] = workspace
        self._save()
        return workspace

    def attach(self, session_id: str) -> SessionWorkspace:
        sid = _safe_session_id(session_id)
        workspace = self._state.get(sid)
        if workspace is None or workspace.archived:
            raise KeyError(f"unknown session: {sid}")
        if not _inside(workspace.path, self.sessions_root):
            raise ValueError("session workspace escapes root")
        if not workspace.path.is_dir():
            raise FileNotFoundError(str(workspace.path))
        return workspace

    def path_for(self, session_id: str) -> Path:
        return self.attach(session_id).path

    def get(self, session_id: str) -> Optional[SessionWorkspace]:
        """Return managed workspace metadata without exposing internal state."""
        return self._state.get(str(session_id))

    def assert_owned(self, session_id: str, path: str | Path) -> Path:
        workspace = self.attach(session_id)
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = workspace.path / candidate
        candidate = candidate.expanduser().resolve()
        if not _inside(candidate, workspace.path):
            raise PermissionError("path escapes session workspace")
        return candidate

    def archive(self, session_id: str) -> SessionWorkspace:
        workspace = self.attach(session_id)
        if workspace.worktree:
            try:
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(workspace.repository),
                        "worktree",
                        "remove",
                        "--force",
                        str(workspace.path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    exc.stderr.strip() or "git worktree remove failed"
                ) from exc
        elif workspace.path.exists():
            shutil.rmtree(workspace.path)
        archived = SessionWorkspace(
            workspace.session_id,
            workspace.path,
            workspace.repository,
            workspace.worktree,
            workspace.branch,
            True,
        )
        self._state[session_id] = archived
        self._save()
        return archived
