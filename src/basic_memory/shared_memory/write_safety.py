"""Snapshot gate used by MCP write tools before destructive changes."""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp.exceptions import ToolError

from basic_memory.shared_memory.file_history import (
    HISTORY_DIR,
    FileHistoryError,
    snapshot_before_destructive_write,
)


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


def snapshot_local_directory(project_home: object, directory_path: str | None) -> None:
    """Copy every regular file under a directory into `.bm-history/` before a delete.

    A failed copy raises ToolError. The caller must not delete after that.
    Missing directories and a project with no local root are a no-op. Symlinks
    are not followed, and `.bm-history` is not copied into itself.
    """
    root = _local_root(project_home)
    if root is None or directory_path is None or not str(directory_path).strip():
        return
    root = root.resolve()
    relative_dir = str(directory_path).replace("\\", "/").strip("/")
    # Trigger: the path is the history folder, or a folder inside it.
    # Why: copying snapshots into new snapshots grows without a bound.
    # Outcome: nothing is copied. The caller may still delete that folder.
    if relative_dir == HISTORY_DIR or relative_dir.startswith(f"{HISTORY_DIR}/"):
        return
    unresolved = root if not relative_dir else root / relative_dir
    # Trigger: the directory path itself is a symlink.
    # Why: walking it would snapshot the target, and a failed or partial copy
    # must not be followed by a delete through the link.
    # Outcome: raise, and the caller does not delete.
    if unresolved.is_symlink():
        raise ToolError("Local history snapshot failed: path is a symlink")
    target = unresolved.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ToolError("Local history snapshot failed: path escapes project") from None
    if not target.exists():
        return
    if target.is_file():
        snapshot_local_note(root, relative_dir)
        return
    if not target.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = [
            name for name in dirnames if name != HISTORY_DIR and not (current / name).is_symlink()
        ]
        for name in filenames:
            child = current / name
            if child.is_symlink() or not child.is_file():
                continue
            snapshot_local_note(root, child.relative_to(root).as_posix())
