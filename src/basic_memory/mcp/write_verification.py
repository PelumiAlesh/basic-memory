"""Read a write back from the index and the disk before reporting success.

Materialization runs off the accept path, so a local project is drained
first (bounded). A cloud project has no local file; its disk check reports
`remote` and the verdict rests on the index read-back.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol

from fastmcp.exceptions import ToolError
from httpx import HTTPStatusError

from basic_memory.config import ConfigManager
from basic_memory.schemas.v2.entity import EntityResponseV2
from basic_memory.shared_memory.verification import (
    WriteVerification,
    combine,
    verify_disk,
    verify_edit,
    verify_full_write,
)

# Longer than a normal local materialization, short enough that a stuck
# worker turns into a `pending` verdict instead of a hung tool call.
DRAIN_TIMEOUT_SECONDS = 5.0


class EntityReader(Protocol):
    async def get_entity(self, entity_id: str) -> EntityResponseV2: ...


def verification_enabled() -> bool:
    return ConfigManager().config.verify_writes


def raise_if_verification_failed(
    verification: WriteVerification | None,
    *,
    output_format: str,
    payload: dict[str, Any],
    text: str,
) -> None:
    """A failed read-back is an error. Pending means the file is still being written."""
    if verification is None or verification.status != "failed":
        return
    failed = {
        **payload,
        "verification": verification.as_dict(),
        "error": "WRITE_VERIFICATION_FAILED",
    }
    if output_format == "json":
        raise ToolError(json.dumps(failed))
    raise ToolError(text)


def _is_not_found(error: ToolError) -> bool:
    cause = error.__cause__
    return isinstance(cause, HTTPStatusError) and cause.response.status_code == 404


async def read_back(reader: EntityReader, external_id: str) -> EntityResponseV2 | None:
    """The note as the index now has it, or None when it is gone."""
    try:
        return await reader.get_entity(external_id)
    except ToolError as error:
        if _is_not_found(error):
            return None
        raise


async def drain_local_materialization() -> bool:
    """Wait for queued file writes. False when the wait ran out."""
    from basic_memory.index.note_content_materialization import drain_pending_materializations

    try:
        await asyncio.wait_for(drain_pending_materializations(), DRAIN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False
    return True


def local_root(home: object) -> Path | None:
    """The project directory when it exists on this machine."""
    if not isinstance(home, (str, Path)) or not str(home).strip():
        return None
    root = Path(home)
    return root if root.is_dir() else None


def read_disk(root: Path | None, file_path: str | None) -> str | None:
    if root is None or not file_path:
        return None
    candidate = root / file_path
    try:
        return candidate.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, IsADirectoryError):
        return None


async def verify_note_write(
    reader: EntityReader,
    *,
    external_id: str,
    expected_content: str,
    project_home: object,
) -> WriteVerification:
    """write_note: the body sent must be the body stored, once, and on disk."""
    stored = await read_back(reader, external_id)
    index = verify_full_write(expected_content, stored.content if stored else None)
    return await _with_disk(index, stored, project_home)


async def verify_note_edit(
    reader: EntityReader,
    *,
    external_id: str,
    operation: str,
    new_content: str,
    before_markdown: str | None,
    find_text: str | None,
    expected_replacements: int,
    project_home: object,
) -> WriteVerification:
    stored = await read_back(reader, external_id)
    index = verify_edit(
        operation,
        new_content,
        before_markdown=before_markdown,
        after_markdown=stored.content if stored else None,
        find_text=find_text,
        expected_replacements=expected_replacements,
    )
    return await _with_disk(index, stored, project_home)


async def verify_note_move(
    reader: EntityReader,
    *,
    external_id: str,
    source_path: str | None,
    destination_path: str,
    project_home: object,
) -> WriteVerification:
    stored = await read_back(reader, external_id)
    checks: dict[str, str] = {}
    if stored is None:
        return WriteVerification("failed", {"index": "missing"}, "note was not found after move")
    if stored.file_path.strip("/") != destination_path.strip("/"):
        checks["index"] = "mismatch"
        return WriteVerification("failed", checks, f"index has the note at {stored.file_path}")
    checks["index"] = "ok"
    root = local_root(project_home)
    if root is None:
        checks["disk"] = "remote"
        return WriteVerification("verified", checks)
    drained = await drain_local_materialization()
    destination_exists = (root / stored.file_path).is_file()
    source_lingers = (
        bool(source_path)
        and source_path != stored.file_path
        and (root / str(source_path)).is_file()
    )
    if destination_exists and not source_lingers:
        checks["disk"] = "ok"
        return WriteVerification("verified", checks)
    if not drained:
        checks["disk"] = "pending"
        return WriteVerification("pending", checks)
    checks["disk"] = "missing" if not destination_exists else "source-lingers"
    return WriteVerification(
        "failed",
        checks,
        "destination file is missing" if not destination_exists else "source file still exists",
    )


async def verify_note_delete(
    reader: EntityReader,
    *,
    external_id: str,
    file_path: str | None,
    project_home: object,
) -> WriteVerification:
    stored = await read_back(reader, external_id)
    checks: dict[str, str] = {}
    if stored is not None:
        checks["index"] = "present"
        return WriteVerification("failed", checks, "note is still in the index")
    checks["index"] = "ok"
    root = local_root(project_home)
    if root is None or not file_path:
        checks["disk"] = "remote" if root is None else "unknown"
        return WriteVerification("verified", checks)
    drained = await drain_local_materialization()
    if not (root / file_path).exists():
        checks["disk"] = "ok"
        return WriteVerification("verified", checks)
    if not drained:
        checks["disk"] = "pending"
        return WriteVerification("pending", checks)
    checks["disk"] = "present"
    return WriteVerification("failed", checks, "file is still on disk")


async def _with_disk(
    index: WriteVerification,
    stored: EntityResponseV2 | None,
    project_home: object,
) -> WriteVerification:
    root = local_root(project_home)
    if root is None:
        checks = dict(index.checks)
        checks["disk"] = "remote"
        return WriteVerification(index.status, checks, index.error)
    if stored is None:
        return combine(index, "unknown", None)
    drained = await drain_local_materialization()
    disk_text = read_disk(root, stored.file_path)
    status = stored.file_write_status if drained else "pending"
    disk_check, disk_error = verify_disk(
        stored_markdown=stored.content,
        disk_markdown=disk_text,
        write_status=status,
    )
    return combine(index, disk_check, disk_error)
