"""Launch-token resolution shared by the standalone server and its tests."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class TokenSelection:
    token: str
    source: str


def resolve_token(
    *,
    cli_token: str | None = None,
    token_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> TokenSelection:
    """Resolve an API token without ever returning an empty credential.

    Explicit CLI input wins over ``--token-file`` and environment configuration.
    ``OPENWORKER_TOKEN`` is the public server setting; ``COWORKER_API_TOKEN`` remains
    supported for the Tauri-managed sidecar.
    """

    if cli_token is not None and token_file is not None:
        raise ValueError("--token and --token-file are mutually exclusive")

    if cli_token is not None:
        token = cli_token.strip()
        if not token:
            raise ValueError("--token must not be empty")
        return TokenSelection(token, "cli")

    if token_file is not None:
        path = Path(token_file).expanduser()
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError(f"token file is empty: {path}")
        return TokenSelection(token, "file")

    env = environ if environ is not None else {}
    for name in ("OPENWORKER_TOKEN", "COWORKER_API_TOKEN"):
        token = str(env.get(name, "")).strip()
        if token:
            return TokenSelection(token, f"env:{name}")

    return TokenSelection(secrets.token_hex(32), "random")


def token_matches(provided: str, expected: str) -> bool:
    """Compare credentials without leaking length/content through timing."""

    return bool(provided and expected and secrets.compare_digest(provided, expected))
