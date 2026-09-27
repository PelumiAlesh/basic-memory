"""List and resolve notes waiting in the review inbox."""

from __future__ import annotations

from typing import Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from basic_memory.mcp.project_context import get_project_client
from basic_memory.mcp.server import mcp
from basic_memory.mcp.tools.delete_note import delete_note
from basic_memory.mcp.tools.edit_note import edit_note
from basic_memory.mcp.tools.read_note import read_note
from basic_memory.schemas.search import SearchItemType, SearchQuery, SearchRetrievalMode
from basic_memory.shared_memory.request_client import remember_mcp_client
from basic_memory.shared_memory.review import status_for_action

ReviewAction = Literal["promote", "merge", "discard"]


async def _queue(project: str | None, project_id: str | None, context: Context | None) -> str:
    await remember_mcp_client(context)
    async with get_project_client(project, context=context, project_id=project_id) as (
        client,
        active_project,
    ):
        from basic_memory.mcp.clients import SearchClient

        search = SearchClient(client, active_project.external_id)
        response = await search.search(
            SearchQuery(
                status="unreviewed",
                entity_types=[SearchItemType.ENTITY],
                retrieval_mode=SearchRetrievalMode.FTS,
            ).model_dump(mode="json"),
            page=1,
            page_size=50,
        )
        lines = [f"# Review queue ({active_project.name})", ""]
        if not response.results:
            lines.append("(empty)")
            return "\n".join(lines) + "\n"
        for hit in response.results:
            lines.append(f"- {hit.title} (`{hit.permalink or hit.file_path}`)")
        return "\n".join(lines) + "\n"


async def _review(
    identifier: str,
    action: str,
    *,
    target: str | None,
    project: str | None,
    project_id: str | None,
    context: Context | None,
) -> str:
    await remember_mcp_client(context)
    if action == "merge" and not (target and target.strip()):
        raise ValueError("merge requires target, the note that should receive the content")
    if action == "discard":
        await delete_note(
            identifier,
            project=project,
            project_id=project_id,
            context=context,
        )
        return f"Discarded `{identifier}`.\n"
    if action == "merge":
        source = await read_note(
            identifier,
            project=project,
            project_id=project_id,
            output_format="json",
            include_frontmatter=False,
            context=context,
        )
        if not isinstance(source, dict) or not source.get("content"):
            raise ToolError(f"Could not read `{identifier}` to merge it")
        body = str(source["content"]).strip()
        title = source.get("title") or identifier
        await edit_note(
            target or "",
            operation="append",
            content=f"\n\n## Merged from {title}\n\n{body}\n",
            project=project,
            project_id=project_id,
            context=context,
        )
    status = status_for_action(action)
    await edit_note(
        identifier,
        operation="append",
        content="",
        metadata={"status": status},
        project=project,
        project_id=project_id,
        context=context,
    )
    if action == "merge":
        return f"Merged `{identifier}` into `{target}` and marked it merged.\n"
    return f"Promoted `{identifier}` (status: {status}).\n"


@mcp.tool(
    title="Review Queue",
    tags={"review"},
    annotations={
        "title": "Review Queue",
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
    },
)
async def review_queue(
    project: str | None = None,
    project_id: str | None = None,
    context: Context | None = None,
) -> str:
    """List notes with status: unreviewed.

    Populated when `review_inbox_enabled` is true and `review_inbox_mode` is
    `status` (the default). Folder-mode notes live under `review_inbox_folder`
    and can be browsed with list_directory.
    """
    return await _queue(project, project_id, context)


@mcp.tool(
    title="Review Note",
    tags={"review"},
    annotations={
        "title": "Review Note",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def review_note(
    identifier: str,
    action: ReviewAction,
    target: str | None = None,
    project: str | None = None,
    project_id: str | None = None,
    context: Context | None = None,
) -> str:
    """Promote, merge, or discard one unreviewed note.

    promote sets status: reviewed. merge appends the note into `target` and
    sets status: merged. discard deletes the note.
    """
    return await _review(
        identifier,
        action,
        target=target,
        project=project,
        project_id=project_id,
        context=context,
    )
