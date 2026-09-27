"""The MCP client identity for the current request.

Token identity (HTTP bearer) wins over clientInfo. A tool calls
`remember_mcp_client` at entry so later helpers can read one slug without
each tool re-parsing the session.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from fastmcp import Context

from basic_memory.mcp.client_info import (
    MCP_CLIENT_INFO_STATE_KEY,
    client_info_from_context,
)
from basic_memory.shared_memory.client_names import slug_from_client_info

_token_client: ContextVar[str | None] = ContextVar("bm_token_client", default=None)
_info_client: ContextVar[str | None] = ContextVar("bm_info_client", default=None)


def bind_token_client(client: str | None) -> Token[str | None]:
    """Bind the client a bearer token authenticated, for this task."""
    return _token_client.set(client)


def reset_token_client(token: Token[str | None]) -> None:
    _token_client.reset(token)


def current_client_slug() -> str | None:
    """Token identity, else the clientInfo slug remembered for this task."""
    return _token_client.get() or _info_client.get()


async def remember_mcp_client(context: Context | None) -> str | None:
    """Record clientInfo for this task unless a bearer token already named the client."""
    if _token_client.get() is not None:
        return _token_client.get()
    info = client_info_from_context(context) if context is not None else None
    if info is None and context is not None:
        state = await context.get_state(MCP_CLIENT_INFO_STATE_KEY)
        info = state if isinstance(state, dict) else None
    slug = slug_from_client_info(info)
    _info_client.set(slug)
    return current_client_slug()
