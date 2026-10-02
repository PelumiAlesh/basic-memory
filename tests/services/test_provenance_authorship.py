"""Fork source-app stamps stay beside upstream created_by/updated_by.

`created_by` and `updated_by` name a person or agent when the runtime
authenticated one. `bm_*` names the source app. A write may carry both, and
neither record may overwrite the other.
"""

from datetime import UTC, datetime
from pathlib import Path

from basic_memory.file_utils import parse_frontmatter
from basic_memory.markdown.schemas import EntityFrontmatter, EntityMarkdown
from basic_memory.services.note_authorship import NoteAuthorship, stamp_note_authorship
from basic_memory.services.note_preparation import (
    PreparedEntityFields,
    PreparedEntityWrite,
    _merge_metadata_into_markdown,
)
from basic_memory.shared_memory.provenance import provenance_stamp

_NOTE = """---
title: Plan
updated: 2024-03-01T09:30:00Z
created_by: Alice
updated_by: Alice
bm_source_client: cursor
bm_created_by_client: cursor
---

Body stays.
"""


def test_source_app_stamp_does_not_use_authorship_or_user_timestamp_keys() -> None:
    stamp = provenance_stamp("cursor", datetime(2026, 9, 27, 14, 4, 5, tzinfo=UTC))

    assert set(stamp) == {"bm_source_client", "bm_updated", "bm_created_by_client"}


def test_provenance_only_edit_keeps_authorship_user_updated_and_first_app() -> None:
    written = _merge_metadata_into_markdown(
        _NOTE,
        provenance_stamp("claude-code", datetime(2026, 9, 29, 12, 0, tzinfo=UTC)),
    )

    assert "updated: 2024-03-01T09:30:00Z" in written
    assert "created_by: Alice" in written
    assert "updated_by: Alice" in written
    frontmatter = parse_frontmatter(written)
    assert frontmatter["bm_source_client"] == "claude-code"
    assert frontmatter["bm_created_by_client"] == "cursor"
    assert "bm_updated" in frontmatter


def test_mixed_metadata_edit_still_keeps_the_first_app_and_authorship() -> None:
    written = _merge_metadata_into_markdown(
        _NOTE,
        {
            **provenance_stamp("claude-code", datetime(2026, 9, 29, 12, 0, tzinfo=UTC)),
            "status": "active",
        },
    )

    frontmatter = parse_frontmatter(written)
    assert frontmatter["status"] == "active"
    assert frontmatter["bm_source_client"] == "claude-code"
    assert frontmatter["bm_created_by_client"] == "cursor"
    assert frontmatter["created_by"] == "Alice"
    assert frontmatter["updated_by"] == "Alice"
    assert "Body stays." in written


def test_an_edit_does_not_invent_a_first_app_or_an_author() -> None:
    note = "---\ntitle: From Obsidian\nupdated: 2024-03-01T09:30:00Z\n---\n\nBody\n"
    written = _merge_metadata_into_markdown(
        note,
        {
            **provenance_stamp("cursor", datetime(2026, 9, 29, 12, 0, tzinfo=UTC)),
            "status": "active",
        },
    )

    frontmatter = parse_frontmatter(written)
    assert frontmatter["bm_source_client"] == "cursor"
    assert "bm_created_by_client" not in frontmatter
    assert "created_by" not in frontmatter
    assert "updated_by" not in frontmatter
    assert NoteAuthorship.for_write(None, current_markdown=written) is None


def test_authorship_stamp_keeps_source_app_fields() -> None:
    markdown = """---
title: Plan
updated: 2024-03-01T09:30:00Z
bm_source_client: cursor
bm_updated: '2026-09-27T14:04:05+00:00'
bm_created_by_client: cursor
created_by: Forged
updated_by: Forged
---

Body stays.
"""
    metadata = {
        "title": "Plan",
        "updated": "2024-03-01T09:30:00Z",
        "bm_source_client": "cursor",
        "bm_updated": "2026-09-27T14:04:05+00:00",
        "bm_created_by_client": "cursor",
        "created_by": "Forged",
        "updated_by": "Forged",
    }
    now = datetime(2026, 9, 29, tzinfo=UTC)
    prepared = PreparedEntityWrite(
        file_path=Path("notes/plan.md"),
        markdown_content=markdown,
        search_content=markdown,
        entity_fields=PreparedEntityFields(
            title="Plan",
            note_type="note",
            entity_metadata=metadata,
            content_type="text/markdown",
            permalink="notes/plan",
            file_path="notes/plan.md",
            created_at=now,
            updated_at=now,
        ),
        entity_markdown=EntityMarkdown(frontmatter=EntityFrontmatter(metadata=metadata)),
    )

    stamped = stamp_note_authorship(
        prepared,
        NoteAuthorship(created_by="Alice", updated_by="Paul"),
    )

    frontmatter = parse_frontmatter(stamped.markdown_content)
    assert frontmatter["created_by"] == "Alice"
    assert frontmatter["updated_by"] == "Paul"
    assert frontmatter["bm_source_client"] == "cursor"
    assert frontmatter["bm_created_by_client"] == "cursor"
    assert frontmatter["bm_updated"] == "2026-09-27T14:04:05+00:00"
    # YAML reads an unquoted timestamp as a datetime. The key is still the user's.
    assert frontmatter["updated"] == datetime(2024, 3, 1, 9, 30, tzinfo=UTC)
    assert stamped.entity_fields.entity_metadata is not None
    assert stamped.entity_fields.entity_metadata["bm_source_client"] == "cursor"
    assert stamped.entity_fields.entity_metadata["created_by"] == "Alice"
