"""Normalize MCP clientInfo names to a stable slug.

The slug is what provenance, privacy policy, and git commit messages store.
It is derived from the name the client sends at initialize, not from a
guess about the network peer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# Known clients collapse onto one slug so a policy for "chatgpt" matches
# OpenAI's reported clientInfo name. Longer keys are checked first so
# "claude-code" does not become "claude".
_ALIASES: tuple[tuple[str, str], ...] = (
    ("openai-mcp", "chatgpt"),
    ("chatgpt", "chatgpt"),
    ("claude-code", "claude-code"),
    ("claude code", "claude-code"),
    ("claude", "claude"),
    ("cursor-vscode", "cursor"),
    ("cursor", "cursor"),
    ("codex", "codex"),
    ("grok-bot", "grok"),
    ("grok", "grok"),
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_SLUG = 40


def client_slug(name: str | None, title: str | None = None) -> str | None:
    """Return a stable slug for a clientInfo name or title, or None when blank."""
    raw = (name or title or "").strip().lower()
    if not raw:
        return None
    # Drop a version suffix ("openai-mcp/1.0") before alias matching.
    raw = raw.split("/", 1)[0].strip()
    for prefix, slug in _ALIASES:
        if raw == prefix or raw.startswith(f"{prefix}-") or raw.startswith(f"{prefix} "):
            return slug
    slug = _SLUG_RE.sub("-", raw).strip("-")[:_MAX_SLUG].strip("-")
    return slug or None


def slug_from_client_info(info: Mapping[str, object] | None) -> str | None:
    """Read name, then title, from a sanitized clientInfo mapping."""
    if info is None:
        return None
    name = info.get("name")
    title = info.get("title")
    return client_slug(
        name if isinstance(name, str) else None,
        title if isinstance(title, str) else None,
    )
