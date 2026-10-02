"""Append harness turns into a single inbox/ note per conversation (local only)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from basic_memory.config import ConfigManager
from basic_memory.session_capture.redact import redact_payload
from basic_memory.session_capture.state import JsonCaptureStateStore, state_path
from basic_memory.setup.paths import cursor_routing_path, default_vault_path

_TEXT_KEYS = (
    "prompt",
    "text",
    "transcript",
    "response",
    "user_message",
    "assistant_message",
)
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def _project_path() -> Path:
    config = ConfigManager().config
    name = config.default_project or "main"
    entry = config.projects.get(name)
    if entry and entry.path:
        return Path(entry.path).expanduser().resolve()
    return default_vault_path().expanduser().resolve()


def _has_turn_text(payload: dict[str, Any]) -> bool:
    """True when the payload carries conversation text worth keeping.

    A Cursor stop event is often only ``status`` and ``loop_count``. Writing a
    note for that creates an inbox file with no turns.
    """
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    messages = payload.get("messages")
    return isinstance(messages, list) and len(messages) > 0


def _turn_id(payload: dict[str, Any]) -> str:
    for key in ("turn_id", "turnId", "message_id", "messageId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # Same payload twice must not append twice when the harness sends no id.
    digest = hashlib.sha256(
        json.dumps(redact_payload(payload), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"content:{digest[:16]}"


def _note_path(conversation_id: str) -> Path:
    safe = _SAFE_ID.sub("_", conversation_id).strip("._")[:80] or "unknown"
    root = _project_path()
    note = (root / "inbox" / f"session-{safe}.md").resolve()
    if not note.is_relative_to(root.resolve()):
        raise ValueError("session note path escapes the project")
    return note


def _format_turn(harness: str, turn_id: str, payload: dict[str, Any]) -> str:
    redacted = redact_payload(payload)
    body = json.dumps(redacted, indent=2, sort_keys=True)
    stamp = datetime.now(timezone.utc).isoformat()
    return f"\n\n## Turn {turn_id} ({harness}) @ {stamp}\n\n```json\n{body}\n```\n"


def handle_stop_event(payload: dict[str, Any], *, harness: str, conversation_id: str) -> None:
    """Append one turn to the conversation's inbox note when capture is enabled."""
    if not conversation_id:
        return
    config = ConfigManager().config
    if not config.session_capture_enabled:
        return
    if not _has_turn_text(payload):
        return

    project = _project_path()
    store = JsonCaptureStateStore(state_path(project))
    state = store.load()
    turn_id = _turn_id(payload)
    if state.last_turn(conversation_id) == turn_id:
        return

    note = _note_path(conversation_id)
    note.parent.mkdir(parents=True, exist_ok=True)
    if not note.exists():
        primary = config.default_project or "main"
        if cursor_routing_path().is_file():
            try:
                routing = json.loads(cursor_routing_path().read_text(encoding="utf-8"))
                if isinstance(routing, dict) and routing.get("primaryProject"):
                    primary = str(routing["primaryProject"])
            except json.JSONDecodeError:
                pass
        header = (
            f"---\ntitle: Session {conversation_id}\n"
            f"type: session_capture\ndirectory: inbox\n"
            f"session_id: {conversation_id}\nproject: {primary}\n---\n"
            f"# Session capture\n\nConversation `{conversation_id}` (local only).\n"
        )
        note.write_text(header, encoding="utf-8")

    with note.open("a", encoding="utf-8") as handle:
        handle.write(_format_turn(harness, turn_id, payload))

    state.record_turn(conversation_id, turn_id)
    store.save(state)
