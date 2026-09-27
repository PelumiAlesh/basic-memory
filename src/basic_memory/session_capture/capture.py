"""Append harness turns into a single inbox/ note per conversation (local only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from basic_memory.config import ConfigManager
from basic_memory.session_capture.redact import redact_payload
from basic_memory.session_capture.state import JsonCaptureStateStore, state_path
from basic_memory.setup.paths import cursor_routing_path, default_vault_path


def _project_path() -> Path:
    config = ConfigManager().config
    name = config.default_project or "main"
    entry = config.projects.get(name)
    if entry and entry.path:
        return Path(entry.path).expanduser().resolve()
    return default_vault_path().expanduser().resolve()


def _turn_id(payload: dict[str, Any]) -> str:
    for key in ("turn_id", "turnId", "message_id", "messageId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    status = payload.get("status")
    ts = datetime.now(timezone.utc).isoformat()
    return f"{status or 'stop'}:{ts}"


def _note_path(conversation_id: str) -> Path:
    safe = conversation_id.replace("/", "_").replace(":", "_")
    return _project_path() / "inbox" / f"session-{safe}.md"


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
