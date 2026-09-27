"""End-of-session summary for the review inbox (off by default).

Builds a short structural summary from harness transcript turns — role and
clipped text only — and stamps it `visibility: private` plus unreviewed so a
denied client cannot later read private note bodies that were never copied
into the capture. Idempotent on `(source, session_id)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

MAX_TURNS = 12
MAX_TURN_CHARS = 240
MAX_SUMMARY_CHARS = 2_500


@dataclass(frozen=True, slots=True)
class SessionCaptureDraft:
    """Ready-to-write note fields for one session end."""

    title: str
    content: str
    directory: str
    note_type: str
    tags: list[str]
    metadata: dict[str, object]
    session_key: str


def session_idempotency_key(source: str, session_id: str) -> str:
    return f"{source}:{session_id}"


def build_session_summary(
    turns: list[tuple[str, str]],
    *,
    status: str | None = None,
) -> str:
    """Structural transcript summary — no private note bodies, clipped turns."""
    lines = [
        "# Session summary",
        "",
        "Auto-captured at session end for human review. Visibility is private.",
        "This is a short structural summary of the transcript, not durable memory.",
        "",
    ]
    if status:
        lines.extend([f"- session_status: {status}", ""])
    lines.append("## Turns")
    lines.append("")
    if not turns:
        lines.append("_No human/assistant turns were available in the transcript._")
    else:
        for role, text in turns[-MAX_TURNS:]:
            clipped = " ".join(text.split())
            if len(clipped) > MAX_TURN_CHARS:
                clipped = clipped[: MAX_TURN_CHARS - 1].rstrip() + "…"
            lines.append(f"- **{role}**: {clipped}")
    body = "\n".join(lines).strip() + "\n"
    if len(body) > MAX_SUMMARY_CHARS:
        body = body[: MAX_SUMMARY_CHARS - 1].rstrip() + "…\n"
    return body


def draft_session_capture(
    *,
    source: str,
    session_id: str,
    project: str,
    turns: list[tuple[str, str]],
    status: str | None,
    capture_folder: str,
    session_id_key: str,
    note_type: str,
    client_tag: str,
    review_inbox_mode: str,
    review_inbox_folder: str,
) -> SessionCaptureDraft | None:
    """Build the inbox note, or None when there is nothing useful to keep."""
    if not session_id.strip():
        return None
    if not any(role == "user" for role, _ in turns) and not status:
        return None

    directory = capture_folder.strip().strip("/") or "sessions"
    if review_inbox_mode == "folder":
        folder = review_inbox_folder.strip().strip("/") or "inbox"
        directory = f"{folder}/{directory}"

    day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    short_id = session_id.strip()[:8]
    title = f"Session {day} ({client_tag} {short_id})"
    key = session_idempotency_key(source, session_id.strip())
    metadata: dict[str, object] = {
        session_id_key: session_id.strip(),
        "session_capture_key": key,
        "source_client": client_tag,
        "visibility": "private",
        "status": "unreviewed",
        "project_hint": project,
        "updated": datetime.now(tz=timezone.utc).isoformat(),
    }
    if status:
        metadata["session_status"] = status

    return SessionCaptureDraft(
        title=title,
        content=build_session_summary(turns, status=status),
        directory=directory,
        note_type=note_type,
        tags=[client_tag, "session-capture", "unreviewed"],
        metadata=metadata,
        session_key=key,
    )
