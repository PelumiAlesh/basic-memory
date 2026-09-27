"""Well-known paths for fork setup."""

from __future__ import annotations

import sys
from pathlib import Path


def default_vault_path() -> Path:
    documents = Path.home() / "Documents" / "AI Memory"
    legacy = Path.home() / "basic-memory"
    if documents.exists():
        return documents
    if legacy.exists():
        return legacy
    return documents


def cursor_routing_path() -> Path:
    return Path.home() / ".cursor" / "basic-memory.json"


def cursor_mcp_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def cursor_hooks_path() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def cursor_user_rule_path() -> Path:
    """Machine-local Cursor rule file.

    The rules reference documents account-synced user rules only through
    Customize → Rules. The help page also documents ``~/.cursor/rules`` as
    files that stay on this machine. Setup writes here and prints the same text.
    """
    return Path.home() / ".cursor" / "rules" / "basic-memory-get-brief.mdc"


def claude_desktop_mcp_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform == "win32":
        appdata = Path.home() / "AppData" / "Roaming"
        return appdata / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def claude_code_settings_path() -> Path:
    """User settings. Claude Code reads hooks here, not MCP server definitions."""
    return Path.home() / ".claude" / "settings.json"


def claude_code_mcp_path() -> Path:
    """User-scope MCP config. ``claude mcp add --scope user`` writes this file.

    ``mcpServers`` in ``~/.claude/settings.json`` is ignored.
    """
    return Path.home() / ".claude.json"


def codex_routing_path() -> Path:
    return Path.home() / ".codex" / "basic-memory.json"


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"
