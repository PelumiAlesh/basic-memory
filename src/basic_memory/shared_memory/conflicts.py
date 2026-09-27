"""Possible-conflict notes and supersedes links.

Decision and preference writes can return nearby active notes. Search hides
`status: superseded` and `status: archived` unless the caller opts in.
A `supersedes` frontmatter value (string or list) is the link that marks the
older note superseded after the new one is written.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# Compared case-insensitively against frontmatter status.
INACTIVE_STATUSES = ("archived", "superseded")
CONFLICT_NOTE_TYPES = frozenset({"decision", "preference"})


def wants_conflict_check(note_type: str, *, enabled: bool) -> bool:
    return enabled and note_type.strip().lower() in CONFLICT_NOTE_TYPES


def _as_targets(value: object) -> list[str]:
    if isinstance(value, str):
        raw_values: Sequence[object] = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        return []
    targets: list[str] = []
    for item in raw_values:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            targets.append(text)
    return targets


def supersedes_targets(
    metadata: Mapping[str, object] | None,
    content_frontmatter: Mapping[str, object] | None = None,
) -> list[str]:
    """Permalink or title targets named by a supersedes field, in order, deduped."""
    seen: set[str] = set()
    ordered: list[str] = []
    for source in (metadata, content_frontmatter):
        if not source:
            continue
        for target in _as_targets(source.get("supersedes")):
            if target not in seen:
                seen.add(target)
                ordered.append(target)
    return ordered


def format_possible_conflicts(notes: Sequence[tuple[str, str]]) -> str:
    """Render (title, reference) pairs as a possible-conflict section."""
    if not notes:
        return ""
    lines = [
        "",
        "## Possible conflicts",
        "These active notes look similar. Check them before keeping both.",
    ]
    lines.extend(f"- {title} (`{ref}`) — possible conflict" for title, ref in notes)
    return "\n".join(lines)
