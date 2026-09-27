"""Provenance through the real MCP tool -> API -> note preparation path.

A named app (MCP clientInfo) gets bm_* frontmatter on write_note and edit_note. The
user's own `updated` key is never written, the first writer is kept, and anonymous
writes are unchanged.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mcp.types as mt
import pytest
from fastmcp import Client

from basic_memory.config import BasicMemoryConfig, ConfigManager
from basic_memory.file_utils import parse_frontmatter
from basic_memory.index.note_content_materialization import drain_pending_materializations
from basic_memory.mcp.server import mcp
from basic_memory.mcp.tools import write_note

USER_FRONTMATTER = (
    "---\n"
    "title: Shared Plan\n"
    "type: note\n"
    "permalink: test-project/notes/shared-plan\n"
    "updated: 2024-03-01T09:30:00Z\n"
    "---\n"
)


async def _call_as(app_name: str, tool: str, arguments: dict[str, Any]) -> Any:
    async with Client(
        mcp, client_info=mt.Implementation(name=app_name, version="1.0.0")
    ) as session:
        result = await session.call_tool(tool, arguments)
    return result.data


async def _note_bytes(project_path: str, relative_path: str) -> str:
    await drain_pending_materializations()
    return (Path(project_path) / relative_path).read_text(encoding="utf-8")


def _frontmatter_lines(note: str) -> list[str]:
    return note.split("---\n")[1].splitlines()


@pytest.mark.asyncio
async def test_named_app_create_records_namespaced_provenance(app, test_project) -> None:
    result = await _call_as(
        "cursor-vscode",
        "write_note",
        {
            "project": test_project.name,
            "title": "Cursor Note",
            "directory": "notes",
            "content": "# Cursor Note\n\nWritten from Cursor.",
        },
    )
    assert "Created note" in result

    frontmatter = parse_frontmatter(await _note_bytes(test_project.path, "notes/Cursor Note.md"))

    assert frontmatter["bm_source_client"] == "cursor"
    assert frontmatter["bm_created_by_client"] == "cursor"
    written_at = datetime.fromisoformat(frontmatter["bm_updated"])
    assert (datetime.now(timezone.utc) - written_at).total_seconds() < 60
    assert not {"updated", "source_client", "created_by_client"} & frontmatter.keys()


@pytest.mark.asyncio
async def test_edit_of_user_note_keeps_every_user_line_and_invents_no_creator(
    app, test_project
) -> None:
    note_path = Path(test_project.path) / "notes" / "Shared Plan.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(USER_FRONTMATTER + "\nWritten in Obsidian.\n", encoding="utf-8")

    await _call_as(
        "openai-mcp",
        "edit_note",
        {
            "project": test_project.name,
            "identifier": "notes/Shared Plan",
            "operation": "append",
            "content": "\nAdded from ChatGPT.",
        },
    )

    note = await _note_bytes(test_project.path, "notes/Shared Plan.md")
    lines = _frontmatter_lines(note)
    # The user's lines, `updated` included, are byte-for-byte what Obsidian wrote.
    assert lines[:4] == _frontmatter_lines(USER_FRONTMATTER)
    frontmatter = parse_frontmatter(note)
    assert frontmatter["bm_source_client"] == "chatgpt"
    assert "bm_updated" in frontmatter
    # ChatGPT edited a note someone else made; it is not recorded as the creator.
    assert "bm_created_by_client" not in frontmatter
    assert "Written in Obsidian." in note and "Added from ChatGPT." in note


@pytest.mark.asyncio
async def test_overwrite_and_edit_keep_user_updated_and_first_writer(app, test_project) -> None:
    earlier_cursor_write = (
        "---\n"
        "updated: 2024-03-01\n"
        "bm_source_client: cursor\n"
        "bm_created_by_client: cursor\n"
        "bm_updated: '2020-01-01T00:00:00+00:00'\n"
        "---\n"
        "# Roadmap\n\nFirst draft."
    )
    # Anonymous writes are unchanged, so this stores a note Cursor wrote in 2020.
    await write_note(
        project=test_project.name, title="Roadmap", directory="plans", content=earlier_cursor_write
    )

    await _call_as(
        "claude-code",
        "write_note",
        {
            "project": test_project.name,
            "title": "Roadmap",
            "directory": "plans",
            "content": "# Roadmap\n\nSecond draft from Claude Code.",
            "overwrite": True,
        },
    )
    after_overwrite = await _note_bytes(test_project.path, "plans/Roadmap.md")
    frontmatter = parse_frontmatter(after_overwrite)
    assert str(frontmatter["updated"]) == "2024-03-01"
    assert frontmatter["bm_source_client"] == "claude-code"
    assert frontmatter["bm_created_by_client"] == "cursor"
    assert frontmatter["bm_updated"] != "2020-01-01T00:00:00+00:00"
    assert "Second draft from Claude Code." in after_overwrite

    await _call_as(
        "grok-bot",
        "edit_note",
        {
            "project": test_project.name,
            "identifier": "plans/roadmap",
            "operation": "append",
            "content": "\nNote from Grok.",
        },
    )
    after_edit = await _note_bytes(test_project.path, "plans/Roadmap.md")
    frontmatter = parse_frontmatter(after_edit)
    assert "updated: 2024-03-01" in _frontmatter_lines(after_edit)
    assert frontmatter["bm_source_client"] == "grok"
    assert frontmatter["bm_created_by_client"] == "cursor"


@pytest.mark.asyncio
async def test_anonymous_and_disabled_writes_carry_no_provenance(
    app, test_project, app_config: BasicMemoryConfig, config_manager: ConfigManager
) -> None:
    await write_note(
        project=test_project.name, title="Anonymous", directory="notes", content="No client."
    )
    anonymous = parse_frontmatter(await _note_bytes(test_project.path, "notes/Anonymous.md"))
    assert not [key for key in anonymous if key.startswith("bm_")]

    app_config.record_provenance = False
    config_manager.save_config(app_config)
    await _call_as(
        "cursor-vscode",
        "write_note",
        {
            "project": test_project.name,
            "title": "Unstamped",
            "directory": "notes",
            "content": "record_provenance is off.",
        },
    )
    unstamped = parse_frontmatter(await _note_bytes(test_project.path, "notes/Unstamped.md"))
    assert not [key for key in unstamped if key.startswith("bm_")]


@pytest.mark.asyncio
async def test_read_and_search_see_the_namespaced_keys(app, test_project) -> None:
    await _call_as(
        "claude-code",
        "write_note",
        {
            "project": test_project.name,
            "title": "Provenance Target",
            "directory": "notes",
            "content": "Written by Claude Code.",
        },
    )
    await write_note(
        project=test_project.name, title="Other Note", directory="notes", content="Anonymous."
    )

    text = await _call_as(
        "cursor-vscode",
        "read_note",
        {"project": test_project.name, "identifier": "notes/provenance-target"},
    )
    assert "bm_source_client: claude-code" in text
    structured = await _call_as(
        "cursor-vscode",
        "read_note",
        {
            "project": test_project.name,
            "identifier": "notes/provenance-target",
            "output_format": "json",
        },
    )
    assert structured["frontmatter"]["bm_created_by_client"] == "claude-code"

    async def search_where(filters: dict[str, str]) -> Any:
        return await _call_as(
            "cursor-vscode",
            "search_notes",
            {"project": test_project.name, "metadata_filters": filters, "output_format": "json"},
        )

    by_writer = await search_where({"bm_source_client": "claude-code"})
    assert [hit["title"] for hit in by_writer["results"]] == ["Provenance Target"]
    # Nothing is written under the old, un-namespaced keys.
    assert not {"source_client", "created_by_client", "updated"} & structured["frontmatter"].keys()
