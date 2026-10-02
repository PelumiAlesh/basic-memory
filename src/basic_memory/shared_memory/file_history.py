"""Local file copies before destructive MCP writes.

Snapshots live under `<project>/.bm-history/` and are independent of git.
The history directory must be a real directory inside the project. A symlink
would copy note bytes to wherever it points.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

HISTORY_DIR = ".bm-history"


class FileHistoryError(RuntimeError):
    """A snapshot could not be taken; the write must not proceed."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """Bytes copied into history, and the checksum of those exact bytes."""

    history_path: Path
    checksum: str
    relative_path: str


def _project_file(project_root: Path, relative_path: str) -> Path:
    root = project_root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise FileHistoryError("path escapes project") from None
    return target


def _history_root(project_root: Path) -> Path:
    """Return `<project>/.bm-history`, refusing to follow a symlink.

    `Path.resolve()` follows links. A linked history directory would store note
    bytes outside the project, so the directory itself must be a real directory
    created here.
    """
    root = project_root.resolve()
    history_root = root / HISTORY_DIR
    if history_root.is_symlink():
        raise FileHistoryError("refusing to write history through a symlinked .bm-history")
    history_root.mkdir(parents=True, exist_ok=True)
    if history_root.is_symlink() or not history_root.resolve().is_relative_to(root):
        raise FileHistoryError("refusing to write history through a symlinked .bm-history")
    return history_root


def snapshot_before_destructive_write(
    project_root: Path, relative_path: str
) -> FileSnapshot | None:
    """Copy the current file bytes into `.bm-history/` before they are overwritten.

    The copy is the bytes read for the checksum, not a second read. Returns None
    when there was no file to copy. Raises FileHistoryError when the copy fails
    or `.bm-history` is a symlink.
    """
    source = _project_file(project_root, relative_path)
    if source.is_symlink() or not source.is_file():
        return None

    history_root = _history_root(project_root)
    try:
        data = source.read_bytes()
    except OSError as error:
        raise FileHistoryError(str(error)) from error
    checksum = hashlib.sha256(data).hexdigest()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    destination = history_root / f"{stamp}_{safe_name}"
    try:
        destination.write_bytes(data)
    except OSError as error:
        raise FileHistoryError(str(error)) from error
    return FileSnapshot(
        history_path=destination,
        checksum=checksum,
        relative_path=relative_path.replace("\\", "/"),
    )
