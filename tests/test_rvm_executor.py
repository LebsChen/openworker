import threading
import time

from coworker.remote.client import RvmTimeoutError
from coworker.remote.executor import RvmExecutor
from coworker.remote.paths import RemotePathStyle


class FakeClient:
    host_label = "DevBox"

    def __init__(self, response):
        self.response = response
        self.calls = []

    def exec_sync(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response

    def close(self):
        pass


def test_posix_exec_trailer_preserves_exit_and_cwd():
    client = FakeClient({"result": {"stdout": "", "stderr": "err\n", "exit_code": 7}})
    def call(*args, **kwargs):
        marker = args[0].split("printf '\\n")[1].split(" %s")[0]
        return {"result": {"stdout": f"before\n\n{marker} 7 /remote/next\n", "stderr": "err\n", "exit_code": 7}}
    client.exec_sync = call
    executor = RvmExecutor(client=client, cwd="/remote", style=RemotePathStyle("posix"), session_id="s")
    # Use the generated marker from the request so the fixture matches it.
    requested = executor.run("cd next && false")
    assert requested["exit_code"] == 7
    assert requested["cwd"] == "/remote/next"
    assert requested["output"] == "before\nerr\n"
    assert executor._first_call is False


def test_windows_exec_trailer_parses_multiline_marker():
    client = FakeClient({"result": {"stdout": "output\r\n", "stderr": "", "exit_code": 3}})
    executor = RvmExecutor(client=client, cwd=r"C:\Work", style=RemotePathStyle("windows"))
    # Replace the generated wrapper response with a matching marker.
    original = client.exec_sync
    def call(*args, **kwargs):
        marker = args[0].split("'")[1]
        return {"result": {"stdout": f"output\r\n{marker}\r\n3\r\nC:\\Work\\next\r\n", "stderr": "", "exit_code": 3}}
    client.exec_sync = call
    result = executor.run("exit 3")
    assert result["exit_code"] == 3
    assert result["cwd"] == r"C:\Work\next"
    assert result["output"] == "output\r\n"


def test_missing_marker_rotates_session_and_resends_cwd():
    client = FakeClient({"result": {"stdout": "died", "stderr": "", "exit_code": 1}})
    executor = RvmExecutor(client=client, cwd="/workspace", session_id="old")
    first = executor.run("bad")
    assert "marker" in first["error"]
    old = executor.session_id
    executor.run("pwd")
    assert executor.session_id != old
    assert client.calls[-1][1]["cwd"] == "/workspace"


def test_timeout_word_in_intact_command_output_does_not_rotate_or_timeout():
    client = FakeClient({})

    def call(*args, **kwargs):
        marker = args[0].split("printf '\\n")[1].split(" %s")[0]
        return {
            "result": {
                "stdout": f"curl: (28) Operation timed out\n\n{marker} 0 /workspace\n",
                "stderr": "",
                "exit_code": 0,
            }
        }

    client.exec_sync = call
    executor = RvmExecutor(client=client, cwd="/workspace", session_id="stable")
    result = executor.run("curl")
    assert result["timed_out"] is False
    assert executor.session_id == "stable"
    assert executor.cwd == "/workspace"


def test_timeout_rotates_session_and_close_does_not_close_shared_client():
    class TimeoutClient(FakeClient):
        def exec_sync(self, *args, **kwargs):
            raise RvmTimeoutError("offline timeout")
        def close(self):
            self.closed = True

    client = TimeoutClient({})
    client.closed = False
    executor = RvmExecutor(client=client, cwd="/workspace")
    result = executor.run("sleep 100")
    assert result["timed_out"] is True
    executor.close()
    assert client.closed is False


def test_interrupt_returns_without_waiting_for_blocking_http():
    class SlowClient(FakeClient):
        def exec_sync(self, *args, **kwargs):
            time.sleep(2)
            return {"result": {"stdout": "", "stderr": "", "exit_code": 0}}

    client = SlowClient({})
    executor = RvmExecutor(client=client, cwd="/workspace", session_id="old")
    result = []
    thread = threading.Thread(target=lambda: result.append(executor.run("sleep")))
    thread.start()
    time.sleep(0.1)
    old = executor.session_id
    executor.interrupt_now()
    thread.join(0.5)
    assert not thread.is_alive()
    assert result[0]["error"] == "interrupted by user"
    assert executor.session_id != old


def test_background_commands_use_process_groups_and_style_quoting():
    class BackgroundClient(FakeClient):
        def exec_sync(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return {"result": {"stdout": "", "stderr": "", "exit_code": 0}}
    posix = BackgroundClient({})
    RvmExecutor(client=posix, cwd="/workspace").run_background("echo hi")
    assert "setsid" in posix.calls[-1][0][0]
    win = BackgroundClient({})
    RvmExecutor(client=win, cwd=r"C:\Work", style=RemotePathStyle("windows")).run_background("Write-Output hi")
    script = win.calls[-1][0][0]
    assert "-EncodedCommand" in script
    assert "RedirectStandardError" not in script
