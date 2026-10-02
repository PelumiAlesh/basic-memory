"""Snapshot gate used by MCP write tools before destructive changes."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastmcp.exceptions import ToolError

from basic_memory.shared_memory.file_history import (
    HISTORY_DIR,
    FileHistoryError,
    FileSnapshot,
    snapshot_before_destructive_write,
)


def _local_root(home: object) -> Path | None:
    if not isinstance(home, (str, Path)) or not str(home).strip():
        return None
    root = Path(home)
    return root if root.is_dir() else None


def snapshot_local_note(project_home: object, file_path: str | None) -> FileSnapshot | None:
    """Copy an existing note file to `.bm-history/` or no-op when there is no local file."""
    root = _local_root(project_home)
    if root is None or not file_path:
        return None
    try:
        return snapshot_before_destructive_write(root, file_path)
    except FileHistoryError as error:
        raise ToolError(f"Local history snapshot failed: {error}") from error


def assert_snapshot_current(project_home: object, snapshot: FileSnapshot | None) -> None:
    """Abort when the file is no longer the bytes that were copied.

    The checksum is of the snapshotted bytes. A save that lands after the copy
    must not be overwritten or deleted: that revision is in neither the file
    nor `.bm-history`.
    """
    if snapshot is None:
        return
    root = _local_root(project_home)
    if root is None:
        raise ToolError("file changed after history snapshot; write aborted")
    source = root.resolve() / snapshot.relative_path
    try:
        if source.is_symlink() or not source.is_file():
            raise ToolError(
                f"file changed after history snapshot; write aborted ({snapshot.relative_path})"
            )
        current = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as error:
        raise ToolError(
            f"file changed after history snapshot; write aborted ({snapshot.relative_path})"
        ) from error
    if current != snapshot.checksum:
        raise ToolError(
            f"file changed after history snapshot; write aborted ({snapshot.relative_path})"
        )


def snapshot_local_directory(
    project_home: object, directory_path: str | None
) -> tuple[FileSnapshot, ...]:
    """Copy every regular file under a directory into `.bm-history/` before a delete.

    A failed copy raises ToolError. The caller must not delete after that.
    Missing directories and a project with no local root are a no-op. Symlinks
    are not followed, and `.bm-history` is not copied into itself.
    """
    root = _local_root(project_home)
    if root is None or directory_path is None or not str(directory_path).strip():
        return ()
    root = root.resolve()
    relative_dir = str(directory_path).replace("\\", "/").strip("/")
    # Trigger: the path is the history folder, or a folder inside it.
    # Why: copying snapshots into new snapshots grows without a bound.
    # Outcome: nothing is copied. The caller may still delete that folder.
    if relative_dir == HISTORY_DIR or relative_dir.startswith(f"{HISTORY_DIR}/"):
        return ()
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
    if not target.exists() or not (target.is_dir() or target.is_file()):
        return ()
    if target.is_file():
        copied = snapshot_local_note(root, relative_dir)
        return (copied,) if copied is not None else ()
    copied_files: list[FileSnapshot] = []
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = [
            name for name in dirnames if name != HISTORY_DIR and not (current / name).is_symlink()
        ]
        for name in filenames:
            child = current / name
            if child.is_symlink() or not child.is_file():
                continue
            copied = snapshot_local_note(root, child.relative_to(root).as_posix())
            if copied is not None:
                copied_files.append(copied)
    return tuple(copied_files)
