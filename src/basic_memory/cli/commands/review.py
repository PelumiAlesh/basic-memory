"""bm review: list, promote, merge, or discard unreviewed notes."""

from __future__ import annotations

from typing import Optional

import typer

from basic_memory.cli.app import app
from basic_memory.cli.commands.command_utils import run_with_cleanup
from basic_memory.mcp.tools.review_tools import review_note, review_queue

review_app = typer.Typer(help="Review notes created by tools (status: unreviewed).")
app.add_typer(review_app, name="review")


@review_app.callback(invoke_without_command=True)
def review(
    ctx: typer.Context,
    project: Optional[str] = typer.Option(None, "--project", help="Project name"),
) -> None:
    """List the review queue when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    typer.echo(run_with_cleanup(review_queue(project=project)))


@review_app.command("list")
def review_list(
    project: Optional[str] = typer.Option(None, "--project", help="Project name"),
) -> None:
    """List notes with status: unreviewed."""
    typer.echo(run_with_cleanup(review_queue(project=project)))


@review_app.command("promote")
def review_promote(
    identifier: str = typer.Argument(..., help="Permalink or title to mark reviewed"),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    """Set status: reviewed."""
    typer.echo(run_with_cleanup(review_note(identifier, action="promote", project=project)))


@review_app.command("merge")
def review_merge(
    identifier: str = typer.Argument(..., help="Note to merge from"),
    target: str = typer.Argument(..., help="Note that receives the content"),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    """Append the note into target and mark the source merged."""
    typer.echo(
        run_with_cleanup(review_note(identifier, action="merge", target=target, project=project))
    )


@review_app.command("discard")
def review_discard(
    identifier: str = typer.Argument(..., help="Note to delete"),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    """Delete the note."""
    typer.echo(run_with_cleanup(review_note(identifier, action="discard", project=project)))
