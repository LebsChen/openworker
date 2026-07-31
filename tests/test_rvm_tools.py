import json

from coworker.remote.client import RvmError, RvmUnreachableError
from coworker.remote.paths import RemotePathStyle
from coworker.remote.tools import (
    RemoteTarget,
    remote_environment_context,
    remote_file_tools,
    remote_git_tools,
    remote_search_tools,
)


class FakeClient:
    host_label = "DevBox"

    def __init__(self):
        self.files = {
            "/workspace/main.py": "\n".join(
                ["first", "second", "x" * 600, "fourth", "fifth"]
            )
        }
        self.calls = []
        self.commands = []
        self.fail_read = False
        self.fail_exec = False

    def read(self, path):
        self.calls.append(("read", path))
        if self.fail_read:
            raise RvmError("DevBox: read failed")
        if path not in self.files:
            raise RvmError("DevBox: not found")
        return {"path": path, "content": self.files[path]}

    def write(self, path, content):
        self.calls.append(("write", path, content))
        self.files[path] = content
        return {"path": path}

    def exists(self, path):
        return {"exists": path in self.files}

    def mkdir(self, path):
        self.calls.append(("mkdir", path))
        return {"ok": True}

    def delete(self, path, **kwargs):
        self.calls.append(("delete", path))
        return {"ok": True}

    def ls(self, path):
        entries = {
            "/workspace": [{"name": "main.py", "dir": False}, {"name": "src", "dir": True}],
            "/workspace/src": [
                {"name": "a.py", "dir": False},
                {"name": "b.txt", "dir": False},
            ],
        }
        return {"items": entries.get(path, [])}

    def exec_sync(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if self.fail_exec:
            raise RvmError("DevBox: command failed")
        if "rg " in command:
            return {
                "result": {
                    "stdout": "/workspace/main.py:2:second\n/workspace/src/a.py:1:hit\n",
                    "stderr": "",
                    "exit_code": 0,
                }
            }
        if " log " in command:
            return {"result": {"stdout": "abc\x1fAda\x1f2026-01-01\x1fsubject\n", "stderr": "", "exit_code": 0}}
        if command.startswith("git apply"):
            return {"result": {"stdout": "", "stderr": "", "exit_code": 0}}
        return {"result": {"stdout": "", "stderr": "", "exit_code": 0}}

    def health(self):
        return {"platform": "linux", "host": "devbox", "workspace": "/workspace"}

    def info(self):
        return {"hostname": "devbox", "platform": "linux", "arch": "x64", "cpus": 4, "memory_gb": 8}


def target(client=None, *, style="posix"):
    client = client or FakeClient()
    return RemoteTarget(
        host=type("Host", (), {"name": "DevBox"})(),
        client=client,
        style=RemotePathStyle(style),
        workspace=r"C:\Workspace" if style == "windows" else "/workspace",
    )


def by_name(tools, name):
    return next(tool for tool in tools if tool.__name__ == name)


def test_file_read_windowing_and_mutations():
    client = FakeClient()
    tools = remote_file_tools(target(client))
    read = by_name(tools, "read_file")
    result = read(path="main.py", start_line=2, max_lines=2)
    assert result["path"] == "main.py"
    assert result["start_line"] == 2
    assert result["end_line"] == 3
    assert result["total_lines"] == 5
    assert "second" in result["content"]
    assert "line truncated" in result["content"]
    assert result["note"].startswith("showing lines 2-3 of 5")

    client.fail_read = True
    assert "error" in read(path="main.py")

    client.fail_read = False
    write = by_name(tools, "write_file")
    assert "exists" in write(path="main.py", content="new", overwrite=False)
    assert write(path="new.txt", content="new") == "wrote new.txt"
    assert by_name(tools, "create_directory")(path="new-dir")["ok"] is True
    replace = by_name(tools, "replace_in_file")
    assert "error" in replace(path="main.py", old="missing", new="x")
    assert replace(path="main.py", old="first", new="updated")["replacements"] == 1


def test_list_files_recursion_glob_and_cap():
    client = FakeClient()
    files = by_name(remote_file_tools(target(client)), "list_files")
    assert files(path=".", pattern="*.py", recursive=True, max_results=1) == ["main.py"]
    assert files(path=".", pattern="*.py", recursive=True, max_results=10) == ["main.py", "src/a.py"]


def test_grep_rg_and_fallback_shapes_and_quoting():
    client = FakeClient()
    grep = by_name(remote_search_tools(target(client)), "grep")
    result = grep(pattern="foo's", path="src", glob="*.py", max_results=1)
    assert result["engine"] == "ripgrep"
    assert result["count"] == 1
    assert set(result["matches"][0]) == {"file", "line", "text"}
    command = client.commands[-1][0]
    assert "--max-count 1" in command
    assert RemotePathStyle().quote("foo's") in command

    class MissingRg(FakeClient):
        def exec_sync(self, command, **kwargs):
            self.commands.append((command, kwargs))
            if "rg " in command:
                return {"result": {"stdout": "", "stderr": "not found", "exit_code": 127}}
            return {"result": {"stdout": "/workspace/main.py:4:hit\n", "stderr": "", "exit_code": 0}}

    fallback = MissingRg()
    result = by_name(remote_search_tools(target(fallback)), "grep")(
        pattern="hit", max_results=1
    )
    assert result["engine"] == "python"
    assert "grep -rn" in fallback.commands[-1][0]

    windows = MissingRg()
    by_name(remote_search_tools(target(windows, style="windows")), "grep")(pattern="hit")
    assert "Select-String" in windows.commands[-1][0]


def test_git_tools_commands_and_log_parsing():
    client = FakeClient()
    tools = remote_git_tools(target(client))
    log = by_name(tools, "git_log")
    result = log(max_count=1)
    assert result["count"] == 1
    assert result["commits"][0]["hash"] == "abc"
    assert "-n1" in client.commands[-1][0]

    diff = by_name(tools, "git_diff")
    diff(path="src/a.py", staged=True)
    assert "--staged" in client.commands[-1][0]
    assert "src/a.py" in client.commands[-1][0]

    client.fail_exec = True
    assert "error" in by_name(tools, "git_status")()


def test_patch_conversion_validation_fallback_and_cleanup():
    client = FakeClient()
    tools = remote_file_tools(target(client))
    patch = """*** Begin Patch
*** Update File: main.py
@@
-first
+updated
*** End Patch
"""
    result = by_name(tools, "apply_patch")(patch=patch)
    assert result["file_count"] == 1
    assert any(call[0] == "write" for call in client.calls)
    assert any(call[0] == "delete" for call in client.calls)
    assert "git apply" in client.commands[-1][0]

    escaped = """--- a/../outside
+++ b/../outside
@@ -1 +1 @@
-a
+b
"""
    assert "error" in by_name(tools, "apply_unified_diff")(diff=escaped)

    class Failed(FakeClient):
        def exec_sync(self, command, **kwargs):
            self.commands.append((command, kwargs))
            return {"result": {"stdout": "", "stderr": "bad patch", "exit_code": 1}}

    failed = Failed()
    assert "error" in by_name(remote_file_tools(target(failed)), "apply_patch")(patch=patch)


def test_remote_environment_context_and_offline_degradation():
    client = FakeClient()
    context = remote_environment_context(target(client))
    assert "Platform: linux" in context
    assert "Remote host: DevBox" in context
    assert "Workspace: /workspace" in context

    client.files["/workspace/AGENTS.md"] = "Use pytest."
    assert "Use pytest." in remote_environment_context(target(client))

    class Offline(FakeClient):
        def health(self):
            raise RvmUnreachableError("DevBox is offline")

    context = remote_environment_context(target(Offline()))
    assert "unavailable" in context
