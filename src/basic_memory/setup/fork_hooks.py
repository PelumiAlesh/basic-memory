"""Fork setup hook runners (Cursor + Claude Code per-turn continuity)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from basic_memory.config import ConfigManager
from basic_memory.setup.paths import cursor_routing_path, default_vault_path
from basic_memory.shared_memory.brief_delivery import (
    JsonBriefDeliveryStore,
    project_delivery_path,
    should_deliver_brief,
)


def _read_stdin_json() -> dict[str, Any]:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _conversation_id(payload: dict[str, Any]) -> str:
    for key in ("conversation_id", "conversationId", "session_id", "sessionId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _project_path() -> Path:
    config = ConfigManager().config
    name = config.default_project or "main"
    entry = config.projects.get(name)
    if entry and entry.path:
        return Path(entry.path).expanduser().resolve()
    return default_vault_path().expanduser().resolve()


def _primary_project() -> str:
    routing = {}
    path = cursor_routing_path()
    if path.is_file():
        try:
            routing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            routing = {}
    if isinstance(routing, dict):
        primary = routing.get("primaryProject")
        if isinstance(primary, str) and primary.strip():
            return primary.strip()
    return ConfigManager().config.default_project or "main"


def _render_brief_text() -> str:
    from basic_memory.cli.commands.brief import render_brief_for_project

    return render_brief_for_project(_primary_project())


def _log_hook_metadata(name: str, client: str, conversation_id: str) -> None:
    """Record that a hook ran. The prompt and the brief stay out of the log."""
    try:
        from basic_memory.shared_memory.usage_log_fast import append_event_line

        event: dict[str, Any] = {"event": "hook", "name": name, "client": client}
        if conversation_id:
            event["conversation_id"] = conversation_id
        append_event_line(event)
    except Exception:
        return


def _maybe_record_delivery(conversation_id: str) -> None:
    if not conversation_id:
        return
    store = JsonBriefDeliveryStore(project_delivery_path(_project_path()))
    state = store.load()
    state.record(conversation_id, datetime.now(timezone.utc))
    store.save(state)


def _should_deliver(conversation_id: str) -> bool:
    if not conversation_id:
        return True
    config = ConfigManager().config
    store = JsonBriefDeliveryStore(project_delivery_path(_project_path()))
    state = store.load()
    return should_deliver_brief(
        state.last_delivered_at(conversation_id),
        refresh_hours=float(config.brief_refresh_hours),
        force=False,
    )


def run_cursor_session_start() -> None:
    payload = _read_stdin_json()
    conversation_id = _conversation_id(payload)
    _log_hook_metadata("session-start", "cursor", conversation_id)
    if not _should_deliver(conversation_id):
        print("{}")
        return
    brief = _render_brief_text()
    _maybe_record_delivery(conversation_id)
    print(json.dumps({"additional_context": brief}))


def run_cursor_before_prompt() -> None:
    """Cursor cannot inject context on beforeSubmitPrompt — acknowledge only."""
    _read_stdin_json()
    print(json.dumps({"continue": True}))


def run_cursor_stop() -> None:
    _run_capture_hook(_read_stdin_json(), harness="cursor")


def run_claude_user_prompt() -> None:
    """Inject the brief as UserPromptSubmit additionalContext.

    Claude Code adds plain stdout to context on exit 0, and it also accepts
    ``hookSpecificOutput.additionalContext``. A top-level ``additionalContext``
    key is ignored. The nested form is what the current hooks guide shows for
    this event, and it stays valid when the brief itself contains braces.
    """
    payload = _read_stdin_json()
    conversation_id = _conversation_id(payload)
    _log_hook_metadata("prompt-submit", "claude-code", conversation_id)
    if not _should_deliver(conversation_id):
        return
    brief = _render_brief_text()[:10_000]
    _maybe_record_delivery(conversation_id)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": brief,
                }
            }
        )
    )


def run_claude_stop() -> None:
    _run_capture_hook(_read_stdin_json(), harness="claude")


def _run_capture_hook(payload: dict[str, Any], *, harness: str) -> None:
    import importlib

    config = ConfigManager().config
    if not config.session_capture_enabled:
        return
    if importlib.util.find_spec("basic_memory.session_capture.capture") is None:
        return
    capture = importlib.import_module("basic_memory.session_capture.capture")
    capture.handle_stop_event(
        payload,
        harness=harness,
        conversation_id=_conversation_id(payload),
    )
