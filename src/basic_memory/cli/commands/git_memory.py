"""bm history and bm undo for agent commits in the project repository."""

from __future__ import annotations

from typing import Optional

import typer

from basic_memory.cli.app import app
from basic_memory.config import ConfigManager
from basic_memory.shared_memory.git_sync import GitMemoryError, history as git_history
from basic_memory.shared_memory.git_sync import undo as git_undo


def _root(project: str | None):
    config = ConfigManager().config
    name = project or config.default_project
    if not name:
        typer.echo("error: no project configured", err=True)
        raise typer.Exit(1)
    return config.get_project_path(name), config


@app.command("history")
def history(
    note: str = typer.Argument(..., help="Note path relative to the project"),
    project: Optional[str] = typer.Option(None, "--project"),
    limit: int = typer.Option(20, "--limit", min=1),
) -> None:
    """Show git history for one note. Uses the local repository only."""
    root, _config = _root(project)
    try:
        typer.echo(git_history(root, note, limit=limit))
    except GitMemoryError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("undo")
def undo(
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    """Revert the last agent commit (messages that start with memory(...):).

    Pushes the revert only when git_auto_push is on and a remote exists.
    """
    root, config = _root(project)
    try:
        subject = git_undo(root, auto_push=config.git_auto_push)
    except GitMemoryError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Reverted {subject}")
