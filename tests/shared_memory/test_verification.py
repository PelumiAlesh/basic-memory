"""Write verification: landed, truncated, duplicated, mismatched, and disk state."""

from basic_memory.shared_memory.verification import (
    combine,
    verify_disk,
    verify_edit,
    verify_full_write,
)

BODY = "# Plan\n\nWe will ship the shared-memory fork this quarter.\n"
STORED = "---\ntitle: Plan\ntype: note\n---\n\n" + BODY


def test_full_write_verified_when_body_is_stored_once() -> None:
    result = verify_full_write(BODY, STORED)
    assert result.status == "verified"
    assert result.checks == {"index": "ok"}


def test_full_write_ignores_incoming_frontmatter_and_whitespace() -> None:
    incoming = (
        "---\ntitle: Plan\n---\n# Plan\n\n\nWe will ship   the shared-memory fork this quarter."
    )
    assert verify_full_write(incoming, STORED).status == "verified"


def test_full_write_detects_truncation() -> None:
    truncated = "---\ntitle: Plan\n---\n\n# Plan\n\nWe will ship the shared"
    result = verify_full_write(BODY, truncated)
    assert result.status == "failed"
    assert result.checks["index"] == "truncated"
    assert result.error is not None and "ends after" in result.error


def test_full_write_detects_duplication_and_missing_note() -> None:
    doubled = STORED + "\n" + BODY
    result = verify_full_write(BODY, doubled)
    assert result.status == "failed"
    assert result.checks["index"] == "duplicated"
    missing = verify_full_write(BODY, None)
    assert missing.status == "failed"
    assert missing.checks["index"] == "missing"


def test_empty_write_matches_only_an_empty_body() -> None:
    blank = "---\ntitle: Plan\n---\n"
    assert verify_full_write("", blank).status == "verified"
    leftover = verify_full_write("", STORED)
    assert leftover.status == "failed"
    assert leftover.checks["index"] == "mismatch"


def test_full_write_rejects_a_body_that_only_contains_the_new_text() -> None:
    leftover = "---\ntitle: Plan\n---\n\nAn old note that mentions sparrow once.\n"
    result = verify_full_write("sparrow", leftover)
    assert result.status == "failed"
    assert result.checks["index"] == "mismatch"


def test_full_write_mismatch_is_named() -> None:
    result = verify_full_write(BODY, "---\ntitle: Plan\n---\n\nSomething else entirely.")
    assert result.status == "failed"
    assert result.checks["index"] == "mismatch"


def test_edit_append_verified_once() -> None:
    added = "\n## Decision\n\nUse SQLite for the local index.\n"
    result = verify_edit("append", added, before_markdown=STORED, after_markdown=STORED + added)
    assert result.status == "verified"


def test_edit_append_duplicated_content_fails() -> None:
    added = "\n## Decision\n\nUse SQLite for the local index.\n"
    result = verify_edit(
        "append", added, before_markdown=STORED, after_markdown=STORED + added + added
    )
    assert result.status == "failed"
    assert result.checks["index"] == "duplicated"


def test_edit_append_that_shrinks_the_note_fails() -> None:
    added = "\n## Decision\n\nUse SQLite for the local index and nothing else.\n"
    result = verify_edit(
        "append",
        added,
        before_markdown=STORED,
        after_markdown="---\ntitle: Plan\n---\n" + added,
    )
    assert result.status == "failed"
    assert result.checks["index"] == "truncated"


def test_edit_missing_content_fails() -> None:
    result = verify_edit(
        "prepend", "brand new intro", before_markdown=STORED, after_markdown=STORED
    )
    assert result.status == "failed"
    assert result.checks["index"] == "missing"


def test_edit_find_replace_counts_replacements() -> None:
    before = "---\ntitle: Plan\n---\n\nalpha alpha beta"
    after_ok = "---\ntitle: Plan\n---\n\ngamma alpha beta"
    assert (
        verify_edit(
            "find_replace",
            "gamma",
            before_markdown=before,
            after_markdown=after_ok,
            find_text="alpha",
            expected_replacements=1,
        ).status
        == "verified"
    )
    after_all = "---\ntitle: Plan\n---\n\ngamma gamma beta"
    result = verify_edit(
        "find_replace",
        "gamma",
        before_markdown=before,
        after_markdown=after_all,
        find_text="alpha",
        expected_replacements=1,
    )
    assert result.status == "failed"
    assert "observed 2" in (result.error or "")


def test_disk_states() -> None:
    assert verify_disk(stored_markdown=STORED, disk_markdown=STORED, write_status="synced") == (
        "ok",
        None,
    )
    assert verify_disk(stored_markdown=STORED, disk_markdown=None, write_status="pending") == (
        "pending",
        None,
    )
    assert verify_disk(stored_markdown=STORED, disk_markdown=None, write_status="synced")[0] == (
        "missing"
    )
    check, error = verify_disk(
        stored_markdown=STORED, disk_markdown=BODY + "x", write_status="synced"
    )
    assert check == "mismatch" and error is not None


def test_combine_folds_disk_into_index_verdict() -> None:
    index_ok = verify_full_write(BODY, STORED)
    assert combine(index_ok, "ok", None).status == "verified"
    assert combine(index_ok, "pending", None).status == "pending"
    failed = combine(index_ok, "missing", "file is not on disk")
    assert failed.status == "failed" and failed.error == "file is not on disk"
    text = failed.as_text()
    assert "## Verification" in text and "disk: missing" in text
    assert failed.as_dict()["status"] == "failed"
