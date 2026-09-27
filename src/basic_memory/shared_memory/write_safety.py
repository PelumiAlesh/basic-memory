"""Snapshot gate used by MCP write tools before destructive changes."""

from __future__ import annotations

from pathlib import Path

from fastmcp.exceptions import ToolError

from basic_memory.shared_memory.file_history import FileHistoryError, snapshot_before_destructive_write


def _local_root(home: object) -> Path | None:
    if not isinstance(home, (str, Path)) or not str(home).strip():
        return None
    root = Path(home)
    return root if root.is_dir() else None


def snapshot_local_note(project_home: object, file_path: str | None) -> None:
    """Copy an existing note file to `.bm-history/` or no-op when there is no local file."""
    root = _local_root(project_home)
    if root is None or not file_path:
        return
    try:
        snapshot_before_destructive_write(root, file_path)
    except FileHistoryError as error:
        raise ToolError(f"Local history snapshot failed: {error}") from error
