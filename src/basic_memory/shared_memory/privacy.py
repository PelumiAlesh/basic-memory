"""Per-client visibility for MCP reads.

Notes declare `visibility: private|work|shareable`. A client policy names what
that client cannot read. When any policy exists and the client is unknown,
only `shareable` notes are readable and every configured path prefix is
denied. Missing or unrecognized visibility is treated as private. No policy
means no filtering, which is the upstream behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Visibility = Literal["private", "work", "shareable"]
_VISIBILITIES = frozenset({"private", "work", "shareable"})
DENIAL = "This note is not visible to this client."


class ClientVisibilityPolicy(BaseModel):
    """What one MCP client is not allowed to read."""

    model_config = ConfigDict(extra="forbid")

    deny_visibility: list[Visibility] = Field(default_factory=list)
    deny_path_prefixes: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Access:
    unrestricted: bool
    deny_visibility: frozenset[str]
    deny_prefixes: tuple[str, ...]


def access_for(
    policies: Mapping[str, ClientVisibilityPolicy],
    client: str | None,
) -> Access:
    """The access decision for this client. Empty policies do not restrict anyone."""
    if not policies:
        return Access(True, frozenset(), ())
    if client and client in policies:
        policy = policies[client]
        return Access(
            False,
            frozenset(policy.deny_visibility),
            tuple(policy.deny_path_prefixes),
        )
    # Trigger: a policy exists and this request has no matching client.
    # Why: an unidentified caller must not inherit the most permissive client.
    # Outcome: private and work are denied, and every configured path prefix is denied.
    prefixes: list[str] = []
    for policy in policies.values():
        prefixes.extend(policy.deny_path_prefixes)
    return Access(False, frozenset({"private", "work"}), tuple(prefixes))


def _normalize_visibility(value: object) -> str:
    if not isinstance(value, str):
        return "private"
    text = value.strip().lower()
    if text not in _VISIBILITIES:
        return "private"
    return text


def _normalize_path(path: str | None) -> str:
    return (path or "").replace("\\", "/").lstrip("/")


def note_is_visible(
    access: Access,
    *,
    visibility: object,
    file_path: str | None,
) -> bool:
    """Whether this client may see the note. Unrestricted access always may."""
    if access.unrestricted:
        return True
    if _normalize_visibility(visibility) in access.deny_visibility:
        return False
    path = _normalize_path(file_path)
    for prefix in access.deny_prefixes:
        norm = _normalize_path(prefix).strip("/")
        if not norm:
            continue
        if path == norm or path.startswith(norm + "/"):
            return False
    return True
