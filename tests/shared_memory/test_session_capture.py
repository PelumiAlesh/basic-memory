"""End-of-session summary draft helpers."""

from basic_memory.shared_memory.session_capture import (
    build_session_summary,
    draft_session_capture,
    session_idempotency_key,
)


def test_build_session_summary_clips_turns() -> None:
    turns = [("user", "hello " * 100), ("assistant", "world")]
    text = build_session_summary(turns, status="completed")
    assert "session_status: completed" in text
    assert "**user**:" in text
    assert "…" in text
    assert "private" in text.lower()


def test_draft_is_private_unreviewed_and_idempotent_key() -> None:
    draft = draft_session_capture(
        source="cursor",
        session_id="abc-123-def",
        project="main",
        turns=[("user", "ship it"), ("assistant", "done")],
        status="completed",
        capture_folder="cursor/sessions",
        session_id_key="cursor_conversation_id",
        note_type="cursor_session",
        client_tag="cursor",
        review_inbox_mode="status",
        review_inbox_folder="inbox",
    )
    assert draft is not None
    assert draft.metadata["visibility"] == "private"
    assert draft.metadata["status"] == "unreviewed"
    assert draft.metadata["session_capture_key"] == session_idempotency_key("cursor", "abc-123-def")
    assert "cursor" in draft.tags
    assert draft.directory == "cursor/sessions"


def test_draft_uses_inbox_folder_when_configured() -> None:
    draft = draft_session_capture(
        source="claude-code",
        session_id="sess-1",
        project="main",
        turns=[("user", "hi")],
        status=None,
        capture_folder="sessions",
        session_id_key="claude_session_id",
        note_type="session",
        client_tag="claude-code",
        review_inbox_mode="folder",
        review_inbox_folder="inbox",
    )
    assert draft is not None
    assert draft.directory == "inbox/sessions"


def test_draft_skips_empty_session() -> None:
    assert (
        draft_session_capture(
            source="cursor",
            session_id="",
            project="main",
            turns=[],
            status=None,
            capture_folder="sessions",
            session_id_key="cursor_conversation_id",
            note_type="cursor_session",
            client_tag="cursor",
            review_inbox_mode="status",
            review_inbox_folder="inbox",
        )
        is None
    )
