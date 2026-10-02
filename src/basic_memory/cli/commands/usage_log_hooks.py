"""Per-turn usage-log hook verbs (stdlib fast path first)."""

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import typer

from basic_memory.cli.commands.hook import hook_app
from basic_memory.shared_memory.usage_log_fast import (
    append_event_line,
    conversation_id_from_payload,
    tool_name_from_post_mcp_payload,
)

_USAGE_SERVER_PREFIX = "mcp__basic-memory__"


class UsageHarness(str, Enum):
    claude = "claude"
    cursor = "cursor"


def _read_payload() -> dict[str, Any]:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _log_hook(
    *,
    name: str,
    harness: UsageHarness,
    project_dir: Path | None,
    payload: dict[str, Any],
    extra: dict[str, Any],
) -> None:
    conversation_id = conversation_id_from_payload(harness.value, payload)
    event = {
        "event": "hook",
        "name": name,
        "client": "claude-code" if harness is UsageHarness.claude else "cursor",
        **extra,
    }
    if conversation_id:
        event["conversation_id"] = conversation_id
    append_event_line(event, project_dir=project_dir)


@hook_app.command("prompt-submit")
def prompt_submit(
    harness: UsageHarness = typer.Option(..., "--harness", help="claude or cursor"),
    project_dir: Optional[Path] = typer.Option(None, "--project-dir"),
) -> None:
    """Log a prompt-submit turn; fail-open with empty JSON when not injecting a brief."""
    payload = _read_payload()
    try:
        _log_hook(
            name="prompt-submit",
            harness=harness,
            project_dir=project_dir,
            payload=payload,
            extra={"reason": "not_due"},
        )
    except Exception:
        pass
    print("{}")


@hook_app.command("turn-end")
def turn_end(
    harness: UsageHarness = typer.Option(..., "--harness", help="claude or cursor"),
    project_dir: Optional[Path] = typer.Option(None, "--project-dir"),
) -> None:
    """Log turn end (Stop / stop)."""
    payload = _read_payload()
    try:
        _log_hook(
            name="turn-end",
            harness=harness,
            project_dir=project_dir,
            payload=payload,
            extra={},
        )
    except Exception:
        pass
    if harness is UsageHarness.claude:
        print('{"continue":true}')
    else:
        print("{}")


@hook_app.command("post-mcp-tool")
def post_mcp_tool(
    harness: UsageHarness = typer.Option(..., "--harness", help="claude or cursor"),
    project_dir: Optional[Path] = typer.Option(None, "--project-dir"),
) -> None:
    """Log a basic-memory MCP tool call with conversation id (no content)."""
    payload = _read_payload()
    tool = tool_name_from_post_mcp_payload(harness.value, payload)
    if harness is UsageHarness.claude and tool and tool.startswith("mcp__"):
        if _USAGE_SERVER_PREFIX in tool:
            tool = tool.split(_USAGE_SERVER_PREFIX, 1)[-1]
    if tool and not _is_basic_memory_tool(tool, payload):
        print("{}")
        return
    try:
        extra: dict[str, Any] = {}
        if tool:
            extra["tool"] = tool
        _log_hook(
            name="post-mcp-tool",
            harness=harness,
            project_dir=project_dir,
            payload=payload,
            extra=extra,
        )
    except Exception:
        pass
    print("{}")


def _is_basic_memory_tool(tool: str, payload: dict[str, Any]) -> bool:
    server = payload.get("server") or payload.get("mcp_server") or payload.get("serverName")
    if isinstance(server, str) and "basic" in server.lower():
        return True
    return tool in {
        "write_note",
        "edit_note",
        "read_note",
        "search_notes",
        "delete_note",
        "move_note",
        "get_brief",
    } or tool.startswith("mcp__basic-memory__")
