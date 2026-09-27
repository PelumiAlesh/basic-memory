"""`bm stats` — local usage log aggregates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from basic_memory.cli.app import app
from basic_memory.config import ConfigManager
from basic_memory.shared_memory.stats import compute_stats, load_events, report_to_json

HARNESS_GAP_NOTES = (
    "Memory-tool attribution is exact when post-MCP-tool hooks log PostToolUse "
    "(Claude Code) or afterMCPExecution (Cursor desktop). HTTP clients without "
    "hooks (ChatGPT, Grok) use INFERRED session boundaries (30-minute idle gap). "
    "Cursor cloud agents do not fire beforeSubmitPrompt or afterMCPExecution; "
    "those numbers are absent or inferred. Cursor beforeSubmitPrompt output is "
    "documented as continue/user_message only — brief injection on resume may be "
    "unavailable until sessionStart or a future harness capability."
)

stats_app = typer.Typer(
    help=(
        "Summarize local usage logs (.bm-logs). Reads only on-disk JSONL; nothing "
        "is sent off the machine. " + HARNESS_GAP_NOTES
    ),
)
app.add_typer(stats_app, name="stats")


def _project_homes(project: Optional[str]) -> list[Path]:
    config = ConfigManager().config
    if project:
        if project not in config.projects:
            typer.echo(f"Unknown project: {project}", err=True)
            raise typer.Exit(1)
        path = Path(config.projects[project].path)
        return [path.resolve()] if path.is_absolute() else []
    homes: list[Path] = []
    for entry in config.projects.values():
        root = Path(entry.path)
        if root.is_absolute():
            homes.append(root.resolve())
    return homes


@stats_app.callback(invoke_without_command=True)
def stats_summary(
    days: int = typer.Option(7, "--days", min=1, help="Lookback window in days"),
    as_json: bool = typer.Option(False, "--json", help="Emit privacy-safe aggregates only"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Limit to one project"),
) -> None:
    """Show usage and conversation coverage from local logs."""
    homes = _project_homes(project)
    events = load_events(homes, days)
    report = compute_stats(events, days=days)
    report.harness_gaps.append(HARNESS_GAP_NOTES)

    if as_json:
        typer.echo(json.dumps(report_to_json(report), indent=2))
        return

    typer.echo(f"Usage stats (last {days} day(s))")
    typer.echo(f"Dropped events (queue pressure): {report.dropped_events}")
    typer.echo(f"Tool error rate: {report.error_rate:.2%}")
    if report.turn_memory_read_pct is not None:
        typer.echo(f"Turns with memory read (hook clients): {report.turn_memory_read_pct:.1f}%")
    if report.resumed_brief_pct is not None:
        typer.echo(f"Resumed conversations with fresh brief: {report.resumed_brief_pct:.1f}%")
    typer.echo(f"Conversations with turns but no memory use: {len(report.zero_use_conversations)}")
    if report.most_active_conversations:
        typer.echo("Most active conversations:")
        for conv, count, title in report.most_active_conversations:
            label = title or conv
            typer.echo(f"  {label}: {count} turn(s)")
    if report.inferred_http_sessions:
        typer.echo("INFERRED HTTP client sessions:")
        for session in report.inferred_http_sessions:
            typer.echo(
                f"  {session.get('client')}: {session.get('tool_calls')} calls, "
                f"first={session.get('first_call')}, "
                f"write_before_idle={session.get('write_before_idle')}"
            )
    if report.most_read_notes:
        typer.echo("Most-read notes:")
        for permalink, count in report.most_read_notes[:5]:
            typer.echo(f"  {permalink}: {count}")
    if report.never_read_written:
        typer.echo("Written but not read afterwards (sample):")
        for permalink in report.never_read_written[:5]:
            typer.echo(f"  {permalink}")
