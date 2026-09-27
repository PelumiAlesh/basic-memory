"""Apply the current client's visibility policy to MCP reads.

Call `remember_mcp_client` before these helpers so a bearer-token identity
or clientInfo name is already bound. With no policies configured every note
is visible.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from basic_memory.config import ConfigManager
from basic_memory.file_utils import ParseError, has_frontmatter, parse_frontmatter
from basic_memory.schemas.search import SearchResponse
from basic_memory.shared_memory.privacy import (
    DENIAL,
    Access,
    access_for,
    note_is_visible,
)
from basic_memory.shared_memory.request_client import current_client_slug


def current_access() -> Access:
    config = ConfigManager().config
    return access_for(config.client_visibility, current_client_slug())


def note_visible(metadata: Mapping[str, Any] | None, file_path: str | None) -> bool:
    meta = metadata or {}
    return note_is_visible(
        current_access(),
        visibility=meta.get("visibility"),
        file_path=file_path,
    )


def denial_for(metadata: Mapping[str, Any] | None, file_path: str | None) -> str | None:
    if note_visible(metadata, file_path):
        return None
    return DENIAL


def denial_for_markdown(text: str, file_path: str | None) -> str | None:
    """Decide from raw markdown. Unparseable frontmatter fails closed when a policy exists."""
    access = current_access()
    if access.unrestricted:
        return None
    metadata: dict[str, Any] = {}
    if has_frontmatter(text):
        try:
            metadata = parse_frontmatter(text)
        except ParseError:
            metadata = {}
    if note_is_visible(access, visibility=metadata.get("visibility"), file_path=file_path):
        return None
    return DENIAL


def restrict_search_response(response: SearchResponse) -> SearchResponse:
    """Drop hits the current client may not see.

    The reported total becomes the visible page length and is marked inexact so
    a caller cannot infer how many notes were hidden.
    """
    access = current_access()
    if access.unrestricted:
        return response
    kept = [
        hit
        for hit in response.results
        if note_is_visible(
            access,
            visibility=(hit.metadata or {}).get("visibility"),
            file_path=hit.file_path,
        )
    ]
    if len(kept) == len(response.results):
        return response
    return response.model_copy(
        update={
            "results": kept,
            "total": len(kept),
            "total_is_exact": False,
            "has_more": False,
        }
    )
