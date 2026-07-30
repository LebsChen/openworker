"""HTTP client for the Cloud-Dev RVM agent API."""

from __future__ import annotations

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
