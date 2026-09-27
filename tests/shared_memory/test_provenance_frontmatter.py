"""Provenance lives in bm_* frontmatter keys and never rewrites the user's own keys."""

from datetime import datetime, timedelta, timezone

from basic_memory.shared_memory.provenance import (
    CREATED_BY_CLIENT_KEY,
    SOURCE_CLIENT_KEY,
    UPDATED_KEY,
    keep_first_writer,
    provenance_stamp,
    write_frontmatter_lines,
)


def test_stamp_uses_namespaced_keys_and_utc_time() -> None:
    later_in_lagos = datetime(2026, 9, 27, 15, 4, 5, 999, tzinfo=timezone(timedelta(hours=1)))

    stamp = provenance_stamp("cursor", later_in_lagos)

    assert stamp == {
        SOURCE_CLIENT_KEY: "cursor",
        UPDATED_KEY: "2026-09-27T14:04:05+00:00",
        CREATED_BY_CLIENT_KEY: "cursor",
    }
    assert not {"updated", "created", "modified", "source_client"} & stamp.keys()


def test_first_writer_survives_a_merge() -> None:
    merged = {CREATED_BY_CLIENT_KEY: "chatgpt", SOURCE_CLIENT_KEY: "chatgpt"}

    keep_first_writer({CREATED_BY_CLIENT_KEY: "cursor"}, merged)

    assert merged == {CREATED_BY_CLIENT_KEY: "cursor", SOURCE_CLIENT_KEY: "chatgpt"}


def test_a_note_without_a_creator_does_not_gain_one_on_update() -> None:
    merged = {CREATED_BY_CLIENT_KEY: "chatgpt", SOURCE_CLIENT_KEY: "chatgpt"}

    keep_first_writer({"title": "Written in Obsidian"}, merged)

    assert merged == {SOURCE_CLIENT_KEY: "chatgpt"}


def test_frontmatter_lines_leave_user_values_byte_for_byte() -> None:
    note = (
        "---\n"
        "title: Plan\n"
        "updated: 2024-03-01T09:30:00Z\n"
        "tags: [a, b]\n"
        "bm_source_client: cursor\n"
        "---\n"
        "\n"
        "Body stays.\n"
    )

    written = write_frontmatter_lines(
        note, {SOURCE_CLIENT_KEY: "claude-code", UPDATED_KEY: "2026-09-27T14:04:05+00:00"}
    )

    assert written == (
        "---\n"
        "title: Plan\n"
        "updated: 2024-03-01T09:30:00Z\n"
        "tags: [a, b]\n"
        "bm_source_client: claude-code\n"
        "bm_updated: '2026-09-27T14:04:05+00:00'\n"
        "---\n"
        "\n"
        "Body stays.\n"
    )


def test_frontmatter_lines_replace_duplicates_and_multiline_values() -> None:
    note = (
        "\r\n---\r\n"
        "bm_source_client:\r\n"
        "  - old\r\n"
        "- older\r\n"
        "title: Plan\r\n"
        "bm_source_client: stale\r\n"
        "---\r\n"
        "Body"
    )

    written = write_frontmatter_lines(note, {SOURCE_CLIENT_KEY: "grok"})

    assert written == "\r\n---\r\nbm_source_client: grok\r\ntitle: Plan\r\n---\r\nBody"
