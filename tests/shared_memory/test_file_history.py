"""Local `.bm-history/` snapshots before destructive writes."""

from pathlib import Path

import pytest

from basic_memory.shared_memory.file_history import (
    FileHistoryError,
    HISTORY_DIR,
    snapshot_before_destructive_write,
)


def test_snapshot_copies_existing_file(tmp_path: Path) -> None:
    note = tmp_path / "plans" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Hello\n", encoding="utf-8")

    history_path = snapshot_before_destructive_write(tmp_path, "plans/note.md")

    assert history_path is not None
    assert history_path.is_file()
    assert history_path.read_text(encoding="utf-8") == "# Hello\n"
    assert history_path.parent == tmp_path / HISTORY_DIR


def test_snapshot_no_op_when_file_missing(tmp_path: Path) -> None:
    assert snapshot_before_destructive_write(tmp_path, "missing.md") is None


def test_snapshot_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(FileHistoryError, match="escapes"):
        snapshot_before_destructive_write(tmp_path, "../outside.md")
