"""Pure remote path operations; never consult the client filesystem."""

from __future__ import annotations

import shlex
from pathlib import PurePath, PurePosixPath, PureWindowsPath


class RemotePathError(ValueError):
    pass


class RemotePathStyle:
    def __init__(self, style: str = "posix") -> None:
        if style not in {"posix", "windows"}:
            raise ValueError(f"unknown remote path style: {style}")
        self.name = style
        self.path_cls = PureWindowsPath if style == "windows" else PurePosixPath

    def _parts(self, value: str | PurePath) -> tuple[str, ...]:
        text = str(value).replace("\\", "/") if self.name == "windows" else str(value)
        p = self.path_cls(text)
        drive = getattr(p, "drive", "")
        anchor = getattr(p, "anchor", "")
        out: list[str] = []
        for part in p.parts:
            if part in {anchor, drive, "/", "\\"}:
                continue
            if part in {"", "."}:
                continue
            if part == "..":
                if out:
                    out.pop()
                else:
                    raise RemotePathError(f"path contains an unresolved '..': {value}")
            else:
                out.append(part)
        return tuple(out)

    def is_absolute(self, value: str | PurePath) -> bool:
        text = str(value).replace("/", "\\") if self.name == "windows" else str(value)
        return self.path_cls(text).is_absolute()

    def normalize(self, value: str | PurePath) -> str:
        text = str(value).replace("\\", "/") if self.name == "windows" else str(value)
        p = self.path_cls(text)
        parts = self._parts(text)
        if self.name == "windows":
            drive = p.drive
            prefix = f"{drive}\\" if p.is_absolute() else ""
            return prefix + "\\".join(parts) or (drive + "\\" if drive and p.is_absolute() else ".")
        return (("/" if p.is_absolute() else "") + "/".join(parts)) or "."

    def join(self, root: str, p: str) -> str:
        if self.is_absolute(p):
            return self.normalize(p)
        return self.normalize(self.normalize(root) + ("/" if self.name == "posix" else "\\") + p)

    def is_under(self, root: str, p: str) -> bool:
        try:
            r = self.normalize(root)
            candidate = self.normalize(p if self.is_absolute(p) else self.join(r, p))
        except RemotePathError:
            return False
        if self.name == "windows":
            r_cmp, c_cmp = r.casefold().rstrip("\\"), candidate.casefold().rstrip("\\")
            return c_cmp == r_cmp or c_cmp.startswith(r_cmp + "\\")
        r_cmp, c_cmp = r.rstrip("/"), candidate.rstrip("/")
        return c_cmp == r_cmp or c_cmp.startswith(r_cmp + "/")

    def relative(self, root: str, p: str) -> str:
        candidate = self.normalize(p if self.is_absolute(p) else self.join(root, p))
        if not self.is_under(root, candidate):
            raise RemotePathError(f"path is outside root: {p}")
        r = self.normalize(root).rstrip("\\/" )
        rel = candidate[len(r):].lstrip("\\/")
        return rel or "."

    def basename(self, value: str) -> str:
        normalized = self.normalize(value)
        return self.path_cls(normalized).name

    def quote(self, value: str) -> str:
        """Quote one literal argument for the remote host's default shell."""
        if self.name == "windows":
            return "'" + str(value).replace("'", "''") + "'"
        return shlex.quote(str(value))
