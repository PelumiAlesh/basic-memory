"""Record which app wrote a note, in frontmatter keys this fork owns.

The keys carry a `bm_` prefix so they never collide with a user's own frontmatter.
`updated`, `created`, and `modified` belong to the user and to Basic Memory's
timestamps; provenance never writes them.

Upstream `created_by` and `updated_by` (see `note_authorship`) name the person or
agent when a runtime authenticated one. A local install supplies no author, so
those keys stay ordinary frontmatter. The `bm_*` keys name the source app, which
that record does not, and this module never writes `created_by` or `updated_by`.
"""

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import yaml

SOURCE_CLIENT_KEY = "bm_source_client"
UPDATED_KEY = "bm_updated"
CREATED_BY_CLIENT_KEY = "bm_created_by_client"
PROVENANCE_KEYS = frozenset({SOURCE_CLIENT_KEY, UPDATED_KEY, CREATED_BY_CLIENT_KEY})

_FENCE = re.compile(r"^---[ \t]*$")
_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_-]+)[ \t]*:(?:[ \t]|$)")


def provenance_stamp(client: str, now: datetime) -> dict[str, str]:
    """Frontmatter for one write by `client` at `now`.

    `bm_created_by_client` rides along on every write. Note preparation keeps the value
    a note already has (see keep_first_writer), so it only lands when the write creates
    the note.
    """
    return {
        SOURCE_CLIENT_KEY: client,
        UPDATED_KEY: now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        CREATED_BY_CLIENT_KEY: client,
    }


def keep_first_writer(existing: Mapping[str, Any], merged: dict[str, Any]) -> None:
    """Restore the note's original creator after merging new frontmatter over it.

    Trigger: an overwrite or edit merges incoming frontmatter over an existing note.
    Why: `bm_created_by_client` names the app that first wrote the note, and every
         stamped write carries the current app, which would otherwise replace it.
    Outcome: an existing value wins; a note that never had one does not gain the
             current writer as its creator.
    """
    original_creator = existing.get(CREATED_BY_CLIENT_KEY)
    if original_creator:
        merged[CREATED_BY_CLIENT_KEY] = original_creator
    else:
        merged.pop(CREATED_BY_CLIENT_KEY, None)


def prepend_frontmatter_block(markdown: str, values: Mapping[str, str]) -> str:
    """Add a frontmatter fence in front of a note that does not have one.

    The original bytes follow the new fence, including trailing blank lines.
    A blank line separates the fence from a body that does not already start
    with a newline.
    """
    newline = "\r\n" if "\r\n" in markdown else "\n"
    lines = ["---" + newline]
    lines.extend(_yaml_line(key, value, newline) for key, value in values.items())
    lines.append("---" + newline)
    if markdown.startswith(("\n", "\r\n")):
        return "".join(lines) + markdown
    return "".join(lines) + newline + markdown


def write_frontmatter_lines(markdown: str, values: Mapping[str, str]) -> str:
    """Set top-level keys in existing frontmatter without re-serializing the rest.

    A YAML dump of the whole block would reformat the user's own values (it rewrites
    `updated: 2024-03-01T09:30:00Z` as `2024-03-01 09:30:00+00:00`). This replaces the
    lines of each key in `values`, or adds them before the closing fence, and leaves
    every other byte of the note as it was. The caller guarantees frontmatter exists.
    """
    lines = markdown.splitlines(keepends=True)
    opening = next(index for index, line in enumerate(lines) if line.strip())
    closing = next(
        index
        for index in range(opening + 1, len(lines))
        if _FENCE.match(lines[index].rstrip("\r\n"))
    )
    newline = "\r\n" if lines[opening].endswith("\r\n") else "\n"

    pending = dict(values)
    kept: list[str] = []
    in_replaced_value = False
    for line in lines[opening + 1 : closing]:
        # Indented lines and `- item` lines continue the previous key's value.
        if in_replaced_value and (line[:1] in (" ", "\t") or line.startswith("-")):
            continue
        key_match = _TOP_LEVEL_KEY.match(line.rstrip("\r\n"))
        key = key_match.group(1) if key_match else None
        in_replaced_value = key is not None and key in values
        if key is None or key not in values:
            kept.append(line)
        elif key in pending:
            # A duplicated key is written once, where it first appeared.
            kept.append(_yaml_line(key, pending.pop(key), newline))
    kept.extend(_yaml_line(key, value, newline) for key, value in pending.items())
    return "".join(lines[: opening + 1] + kept + lines[closing:])


def _yaml_line(key: str, value: str, newline: str) -> str:
    dumped = yaml.safe_dump({key: value}, allow_unicode=True, width=10_000)
    return dumped.rstrip("\n") + newline
