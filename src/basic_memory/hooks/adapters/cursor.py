"""Cursor hook stdin adapter.

Cursor sends one JSON object on stdin. The fields used here are the ones
documented for command hooks (cursor.com/docs/hooks and the hooks.json
reference): every event carries conversation_id, generation_id,
hook_event_name, and workspace_roots. sessionStart can return
{"additional_context": "..."} on stdout. cwd is not always present; the
first workspace root is the project directory when cwd is absent.
"""

from __future__ import annotations

from basic_memory.hooks.adapters.base import HarnessAdapter, HookPayload, NormalizedHookEvent

SOURCE = "cursor"


def normalize(event: str, payload: HookPayload) -> NormalizedHookEvent:
    """Normalize a Cursor hook payload into the shared event shape."""
    roots = payload.get("workspace_roots")
    first_root = ""
    if isinstance(roots, list) and roots:
        first_root = str(roots[0])
    cwd = payload.get("cwd") or first_root
    session_id = payload.get("conversation_id") or payload.get("session_id") or ""
    generation = payload.get("generation_id")
    model = payload.get("model")
    trigger = payload.get("trigger") or payload.get("hook_event_name")
    return NormalizedHookEvent(
        source=SOURCE,
        event=event,
        session_id=str(session_id),
        turn_id=str(generation) if generation else None,
        cwd=str(cwd or ""),
        transcript_path=str(payload.get("transcript_path") or ""),
        trigger=str(trigger) if trigger else None,
        model=str(model) if model else None,
    )


ADAPTER = HarnessAdapter(source=SOURCE, normalize=normalize)
