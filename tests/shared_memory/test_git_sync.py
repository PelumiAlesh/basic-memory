"""Local git autocommit, history, and undo. Nothing is pushed without a remote."""

import subprocess
from pathlib import Path

import pytest

from basic_memory.shared_memory.git_sync import (
    GitMemoryError,
    commit_files,
    commit_message,
    history,
    scrub_git_text,
    undo,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def test_commit_message_is_one_line() -> None:
    assert commit_message("cursor", ["Hello\nworld"]) == "memory(cursor): update Hello world"
    assert "\n" not in commit_message("cursor", ["A"])
    scrubbed = scrub_git_text("failed https://user:secret@github.com/org/repo")
    assert "secret" not in scrubbed
    assert "github.com/org/repo" in scrubbed


def test_commit_history_and_undo(repo: Path) -> None:
    note = repo / "notes.md"
    note.write_text("v0\n", encoding="utf-8")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-m", "human seed")
    note.write_text("v1\n", encoding="utf-8")
    subject = commit_files(
        repo,
        {note},
        client="cursor",
        notes=["Notes"],
        auto_push=True,
    )
    assert subject == "memory(cursor): update Notes"
    log = history(repo, "notes.md")
    assert "memory(cursor): update Notes" in log

    undo(repo, auto_push=True)
    assert note.read_text(encoding="utf-8") == "v0\n"
    # No remote, so auto_push must not fail.
    remotes = subprocess.run(
        ["git", "remote"], cwd=repo, check=True, capture_output=True, text=True
    )
    assert remotes.stdout.strip() == ""


def test_undo_refuses_a_non_agent_commit(repo: Path) -> None:
    note = repo / "notes.md"
    note.write_text("human\n", encoding="utf-8")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-m", "human edit")
    with pytest.raises(GitMemoryError, match="not an agent commit"):
        undo(repo, auto_push=False)


def test_undo_refuses_a_dirty_tree(repo: Path) -> None:
    note = repo / "notes.md"
    note.write_text("v1\n", encoding="utf-8")
    commit_files(repo, {note}, client="grok", notes=["Notes"], auto_push=False)
    (repo / "other.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(GitMemoryError, match="uncommitted"):
        undo(repo, auto_push=False)


def test_missing_repo_is_not_a_commit(tmp_path: Path) -> None:
    assert (
        commit_files(
            tmp_path,
            {tmp_path / "a.md"},
            client="cursor",
            notes=["A"],
            auto_push=False,
        )
        is None
    )
