"""Name the app behind an MCP request with a short client slug.

The slug is a label for provenance, not a credential: MCP clientInfo is whatever the
connecting app says about itself, so nothing may be allowed or denied on it.
"""

import re

from fastmcp import Context

from basic_memory.mcp.client_info import MCP_CLIENT_INFO_STATE_KEY, client_info_from_context

# clientInfo names the apps sharing the memory folder are known to send, mapped to one
# slug per app. The match is exact: a prefix rule let `cursor-attacker` label its
# writes as Cursor. Any other name keeps its own cleaned slug.
KNOWN_CLIENT_NAMES: dict[str, str] = {
    "cursor": "cursor",
    "cursor-vscode": "cursor",
    "claude-code": "claude-code",
    "claude-ai": "claude",
    "claude": "claude",
    "openai-mcp": "chatgpt",
    "chatgpt": "chatgpt",
    "codex": "codex",
    "codex-mcp-client": "codex",
    "grok": "grok",
    "grok-bot": "grok",
}
MAX_CLIENT_SLUG_LENGTH = 40
_NON_SLUG_CHARACTERS = re.compile(r"[^a-z0-9]+")


def client_slug(name: str) -> str | None:
    """Map a reported client name to its slug, or None when nothing usable remains."""
    # Some clients append their version ("openai-mcp/1.0.0"); it is not the identity.
    base_name = name.strip().lower().split("/", 1)[0]
    slug = _NON_SLUG_CHARACTERS.sub("-", base_name).strip("-")
    slug = slug[:MAX_CLIENT_SLUG_LENGTH].rstrip("-")
    if not slug:
        return None
    return KNOWN_CLIENT_NAMES.get(slug, slug)


async def request_client(context: Context | None) -> str | None:
    """The slug of the app making this MCP request, or None when it never named itself."""
    if context is None:
        return None
    client_info = client_info_from_context(context)
    if client_info is None:
        # Legacy sessions only expose clientInfo through the initialize-time state.
        state = await context.get_state(MCP_CLIENT_INFO_STATE_KEY)
        client_info = state if isinstance(state, dict) else None
    if client_info is None:
        return None
    reported_name = client_info.get("name") or client_info.get("title")
    return client_slug(reported_name) if reported_name else None
