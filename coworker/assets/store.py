from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..secrets import state_dir, write_private_text

_BOOLS = {"true": True, "false": False}
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
PLAYBOOK_TEMPLATE = """# {name}

## Overview

{description}

## What to do

Describe the steps this playbook should guide.

## Advice and pointers

Add useful context, links, and examples.

## Specifications

Record inputs, outputs, and acceptance criteria.

## Forbidden actions

List actions the agent must not take.
"""


@dataclass
class Asset:
    name: str
    description: str
    body: str
    enabled: bool = True
    scope: str = "global"
    project: str | None = None
    trigger: str | None = None
    path: str | None = None

    def metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "scope": self.scope,
        }
        if self.project is not None:
            out["project"] = self.project
        if self.trigger is not None:
            out["trigger"] = self.trigger
        return out


class AssetStore:
    """Markdown assets with a deliberately tiny YAML-frontmatter subset.

    Names are filenames, rather than opaque IDs, so users can inspect and back up
    their assets directly. Writes use the same private atomic writer as secrets.
    """

    def __init__(self, kind: str, directory: str | Path | None = None) -> None:
        if kind not in {"knowledge", "playbooks"}:
            raise ValueError("asset kind must be knowledge or playbooks")
        self.kind = kind
        self.directory = Path(directory).expanduser() if directory else state_dir() / kind
        self.directory.mkdir(parents=True, exist_ok=True)

    def list(self, *, workspace: str | None = None) -> list[dict[str, Any]]:
        return [a.metadata() for a in self.iter_matching(workspace=workspace, enabled_only=False)]

    def iter_matching(
        self, *, workspace: str | None = None, enabled_only: bool = True
    ) -> Iterable[Asset]:
        for path in sorted(self.directory.glob("*.md")):
            try:
                asset = self._read(path)
            except (OSError, ValueError):
                continue
            if enabled_only and not asset.enabled:
                continue
            if _scope_matches(asset, workspace):
                yield asset

    def get(self, name: str, *, workspace: str | None = None) -> Asset | None:
        path = self._path(name)
        if not path.is_file():
            return None
        asset = self._read(path)
        return asset if _scope_matches(asset, workspace) else None

    def save(self, data: dict[str, Any], *, existing: str | None = None) -> dict[str, Any]:
        name = str(data.get("name") or existing or "").strip()
        if not name or "/" in name or "\\" in name:
            raise ValueError("asset name must be a non-empty filename")
        scope = str(data.get("scope", "global")).strip().lower()
        if scope not in {"global", "project"}:
            raise ValueError("scope must be global or project")
        project = str(data.get("project", "")).strip() or None
        if scope == "project" and not project:
            raise ValueError("project is required for project-scoped assets")
        old = self.get(existing or name)
        description = str(data.get("description", old.description if old else "")).strip()
        body = str(data.get("body", old.body if old else "")).strip()
        if self.kind == "playbooks" and not body and old is None:
            body = PLAYBOOK_TEMPLATE.format(name=name, description=description or "A reusable procedure.")
        asset = Asset(
            name=name,
            description=description,
            body=body,
            enabled=bool(data.get("enabled", old.enabled if old else True)),
            scope=scope,
            project=project,
            trigger=(str(data["trigger"]).strip() if data.get("trigger") is not None else (old.trigger if old else None)),
        )
        if self.kind == "knowledge" and asset.trigger not in {None, "always"}:
            asset.trigger = str(asset.trigger)
        if existing and existing != name:
            self._path(existing).unlink(missing_ok=True)
        write_private_text(self._path(name), _render(asset))
        return asset.metadata() | {"body": asset.body}

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def catalog_text(self, *, workspace: str | None = None) -> str:
        items = list(self.iter_matching(workspace=workspace))
        if not items:
            return ""
        noun = "knowledge notes" if self.kind == "knowledge" else "playbooks"
        tool = "load_knowledge" if self.kind == "knowledge" else "load_playbook"
        lines = [f"- {a.name}: {a.description}" for a in items]
        return f"Available {noun} — call {tool}(name) when relevant:\n" + "\n".join(lines)

    def _path(self, name: str) -> Path:
        safe = Path(name).name
        if safe != name or not safe:
            raise ValueError("invalid asset name")
        return self.directory / (safe if safe.endswith(".md") else f"{safe}.md")

    def _read(self, path: Path) -> Asset:
        text = path.read_text(encoding="utf-8")
        match = _FRONTMATTER.match(text)
        raw: dict[str, Any] = {}
        body = text
        if match:
            body = text[match.end() :]
            for line in match.group(1).splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                value = value.strip().strip('"').strip("'")
                raw[key.strip().lower()] = _BOOLS.get(value.lower(), value)
        return Asset(
            name=str(raw.get("name") or path.stem),
            description=str(raw.get("description") or ""),
            body=body.strip(),
            enabled=bool(raw.get("enabled", True)),
            scope=str(raw.get("scope") or "global"),
            project=str(raw["project"]) if raw.get("project") else None,
            trigger=str(raw["trigger"]) if raw.get("trigger") else None,
            path=str(path),
        )


def _scope_matches(asset: Asset, workspace: str | None) -> bool:
    if asset.scope == "global":
        return True
    if not workspace or not asset.project:
        return False
    return str(Path(workspace)) == asset.project


def _render(asset: Asset) -> str:
    lines = [
        "---",
        f"name: {asset.name}",
        f"description: {asset.description}",
        f"enabled: {'true' if asset.enabled else 'false'}",
        f"scope: {asset.scope}",
    ]
    if asset.project:
        lines.append(f"project: {asset.project}")
    if asset.trigger:
        lines.append(f"trigger: {asset.trigger}")
    lines += ["---", "", asset.body.rstrip(), ""]
    return "\n".join(lines)
