"""Dedicated MCP HTTP token file (0600), reused across setup runs."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from basic_memory.config_models import _secure_config_file

TOKEN_FILE_NAME = "fork-mcp-tokens.json"


@dataclass(frozen=True, slots=True)
class ForkTokens:
    shared_token: str
    client_tokens: dict[str, str]


def token_file_path(config_dir: Path) -> Path:
    return config_dir / TOKEN_FILE_NAME


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def default_client_names() -> tuple[str, ...]:
    return ("cursor", "claude-code", "claude-desktop", "codex")


def load_tokens(config_dir: Path) -> ForkTokens | None:
    path = token_file_path(config_dir)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    shared = data.get("shared_token")
    clients = data.get("client_tokens")
    if not isinstance(shared, str) or not isinstance(clients, dict):
        return None
    return ForkTokens(
        shared_token=shared,
        client_tokens={str(k): str(v) for k, v in clients.items()},
    )


def ensure_tokens(config_dir: Path) -> ForkTokens:
    """Load existing tokens or create a new set once."""
    existing = load_tokens(config_dir)
    if existing is not None:
        return existing
    clients = {name: _new_token() for name in default_client_names()}
    tokens = ForkTokens(shared_token=_new_token(), client_tokens=clients)
    write_tokens(config_dir, tokens)
    return tokens


def write_tokens(config_dir: Path, tokens: ForkTokens) -> Path:
    path = token_file_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "shared_token": tokens.shared_token,
        "client_tokens": dict(tokens.client_tokens),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _secure_config_file(path)
    return path
