"""bm import claude transcripts — Claude Code JSONL sessions from ~/.claude/projects."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel

from basic_memory.cli.app import claude_app
from basic_memory.cli.commands.command_utils import run_with_cleanup
from basic_memory.cli.commands.import_memory_json import get_importer_dependencies
from basic_memory.config import get_project_config

console = Console()

DEFAULT_SOURCE = Path("~/.claude/projects")


async def _import(source: Path, folder: str, since_days: int | None, include_existing: bool):
    from basic_memory.importers.claude_transcripts_importer import ClaudeTranscriptsImporter

    config = get_project_config()
    markdown_processor, file_service = await get_importer_dependencies()
    importer = ClaudeTranscriptsImporter(
        config.home, markdown_processor, file_service, project_name=config.name
    )
    return await importer.import_data(
        source,
        folder,
        since_days=since_days,
        skip_existing=not include_existing,
    )


@claude_app.command(name="transcripts", help="Import Claude Code session transcripts (JSONL).")
def import_claude_transcripts(
    source: Annotated[
        Path,
        typer.Argument(help="A transcript .jsonl, a project folder, or ~/.claude/projects"),
    ] = DEFAULT_SOURCE,
    folder: Annotated[
        str, typer.Option(help="Folder inside the project for the notes")
    ] = "conversations/claude-code",
    since_days: Annotated[
        Optional[int],
        typer.Option("--since-days", min=1, help="Only transcripts modified in the last N days"),
    ] = None,
    include_existing: Annotated[
        bool,
        typer.Option("--include-existing", help="Rewrite notes that already exist"),
    ] = False,
) -> None:
    """Import Claude Code sessions before Claude Code prunes them (~30 days).

    One note per session, type: conversation, with the session id, cwd, and
    branch in frontmatter. Tool calls and subagent sidechains are left out.
    Re-running skips notes that already exist unless --include-existing is set.
    """
    resolved = source.expanduser()
    if not resolved.exists():
        typer.echo(f"Error: not found: {resolved}", err=True)
        raise typer.Exit(1)
    result = run_with_cleanup(_import(resolved, folder, since_days, include_existing))
    if not result.success:
        typer.echo(f"Error during import: {result.error_message}", err=True)
        raise typer.Exit(1)
    skipped = result.import_count.get("skipped", 0)
    console.print(
        Panel(
            f"[green]Import complete![/green]\n\n"
            f"Imported {result.conversations} session(s) with {result.messages} message(s)\n"
            f"Skipped {skipped} (existing, empty, or outside --since-days)",
            expand=False,
        )
    )
