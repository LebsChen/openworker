import json

from coworker.remote.client import RvmError, RvmUnreachableError
from coworker.remote.paths import RemotePathStyle
from coworker.remote.tools import (
    RemoteTarget,
    remote_environment_context,
    remote_browser_tools,
    remote_computer_tools,
    remote_file_tools,
    remote_git_tools,
    remote_lsp_tools,
    remote_search_tools,
)
from coworker.permissions import Mode, PermissionEngine


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
        return {
            "platform": "linux",
            "host": "devbox",
            "workspace": "/workspace",
            "capabilities": ["screenshot", "computer_use"],
        }

    def browser_navigate(self, url):
        self.calls.append(("browser_navigate", url))
        return {"url": url, "result": {}}

    def browser_eval(self, expression):
        self.calls.append(("browser_eval", expression))
        return {"result": {"value": "Example"}}

    def browser_screenshot(self):
        self.calls.append(("browser_screenshot",))
        return {"image": "abc", "format": "png"}

    def browser_close(self):
        self.calls.append(("browser_close",))
        return {"ok": True}

    def screenshot(self):
        self.calls.append(("screenshot",))
        return {"image": "abc", "format": "png"}

    def computer(self, **body):
        self.calls.append(("computer", body))
        return {"ok": True, **body}

    def info(self):
        return {"hostname": "devbox", "platform": "linux", "arch": "x64", "cpus": 4, "memory_gb": 8}

    def lsp(self, **arguments):
        self.calls.append(("lsp", arguments))
        if arguments["op"] == "hover":
            return {"contents": [{"language": "python", "value": "str"}]}
        if arguments["op"] == "definition":
            return [{"uri": "file:///workspace/lib.py", "range": {"start": {"line": 4, "character": 2}}}]
        if arguments["op"] == "references":
            return [
                {"uri": "file:///workspace/main.py", "range": {"start": {"line": 0, "character": 0}}},
                {"uri": "file:///workspace/lib.py", "range": {"start": {"line": 1, "character": 1}}},
            ]
        if arguments["op"] == "documentSymbol":
            return [{"name": "main", "kind": 12, "uri": "file:///workspace/main.py", "range": {"start": {"line": 0, "character": 0}}, "children": []}]
        return {"uri": "file:///workspace/main.py", "diagnostics": [{"range": {"start": {"line": 2, "character": 3}}, "message": "bad", "severity": 1}]}


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


def test_computer_tools_support_single_and_batched_actions():
    client = FakeClient()
    tools = remote_computer_tools(target(client))
    screenshot = by_name(tools, "screenshot")
    computer = by_name(tools, "computer")
    assert screenshot()["format"] == "png"
    assert computer(action="resolution")["action"] == "resolution"
    actions = [{"action": "mouse_move", "coordinate": [10, 20]}, {"action": "left_click"}]
    assert computer(actions=actions)["actions"] == actions
    assert ("screenshot",) in client.calls


def test_computer_tools_are_capability_gated():
    client = FakeClient()
    remote = target(client)
    remote.capabilities = {"screenshot"}
    assert [tool.__name__ for tool in remote_computer_tools(remote)] == ["screenshot"]
    remote.capabilities = {"computer_use"}
    assert [tool.__name__ for tool in remote_computer_tools(remote)] == ["computer"]


def test_browser_tools_are_capability_gated_and_validate_schemes():
    client = FakeClient()
    remote = target(client)
    remote.capabilities = {"screenshot", "computer_use"}
    assert remote_browser_tools(remote) == []
    remote.capabilities = {"browser_cdp"}
    tools = remote_browser_tools(remote)
    navigate = by_name(tools, "browser_navigate")
    evaluate = by_name(tools, "browser_eval")
    screenshot = by_name(tools, "browser_screenshot")
    assert "error" in navigate("file:///etc/passwd")
    assert "error" in navigate("data:text/html,hello")
    assert navigate("https://example.com")["url"] == "https://example.com"
    assert evaluate("document.title", "https://example.com")["result"]["value"] == "Example"
    assert "error" in evaluate("document.title", "https://other.example")
    assert screenshot()["format"] == "png"


def test_browser_eval_requires_approval_or_is_read_only_denied():
    remote = target(FakeClient())
    remote.capabilities = {"browser_cdp"}
    metadata = by_name(remote_browser_tools(remote), "browser_eval").__aisuite_tool_metadata__
    args = {"expression": "document.cookie", "target_url": "https://example.com"}
    interactive = PermissionEngine("/workspace", mode=Mode.INTERACTIVE)
    assert interactive.evaluate("browser_eval", args, metadata).needs_user
    custom = PermissionEngine("/workspace", mode=Mode.CUSTOM)
    assert custom.evaluate("browser_eval", args, metadata).needs_user
    for mode in (Mode.DISCUSS, Mode.PLAN):
        decision = PermissionEngine("/workspace", mode=mode).evaluate("browser_eval", args, metadata)
        assert not decision.allowed
        assert not decision.needs_user


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


def test_lsp_tools_are_capability_gated_normalized_and_remote_path_safe():
    client = FakeClient()
    remote = target(client)
    assert remote_lsp_tools(remote) == []
    remote.capabilities = {"lsp"}
    tools = {tool.__name__: tool for tool in remote_lsp_tools(remote)}
    assert tools["hover"]("main.py", 1, 1)["text"] == "str"
    assert tools["definition"]("main.py", 1, 1)["items"][0]["line"] == 5
    assert tools["references"]("main.py", 1, 1)["items"][1]["column"] == 2
    assert tools["document_symbols"]("main.py")["items"][0]["line"] == 1
    assert tools["diagnostics"]("main.py")["items"][0]["line"] == 3
    assert "error" in tools["hover"]("../outside.py", 1, 1)

    windows = target(FakeClient(), style="windows")
    windows.capabilities = {"language_server"}
    result = by_name(remote_lsp_tools(windows), "hover")(
        r"C:\Workspace\main.py", 1, 1
    )
    assert result["text"] == "str"


def test_lsp_locations_accept_flattened_rvm_positions_and_windows_uris():
    class Flattened(FakeClient):
        def lsp(self, **arguments):
            if arguments["op"] == "definition":
                return [{
                    "uri": "file:///c%3A/Workspace/lib.py",
                    "path": "/c:/Workspace/lib.py",
                    "line": 1,
                    "character": 5,
                }]
            return [
                {
                    "uri": "file:///c%3A/Workspace/main.py",
                    "path": "/c:/Workspace/main.py",
                    "line": 3,
                    "character": 10,
                },
            ]

    remote = target(Flattened(), style="windows")
    remote.capabilities = {"lsp"}
    tools = {tool.__name__: tool for tool in remote_lsp_tools(remote)}
    assert tools["definition"]("main.py", 4, 11, "python") == {
        "items": [{"file": "lib.py", "line": 1, "column": 5}],
        "count": 1,
    }
    assert tools["references"]("lib.py", 2, 6, "python") == {
        "items": [{"file": "main.py", "line": 3, "column": 10}],
        "count": 1,
    }
