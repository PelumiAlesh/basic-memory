"""bm care: notes past review_by, missing provenance, orphans, and oversized files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx
import typer
from fastmcp.exceptions import ToolError

from basic_memory.cli.app import app
from basic_memory.cli.commands.command_utils import run_with_cleanup
from basic_memory.cli.commands.orphans import run_orphans
from basic_memory.config import ConfigManager
from basic_memory.shared_memory.care import render_care_report, scan_tree


def _project_root(project: str | None) -> tuple[str, Path]:
    config = ConfigManager().config
    name = project or config.default_project
    if not name:
        typer.echo("error: no project configured", err=True)
        raise typer.Exit(1)
    return name, config.get_project_path(name)


async def _orphan_paths(project: str) -> tuple[list[str], str | None]:
    # Trigger: the knowledge API cannot answer the orphan query.
    # Why: the file scan is still useful, and care is a report not a gate.
    # Outcome: print the file findings and say orphans were unavailable.
    try:
        _name, nodes = await run_orphans(project)
    except (ToolError, httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
        return [], type(exc).__name__
    return [node.file_path for node in nodes], None


@app.command()
def care(
    project: Optional[str] = typer.Option(None, "--project", help="Project name"),
) -> None:
    """Report stale, unprovenanced, orphaned, and oversized notes.

    Reuses `bm orphans` for the graph check. `bm doctor` is still the
    file-to-database consistency check and is not run from here.
    """
    name, root = _project_root(project)
    config = ConfigManager().config
    findings = scan_tree(root, oversized_bytes=config.care_oversized_bytes)
    orphans, error = run_with_cleanup(_orphan_paths(name))
    typer.echo(
        render_care_report(findings, orphans=orphans, orphan_error=error),
    )
