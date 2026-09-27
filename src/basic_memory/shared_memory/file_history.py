"""Local file copies before destructive MCP writes.

Snapshots live under `<project>/.bm-history/` and are independent of git.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

HISTORY_DIR = ".bm-history"


class FileHistoryError(RuntimeError):
    """A snapshot could not be taken; the write must not proceed."""


def _project_file(project_root: Path, relative_path: str) -> Path:
    root = project_root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise FileHistoryError("path escapes project") from None
    return target


def snapshot_before_destructive_write(project_root: Path, relative_path: str) -> Path | None:
    """Copy the current file bytes into `.bm-history/` before they are overwritten.

    Returns the history path, or None when there was no file to copy.
    Raises FileHistoryError when the copy fails.
    """
    source = _project_file(project_root, relative_path)
    if not source.is_file():
        return None

    history_root = (project_root / HISTORY_DIR).resolve()
    history_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    destination = history_root / f"{stamp}_{safe_name}"
    try:
        shutil.copy2(source, destination)
    except OSError as error:
        raise FileHistoryError(str(error)) from error
    return destination
