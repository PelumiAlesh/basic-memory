"""bm brief — bounded project briefing with per-conversation delivery throttling."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

from basic_memory.cli.app import app
from basic_memory.cli.commands.hook import (
    Harness,
    PROFILES,
    _build_brief,
    load_harness_settings,
)
from basic_memory.config import ConfigManager
from basic_memory.setup.paths import cursor_routing_path, default_vault_path
from basic_memory.shared_memory.brief_delivery import (
    JsonBriefDeliveryStore,
    project_delivery_path,
    should_deliver_brief,
)


class _BriefDeliverySkipped(Exception):
    """Raised when refresh throttling skips printing a brief."""


def _resolve_project_path(project_name: str) -> Path:
    config = ConfigManager().config
    entry = config.projects.get(project_name)
    if entry is None or not entry.path:
        return default_vault_path().expanduser().resolve()
    return Path(entry.path).expanduser().resolve()


def render_brief_for_project(project_name: str) -> str:
    """Render the session brief for a pinned project (no delivery bookkeeping)."""
    mapping_dir = _resolve_project_path(project_name)
    cfg: dict[str, object] = {"primaryProject": project_name}
    routing_path = cursor_routing_path()
    if routing_path.is_file():
        try:
            routing = json.loads(routing_path.read_text(encoding="utf-8"))
            if isinstance(routing, dict):
                cfg.update(routing)
        except json.JSONDecodeError:
            pass
    loaded, configured = load_harness_settings(Harness.claude, mapping_dir)
    cfg = {**cfg, **loaded}
    profile = PROFILES[Harness.claude]
    return _build_brief(profile, cfg, configured, None)


@app.command("brief")
def brief_command(
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Project name")] = None,
    conversation: Annotated[
        Optional[str],
        typer.Option(
            "--conversation",
            "--conversation-id",
            help="Track delivery per harness conversation id",
        ),
    ] = None,
    refresh_hours: Annotated[
        Optional[float],
        typer.Option("--refresh-hours", help="Override brief_refresh_hours"),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Print even inside the refresh window")
    ] = False,
) -> None:
    """Print a bounded project briefing, optionally throttled per conversation."""
    config = ConfigManager().config
    project_name = project or config.default_project or "main"
    hours = refresh_hours if refresh_hours is not None else float(config.brief_refresh_hours)

    if conversation and not force:
        store = JsonBriefDeliveryStore(project_delivery_path(_resolve_project_path(project_name)))
        state = store.load()
        if not should_deliver_brief(
            state.last_delivered_at(conversation),
            refresh_hours=hours,
            force=False,
        ):
            raise typer.Exit(0)

    text = render_brief_for_project(project_name)
    if conversation:
        store = JsonBriefDeliveryStore(project_delivery_path(_resolve_project_path(project_name)))
        state = store.load()
        state.record(conversation, datetime.now(timezone.utc))
        store.save(state)

    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
