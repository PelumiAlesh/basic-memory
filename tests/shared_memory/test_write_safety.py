"""Directory snapshots before a destructive delete."""

import os
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from basic_memory.shared_memory.file_history import HISTORY_DIR
from basic_memory.shared_memory.file_history import snapshot_before_destructive_write
from basic_memory.shared_memory.write_safety import (
    assert_snapshot_current,
    snapshot_local_directory,
)


def test_directory_snapshot_copies_every_regular_child(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "nested").mkdir(parents=True)
    (bundle / "a.md").write_text("alpha", encoding="utf-8")
    (bundle / "nested" / "b.md").write_text("beta", encoding="utf-8")
    (bundle / "link.md").symlink_to(bundle / "a.md")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    (bundle / "linked").symlink_to(outside, target_is_directory=True)
    (bundle / HISTORY_DIR).mkdir()
    (bundle / HISTORY_DIR / "old.md").write_text("old", encoding="utf-8")
    os.mkfifo(bundle / "pipe")

    snapshots = snapshot_local_directory(tmp_path, "bundle")

    assert {item.relative_path for item in snapshots} == {"bundle/a.md", "bundle/nested/b.md"}
    texts = {
        path.read_text(encoding="utf-8")
        for path in (tmp_path / HISTORY_DIR).iterdir()
        if path.is_file()
    }
    assert texts == {"alpha", "beta"}


def test_directory_snapshot_aborts_when_a_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.md").write_text("alpha", encoding="utf-8")
    (bundle / "b.md").write_text("beta", encoding="utf-8")

    from basic_memory.shared_memory import write_safety

    original = write_safety.snapshot_local_note

    def flaky(home: object, path: str | None) -> None:
        if path is not None and path.endswith("b.md"):
            raise ToolError("Local history snapshot failed: simulated")
        original(home, path)

    monkeypatch.setattr(write_safety, "snapshot_local_note", flaky)
    with pytest.raises(ToolError, match="snapshot failed"):
        snapshot_local_directory(tmp_path, "bundle")


def test_directory_snapshot_noop_escape_and_symlink(tmp_path: Path) -> None:
    snapshot_local_directory(None, "bundle")
    snapshot_local_directory(tmp_path / "missing-root", "bundle")
    snapshot_local_directory(tmp_path, None)
    snapshot_local_directory(tmp_path, "   ")
    snapshot_local_directory(tmp_path, "missing")
    snapshot_local_directory(tmp_path, HISTORY_DIR)
    snapshot_local_directory(tmp_path, f"{HISTORY_DIR}/nested")

    note = tmp_path / "only.md"
    note.write_text("one", encoding="utf-8")
    snapshot_local_directory(tmp_path, "only.md")
    os.mkfifo(tmp_path / "fifo")
    snapshot_local_directory(tmp_path, "fifo")
    snapshot_local_directory(tmp_path, "/")
    copies = [path for path in (tmp_path / HISTORY_DIR).iterdir() if path.is_file()]
    assert copies
    assert any(path.read_text(encoding="utf-8") == "one" for path in copies)

    link = tmp_path / "linked-dir"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ToolError, match="symlink"):
        snapshot_local_directory(tmp_path, "linked-dir")
    with pytest.raises(ToolError, match="escapes"):
        snapshot_local_directory(tmp_path, "../outside")


def test_snapshot_checksum_aborts_when_the_file_changes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("before\n", encoding="utf-8")
    snapshot = snapshot_before_destructive_write(tmp_path, "note.md")
    assert snapshot is not None
    assert_snapshot_current(tmp_path, snapshot)

    note.write_text("after\n", encoding="utf-8")
    with pytest.raises(ToolError, match="changed after history snapshot"):
        assert_snapshot_current(tmp_path, snapshot)
    assert note.read_text(encoding="utf-8") == "after\n"
