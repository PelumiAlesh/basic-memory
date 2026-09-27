"""`.bm-logs/` is excluded from indexing ignore patterns."""

from pathlib import Path

from basic_memory.ignore_utils import DEFAULT_IGNORE_PATTERNS, should_ignore_path


def test_bm_logs_directory_ignored(tmp_path: Path) -> None:
    assert ".bm-logs" in DEFAULT_IGNORE_PATTERNS
    root = tmp_path / "vault"
    root.mkdir()
    patterns = DEFAULT_IGNORE_PATTERNS
    assert should_ignore_path(root / "inbox/note.md", root, patterns) is False
    assert should_ignore_path(root / ".bm-logs/events.jsonl", root, patterns) is True
