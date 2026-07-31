"""Read-only Git state and diff normalization for session workspaces."""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
from typing import Any

from .environment import _git
from .remote.client import RvmRemoteError
from .remote.paths import RemotePathError
from .remote.tools import RemoteTarget


def _run_git(workspace: Path, *args: str) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def empty_status() -> dict[str, Any]:
    return {
        "repository": False,
        "branch": None,
        "upstream": None,
        "sync": None,
        "dirty": False,
        "untracked": False,
        "files": [],
    }


def _file(path: str, status: str, additions: int = 0, deletions: int = 0) -> dict[str, Any]:
    return {
        "path": path,
        "status": status,
        "additions": max(0, additions),
        "deletions": max(0, deletions),
    }


def _new_git_path(path: str) -> str:
    return path.rsplit(" -> ", 1)[-1].rsplit(" => ", 1)[-1]


def local_status(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return empty_status()

    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "@{upstream}")
    status_out = _git(root, "-c", "core.quotePath=false", "status", "--porcelain=v1", "--branch") or ""
    numstat_out = _git(root, "-c", "core.quotePath=false", "diff", "HEAD", "--numstat") or ""
    counts: dict[str, tuple[int, int]] = {}
    for line in numstat_out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            additions = int(parts[0]) if parts[0].isdigit() else 0
            deletions = int(parts[1]) if parts[1].isdigit() else 0
        except ValueError:
            continue
        counts[_new_git_path(parts[2])] = (additions, deletions)

    files: list[dict[str, Any]] = []
    for line in status_out.splitlines():
        if not line or line.startswith("##"):
            continue
        if len(line) < 4:
            continue
        code_text, path = line[:2], line[3:]
        if "R" in code_text or "C" in code_text:
            path = _new_git_path(path)
        status = "??" if code_text == "??" else code_text.strip() or code_text
        additions, deletions = counts.get(path, (0, 0))
        files.append(_file(path, status, additions, deletions))
    return {
        "repository": True,
        "branch": branch or None,
        "upstream": upstream or None,
        "sync": _sync_from_status(status_out),
        "dirty": bool(files),
        "untracked": any(item["status"] == "??" for item in files),
        "files": files,
    }


def _sync_from_status(status: str) -> str | None:
    header = next((line for line in status.splitlines() if line.startswith("##")), "")
    if "[ahead " in header and "[behind " in header:
        return "ahead_behind"
    if "[ahead " in header:
        return "ahead"
    if "[behind " in header:
        return "behind"
    if "..." in header:
        return "in_sync"
    return None


def local_diff(workspace: str | Path, path: str) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    candidate = (root / path).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return {"ok": False, "error": "path escapes workspace"}
    relative_text = str(relative)
    code, diff, _ = _run_git(root, "-c", "core.quotePath=false", "diff", "HEAD", "--", relative_text)
    if code == 0 and diff:
        return {"ok": True, "path": path, "diff": diff}
    if not candidate.is_file():
        return {"ok": True, "path": path, "diff": ""}
    try:
        text = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "path": path, "error": "binary file cannot be previewed"}
    lines = difflib.unified_diff(
        [],
        text.splitlines(keepends=True),
        fromfile="/dev/null",
        tofile=f"b/{relative_text}",
    )
    return {"ok": True, "path": path, "diff": "".join(lines)}


def remote_status(target: RemoteTarget) -> dict[str, Any]:
    try:
        status = target.client.git_status()
        changes = target.client.git_changes()
    except RvmRemoteError as exc:
        if exc.status_code in {400, 404}:
            return empty_status()
        raise
    files_by_path: dict[str, dict[str, Any]] = {}
    for item in changes.get("files", []) if isinstance(changes.get("files"), list) else []:
        path = str(item.get("path", ""))
        if not path:
            continue
        files_by_path[path] = _file(
            path,
            str(item.get("changeType") or item.get("status") or "M"),
            int(item.get("additions") or 0),
            int(item.get("deletions") or 0),
        )
    for item in status.get("files", []) if isinstance(status.get("files"), list) else []:
        path = str(item.get("path", ""))
        if not path:
            continue
        existing = files_by_path.get(path)
        if existing:
            existing["status"] = str(item.get("status") or existing["status"])
        else:
            files_by_path[path] = _file(path, str(item.get("status") or "M"))
    short_status = str(status.get("short_status") or "")
    header = next((line for line in short_status.splitlines() if line.startswith("##")), "")
    upstream = status.get("upstream")
    if not upstream and "..." in header:
        upstream = header.split("...", 1)[1].split(" ", 1)[0]
    sync = status.get("sync")
    if not sync:
        sync = _sync_from_status(short_status)
    return {
        "repository": True,
        "branch": status.get("branch") or changes.get("branch"),
        "upstream": upstream,
        "sync": sync or ("in_sync" if status.get("in_sync") else None),
        "dirty": bool(status["has_uncommitted"]) if "has_uncommitted" in status else bool(files_by_path),
        "untracked": bool(status.get("has_untracked")),
        "files": list(files_by_path.values()),
    }


def remote_diff(target: RemoteTarget, path: str) -> dict[str, Any]:
    try:
        remote_path = target.resolve(path)
    except RemotePathError as exc:
        return {"ok": False, "path": path, "error": str(exc)}
    response = target.client.git_file_diff(target.relative(remote_path))
    diff = response.get("diff", response.get("content", ""))
    return {"ok": True, "path": path, "diff": str(diff or "")}
