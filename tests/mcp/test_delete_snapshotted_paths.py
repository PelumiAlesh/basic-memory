"""Directory deletes remove only the files that were copied into history."""

from pathlib import Path

import pytest

from basic_memory.mcp.tools.delete_note import _delete_snapshotted_paths
from basic_memory.schemas.response import DeleteEntitiesResponse
from basic_memory.shared_memory.file_history import snapshot_before_destructive_write


class _RecordingClient:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def resolve_entity(self, path: str, strict: bool = True) -> str:
        return path

    async def delete_entity(self, entity_id: str) -> DeleteEntitiesResponse:
        self.deleted.append(entity_id)
        return DeleteEntitiesResponse(deleted=True)


@pytest.mark.asyncio
async def test_directory_delete_skips_a_file_that_was_not_snapshotted(tmp_path: Path) -> None:
    copied = tmp_path / "gone.md"
    copied.write_text("copied\n", encoding="utf-8")
    left = tmp_path / "left.md"
    left.write_text("left\n", encoding="utf-8")
    snapshot = snapshot_before_destructive_write(tmp_path, "gone.md")
    assert snapshot is not None
    client = _RecordingClient()

    result = await _delete_snapshotted_paths(client, tmp_path, (snapshot,))

    assert result.successful_deletes == 1
    assert client.deleted == ["gone.md"]
    assert left.read_text(encoding="utf-8") == "left\n"


@pytest.mark.asyncio
async def test_directory_delete_leaves_a_file_that_changed_after_the_copy(tmp_path: Path) -> None:
    note = tmp_path / "keep.md"
    note.write_text("old\n", encoding="utf-8")
    snapshot = snapshot_before_destructive_write(tmp_path, "keep.md")
    assert snapshot is not None
    note.write_text("new\n", encoding="utf-8")
    client = _RecordingClient()

    result = await _delete_snapshotted_paths(client, tmp_path, (snapshot,))

    assert result.successful_deletes == 0
    assert result.failed_deletes == 1
    assert client.deleted == []
    assert note.read_text(encoding="utf-8") == "new\n"
    assert "changed after history snapshot" in result.errors[0].error
