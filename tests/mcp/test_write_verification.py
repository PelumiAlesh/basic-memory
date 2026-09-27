"""write_note, edit_note, move_note, and delete_note read their result back."""

from pathlib import Path

import pytest

from basic_memory.mcp import clients as clients_module
from basic_memory.mcp.tools import delete_note, edit_note, move_note, write_note
from basic_memory.schemas.v2.entity import EntityResponseV2


@pytest.mark.asyncio
async def test_write_note_reports_verified_against_index_and_disk(client, test_project):
    result = await write_note(
        project=test_project.name,
        title="Verified Plan",
        directory="plans",
        content="# Verified Plan\n\nThis body must land on disk exactly once.",
        output_format="json",
    )
    assert isinstance(result, dict)
    assert result["verification"]["status"] == "verified"
    assert result["verification"]["checks"] == {"index": "ok", "disk": "ok"}
    assert "error" not in result
    assert (Path(test_project.path) / "plans" / "Verified Plan.md").is_file()


@pytest.mark.asyncio
async def test_write_note_text_output_carries_verification_section(client, test_project):
    result = await write_note(
        project=test_project.name,
        title="Text Verified",
        directory="plans",
        content="# Text Verified\n\nBody.",
    )
    assert isinstance(result, str)
    assert "## Verification" in result
    assert "status: verified" in result


@pytest.mark.asyncio
async def test_write_note_flags_truncated_readback(client, test_project, monkeypatch):
    original = clients_module.KnowledgeClient.get_entity

    async def truncated(self, entity_id, **kwargs):
        entity: EntityResponseV2 = await original(self, entity_id, **kwargs)
        cut = (entity.content or "")[: len(entity.content or "") - 20]
        return entity.model_copy(update={"content": cut})

    monkeypatch.setattr(clients_module.KnowledgeClient, "get_entity", truncated)
    result = await write_note(
        project=test_project.name,
        title="Truncated Plan",
        directory="plans",
        content="# Truncated Plan\n\nA body long enough that cutting twenty characters shows.",
        output_format="json",
    )
    assert isinstance(result, dict)
    assert result["verification"]["status"] == "failed"
    assert result["verification"]["checks"]["index"] == "truncated"
    assert result["error"] == "WRITE_VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_edit_note_append_verified_and_duplicate_flagged(client, test_project, monkeypatch):
    await write_note(
        project=test_project.name,
        title="Edit Verified",
        directory="plans",
        content="# Edit Verified\n\nOriginal body stays here.",
    )
    ok = await edit_note(
        project=test_project.name,
        identifier="plans/edit-verified",
        operation="append",
        content="\n## Decision\n\nUse SQLite for the local index.",
        output_format="json",
    )
    assert isinstance(ok, dict)
    assert ok["verification"]["status"] == "verified"

    original = clients_module.KnowledgeClient.get_entity
    calls = {"n": 0}

    async def doubled_after(self, entity_id, **kwargs):
        entity: EntityResponseV2 = await original(self, entity_id, **kwargs)
        calls["n"] += 1
        # First call is the pre-edit read; the second is the read-back.
        if calls["n"] == 2:
            extra = "\n## Follow-up\n\nSecond decision that gets duplicated by a bug."
            return entity.model_copy(update={"content": (entity.content or "") + extra})
        return entity

    monkeypatch.setattr(clients_module.KnowledgeClient, "get_entity", doubled_after)
    dup = await edit_note(
        project=test_project.name,
        identifier="plans/edit-verified",
        operation="append",
        content="\n## Follow-up\n\nSecond decision that gets duplicated by a bug.",
        output_format="json",
    )
    assert isinstance(dup, dict)
    assert dup["verification"]["status"] == "failed"
    assert dup["verification"]["checks"]["index"] == "duplicated"


@pytest.mark.asyncio
async def test_move_and_delete_verify_disk_state(client, test_project):
    await write_note(
        project=test_project.name,
        title="Mover",
        directory="plans",
        content="# Mover\n\nMoves around.",
    )
    moved = await move_note(
        project=test_project.name,
        identifier="plans/mover",
        destination_path="archive/mover.md",
        output_format="json",
    )
    assert isinstance(moved, dict)
    assert moved["moved"] is True
    assert moved["verification"]["status"] == "verified"
    assert moved["verification"]["checks"] == {"index": "ok", "disk": "ok"}
    assert (Path(test_project.path) / "archive" / "mover.md").is_file()
    assert not (Path(test_project.path) / "plans" / "Mover.md").exists()

    deleted = await delete_note(
        project=test_project.name,
        identifier="archive/mover",
        output_format="json",
    )
    assert isinstance(deleted, dict)
    assert deleted["deleted"] is True
    assert deleted["verification"]["status"] == "verified"
    assert not (Path(test_project.path) / "archive" / "mover.md").exists()


@pytest.mark.asyncio
async def test_verification_can_be_disabled(client, test_project, app_config, config_manager):
    from basic_memory import config as config_module

    app_config.verify_writes = False
    config_module._CONFIG_CACHE = app_config
    # Pin mtime and size so the cache guard keeps the injected config.
    stat = config_manager.config_file.stat()
    config_module._CONFIG_MTIME = stat.st_mtime
    config_module._CONFIG_SIZE = stat.st_size
    try:
        result = await write_note(
            project=test_project.name,
            title="Unverified",
            directory="plans",
            content="# Unverified\n\nBody.",
            output_format="json",
        )
    finally:
        app_config.verify_writes = True
        config_module._CONFIG_CACHE = app_config
    assert isinstance(result, dict)
    assert "verification" not in result


@pytest.mark.asyncio
async def test_overwrite_creates_bm_history_snapshot(client, test_project):
    first = await write_note(
        project=test_project.name,
        title="History Note",
        directory="plans",
        content="# History Note\n\nVersion one.",
        output_format="json",
    )
    assert isinstance(first, dict)
    await write_note(
        project=test_project.name,
        title="History Note",
        directory="plans",
        content="# History Note\n\nVersion two.",
        overwrite=True,
        output_format="json",
    )
    history_dir = Path(test_project.path) / ".bm-history"
    copies = list(history_dir.glob("*plans__History Note.md"))
    assert copies
    assert "Version one." in copies[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_overwrite_aborts_when_snapshot_fails(client, test_project, monkeypatch):
    await write_note(
        project=test_project.name,
        title="Blocked Overwrite",
        directory="plans",
        content="# Blocked Overwrite\n\nOriginal.",
    )

    def _fail_snapshot(*_args: object, **_kwargs: object) -> None:
        from fastmcp.exceptions import ToolError

        raise ToolError("Local history snapshot failed: simulated")

    import importlib

    write_note_module = importlib.import_module("basic_memory.mcp.tools.write_note")
    monkeypatch.setattr(write_note_module, "snapshot_local_note", _fail_snapshot)

    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="snapshot failed"):
        await write_note(
            project=test_project.name,
            title="Blocked Overwrite",
            directory="plans",
            content="# Blocked Overwrite\n\nNew body.",
            overwrite=True,
        )

    note_path = Path(test_project.path) / "plans" / "Blocked Overwrite.md"
    assert "Original." in note_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_directory_delete_snapshots_every_child(client, test_project):
    from basic_memory.mcp.tools.delete_note import delete_note

    await write_note(
        project=test_project.name,
        title="Alpha",
        directory="bundle",
        content="# Alpha\n\nkeep-alpha",
    )
    await write_note(
        project=test_project.name,
        title="Beta",
        directory="bundle/nested",
        content="# Beta\n\nkeep-beta",
    )

    result = await delete_note("bundle", is_directory=True, project=test_project.name)
    assert result is not False
    history = Path(test_project.path) / ".bm-history"
    texts = [path.read_text(encoding="utf-8") for path in history.iterdir() if path.is_file()]
    assert any("keep-alpha" in text for text in texts)
    assert any("keep-beta" in text for text in texts)
    assert not (Path(test_project.path) / "bundle" / "Alpha.md").exists()


@pytest.mark.asyncio
async def test_directory_delete_aborts_when_snapshot_fails(client, test_project, monkeypatch):
    from basic_memory.mcp.tools.delete_note import delete_note

    await write_note(
        project=test_project.name,
        title="Alpha",
        directory="bundle",
        content="# Alpha\n\nkeep-alpha",
    )

    def _fail_snapshot(*_args: object, **_kwargs: object) -> None:
        from fastmcp.exceptions import ToolError

        raise ToolError("Local history snapshot failed: simulated")

    import importlib

    delete_module = importlib.import_module("basic_memory.mcp.tools.delete_note")
    monkeypatch.setattr(delete_module, "snapshot_local_directory", _fail_snapshot)

    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="snapshot failed"):
        await delete_note("bundle", is_directory=True, project=test_project.name)

    note_path = Path(test_project.path) / "bundle" / "Alpha.md"
    assert "keep-alpha" in note_path.read_text(encoding="utf-8")
