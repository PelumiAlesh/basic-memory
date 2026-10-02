"""`.bm-logs/` is excluded from indexing ignore patterns."""

from pathlib import Path

from basic_memory.ignore_utils import DEFAULT_IGNORE_PATTERNS, should_ignore_path


def test_bm_logs_directory_ignored(tmp_path: Path) -> None:
    assert ".bm-logs" in DEFAULT_IGNORE_PATTERNS
    assert ".bm-history" in DEFAULT_IGNORE_PATTERNS
    root = tmp_path / "vault"
    root.mkdir()
    patterns = DEFAULT_IGNORE_PATTERNS
    assert should_ignore_path(root / "inbox/note.md", root, patterns) is False
    assert should_ignore_path(root / ".bm-logs/events.jsonl", root, patterns) is True
    assert should_ignore_path(root / ".bm-history/old.md", root, patterns) is True


def test_default_bmignore_template_lists_history(tmp_path: Path, monkeypatch) -> None:
    from basic_memory.ignore_utils import create_default_bmignore

    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(tmp_path))
    create_default_bmignore()
    text = (tmp_path / ".bmignore").read_text(encoding="utf-8")
    assert "\n.bm-logs\n" in text
    assert "\n.bm-history\n" in text
