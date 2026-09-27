"""bm brief — print a bounded project briefing with optional delivery throttling."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

from basic_memory.cli.app import app
from basic_memory.cli.commands.command_utils import run_with_cleanup
from basic_memory.cli.commands.routing import force_routing, validate_routing_flags
from basic_memory.config import ConfigManager
from basic_memory.mcp.async_client import get_client
from basic_memory.mcp.project_context import get_active_project
from basic_memory.mcp.tools.brief import build_brief
from basic_memory.shared_memory.brief_delivery import (
    JsonBriefDeliveryStore,
    project_delivery_path,
    should_deliver_brief,
)

HARNESS_FENCE = "```basic-memory-brief"


class _BriefDeliverySkipped(Exception):
    """Raised when refresh throttling skips printing a brief."""


def _wrap_harness(text: str) -> str:
    return f"{HARNESS_FENCE}\n{text.rstrip()}\n```\n"


def _resolve_project_path(project_name: str) -> Path:
    config = ConfigManager().config
    entry = config.projects.get(project_name)
    if entry is None or not entry.path:
        typer.echo(f"Error: unknown local project '{project_name}'.", err=True)
        raise typer.Exit(1)
    return Path(entry.path).expanduser().resolve()


@app.command("brief")
def brief_command(
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Project name")] = None,
    conversation_id: Annotated[
        Optional[str],
        typer.Option("--conversation-id", help="Track delivery per conversation"),
    ] = None,
    refresh_hours: Annotated[
        Optional[float],
        typer.Option("--refresh-hours", help="Override brief_refresh_hours"),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Print even inside the refresh window")
    ] = False,
    harness: Annotated[
        bool,
        typer.Option("--harness", help="Wrap output in a fenced block for hook scripts"),
    ] = False,
    local: Annotated[bool, typer.Option("--local", help="Force local routing")] = False,
    cloud: Annotated[bool, typer.Option("--cloud", help="Force cloud routing")] = False,
    delivery_store: Annotated[
        Optional[Path],
        typer.Option(
            "--delivery-store",
            help="Override brief delivery JSON path (advanced; default: <project>/.basic-memory/)",
            hidden=True,
        ),
    ] = None,
) -> None:
    """Print the same bounded briefing as the get_brief MCP tool."""
    validate_routing_flags(local=local, cloud=cloud)
    force_routing(local=local, cloud=cloud)

    config = ConfigManager().config
    project_arg = project or config.default_project
    hours = refresh_hours if refresh_hours is not None else float(config.brief_refresh_hours)

    async def _run() -> str:
        store: JsonBriefDeliveryStore | None = None
        state = None
        async with get_client(project_name=project_arg) as client:
            project_item = await get_active_project(client, project_arg, None)
            if conversation_id:
                project_path = _resolve_project_path(project_item.name)
                store_path = delivery_store or project_delivery_path(project_path)
                store = JsonBriefDeliveryStore(store_path)
                state = store.load()
                last = state.last_delivered_at(conversation_id)
                if not should_deliver_brief(last, refresh_hours=hours, force=force):
                    raise _BriefDeliverySkipped()
            text = await build_brief(
                project=project_item.name,
                project_id=None,
                token_budget=None,
                context=None,
            )
            if conversation_id and store is not None and state is not None:
                state.record(conversation_id, datetime.now(timezone.utc))
                store.save(state)
            return text

    try:
        text = run_with_cleanup(_run())
    except _BriefDeliverySkipped:
        raise typer.Exit(0)
    if harness:
        text = _wrap_harness(text)
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
