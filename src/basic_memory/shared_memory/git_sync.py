"""Optional git commits for the project folder after MCP writes.

Commits stay local. A push happens only when `git_auto_push` is on and the
repository has a remote. The commit message names the client and the note.
Tokens in git error text are stripped before anything is logged.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

_SECRET_IN_URL = re.compile(r"://[^/\s]+@")
_AGENT_SUBJECT = re.compile(r"^memory\([^)]+\): ")

_lock = threading.Lock()
_pending: dict[str, "_Batch"] = {}
_timers: dict[str, threading.Timer] = {}


class GitMemoryError(RuntimeError):
    """A history or undo request that the caller can show as-is."""


@dataclass
class _Batch:
    root: Path
    files: set[Path] = field(default_factory=set)
    client: str = "unknown"
    notes: list[str] = field(default_factory=list)
    auto_push: bool = False


def scrub_git_text(text: str) -> str:
    """Remove userinfo from URLs so a credential in a git error is not logged."""
    return _SECRET_IN_URL.sub("://", text)


def _run(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _is_work_tree(root: Path) -> bool:
    if not root.is_dir():
        return False
    result = _run(root, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _has_remote(root: Path) -> bool:
    result = _run(root, ["remote"])
    return result.returncode == 0 and bool(result.stdout.strip())


def commit_message(client: str, notes: list[str]) -> str:
    """One line, no newlines, client and note names only."""
    safe_client = "".join(ch for ch in client if ch.isalnum() or ch in "-_") or "unknown"
    titles = ", ".join(note.replace("\n", " ").strip() for note in notes if note.strip())
    titles = titles[:120] or "notes"
    return f"memory({safe_client}): update {titles}"


def commit_files(
    root: Path,
    files: set[Path],
    *,
    client: str,
    notes: list[str],
    auto_push: bool,
) -> str | None:
    """Commit the given files. Returns the subject, or None when there was nothing to do.

    A missing git repository is not an error: the project is not a repo.
    Push runs only when auto_push is true and `git remote` prints a name.
    """
    if not files or not _is_work_tree(root):
        return None
    relative: list[str] = []
    for path in files:
        candidate = path if path.is_absolute() else root / path
        try:
            relative.append(candidate.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            continue
    if not relative:
        return None
    added = _run(root, ["add", "--", *relative])
    if added.returncode != 0:
        raise GitMemoryError(scrub_git_text(added.stderr.strip() or "git add failed"))
    staged = _run(root, ["diff", "--cached", "--quiet"])
    # Exit 0 means no staged changes. Exit 1 means there is a diff.
    if staged.returncode == 0:
        return None
    subject = commit_message(client, notes)
    committed = _run(root, ["commit", "-m", subject])
    if committed.returncode != 0:
        raise GitMemoryError(scrub_git_text(committed.stderr.strip() or "git commit failed"))
    if auto_push and _has_remote(root):
        pushed = _run(root, ["push"])
        if pushed.returncode != 0:
            raise GitMemoryError(scrub_git_text(pushed.stderr.strip() or "git push failed"))
    return subject


def _flush(key: str) -> None:
    with _lock:
        batch = _pending.pop(key, None)
        _timers.pop(key, None)
    if batch is None:
        return
    # A commit failure must not crash the timer thread. The note write already
    # succeeded; the message is scrubbed before it is logged.
    try:
        commit_files(
            batch.root,
            batch.files,
            client=batch.client,
            notes=batch.notes,
            auto_push=batch.auto_push,
        )
    except GitMemoryError as exc:
        from loguru import logger

        logger.warning(f"git autocommit skipped: {exc}")


def schedule_autocommit(
    root: Path,
    file_path: str,
    *,
    client: str | None,
    note: str,
    enabled: bool,
    debounce_seconds: float,
    auto_push: bool,
) -> None:
    """Queue a commit of one note file. Disabled config and non-repos do nothing."""
    if not enabled or not file_path or not root:
        return
    key = str(root.resolve())
    with _lock:
        batch = _pending.get(key)
        if batch is None:
            batch = _Batch(root=root.resolve(), auto_push=auto_push)
            _pending[key] = batch
        batch.files.add(root / file_path)
        batch.client = client or batch.client
        batch.notes.append(note)
        batch.auto_push = auto_push
        existing = _timers.get(key)
        if existing is not None:
            existing.cancel()
        if debounce_seconds <= 0:
            _pending.pop(key, None)
            timer = None
        else:
            timer = threading.Timer(debounce_seconds, _flush, args=(key,))
            timer.daemon = True
            _timers[key] = timer
    if debounce_seconds <= 0:
        commit_files(
            root,
            {root / file_path},
            client=client or "unknown",
            notes=[note],
            auto_push=auto_push,
        )
        return
    if timer is not None:
        timer.start()


def history(root: Path, note: str, *, limit: int = 20) -> str:
    """git log for one note path. The path is relative to the project root."""
    if not _is_work_tree(root):
        raise GitMemoryError(f"{root} is not a git repository")
    result = _run(
        root,
        [
            "log",
            "--follow",
            f"-n{limit}",
            "--format=%h %ad %s",
            "--date=short",
            "--",
            note,
        ],
    )
    if result.returncode != 0:
        raise GitMemoryError(scrub_git_text(result.stderr.strip() or "git log failed"))
    text = result.stdout.strip()
    return text or f"No history for {note}"


def undo(root: Path, *, auto_push: bool) -> str:
    """Revert the last agent commit. Refuses other commits and a dirty tree."""
    if not _is_work_tree(root):
        raise GitMemoryError(f"{root} is not a git repository")
    subject = _run(root, ["log", "-1", "--format=%s"])
    if subject.returncode != 0:
        raise GitMemoryError(scrub_git_text(subject.stderr.strip() or "git log failed"))
    message = subject.stdout.strip()
    if not _AGENT_SUBJECT.match(message):
        raise GitMemoryError("HEAD is not an agent commit; refusing to undo")
    dirty = _run(root, ["status", "--porcelain"])
    if dirty.stdout.strip():
        raise GitMemoryError("working tree has uncommitted changes; refusing to undo")
    reverted = _run(root, ["revert", "--no-edit", "HEAD"])
    if reverted.returncode != 0:
        raise GitMemoryError(scrub_git_text(reverted.stderr.strip() or "git revert failed"))
    if auto_push and _has_remote(root):
        pushed = _run(root, ["push"])
        if pushed.returncode != 0:
            raise GitMemoryError(scrub_git_text(pushed.stderr.strip() or "git push failed"))
    return message
