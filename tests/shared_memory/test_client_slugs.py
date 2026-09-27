"""Client slugs name the app behind an MCP request; they are labels, not credentials."""

from typing import Any, cast

import mcp.types as mt
import pytest
from fastmcp import Client, Context, FastMCP

from basic_memory.mcp.client_info import MCP_CLIENT_INFO_STATE_KEY
from basic_memory.shared_memory.clients import (
    MAX_CLIENT_SLUG_LENGTH,
    client_slug,
    request_client,
)


@pytest.mark.parametrize(
    ("reported_name", "slug"),
    [
        ("cursor-vscode", "cursor"),
        ("Cursor", "cursor"),
        ("claude-code", "claude-code"),
        ("Claude Code", "claude-code"),
        ("claude-ai", "claude"),
        ("openai-mcp", "chatgpt"),
        ("openai-mcp/1.0.0", "chatgpt"),
        ("codex-mcp-client", "codex"),
        ("grok-bot", "grok"),
    ],
)
def test_known_client_names_map_to_one_slug_per_app(reported_name: str, slug: str) -> None:
    assert client_slug(reported_name) == slug


def test_lookalike_names_keep_their_own_slug() -> None:
    # The old prefix rule turned this into "cursor"; a label must not be borrowable.
    assert client_slug("cursor-attacker") == "cursor-attacker"
    assert client_slug("claude-code-fork") == "claude-code-fork"


def test_unknown_names_are_cleaned_and_bounded() -> None:
    assert client_slug("  My Bot!! (beta) ") == "my-bot-beta"
    long_slug = client_slug("x" * 100)
    assert long_slug is not None
    assert len(long_slug) == MAX_CLIENT_SLUG_LENGTH


def test_names_with_nothing_usable_have_no_slug() -> None:
    assert client_slug("   ") is None
    assert client_slug("!!!") is None


class _StateOnlyContext:
    """A legacy session: no per-request clientInfo, only the initialize-time state."""

    def __init__(self, state: dict[str, object]) -> None:
        self.request_context = None
        self._state = state

    async def get_state(self, key: str) -> object | None:
        return self._state.get(key)


@pytest.mark.asyncio
async def test_request_client_without_context_is_anonymous() -> None:
    assert await request_client(None) is None


@pytest.mark.asyncio
async def test_request_client_reads_initialize_state_for_legacy_sessions() -> None:
    context = _StateOnlyContext(
        {MCP_CLIENT_INFO_STATE_KEY: {"name": None, "title": "Claude Code", "version": "2"}}
    )
    assert await request_client(cast(Any, context)) == "claude-code"
    assert await request_client(cast(Any, _StateOnlyContext({}))) is None


@pytest.mark.asyncio
async def test_request_client_reads_client_info_from_a_live_session() -> None:
    server = FastMCP("client-slug-test")

    @server.tool
    async def whoami(context: Context) -> str:
        return await request_client(context) or "anonymous"

    async with Client(
        server, client_info=mt.Implementation(name="cursor-vscode", version="1.0.0")
    ) as session:
        result = await session.call_tool("whoami", {})

    assert result.data == "cursor"
