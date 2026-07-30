"""Remote counterparts of the coding tools, using only the RVM HTTP API."""

from __future__ import annotations

import fnmatch
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import aisuite as ai

from .client import RvmClient, RvmError
from .paths import RemotePathError, RemotePathStyle

_DEFAULT_MAX_LINES = 2000
_MAX_LINE_CHARS = 500


@dataclass
class RemoteTarget:
    host: Any
    client: RvmClient
    style: RemotePathStyle
    workspace: str
    roots: list[Any] | None = None

    @staticmethod
    def _root_path(root: Any) -> str:
        if isinstance(root, dict):
            return str(root.get("path", ""))
        return str(getattr(root, "path", root))

    def resolve(self, path: str) -> str:
        if self.style.is_absolute(path):
            candidate = self.style.normalize(path)
        else:
            candidate = self.style.join(self.workspace, path)
        roots = self.roots or [self.workspace]
        if not any(self.style.is_under(self._root_path(r), candidate) for r in roots):
            raise RemotePathError("path escapes the workspace")
        return candidate

    def relative(self, path: str) -> str:
        normalized = self.style.normalize(path)
        roots = self.roots or [self.workspace]
        for root in roots:
            root_path = self._root_path(root)
            if self.style.is_under(root_path, normalized):
                return self.style.relative(root_path, normalized)
        return normalized


def remote_environment_context(target: RemoteTarget) -> str:
    """Build prompt context from remote APIs without touching the client filesystem."""
    lines = [
        f"Workspace: {target.workspace}",
        f"Remote host: {getattr(target.host, 'name', target.client.host_label)}",
    ]
    try:
        health = target.client.health()
        info = target.client.info()
        for key, label in (
            ("platform", "Platform"),
            ("hostname", "Hostname"),
            ("arch", "Architecture"),
            ("cpu", "CPU"),
            ("cpus", "CPUs"),
            ("memory", "Memory"),
            ("memory_gb", "Memory (GB)"),
            ("shell", "Shell"),
        ):
            value = info.get(key, health.get(key))
            if value not in (None, ""):
                lines.append(f"{label}: {value}")
        if "shell" not in info and "shell" not in health:
            lines.append(
                "Shell: PowerShell"
                if target.style.name == "windows"
                else "Shell: POSIX shell"
            )
        capabilities = health.get("capabilities")
        if capabilities:
            lines.append(f"Capabilities: {capabilities}")
    except RvmError as exc:
        lines.append(f"Remote host status: unavailable ({exc})")

    for filename in ("AGENTS.md", "CLAUDE.md"):
        try:
            data = target.client.read(target.style.join(target.workspace, filename))
            content = str(data.get("content") or "").strip()
            if content:
                lines.append(f"<remote {filename}>\n{content}\n</remote {filename}>")
        except (RvmError, RemotePathError):
            continue
    return (
        "Remote environment (snapshot from session start):\n<environment>\n"
        + "\n".join(lines)
        + "\n</environment>\n"
        f"Workspace lives on remote host {getattr(target.host, 'name', target.client.host_label)}. "
        "All shell and file tools operate on that host; do not assume the client filesystem "
        "contains the workspace."
    )


def _error(exc: Exception) -> dict[str, str]:
    return {"error": str(exc)}


def _codex_to_unified(patch: str) -> str:
    lines = patch.splitlines(keepends=True)
    if not lines or lines[0].strip() != "*** Begin Patch" or lines[-1].strip() != "*** End Patch":
        return patch
    out: list[str] = []
    i = 1
    while i < len(lines) - 1:
        line = lines[i].rstrip("\r\n")
        if not line:
            i += 1
            continue
        if line.startswith("*** Add File: "):
            path = line.removeprefix("*** Add File: ").strip()
            out += [f"diff --git a/{path} b/{path}\n", "--- /dev/null\n", f"+++ b/{path}\n"]
            i += 1
            content: list[str] = []
            while i < len(lines) - 1 and not lines[i].startswith("*** "):
                current = lines[i]
                if not current.startswith("+"):
                    raise ValueError(f"invalid add-file patch line: {current.rstrip()}")
                content.append(current[1:])
                i += 1
            out.append(f"@@ -0,0 +1,{len(content)} @@\n")
            out.extend(content)
            continue
        if line.startswith("*** Delete File: "):
            path = line.removeprefix("*** Delete File: ").strip()
            out += [f"diff --git a/{path} b/{path}\n", f"--- a/{path}\n", "+++ /dev/null\n"]
            i += 1
            continue
        if line.startswith("*** Update File: "):
            old = line.removeprefix("*** Update File: ").strip()
            i += 1
            new = old
            if i < len(lines) - 1 and lines[i].startswith("*** Move to: "):
                new = lines[i].removeprefix("*** Move to: ").strip()
                i += 1
            out += [f"diff --git a/{old} b/{new}\n", f"--- a/{old}\n", f"+++ b/{new}\n"]
            while i < len(lines) - 1 and not lines[i].startswith("*** "):
                out.append(lines[i])
                i += 1
            continue
        raise ValueError(f"invalid patch directive: {line}")
    return "".join(out)


def _apply_remote_diff(target: RemoteTarget, diff: str) -> dict[str, Any]:
    unified = _codex_to_unified(diff)
    paths = re.findall(
        r"^(?:\+\+\+|---) (?:[ab]/)?([^\t\r\n]+)", unified, re.MULTILINE
    )
    remote_path = target.style.join(
        target.workspace, f".coworker/tmp/patch-{uuid.uuid4().hex}.diff"
    )
    try:
        for path in paths:
            if path != "/dev/null":
                target.resolve(path)
        target.client.mkdir(target.style.join(target.workspace, ".coworker/tmp"))
        target.client.write(remote_path, unified)
        if target.style.name == "windows":
            q = target.style.quote(remote_path)
            command = (
                f"git apply {q}; if ($LASTEXITCODE -ne 0) "
                f"{{ patch --batch -p1 < {q} }}"
            )
        else:
            q = target.style.quote(remote_path)
            command = f"git apply {q} || patch --batch -p1 < {q}"
        response = target.client.exec_sync(command, cwd=target.workspace)
        result = response.get("result", {})
        output = str(result.get("stdout") or "") + str(result.get("stderr") or "")
        code = result.get("exit_code")
        if code not in (0, None):
            return {"error": output or f"remote patch failed with exit code {code}"}
        return {
            "changed_files": [
                target.relative(path) for path in dict.fromkeys(paths) if path != "/dev/null"
            ],
            "added_files": [],
            "deleted_files": [],
            "file_count": len(dict.fromkeys(paths)),
            "hunk_count": unified.count("\n@@"),
        }
    except (RvmError, RemotePathError, ValueError) as exc:
        return _error(exc)
    finally:
        try:
            target.client.delete(remote_path)
        except RvmError:
            pass


def remote_file_tools(target: RemoteTarget, *, repo_oriented: bool = True) -> list:
    def read_file(
        path: str,
        start_line: int = 1,
        max_lines: int = _DEFAULT_MAX_LINES,
    ) -> dict[str, Any] | str:
        start = start_line if isinstance(start_line, int) and start_line > 0 else 1
        n = min(max_lines if isinstance(max_lines, int) and max_lines > 0 else _DEFAULT_MAX_LINES, _DEFAULT_MAX_LINES)
        try:
            raw = target.client.read(target.resolve(path))
            if not repo_oriented:
                return str(raw.get("content") or "")
            lines = str(raw.get("content") or "").splitlines()
            selected = []
            for i, line in enumerate(lines, 1):
                if i < start or len(selected) >= n:
                    continue
                if len(line) > _MAX_LINE_CHARS:
                    line = line[:_MAX_LINE_CHARS] + "… (line truncated)"
                selected.append(f"{i:>6}\t{line}")
            end = start + len(selected) - 1 if selected else start - 1
            result: dict[str, Any] = {
                "path": target.relative(raw.get("path", target.resolve(path))),
                "start_line": start, "end_line": end, "total_lines": len(lines),
                "content": "\n".join(selected),
            }
            if end < len(lines):
                result["note"] = f"showing lines {start}-{end} of {len(lines)}; call again with start_line={end + 1} to continue"
            return result
        except (RvmError, RemotePathError) as exc:
            return _error(exc)

    def list_files(
        path: str = ".",
        pattern: str = "*",
        recursive: bool = True,
        max_results: int = 100,
    ) -> list[str] | list[dict[str, str]]:
        try:
            root = target.resolve(path)
            out: list[str] = []
            pending = [root]
            while pending and len(out) < max_results:
                current = pending.pop(0)
                data = target.client.ls(current)
                for item in data.get("items", []):
                    name = str(item.get("name", ""))
                    child = target.style.join(current, name)
                    if item.get("dir") and recursive:
                        pending.append(child)
                    elif not item.get("dir") and _fnmatch(name, pattern):
                        out.append(target.relative(child))
                        if len(out) >= max_results:
                            break
            return out
        except (RvmError, RemotePathError) as exc:
            return [_error(exc)]  # type: ignore[list-item]

    def read_file_lines(path: str, start_line: int = 1, max_lines: int = 100) -> dict[str, object]:
        if not repo_oriented:
            try:
                resolved = target.resolve(path)
                content = str(target.client.read(resolved).get("content") or "")
                lines = content.splitlines()
                selected = lines[start_line - 1 : start_line - 1 + max_lines]
                return {
                    "path": target.relative(resolved),
                    "start_line": start_line,
                    "end_line": start_line + len(selected) - 1 if selected else start_line - 1,
                    "total_lines": len(lines),
                    "content": "\n".join(selected),
                }
            except (RvmError, RemotePathError) as exc:
                return _error(exc)
        result = read_file(path, start_line=start_line, max_lines=max_lines)
        if "error" in result:
            return result
        return {
            "path": result["path"],
            "start_line": result["start_line"],
            "end_line": result["end_line"],
            "total_lines": result["total_lines"],
            "lines": str(result["content"]).splitlines(),
        }

    def write_file(path: str, content: str, overwrite: bool = True) -> str:
        try:
            resolved = target.resolve(path)
            if not overwrite and bool(target.client.exists(resolved).get("exists")):
                return f"file exists: {path}"
            target.client.write(resolved, content)
            return f"wrote {path}"
        except (RvmError, RemotePathError) as exc:
            return str(exc)

    def replace_in_file(path: str, old: str, new: str, expected_replacements: int = 1) -> dict[str, Any]:
        try:
            resolved = target.resolve(path)
            content = str(target.client.read(resolved).get("content") or "")
            count = content.count(old)
            if count != expected_replacements:
                return {"error": f"expected {expected_replacements} replacements, found {count}"}
            target.client.write(resolved, content.replace(old, new))
            return {"ok": True, "path": path, "replacements": count}
        except (RvmError, RemotePathError) as exc:
            return _error(exc)

    def create_directory(path: str) -> dict[str, Any]:
        try:
            return target.client.mkdir(target.resolve(path))
        except (RvmError, RemotePathError) as exc:
            return _error(exc)

    def apply_unified_diff(diff: str) -> dict[str, Any]:
        return _apply_remote_diff(target, diff)

    def apply_patch(patch: str) -> dict[str, Any]:
        return _apply_remote_diff(target, patch)

    tools = [
        _wrap(read_file, "filesystem", "low", False, capabilities=["read"]),
        _wrap(list_files, "filesystem", "low", False, capabilities=["list_files"]),
    ]
    if not repo_oriented:
        tools.append(_wrap(read_file_lines, "filesystem", "low", False, capabilities=["read_file_lines"]))
    tools.extend([
        _wrap(write_file, "filesystem", "medium", True, capabilities=["write_file"]),
        _wrap(replace_in_file, "filesystem", "medium", True, capabilities=["edit_file"]),
        _wrap(create_directory, "filesystem", "medium", True, capabilities=["create_directory"]),
        _wrap(apply_unified_diff, "filesystem", "medium", True, capabilities=["apply_patch"]),
        _wrap(apply_patch, "filesystem", "medium", True, capabilities=["apply_patch"]),
    ])
    return tools


def remote_search_tools(target: RemoteTarget) -> list:
    schema = {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search the workspace for a regular-expression pattern and return matching lines as file:line:text. Read-only.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "glob": {"type": "string"}, "max_results": {"type": "integer"},
            }, "required": ["pattern"]},
        },
    }

    def grep(pattern: str, path: str = ".", glob: Optional[str] = None, max_results: int = 100) -> dict[str, Any]:
        try:
            root = target.resolve(path)
            n = min(max_results if isinstance(max_results, int) and max_results > 0 else 100, 1000)
            rg = "rg --line-number --no-heading --color=never"
            cmd = f"{rg} --max-count {n}"
            if glob:
                cmd += f" --glob {shell_quote(glob, target.style)}"
            cmd += f" {shell_quote(pattern, target.style)} {shell_quote(root, target.style)}"
            response = target.client.exec_sync(cmd, cwd=target.workspace)
            result = response.get("result", {})
            text = str(result.get("stdout") or "") + str(result.get("stderr") or "")
            if result.get("exit_code") not in (0, 1):
                if target.style.name == "windows":
                    command = (
                        f"Get-ChildItem -LiteralPath {shell_quote(root, target.style)} -Recurse -File "
                        f"| Select-String -Pattern {shell_quote(pattern, target.style)} "
                        "| ForEach-Object { \"$($_.Path):$($_.LineNumber):$($_.Line)\" }"
                    )
                else:
                    command = (
                        f"grep -rn --exclude-dir=.git --exclude-dir=node_modules "
                        f"-e {shell_quote(pattern, target.style)} {shell_quote(root, target.style)}"
                    )
                fallback = target.client.exec_sync(command, cwd=target.workspace)
                fallback_result = fallback.get("result", {})
                text = str(fallback_result.get("stdout") or "")
                engine = "python"
            else:
                engine = "ripgrep"
            matches = []
            for line in text.splitlines():
                parts = line.split(":", 2)
                if len(parts) == 3 and parts[1].isdigit():
                    try:
                        rel = target.relative(parts[0])
                    except RemotePathError:
                        rel = parts[0]
                    matches.append({"file": rel, "line": int(parts[1]), "text": parts[2][:300]})
                    if len(matches) >= n:
                        break
            return {"engine": engine, "count": len(matches), "matches": matches}
        except (RvmError, RemotePathError) as exc:
            return _error(exc)

    fn = _wrap(grep, "search", "low", False)
    fn.__coworker_schema__ = schema
    return [fn]


def remote_git_tools(target: RemoteTarget) -> list:
    def git_status() -> dict[str, Any]:
        return _git(target, ["status", "--short", "--branch"])

    def git_diff(path: Optional[str] = None, staged: bool = False) -> dict[str, Any]:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args += ["--", target.resolve(path)]
        return _git(target, args)

    def git_log(path: Optional[str] = None, max_count: int = 20) -> dict[str, Any]:
        args = ["log", f"-n{min(max_count if max_count > 0 else 20, 200)}", "--pretty=format:%h%x1f%an%x1f%ad%x1f%s", "--date=short"]
        if path:
            args += ["--", target.resolve(path)]
        result = _git(target, args)
        if "error" in result:
            return result
        commits = []
        for line in str(result.get("stdout") or "").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append({"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]})
        return {"count": len(commits), "commits": commits}

    return [_wrap(git_status, "git", "low", False), _wrap(git_diff, "git", "low", False), _wrap(git_log, "git", "low", False)]


def _git(target: RemoteTarget, args: list[str]) -> dict[str, Any]:
    try:
        command = "git -C " + shell_quote(target.workspace, target.style) + " " + " ".join(
            shell_quote(x, target.style) for x in args
        )
        response = target.client.exec_sync(command, cwd=target.workspace)
        result = response.get("result", {})
        output = str(result.get("stdout") or "") + str(result.get("stderr") or "")
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        max_output = 20_000
        clipped_stdout = stdout if len(stdout) <= max_output else stdout[: max_output - 3] + "..."
        clipped_stderr = stderr if len(stderr) <= max_output else stderr[: max_output - 3] + "..."
        return {
            "command": command,
            "exit_code": result.get("exit_code"),
            "stdout": clipped_stdout,
            "stderr": clipped_stderr,
            "truncated": len(stdout) != len(clipped_stdout) or len(stderr) != len(clipped_stderr),
        }
    except (RvmError, RemotePathError) as exc:
        return _error(exc)


def _wrap(
    fn: Any,
    category: str,
    risk_level: str,
    approval: bool,
    *,
    capabilities: list[str] | None = None,
) -> Any:
    wrapped = ai.tool(fn, metadata=ai.ToolMetadata(
        category=category, risk_level=risk_level, requires_approval=approval,
        capabilities=capabilities or [fn.__name__],
    ))
    wrapped.__name__ = fn.__name__
    return wrapped


def _fnmatch(value: str, pattern: str) -> bool:
    return fnmatch.fnmatch(value, pattern or "*")


def shell_quote(value: str, style: RemotePathStyle | None = None) -> str:
    return (style or RemotePathStyle()).quote(value)
