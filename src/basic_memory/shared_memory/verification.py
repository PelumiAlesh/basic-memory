"""Decide whether a write landed as requested.

Pure comparisons over markdown text. The MCP layer fetches the note back
from the index and from disk and hands the texts here. A result is either
verified, pending (the file is still being written), or failed with one
named reason: missing, truncated, duplicated, or mismatched content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from basic_memory.file_utils import has_frontmatter, remove_frontmatter

VerificationStatus = Literal["verified", "pending", "failed"]

# Shorter content repeats legitimately (a bullet, a heading), so duplication is
# only reported for content long enough that two copies are unlikely to be intended.
DUPLICATE_MIN_CHARS = 24

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class WriteVerification:
    status: VerificationStatus
    checks: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status, "checks": dict(self.checks)}
        if self.error is not None:
            payload["error"] = self.error
        return payload

    def as_text(self) -> str:
        lines = ["", "## Verification", f"status: {self.status}"]
        lines.extend(f"{name}: {value}" for name, value in self.checks.items())
        if self.error is not None:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)


def normalize_markdown(text: str | None) -> str:
    """Body only, whitespace collapsed, so formatting differences do not count."""
    if not text:
        return ""
    body = remove_frontmatter(text) if has_frontmatter(text) else text
    return _WHITESPACE.sub(" ", body).strip()


def count_occurrences(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    return haystack.count(needle)


def verify_full_write(expected_content: str, stored_markdown: str | None) -> WriteVerification:
    """A write_note result must hold the body that was sent, once."""
    expected = normalize_markdown(expected_content)
    actual = normalize_markdown(stored_markdown)
    checks: dict[str, str] = {}
    if stored_markdown is None:
        return WriteVerification("failed", {"index": "missing"}, "note was not found after write")
    if not expected:
        checks["index"] = "ok"
        return WriteVerification("verified", checks)
    if expected in actual:
        if len(expected) >= DUPLICATE_MIN_CHARS and count_occurrences(actual, expected) > 1:
            checks["index"] = "duplicated"
            return WriteVerification("failed", checks, "content appears more than once")
        checks["index"] = "ok"
        return WriteVerification("verified", checks)
    if actual and expected.startswith(actual):
        checks["index"] = "truncated"
        return WriteVerification(
            "failed",
            checks,
            f"stored content ends after {len(actual)} of {len(expected)} characters",
        )
    checks["index"] = "mismatch"
    return WriteVerification("failed", checks, "stored content does not contain what was written")


def verify_edit(
    operation: str,
    new_content: str,
    *,
    before_markdown: str | None,
    after_markdown: str | None,
    find_text: str | None = None,
    expected_replacements: int = 1,
) -> WriteVerification:
    """An edit must add its content exactly once and must not lose the rest."""
    if after_markdown is None:
        return WriteVerification("failed", {"index": "missing"}, "note was not found after edit")
    added = normalize_markdown(new_content)
    before = normalize_markdown(before_markdown)
    after = normalize_markdown(after_markdown)
    checks: dict[str, str] = {}

    if operation == "find_replace":
        target = normalize_markdown(find_text)
        remaining = count_occurrences(after, target) if target else 0
        prior = count_occurrences(before, target) if target and before else None
        if prior is not None and prior - remaining != expected_replacements:
            checks["index"] = "mismatch"
            return WriteVerification(
                "failed",
                checks,
                f"expected {expected_replacements} replacement(s), observed {prior - remaining}",
            )
        checks["index"] = "ok"
        return WriteVerification("verified", checks)

    if added and added not in after:
        checks["index"] = "missing"
        return WriteVerification("failed", checks, "edited content is not in the stored note")

    if added and len(added) >= DUPLICATE_MIN_CHARS:
        now = count_occurrences(after, added)
        was = count_occurrences(before, added) if before_markdown is not None else 0
        expected_delta = (
            1
            if operation in {"append", "prepend", "insert_before_section", "insert_after_section"}
            else None
        )
        if expected_delta is not None and now - was > expected_delta:
            checks["index"] = "duplicated"
            return WriteVerification("failed", checks, "edited content appears more than once")

    # Trigger: an append or prepend no longer contains the body it started with.
    # Why: those operations only add text. Losing the previous body is the
    # corruption the upstream reports describe.
    # Outcome: fail and name it.
    if (
        before_markdown is not None
        and before
        and operation in {"append", "prepend"}
        and before not in after
    ):
        checks["index"] = "truncated"
        return WriteVerification(
            "failed",
            checks,
            f"previous content ({len(before)} characters) is missing after {operation}",
        )
    checks["index"] = "ok"
    return WriteVerification("verified", checks)


def verify_disk(
    *,
    stored_markdown: str | None,
    disk_markdown: str | None,
    write_status: str | None,
) -> tuple[str, str | None]:
    """Compare the accepted note with the file. Returns (check value, error)."""
    if disk_markdown is None:
        if write_status in {"pending", "writing", None}:
            return "pending", None
        return "missing", "file is not on disk"
    if stored_markdown is None:
        return "present", None
    if normalize_markdown(stored_markdown) == normalize_markdown(disk_markdown):
        return "ok", None
    if write_status in {"pending", "writing"}:
        return "pending", None
    return "mismatch", "file on disk differs from the accepted note"


def combine(index: WriteVerification, disk_check: str, disk_error: str | None) -> WriteVerification:
    """Fold the disk comparison into the index verdict."""
    checks = dict(index.checks)
    checks["disk"] = disk_check
    if index.status == "failed":
        return WriteVerification("failed", checks, index.error)
    if disk_error is not None:
        return WriteVerification("failed", checks, disk_error)
    if disk_check == "pending":
        return WriteVerification("pending", checks)
    return WriteVerification("verified", checks)
