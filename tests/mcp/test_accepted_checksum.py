"""Overwrite sends a snapshot checksum only when it is the accepted revision."""

import pytest

from basic_memory.mcp.tools.write_note import _accepted_checksum_matching_file


class _Entity:
    def __init__(self, db_checksum: str) -> None:
        self.db_checksum = db_checksum


class _Client:
    def __init__(self, db_checksum: str) -> None:
        self.entity = _Entity(db_checksum)

    async def resolve_entity(self, path: str, strict: bool = True) -> str:
        return "entity-id"

    async def get_entity(self, entity_id: str) -> _Entity:
        return self.entity


@pytest.mark.asyncio
async def test_file_checksum_is_used_only_when_it_matches_db_checksum() -> None:
    client = _Client("accepted")
    assert await _accepted_checksum_matching_file(client, "note.md", "accepted") == "accepted"
    assert await _accepted_checksum_matching_file(client, "note.md", "drifted-file") is None
