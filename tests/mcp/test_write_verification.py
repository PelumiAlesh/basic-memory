"""The MCP write tools read their result back and report a write that did not land as an error.

Each failure is injected where it happens in real use: between the tool and the API (a
body cut short or doubled), behind the index on disk (a file changed, lost, or left
behind), or in the file writer (stuck).
"""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from basic_memory.index.note_content_materialization import (
    InlineNoteFileDeleteEnqueuer,
    LocalNoteContentMaterializationProvider,
)
from basic_memory.mcp.clients import KnowledgeClient
from basic_memory.mcp.tools.delete_note import delete_note
from basic_memory.mcp.tools.edit_note import edit_note
from basic_memory.mcp.tools.move_note import move_note
from basic_memory.mcp.tools.write_note import write_note
from basic_memory.schemas.base import Entity
from basic_memory.schemas.response import DeleteEntitiesResponse
from basic_memory.shared_memory import verification

PLAN = "# Plan\n\nShip the parser first.\n\n## Log\n\n- started"
VERIFIED = "verification: verified (index and file)"


# --- Injections ---


def _send_instead(monkeypatch: pytest.MonkeyPatch, change: Callable[[str], str]) -> None:
    """write_note sends `change(content)` to the API, like a client that mangles the body."""
    original = KnowledgeClient.write_note

    async def mangled(self: KnowledgeClient, note: Entity, *, overwrite: bool) -> Any:
        changed = note.model_copy(update={"content": change(note.content or "")})
        return await original(self, changed, overwrite=overwrite)

    monkeypatch.setattr(KnowledgeClient, "write_note", mangled)


def _patch_instead(monkeypatch: pytest.MonkeyPatch, change: Callable[[str], str]) -> None:
    """edit_note sends its edit with `change(content)` as the new text."""
    original = KnowledgeClient.patch_entity

    async def mangled(self: KnowledgeClient, entity_id: str, patch_data: dict[str, Any]) -> Any:
        changed = {**patch_data, "content": change(patch_data["content"])}
        return await original(self, entity_id, changed)

    monkeypatch.setattr(KnowledgeClient, "patch_entity", mangled)


def _after_file_writer(monkeypatch: pytest.MonkeyPatch, damage: Callable[[], object]) -> None:
    """Let the file writer finish, then `damage` the disk before the check reads it."""
    drain = verification.drain_pending_materializations

    async def drain_then_damage() -> None:
        await drain()
        damage()

    monkeypatch.setattr(verification, "drain_pending_materializations", drain_then_damage)


def _skip_file_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accept writes without writing their files, like a file writer that has not run yet."""

    async def accepted_only(self: LocalNoteContentMaterializationProvider, accepted: Any) -> Any:
        return accepted

    monkeypatch.setattr(
        LocalNoteContentMaterializationProvider, "materialize_write_change", accepted_only
    )


def _stick_file_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never_drains() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(verification, "drain_pending_materializations", never_drains)
    monkeypatch.setattr(verification, "DRAIN_TIMEOUT_SECONDS", 0.05)


def _keep_deleted_files(monkeypatch: pytest.MonkeyPatch) -> None:
    async def keep(self: InlineNoteFileDeleteEnqueuer, request: Any) -> None:
        return None

    monkeypatch.setattr(InlineNoteFileDeleteEnqueuer, "enqueue_note_file_delete", keep)


def _disable_verification(config_manager: Any) -> None:
    config = config_manager.load_config()
    config.verify_writes = False
    config_manager.save_config(config)


async def _write_plan(project: str, title: str = "plan") -> dict[str, Any]:
    result = await write_note(
        project=project, title=title, directory="notes", content=PLAN, output_format="json"
    )
    assert isinstance(result, dict)
    return result


# --- write_note ---


@pytest.mark.asyncio
async def test_write_note_reports_the_read_back(app, client, test_project) -> None:
    text = await write_note(
        project=test_project.name, title="plan", directory="notes", content=PLAN
    )
    data = await _write_plan(test_project.name, title="spec")

    assert VERIFIED in text
    assert data["verification"] == {"status": "verified", "disk_checked": True}
    assert "error" not in data


@pytest.mark.asyncio
async def test_write_note_cut_short_is_an_error(app, client, test_project, monkeypatch) -> None:
    _send_instead(monkeypatch, lambda body: body[: len(body) // 2])

    text = await write_note(
        project=test_project.name, title="plan", directory="notes", content=PLAN
    )

    assert isinstance(text, str)
    assert text.startswith("# Error: Write not verified")
    assert "Do not report this as done" in text
    assert text.endswith("verification: failed (truncated)")


@pytest.mark.asyncio
async def test_write_note_doubled_is_an_error(app, client, test_project, monkeypatch) -> None:
    _send_instead(monkeypatch, lambda body: f"{body}\n\n{body}")

    data = await _write_plan(test_project.name)

    assert data["error"] == "WRITE_VERIFICATION_FAILED"
    assert data["verification"]["status"] == "failed"
    assert data["verification"]["reason"] == "duplicated"
    assert data["file_path"] == "notes/plan.md"


@pytest.mark.asyncio
async def test_write_note_with_no_body_is_not_verified(app, client, test_project) -> None:
    data = await write_note(
        project=test_project.name,
        title="empty",
        directory="notes",
        content="---\nstatus: draft\n---\n",
        output_format="json",
    )

    assert isinstance(data, dict)
    assert data["error"] == "WRITE_VERIFICATION_FAILED"
    assert data["verification"]["reason"] == "empty"


@pytest.mark.asyncio
async def test_write_note_file_changed_on_disk_is_an_error(
    app, client, test_project, monkeypatch
) -> None:
    note_file = Path(test_project.path) / "notes" / "plan.md"
    _after_file_writer(monkeypatch, lambda: note_file.write_text("# Plan\n\nSomething else.\n"))

    data = await _write_plan(test_project.name)

    assert data["verification"]["reason"] == "file_differs"
    assert "file write status: synced" in data["verification"]["detail"]


@pytest.mark.asyncio
async def test_write_note_file_lost_on_disk_is_an_error(
    app, client, test_project, monkeypatch
) -> None:
    note_file = Path(test_project.path) / "notes" / "plan.md"
    _after_file_writer(monkeypatch, note_file.unlink)

    text = await write_note(
        project=test_project.name, title="plan", directory="notes", content=PLAN
    )

    assert isinstance(text, str)
    assert text.endswith("verification: failed (file_missing)")


@pytest.mark.asyncio
async def test_write_note_waits_a_bounded_time_for_a_stuck_file_writer(
    app, client, test_project, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    _skip_file_writes(monkeypatch)
    _stick_file_writer(monkeypatch)

    started = time.monotonic()
    text = await write_note(
        project=test_project.name,
        title="plan",
        directory="notes",
        content=PLAN + "\n- rewritten",
        overwrite=True,
    )

    assert time.monotonic() - started < 5
    assert isinstance(text, str)
    assert "# Updated note" in text
    assert "verification: pending (notes/plan.md was still being written" in text


@pytest.mark.asyncio
async def test_write_note_skips_the_check_when_disabled(
    app, client, test_project, config_manager, monkeypatch
) -> None:
    _disable_verification(config_manager)
    _send_instead(monkeypatch, lambda body: body[: len(body) // 2])

    text = await write_note(
        project=test_project.name, title="plan", directory="notes", content=PLAN
    )
    data = await _write_plan(test_project.name, title="spec")

    assert "verification:" not in text
    assert data["verification"] is None


# --- edit_note ---


@pytest.mark.asyncio
async def test_edit_note_reports_the_read_back(app, client, test_project) -> None:
    await _write_plan(test_project.name)

    appended = await edit_note(
        "notes/plan", operation="append", content="- shipped", project=test_project.name
    )
    created = await edit_note(
        "notes/fresh", operation="append", content="# Fresh\n\nNew.", project=test_project.name
    )

    assert VERIFIED in appended
    assert "# Created note (append)" in created
    assert VERIFIED in created


@pytest.mark.asyncio
async def test_edit_note_doubled_append_is_an_error(app, client, test_project, monkeypatch) -> None:
    await _write_plan(test_project.name)
    _patch_instead(monkeypatch, lambda text: f"{text}\n{text}")

    data = await edit_note(
        "notes/plan",
        operation="append",
        content="- ok",
        project=test_project.name,
        output_format="json",
    )

    assert isinstance(data, dict)
    assert data["error"] == "WRITE_VERIFICATION_FAILED"
    assert data["verification"]["reason"] == "duplicated"
    assert data["fileCreated"] is False


@pytest.mark.asyncio
async def test_edit_note_append_cut_short_is_an_error(
    app, client, test_project, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    _patch_instead(monkeypatch, lambda text: text[: len(text) // 2])

    text = await edit_note(
        "notes/plan",
        operation="append",
        content="- deployed the parser to staging",
        project=test_project.name,
    )

    assert isinstance(text, str)
    assert text.startswith("# Edit Failed - Not Verified")
    assert text.endswith("verification: failed (truncated)")


@pytest.mark.asyncio
async def test_edit_note_after_a_concurrent_change_is_a_mismatch(
    app, client, test_project, monkeypatch
) -> None:
    """Another writer edits the note between edit_note's read and its PATCH."""
    await _write_plan(test_project.name)
    original = KnowledgeClient.patch_entity

    async def other_writer_first(
        self: KnowledgeClient, entity_id: str, patch_data: dict[str, Any]
    ) -> Any:
        concurrent = {"operation": "find_replace", "find_text": "parser", "content": "lexer"}
        await original(self, entity_id, concurrent)
        return await original(self, entity_id, patch_data)

    monkeypatch.setattr(KnowledgeClient, "patch_entity", other_writer_first)

    data = await edit_note(
        "notes/plan",
        operation="find_replace",
        find_text="lexer",
        content="tokenizer",
        project=test_project.name,
        output_format="json",
    )

    assert isinstance(data, dict)
    assert data["verification"] == {
        "status": "failed",
        "reason": "mismatch",
        "detail": "the note changed between the read before this edit and the edit itself",
    }


@pytest.mark.asyncio
async def test_edit_note_skips_the_read_before_the_edit_when_disabled(
    app, client, test_project, config_manager, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    _disable_verification(config_manager)
    reads: list[str] = []
    original = KnowledgeClient.get_entity

    async def counted(self: KnowledgeClient, entity_id: str, **kwargs: Any) -> Any:
        reads.append(entity_id)
        return await original(self, entity_id, **kwargs)

    monkeypatch.setattr(KnowledgeClient, "get_entity", counted)

    data = await edit_note(
        "notes/plan",
        operation="append",
        content="- shipped",
        project=test_project.name,
        output_format="json",
    )

    assert isinstance(data, dict)
    assert data["verification"] is None
    assert reads == []


# --- move_note ---


@pytest.mark.asyncio
async def test_move_note_reports_the_read_back(app, client, test_project) -> None:
    await _write_plan(test_project.name)
    await _write_plan(test_project.name, title="spec")

    text = await move_note(
        "notes/plan", destination_path="archive/plan.md", project=test_project.name
    )
    data = await move_note(
        "notes/spec",
        destination_path="archive/spec.md",
        project=test_project.name,
        output_format="json",
    )

    assert "✅ Note moved successfully" in text
    assert VERIFIED in text
    assert isinstance(data, dict)
    assert data["moved"] is True
    assert data["verification"] == {"status": "verified", "disk_checked": True}


@pytest.mark.asyncio
async def test_move_note_leaving_the_old_file_is_an_error(
    app, client, test_project, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    source = Path(test_project.path) / "notes" / "plan.md"
    old_bytes = source.read_bytes()
    _after_file_writer(monkeypatch, lambda: source.write_bytes(old_bytes))

    data = await move_note(
        "notes/plan",
        destination_path="archive/plan.md",
        project=test_project.name,
        output_format="json",
    )

    assert isinstance(data, dict)
    assert data["moved"] is False
    assert data["error"] == "WRITE_VERIFICATION_FAILED"
    assert data["verification"] == {
        "status": "failed",
        "reason": "source_remains",
        "detail": "notes/plan.md is still on disk after the move",
    }


@pytest.mark.asyncio
async def test_move_note_losing_the_new_file_is_an_error(
    app, client, test_project, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    destination = Path(test_project.path) / "archive" / "plan.md"
    _after_file_writer(monkeypatch, destination.unlink)

    text = await move_note(
        "notes/plan", destination_path="archive/plan.md", project=test_project.name
    )

    assert isinstance(text, str)
    assert text.startswith("# Move Failed - Not Verified")
    assert text.endswith("verification: failed (file_missing)")


# --- delete_note ---


@pytest.mark.asyncio
async def test_delete_note_reports_the_read_back(app, client, test_project) -> None:
    await _write_plan(test_project.name)
    await _write_plan(test_project.name, title="spec")

    deleted = await delete_note("notes/plan", project=test_project.name)
    data = await delete_note("notes/spec", project=test_project.name, output_format="json")

    assert deleted is True
    assert isinstance(data, dict)
    assert data["deleted"] is True
    assert data["verification"] == {"status": "verified", "disk_checked": True}
    assert not (Path(test_project.path) / "notes" / "plan.md").exists()


@pytest.mark.asyncio
async def test_delete_note_leaving_the_file_is_an_error(
    app, client, test_project, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    await _write_plan(test_project.name, title="spec")
    _keep_deleted_files(monkeypatch)

    data = await delete_note("notes/plan", project=test_project.name, output_format="json")
    text = await delete_note("notes/spec", project=test_project.name)

    assert isinstance(data, dict)
    assert data["deleted"] is False
    assert data["error"] == "WRITE_VERIFICATION_FAILED"
    assert data["verification"]["reason"] == "file_remains"
    assert isinstance(text, str)
    assert text.startswith("# Delete Failed - Not Verified")
    assert text.endswith("verification: failed (file_remains)")


@pytest.mark.asyncio
async def test_delete_note_still_indexed_is_an_error(
    app, client, test_project, monkeypatch
) -> None:
    await _write_plan(test_project.name)

    async def claims_deleted(self: KnowledgeClient, entity_id: str) -> DeleteEntitiesResponse:
        return DeleteEntitiesResponse(deleted=True)

    monkeypatch.setattr(KnowledgeClient, "delete_entity", claims_deleted)

    data = await delete_note("notes/plan", project=test_project.name, output_format="json")

    assert isinstance(data, dict)
    assert data["deleted"] is False
    assert data["verification"]["reason"] == "still_indexed"


@pytest.mark.asyncio
async def test_delete_note_not_yet_confirmed_says_so(
    app, client, test_project, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    _keep_deleted_files(monkeypatch)
    _stick_file_writer(monkeypatch)

    text = await delete_note("notes/plan", project=test_project.name)

    assert isinstance(text, str)
    assert text.startswith("# Note Deleted - Not Yet Confirmed")
    assert text.endswith(
        "verification: pending (notes/plan.md was still on disk when the check stopped waiting)"
    )


@pytest.mark.asyncio
async def test_delete_note_skips_the_check_when_disabled(
    app, client, test_project, config_manager, monkeypatch
) -> None:
    await _write_plan(test_project.name)
    await _write_plan(test_project.name, title="spec")
    _disable_verification(config_manager)
    _keep_deleted_files(monkeypatch)

    deleted = await delete_note("notes/plan", project=test_project.name)
    data = await delete_note("notes/spec", project=test_project.name, output_format="json")

    assert deleted is True
    assert isinstance(data, dict)
    assert data["deleted"] is True
    assert data["verification"] is None
