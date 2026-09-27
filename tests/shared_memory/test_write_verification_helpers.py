"""Read-back helper branches: 404s, remote projects, pending drains, lingering files."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastmcp.exceptions import ToolError

from basic_memory.mcp import write_verification as wv
from basic_memory.schemas.v2.entity import EntityResponseV2


def _entity(file_path: str, content: str, status: str | None = "synced") -> EntityResponseV2:
    now = datetime.now(timezone.utc)
    return EntityResponseV2(
        external_id="11111111-1111-1111-1111-111111111111",
        id=1,
        title="Note",
        note_type="note",
        permalink="notes/note",
        file_path=file_path,
        content=content,
        created_at=now,
        updated_at=now,
        file_write_status=status,
    )


class _Reader:
    def __init__(self, entity: EntityResponseV2 | None, *, error: Exception | None = None):
        self.entity = entity
        self.error = error

    async def get_entity(self, entity_id: str) -> EntityResponseV2:
        if self.error is not None:
            raise self.error
        assert self.entity is not None
        return self.entity


def _not_found() -> ToolError:
    request = httpx.Request("GET", "http://test/entity")
    response = httpx.Response(404, request=request)
    error = ToolError("Entity not found")
    error.__cause__ = httpx.HTTPStatusError("404", request=request, response=response)
    return error


@pytest.mark.asyncio
async def test_read_back_maps_404_to_none_and_reraises_other_errors() -> None:
    assert await wv.read_back(_Reader(None, error=_not_found()), "x") is None
    with pytest.raises(ToolError):
        await wv.read_back(_Reader(None, error=ToolError("boom")), "x")


def test_local_root_and_read_disk(tmp_path: Path) -> None:
    assert wv.local_root(None) is None
    assert wv.local_root("") is None
    assert wv.local_root(tmp_path / "missing") is None
    assert wv.local_root(str(tmp_path)) == tmp_path
    assert wv.read_disk(None, "a.md") is None
    assert wv.read_disk(tmp_path, None) is None
    assert wv.read_disk(tmp_path, "missing.md") is None
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    assert wv.read_disk(tmp_path, "a.md") == "hello"


@pytest.mark.asyncio
async def test_remote_project_reports_disk_remote() -> None:
    entity = _entity("notes/note.md", "---\ntitle: Note\n---\n\nbody text here")
    result = await wv.verify_note_write(
        _Reader(entity),
        external_id="x",
        expected_content="body text here",
        project_home="",
    )
    assert result.status == "verified"
    assert result.checks == {"index": "ok", "disk": "remote"}


@pytest.mark.asyncio
async def test_missing_file_after_drain_fails(tmp_path: Path) -> None:
    entity = _entity("notes/note.md", "---\ntitle: Note\n---\n\nbody text here")
    result = await wv.verify_note_write(
        _Reader(entity),
        external_id="x",
        expected_content="body text here",
        project_home=str(tmp_path),
    )
    assert result.status == "failed"
    assert result.checks["disk"] == "missing"


@pytest.mark.asyncio
async def test_drain_timeout_reports_pending(tmp_path: Path, monkeypatch) -> None:
    from basic_memory.index import note_content_materialization as materialization

    async def slow() -> None:
        await asyncio.sleep(1)

    monkeypatch.setattr(materialization, "drain_pending_materializations", slow)
    monkeypatch.setattr(wv, "DRAIN_TIMEOUT_SECONDS", 0.01)
    entity = _entity("notes/note.md", "---\ntitle: Note\n---\n\nbody text here")
    result = await wv.verify_note_write(
        _Reader(entity),
        external_id="x",
        expected_content="body text here",
        project_home=str(tmp_path),
    )
    assert result.status == "pending"
    assert result.checks["disk"] == "pending"


@pytest.mark.asyncio
async def test_move_verification_states(tmp_path: Path) -> None:
    entity = _entity("archive/note.md", "body")
    missing = await wv.verify_note_move(
        _Reader(None, error=_not_found()),
        external_id="x",
        source_path="notes/note.md",
        destination_path="archive/note.md",
        project_home=str(tmp_path),
    )
    assert missing.status == "failed" and missing.checks["index"] == "missing"

    wrong = await wv.verify_note_move(
        _Reader(entity),
        external_id="x",
        source_path="notes/note.md",
        destination_path="elsewhere/note.md",
        project_home=str(tmp_path),
    )
    assert wrong.status == "failed" and wrong.checks["index"] == "mismatch"

    remote = await wv.verify_note_move(
        _Reader(entity),
        external_id="x",
        source_path=None,
        destination_path="archive/note.md",
        project_home=None,
    )
    assert remote.checks == {"index": "ok", "disk": "remote"}

    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "note.md").write_text("body", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "note.md").write_text("old copy", encoding="utf-8")
    lingering = await wv.verify_note_move(
        _Reader(entity),
        external_id="x",
        source_path="notes/note.md",
        destination_path="archive/note.md",
        project_home=str(tmp_path),
    )
    assert lingering.status == "failed" and lingering.checks["disk"] == "source-lingers"


@pytest.mark.asyncio
async def test_delete_verification_states(tmp_path: Path) -> None:
    entity = _entity("notes/note.md", "body")
    still_indexed = await wv.verify_note_delete(
        _Reader(entity), external_id="x", file_path="notes/note.md", project_home=str(tmp_path)
    )
    assert still_indexed.status == "failed" and still_indexed.checks["index"] == "present"

    gone_remote = await wv.verify_note_delete(
        _Reader(None, error=_not_found()), external_id="x", file_path="n.md", project_home=None
    )
    assert gone_remote.checks == {"index": "ok", "disk": "remote"}

    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "note.md").write_text("still here", encoding="utf-8")
    on_disk = await wv.verify_note_delete(
        _Reader(None, error=_not_found()),
        external_id="x",
        file_path="notes/note.md",
        project_home=str(tmp_path),
    )
    assert on_disk.status == "failed" and on_disk.checks["disk"] == "present"
