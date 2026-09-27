"""Frontmatter provenance for MCP writes.

`source_client` and `updated` move with every write from an identified
client. `created_by_client` is set on the first write and kept after that,
even when a later client sends its own value. Cloud `created_by` stays the
account id; this is the MCP client, a different fact.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

SOURCE_CLIENT = "source_client"
CREATED_BY_CLIENT = "created_by_client"
UPDATED = "updated"

PROVENANCE_KEYS = (SOURCE_CLIENT, CREATED_BY_CLIENT, UPDATED)


def stamp_provenance(
    metadata: Mapping[str, Any] | None,
    *,
    client: str | None,
    enabled: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Copy metadata and add provenance when the feature is on and a client is known.

    No client means no stamp. API and CLI writes, and MCP sessions that never
    send clientInfo, keep the bytes they would have written before.
    """
    stamped = dict(metadata or {})
    if not enabled or not client:
        return stamped
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamped[SOURCE_CLIENT] = client
    stamped[UPDATED] = moment.astimezone(timezone.utc).isoformat()
    # The preparation layer drops this on update when the note has no creator
    # yet, so an edit does not pretend the editor created the note.
    stamped.setdefault(CREATED_BY_CLIENT, client)
    return stamped


def keep_original_creator(existing: Mapping[str, Any], merged: dict[str, Any]) -> None:
    """Preserve the first writer's client across later metadata merges.

    Trigger: a write or edit is merging new frontmatter over a note that
    already exists.
    Why: `created_by_client` means who wrote the note the first time. The
    tool always sends the current client, which would otherwise overwrite it.
    Outcome: an existing value wins; a note that never had one does not gain
    the editor's name as if they had created it.
    """
    prior = existing.get(CREATED_BY_CLIENT)
    if isinstance(prior, str) and prior.strip():
        merged[CREATED_BY_CLIENT] = prior
        return
    merged.pop(CREATED_BY_CLIENT, None)


def provenance_lines(metadata: Mapping[str, Any] | None) -> list[str]:
    """Lines to show on a read or search hit. Empty when the note has none."""
    if not metadata:
        return []
    lines: list[str] = []
    for key in PROVENANCE_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f"{key}: {value.strip()}")
    return lines


def provenance_footer(metadata: Mapping[str, Any] | None) -> str:
    """A short trailer for text reads whose frontmatter was stripped."""
    lines = provenance_lines(metadata)
    if not lines:
        return ""
    return "\n\n---\n" + "\n".join(lines) + "\n"
