"""Remote HTTP-backed implementation of the shell Executor contract."""

from __future__ import annotations

import base64
import re
import threading
import uuid
from typing import Any, Optional

from ..tools.shell import Executor
from .client import RvmClient, RvmError, RvmTimeoutError
from .paths import RemotePathStyle

_DEFAULT_TIMEOUT = 120.0
_MAX_TIMEOUT = 600.0


class RvmExecutor(Executor):
    def __init__(
        self,
        *,
        client: RvmClient,
        cwd: str,
        style: RemotePathStyle | None = None,
        session_id: str | None = None,
        max_output_chars: int = 20_000,
    ) -> None:
        self.client = client
        self.cwd = cwd
        self.style = style or RemotePathStyle()
        self.session_id = session_id or f"coworker-{uuid.uuid4().hex}"
        self.max_output_chars = max_output_chars
        self._first_call = True
        self._cancel = threading.Event()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._marker_seen = False

    def _marker(self) -> str:
        return f"__COWORKER_RVM_{uuid.uuid4().hex}__"

    def _wrap(self, command: str, marker: str) -> str:
        if self.style.name == "windows":
            return (
                f"{command}\n"
                "$__ow_rc = if ($LASTEXITCODE -ne 0) { [int]$LASTEXITCODE } "
                "elseif ($?) { 0 } else { 1 }\n"
                f"Write-Output '{marker}'\nWrite-Output $__ow_rc\n"
                "Write-Output ((Get-Location).Path)\n"
                "$global:LASTEXITCODE = $__ow_rc"
            )
        return (
            f"{{\n{command}\n}}\n"
            "__ow_rc=$?\n"
            f"printf '\\n{marker} %s %s\\n' \"$__ow_rc\" \"$PWD\"\n"
            "(exit $__ow_rc)"
        )

    def _parse(
        self, result: dict[str, Any], marker: str
    ) -> tuple[str, str, int | None, bool]:
        payload = result.get("result")
        if not isinstance(payload, dict):
            raise RvmError(f"{self.client.host_label}: malformed exec result")
        stdout = str(payload.get("stdout") or "")
        stderr = str(payload.get("stderr") or "")
        exit_code = payload.get("exit_code")
        if self.style.name == "windows":
            match = re.search(
                re.escape(marker) + r"\r?\n(-?\d+)\r?\n([^\r\n]*)",
                stdout,
            )
        else:
            normalized = stdout.replace("\r\n", "\n")
            match = re.search(
                re.escape(marker) + r"\s+(-?\d+)\s+([^\r\n]*)",
                normalized,
            )
        if match:
            self._marker_seen = True
            if self.style.name == "windows":
                stdout = stdout[: match.start()]
            else:
                stdout = normalized[: match.start()]
            if self.style.name == "posix":
                if stdout == "\n":
                    stdout = ""
                elif stdout.endswith("\n\n"):
                    stdout = stdout[:-1]
            try:
                exit_code = int(match.group(1))
            except ValueError:
                pass
            self.cwd = match.group(2).strip() or self.cwd
        else:
            self._marker_seen = False
        return (
            stdout + stderr,
            self.cwd,
            int(exit_code) if isinstance(exit_code, int) else None,
            self._marker_seen,
        )

    def _rotate_session(self) -> None:
        self.session_id = f"coworker-{uuid.uuid4().hex}"
        self._first_call = True

    def _exec_interruptibly(
        self, command: str, *, cwd: str | None, timeout: float
    ) -> dict[str, Any] | None:
        result: list[dict[str, Any]] = []
        failure: list[BaseException] = []
        done = threading.Event()
        session_id = self.session_id

        def worker() -> None:
            try:
                result.append(
                    self.client.exec_sync(
                        command,
                        cwd=cwd,
                        timeout=timeout,
                        session=session_id,
                    )
                )
            except BaseException as exc:
                failure.append(exc)
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        while not done.wait(0.05):
            if self._cancel.is_set():
                return None
        if failure:
            raise failure[0]
        return result[0]

    def run(self, command: str, timeout: Optional[float] = None) -> dict[str, Any]:
        self._cancel.clear()
        requested = min(float(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT)
        marker = self._marker()
        send_cwd = self.cwd if self._first_call else None
        try:
            response = self._exec_interruptibly(
                self._wrap(command, marker), cwd=send_cwd, timeout=requested
            )
            if response is None:
                self._rotate_session()
                return {
                    "command": command, "cwd": self.cwd, "exit_code": None,
                    "output": "", "timed_out": False, "truncated": False,
                    "error": "interrupted by user",
                }
            output, cwd, exit_code, marker_seen = self._parse(response, marker)
            payload = response.get("result", {})
            if not marker_seen:
                remote_timed_out = (
                    isinstance(payload, dict)
                    and (
                        "timed out" in str(payload.get("stderr") or "").lower()
                        or "timeout" in str(payload.get("stderr") or "").lower()
                    )
                )
                self._rotate_session()
                return {
                    "command": command, "cwd": self.cwd, "exit_code": None,
                    "output": output, "timed_out": remote_timed_out,
                    "truncated": len(output) > self.max_output_chars,
                    "error": "remote shell session ended before returning its marker",
                }
            self._first_call = False
            truncated = len(output) > self.max_output_chars
            if truncated:
                output = output[-self.max_output_chars :]
            result: dict[str, Any] = {
                "command": command, "cwd": cwd, "exit_code": exit_code,
                "output": output, "timed_out": False, "truncated": truncated,
            }
            if self._cancel.is_set():
                result["error"] = "interrupted by user"
            return result
        except RvmError as exc:
            timed_out = isinstance(exc, RvmTimeoutError) or "timeout" in str(exc).lower()
            if self._cancel.is_set():
                return {
                    "command": command, "cwd": self.cwd, "exit_code": None, "output": "",
                    "timed_out": False, "truncated": False, "error": "interrupted by user",
                }
            return {
                "command": command, "cwd": self.cwd, "exit_code": None, "output": "",
                "timed_out": timed_out, "truncated": False, "error": str(exc),
            }

    def run_background(self, command: str) -> dict[str, Any]:
        task_id = f"bg-{uuid.uuid4().hex[:12]}"
        root = self.style.join(self.cwd, ".coworker/bg")
        log = self.style.join(root, task_id + ".log")
        err = self.style.join(root, task_id + ".err")
        rc = self.style.join(root, task_id + ".rc")
        pid = self.style.join(root, task_id + ".pid")
        if self.style.name == "windows":
            child = (
                f"& {{ {command} }}\n"
                "$__ow_rc = if ($LASTEXITCODE -ne 0) { [int]$LASTEXITCODE } "
                "elseif ($?) { 0 } else { 1 }\n"
                "Write-Output ('__COWORKER_BG_RC__' + [string]$__ow_rc)"
            )
            encoded = base64.b64encode(child.encode("utf-16le")).decode("ascii")
            script = (
                f"New-Item -ItemType Directory -Force -Path {self.style.quote(root)} | Out-Null; "
                f"$p=Start-Process powershell.exe -WindowStyle Hidden "
                f"-ArgumentList '-NoProfile','-EncodedCommand','{encoded}' "
                f"-WorkingDirectory {self.style.quote(self.cwd)} "
                f"-RedirectStandardOutput {self.style.quote(log)} "
                f"-RedirectStandardError {self.style.quote(err)} -PassThru; "
                "$p.Id; $global:LASTEXITCODE=0"
            )
        else:
            child = (
                f"cd {self.style.quote(self.cwd)} && "
                f"({command}) >{self.style.quote(log)} 2>&1; "
                f"echo $? >{self.style.quote(rc)}"
            )
            script = (
                f"mkdir -p {self.style.quote(root)}; "
                f"(command -v setsid >/dev/null 2>&1 && setsid sh -c {self.style.quote(child)} "
                f"|| sh -c {self.style.quote(child)}) & echo $! >{self.style.quote(pid)}"
            )
        response = self.client.exec_sync(script, cwd=self.cwd, session=self.session_id)
        if isinstance(response.get("result"), dict) and int(response["result"].get("exit_code", 1)) != 0:
            return {"error": str(response["result"].get("stderr") or "failed to start background task")}
        result = response.get("result", {})
        launch_output = str(result.get("stdout") or "").strip().splitlines()
        if self.style.name == "windows":
            try:
                pid_value: str | int = int(launch_output[-1])
            except (IndexError, ValueError):
                return {"error": "remote background launch did not return a process id"}
        else:
            pid_value = pid
        self._tasks[task_id] = {"log": log, "err": err, "rc": rc, "pid": pid_value, "cursor": 0}
        return {
            "task_id": task_id, "command": command, "status": "running",
            "note": "use shell_task_output to read its output, shell_task_kill to stop it",
        }

    def background_output(self, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(task_id)
        if task is None:
            return {"error": f"unknown task: {task_id}"}
        try:
            content = str(self.client.read(task["log"]).get("content") or "")
        except RvmError:
            content = ""
        cursor = task["cursor"]
        exit_code: int | None = None
        status = "running"
        try:
            rc_text = str(self.client.read(task["rc"]).get("content") or "").strip()
            exit_code = int(rc_text)
            status = "exited"
        except (RvmError, ValueError):
            pass
        if exit_code is None and self.style.name == "windows":
            match = re.search(r"(?:^|\r?\n)__COWORKER_BG_RC__(-?\d+)\s*$", content)
            if match:
                exit_code = int(match.group(1))
                status = "exited"
                content = content[: match.start()].rstrip("\r\n") + "\n"
        new = content[cursor:]
        task["cursor"] = len(content)
        truncated = len(new) > self.max_output_chars
        if truncated:
            new = new[-self.max_output_chars :]
        return {"task_id": task_id, "status": status, "exit_code": exit_code, "output": new, "truncated": truncated}

    def background_kill(self, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(task_id)
        if task is None:
            return {"error": f"unknown task: {task_id}"}
        if self.style.name == "windows":
            command = (
                f"taskkill /PID {int(task['pid'])} /T /F "
                "2>$null; $global:LASTEXITCODE=0"
            )
        else:
            command = (
                f"if kill -- -$(cat {self.style.quote(task['pid'])}) 2>/dev/null; "
                f"then :; else kill $(cat {self.style.quote(task['pid'])}) "
                "2>/dev/null || true; fi"
            )
        try:
            self.client.exec_sync(command, cwd=self.cwd, session=self.session_id)
        except RvmError as exc:
            return {"task_id": task_id, "status": "running", "exit_code": None, "error": str(exc)}
        return {"task_id": task_id, "status": "killed", "exit_code": None}

    def interrupt_now(self) -> None:
        self._cancel.set()

    def interrupt(self) -> None:
        self.interrupt_now()

    def close(self) -> None:
        # RvmClient is shared with remote file/search/git tools and is owned by the
        # host/session manager, not by this executor.
        return None
