"""Redact or truncate noisy harness payloads before persisting."""

from __future__ import annotations

import json
from typing import Any

MAX_TOOL_OUTPUT_CHARS = 2_000


def _truncate(value: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n… [truncated]"


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to persist (no huge tool blobs)."""
    data = json.loads(json.dumps(payload))
    for key in ("tool_output", "output", "result"):
        raw = data.get(key)
        if isinstance(raw, str):
            data[key] = _truncate(raw)
    messages = data.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                message["content"] = _truncate(content)
    return data
