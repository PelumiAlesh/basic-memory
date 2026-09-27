"""Provenance stamps and client slug normalization."""

from datetime import datetime, timezone

from basic_memory.services.note_preparation import _merge_metadata_into_markdown
from basic_memory.shared_memory.client_names import client_slug, slug_from_client_info
from basic_memory.shared_memory.provenance import (
    keep_original_creator,
    provenance_lines,
    stamp_provenance,
)


def test_client_slug_maps_known_clients() -> None:
    assert client_slug("openai-mcp") == "chatgpt"
    assert client_slug("openai-mcp/1.2.3") == "chatgpt"
    assert client_slug("Claude Code") == "claude-code"
    assert client_slug("cursor-vscode") == "cursor"
    assert client_slug("Grok Bot") == "grok"
    assert client_slug(None, "Cursor") == "cursor"


def test_client_slug_rejects_blank_and_keeps_unknown_names() -> None:
    assert client_slug("  ") is None
    assert client_slug(None, None) is None
    assert client_slug("My Custom Client") == "my-custom-client"
    assert slug_from_client_info({"name": "codex", "title": None}) == "codex"
    assert slug_from_client_info(None) is None


def test_stamp_provenance_skips_when_disabled_or_anonymous() -> None:
    original = {"status": "open"}
    assert stamp_provenance(original, client="cursor", enabled=False) == original
    assert stamp_provenance(original, client=None, enabled=True) == original
    assert original == {"status": "open"}


def test_stamp_provenance_records_client_and_time() -> None:
    moment = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    stamped = stamp_provenance({"tags": ["a"]}, client="cursor", enabled=True, now=moment)
    assert stamped["source_client"] == "cursor"
    assert stamped["created_by_client"] == "cursor"
    assert stamped["updated"] == "2026-09-27T12:00:00+00:00"
    assert stamped["tags"] == ["a"]


def test_keep_original_creator_on_later_edit() -> None:
    merged = {"source_client": "chatgpt", "created_by_client": "chatgpt", "status": "open"}
    keep_original_creator({"created_by_client": "cursor"}, merged)
    assert merged["created_by_client"] == "cursor"
    assert merged["source_client"] == "chatgpt"


def test_keep_original_creator_does_not_invent_one() -> None:
    merged = {"source_client": "cursor", "created_by_client": "cursor"}
    keep_original_creator({}, merged)
    assert "created_by_client" not in merged
    assert merged["source_client"] == "cursor"


def test_edit_merge_preserves_created_by_client() -> None:
    original = """---
title: Decision
type: decision
created_by_client: cursor
---

Body
"""
    merged = _merge_metadata_into_markdown(
        original,
        {
            "source_client": "chatgpt",
            "created_by_client": "chatgpt",
            "updated": "2026-09-27T12:00:00+00:00",
        },
    )
    assert "created_by_client: cursor" in merged
    assert "source_client: chatgpt" in merged
    assert "created_by_client: chatgpt" not in merged


def test_provenance_lines_skip_blank_values() -> None:
    assert provenance_lines({"source_client": "cursor", "updated": "  "}) == [
        "source_client: cursor"
    ]
    assert provenance_lines(None) == []
