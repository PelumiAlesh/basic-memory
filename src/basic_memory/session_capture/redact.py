"""Redact or truncate noisy harness payloads before persisting."""

from __future__ import annotations

import json
from typing import Any

MAX_TOOL_OUTPUT_CHARS = 2_000
_SECRET_KEYS = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "password",
        "secret",
    }
)


def _truncate(value: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n… [truncated]"


def _redact_tree(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = _redact_tree(item)
        return cleaned
    if isinstance(value, list):
        return [_redact_tree(item) for item in value]
    if isinstance(value, str):
        return _truncate(value)
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to persist: clipped text, credential fields removed."""
    data = json.loads(json.dumps(payload))
    redacted = _redact_tree(data)
    return redacted if isinstance(redacted, dict) else {}
