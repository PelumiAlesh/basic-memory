"""bm import notion — Notion Markdown & CSV export."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from basic_memory.cli.app import import_app
from basic_memory.cli.commands.command_utils import run_with_cleanup
from basic_memory.config import ConfigManager, get_project_config


async def _import(source: Path, destination_folder: str) -> str:
    from basic_memory.cli.commands.import_memory_json import get_importer_dependencies
    from basic_memory.importers.notion_importer import NotionImporter

    config = get_project_config()
    markdown_processor, file_service = await get_importer_dependencies()
    importer = NotionImporter(
        config.home, markdown_processor, file_service, project_name=config.name
    )
    result = await importer.import_data(source, destination_folder)
    if not result.success:
        return f"error: {result.error_message}"
    return (
        f"Imported {result.notes} note(s) "
        f"({result.csv_rows} from CSV) into {destination_folder}. "
        f"Skipped {result.skipped}."
    )


@import_app.command("notion")
def notion(
    source: Annotated[Path, typer.Argument(help="Notion 'Markdown & CSV' export zip or folder")],
    destination_folder: Annotated[
        str,
        typer.Option("--destination", help="Folder inside the project"),
    ] = "imports/notion",
) -> None:
    """Import a Notion Markdown & CSV export.

    Strips Notion's 32-character id suffixes, rewrites internal links to wiki
    links, and turns database CSV rows into notes with frontmatter properties.
    """
    if not source.exists():
        typer.echo(f"error: not found: {source}", err=True)
        raise typer.Exit(1)
    # Touch config so a missing config fails here with the usual message.
    ConfigManager().config
    message = run_with_cleanup(_import(source, destination_folder))
    if message.startswith("error:"):
        typer.echo(message, err=True)
        raise typer.Exit(1)
    typer.echo(message)
