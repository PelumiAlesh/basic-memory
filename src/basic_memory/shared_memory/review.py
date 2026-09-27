"""Decisions for the optional review inbox.

Tool-created notes can land as `status: unreviewed` or under `inbox/`.
Promotion, merge, and discard are explicit. The inbox is off unless
`review_inbox_enabled` is set, so existing projects are unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

ReviewAction = Literal["promote", "merge", "discard"]
UNREVIEWED = "unreviewed"
REVIEWED = "reviewed"
MERGED = "merged"


def inbox_directory(
    directory: str,
    *,
    enabled: bool,
    mode: str,
    folder: str,
) -> str:
    """Place a note in the inbox only when folder mode is on and no directory was chosen."""
    if not enabled or mode != "folder":
        return directory
    if directory.strip().strip("/"):
        return directory
    return folder.strip().strip("/")


def mark_unreviewed_on_create(
    metadata: Mapping[str, object] | None,
    *,
    enabled: bool,
    mode: str,
) -> bool:
    """True when a newly created note should gain status: unreviewed.

    A caller-supplied status wins. Updates are not handled here; the caller
    only invokes this after a create.
    """
    if not enabled or mode != "status":
        return False
    if metadata and "status" in metadata:
        return False
    return True


def status_for_action(action: str) -> str | None:
    """Frontmatter status for promote and merge. Discard deletes the note."""
    if action == "promote":
        return REVIEWED
    if action == "merge":
        return MERGED
    if action == "discard":
        return None
    raise ValueError("action must be promote, merge, or discard")
