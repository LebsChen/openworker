"""Persistent RVM host metadata and SecretStore-backed tokens."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from ..secrets import SecretStore, state_dir, write_private_text
from .client import RvmClient
from .paths import RemotePathStyle


@dataclass
class RvmHost:
    id: str
    name: str
    base_url: str
    platform: str | None = None
    workspace: str | None = None
    offline: bool = False


class RvmHostStore:
    def __init__(self, path: str | Path | None = None, *, secrets: SecretStore | None = None) -> None:
        self.path = Path(path) if path else state_dir() / "rvm-hosts.json"
        self.secrets = secrets or SecretStore()
        self._lock = threading.RLock()
        self._hosts: dict[str, RvmHost] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        except (OSError, ValueError):
            raw = {}
        if not raw and self.path.name == "rvm-hosts.json":
            legacy_path = self.path.with_name("remote-hosts.json")
            try:
                legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                legacy = {}
            if isinstance(legacy, dict):
                for item in legacy.get("hosts", []):
                    if not isinstance(item, dict) or not item.get("name") or not item.get("url"):
                        continue
                    host_id = str(item["name"])
                    host = RvmHost(
                        id=host_id,
                        name=host_id,
                        base_url=str(item["url"]).rstrip("/"),
                        offline=bool(item.get("offline", False)),
                    )
                    self._hosts[host_id] = host
                    token = item.get("token")
                    self.put(
                        host,
                        str(token) if token else None,
                        str(item.get("vnc_password") or item.get("vncPassword") or ""),
                    )
                return
        for item in raw.get("hosts", []) if isinstance(raw, dict) else []:
            if isinstance(item, dict) and item.get("id") and item.get("base_url"):
                self._hosts[str(item["id"])] = RvmHost(
                    id=str(item["id"]), name=str(item.get("name") or item["id"]),
                    base_url=str(item["base_url"]), platform=item.get("platform"),
                    workspace=item.get("workspace"), offline=bool(item.get("offline", False)),
                )

    def _save(self) -> None:
        write_private_text(
            self.path,
            json.dumps({"hosts": [asdict(h) for h in self._hosts.values()]}, indent=2) + "\n",
        )

    def list(self) -> list[RvmHost]:
        with self._lock:
            return list(self._hosts.values())

    def get(self, host_id: str) -> RvmHost | None:
        with self._lock:
            return self._hosts.get(host_id)

    def _secret(self, host_id: str) -> dict[str, object]:
        data = self.secrets.get(self._profile(host_id))
        return data if isinstance(data, dict) else {}

    def token(self, host_id: str) -> str | None:
        value = self._secret(host_id).get("token")
        return str(value) if value else None

    def vnc_password(self, host_id: str) -> str | None:
        value = self._secret(host_id).get("vnc_password")
        return str(value) if value else None

    def put(
        self,
        host: RvmHost,
        token: str | None = None,
        vnc_password: str | None = None,
    ) -> None:
        with self._lock:
            self._hosts[host.id] = host
            self._save()
            secret = self._secret(host.id)
            if token is not None:
                secret["token"] = token
            if vnc_password is not None:
                secret["vnc_password"] = vnc_password
            if secret:
                secret.update({"type": "rvm", "host_id": host.id})
                self.secrets.put(self._profile(host.id), secret)

    def set_offline(self, host_id: str, offline: bool) -> bool:
        with self._lock:
            host = self._hosts.get(host_id)
            if host is None:
                return False
            host.offline = offline
            self._save()
            return True

    def delete(self, host_id: str) -> bool:
        with self._lock:
            existed = self._hosts.pop(host_id, None) is not None
            if existed:
                self._save()
            self.secrets.delete(self._profile(host_id))
            return existed

    def client(self, host_id: str) -> RvmClient:
        host = self.get(host_id)
        if host is None:
            raise KeyError(f"unknown RVM host: {host_id}")
        token = self.token(host_id)
        if not token:
            raise KeyError(f"no token configured for RVM host: {host_id}")
        return RvmClient(host.base_url, token, host_label=f"{host.name} ({host.id})")

    def path_style_for(
        self, host: RvmHost, *, health: dict[str, Any] | None = None
    ) -> RemotePathStyle:
        if host.platform:
            return _style(host.platform)
        if health is None:
            client = self.client(host.id)
            try:
                health = client.health()
            finally:
                client.close()
        host.platform = str(health.get("platform") or "posix")
        with self._lock:
            self._hosts[host.id] = host
            self._save()
        return _style(host.platform)

    @staticmethod
    def _profile(host_id: str) -> str:
        return f"rvm:{host_id}"


def path_style_for(host: RvmHost, *, client: RvmClient | None = None) -> RemotePathStyle:
    if host.platform:
        return _style(host.platform)
    if client is None:
        raise ValueError("client required to probe an unclassified RVM host")
    host.platform = str(client.health().get("platform") or "posix")
    return _style(host.platform)


def _style(platform: str) -> RemotePathStyle:
    return RemotePathStyle("windows" if platform.lower().startswith("win") else "posix")
