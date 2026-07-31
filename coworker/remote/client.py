"""HTTP client for the Cloud-Dev RVM agent API."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx


class RvmError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RvmUnreachableError(RvmError):
    pass


class RvmTimeoutError(RvmUnreachableError):
    pass


class RvmUnauthorizedError(RvmError):
    pass


class RvmRemoteError(RvmError):
    pass


class RvmMalformedResponseError(RvmError):
    pass


class RvmClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        host_label: str = "remote host",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.host_label = host_label
        self.timeout = timeout
        kwargs: dict[str, Any] = {"timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.Client(**kwargs)
        self._mcp_id = 0

    def __repr__(self) -> str:
        return f"RvmClient(host_label={self.host_label!r})"

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, *, timeout: float | None = None, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
                timeout=timeout or self.timeout,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise RvmTimeoutError(f"{self.host_label} request timed out") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise RvmUnreachableError(f"{self.host_label} is offline or unreachable") from exc
        if response.status_code == 401:
            raise RvmUnauthorizedError(f"{self.host_label} rejected the remote token", status_code=401)
        if response.status_code < 200 or response.status_code >= 300:
            detail = "remote request failed"
            try:
                raw = response.json()
                if isinstance(raw, dict) and isinstance(raw.get("error"), str):
                    detail = raw["error"]
            except ValueError:
                pass
            raise RvmRemoteError(f"{self.host_label}: {detail}", status_code=response.status_code)
        try:
            value = response.json()
        except ValueError as exc:
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise RvmMalformedResponseError(f"{self.host_label} returned a non-object response")
        return value

    def health(self) -> dict[str, Any]:
        # Health is intentionally unauthenticated in the RVM protocol.
        try:
            response = self._http.get(self.base_url + "/api/health", timeout=8.0)
        except httpx.TimeoutException as exc:
            raise RvmTimeoutError(f"{self.host_label} health check timed out") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise RvmUnreachableError(f"{self.host_label} is offline or unreachable") from exc
        if response.status_code == 401:
            raise RvmUnauthorizedError(f"{self.host_label} rejected the remote token", status_code=401)
        if response.status_code < 200 or response.status_code >= 300:
            raise RvmRemoteError(f"{self.host_label}: health check failed", status_code=response.status_code)
        try:
            value = response.json()
        except ValueError as exc:
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed health JSON") from exc
        if not isinstance(value, dict):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed health data")
        return value

    def info(self) -> dict[str, Any]:
        return self._request("GET", "/api/info")

    def screenshot(self) -> dict[str, Any]:
        return self._request("POST", "/api/screenshot", json={})

    def computer(self, **body: Any) -> dict[str, Any]:
        return self._request("POST", "/api/computer-use", json=body)

    def _mcp_call(self, name: str, arguments: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._mcp_id += 1
        response = self._request(
            "POST",
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": self._mcp_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            },
        )
        if response.get("error"):
            error = response["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise RvmRemoteError(f"{self.host_label}: MCP request failed: {detail}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed MCP response")
        content = result.get("content")
        if not isinstance(content, list):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed MCP content")
        if result.get("isError"):
            text = next(
                (item.get("text") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)),
                "remote MCP request failed",
            )
            raise RvmRemoteError(f"{self.host_label}: MCP request failed: {text}")
        return content

    def mcp_tools(self) -> list[str]:
        self._mcp_id += 1
        response = self._request(
            "POST",
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": self._mcp_id,
                "method": "tools/list",
                "params": {},
            },
        )
        if response.get("error"):
            error = response["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise RvmRemoteError(f"{self.host_label}: MCP capability query failed: {detail}")
        result = response.get("result")
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed MCP capabilities")
        return [item["name"] for item in tools if isinstance(item, dict) and isinstance(item.get("name"), str)]

    def browser_navigate(self, url: str) -> dict[str, Any]:
        content = self._mcp_call("browser_navigate", {"url": url})
        text = next((item.get("text") for item in content if item.get("type") == "text"), None)
        if not isinstance(text, str):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed browser navigation")
        try:
            value = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed browser navigation") from exc
        if not isinstance(value, dict):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed browser navigation")
        return value

    def browser_eval(self, expression: str) -> dict[str, Any]:
        content = self._mcp_call("browser_eval", {"expression": expression})
        text = next((item.get("text") for item in content if item.get("type") == "text"), None)
        if not isinstance(text, str):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed browser evaluation")
        try:
            value = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed browser evaluation") from exc
        if not isinstance(value, dict):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed browser evaluation")
        return value

    def browser_screenshot(self) -> dict[str, Any]:
        content = self._mcp_call("browser_screenshot")
        image = next(
            (
                item.get("data")
                for item in content
                if isinstance(item, dict) and item.get("type") == "image" and isinstance(item.get("data"), str)
            ),
            None,
        )
        if not image:
            raise RvmMalformedResponseError(f"{self.host_label} returned no browser screenshot")
        return {"image": image, "format": "png"}

    def browser_close(self) -> dict[str, Any]:
        content = self._mcp_call("browser_close")
        text = next((item.get("text") for item in content if item.get("type") == "text"), "Browser closed")
        return {"ok": True, "message": text}

    def lsp(self, **arguments: Any) -> Any:
        content = self._mcp_call("lsp", arguments)
        text = next((item.get("text") for item in content if item.get("type") == "text"), None)
        if not isinstance(text, str):
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed LSP response")
        try:
            return json.loads(text)
        except (TypeError, ValueError) as exc:
            raise RvmMalformedResponseError(f"{self.host_label} returned malformed LSP response") from exc

    def exec_sync(
        self, cmd: str, *, cwd: str | None = None, timeout: float | None = None,
        session: str | None = None, env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = {"cmd": cmd}
        if cwd is not None:
            body["cwd"] = cwd
        if timeout is not None:
            body["timeout"] = timeout
        if session is not None:
            body["session"] = session
        if env is not None:
            body["env"] = env
        return self._request("POST", "/api/exec-sync", json=body, timeout=(timeout or self.timeout) + 5)

    def read(self, path: str) -> dict[str, Any]:
        return self._request("POST", "/api/read", json={"path": path})

    def write(self, path: str, content: str) -> dict[str, Any]:
        return self._request("POST", "/api/write", json={"path": path, "content": content})

    def ls(self, path: str) -> dict[str, Any]:
        return self._request("POST", "/api/ls", json={"path": path})

    def _storage(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/storage/{operation}", json=body)

    def stat(self, path: str) -> dict[str, Any]:
        return self._storage("stat", {"path": path})

    def mkdir(self, path: str) -> dict[str, Any]:
        return self._storage("mkdir", {"path": path})

    def exists(self, path: str) -> dict[str, Any]:
        return self._storage("exists", {"path": path})

    def delete(self, path: str, *, recursive: bool = True) -> dict[str, Any]:
        return self._storage("delete", {"path": path, "recursive": recursive})

    def rename(self, source: str, target: str) -> dict[str, Any]:
        return self._storage("rename", {"from": source, "to": target})
