"""get_brief: a bounded orientation for clients that have no session hook."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError

from basic_memory.config import ConfigManager
from basic_memory.mcp.project_context import get_project_client
from basic_memory.mcp.server import mcp
from basic_memory.schemas.search import SearchItemType, SearchQuery, SearchRetrievalMode
from basic_memory.shared_memory.brief_delivery import (
    BriefDeliveryState,
    JsonBriefDeliveryStore,
    project_delivery_path,
    should_deliver_brief,
)
from basic_memory.shared_memory.briefing import BriefSection, render_brief

_EXCERPT_CHARS = 800
_LIST_LIMIT = 8


def _hit_line(title: str | None, permalink: str | None) -> str:
    name = title or permalink or "(untitled)"
    if permalink:
        return f"- {name} (`{permalink}`)"
    return f"- {name}"


async def _optional_excerpt(knowledge: Any, identifier: str) -> str | None:
    """Return a short excerpt when the note exists; None when it does not."""
    try:
        entity_id = await knowledge.resolve_entity(identifier, strict=True)
        entity = await knowledge.get_entity(entity_id)
    except ToolError:
        return None
    body = (entity.content or "").strip()
    if not body:
        return f"**{entity.title}**"
    if len(body) > _EXCERPT_CHARS:
        body = body[:_EXCERPT_CHARS].rstrip() + "…"
    return f"**{entity.title}**\n\n{body}"


async def _search_lines(
    search: Any, query: SearchQuery, *, page_size: int
) -> tuple[list[str], int]:
    response = await search.search(query.model_dump(mode="json"), page=1, page_size=page_size)
    lines = [_hit_line(hit.title, hit.permalink) for hit in response.results]
    return lines, response.total


async def _count_inbox_files(directory: Any, folder: str) -> int:
    """Count markdown files directly under ``folder`` (default ``inbox/``)."""
    total = 0
    page = 1
    while True:
        listing = await directory.list(
            folder if folder.startswith("/") else f"/{folder}",
            depth=1,
            file_name_glob="*.md",
            page=page,
            page_size=200,
        )
        for node in listing.nodes:
            if node.type == "file":
                total += 1
        if not listing.has_more:
            return total
        page += 1


async def build_brief(
    *,
    project: str | None,
    project_id: str | None,
    token_budget: int | None,
    context: Context | None,
    conversation_id: str | None = None,
) -> str:
    """Assemble the brief for one project. Shared by the tool and the resource."""
    config = ConfigManager().config
    budget = token_budget if token_budget is not None else config.brief_token_budget
    if budget < 1:
        raise ValueError("token_budget must be >= 1")

    async with get_project_client(project, context=context, project_id=project_id) as (
        client,
        active_project,
    ):
        from basic_memory.mcp.clients import DirectoryClient, KnowledgeClient, SearchClient

        conversation = (conversation_id or "").strip() or None
        pending_delivery: tuple[JsonBriefDeliveryStore, BriefDeliveryState, str] | None = None
        if conversation is not None:
            delivery_store = JsonBriefDeliveryStore(project_delivery_path(active_project.home))
            delivery_state = delivery_store.load()
            # Trigger: this conversation already received a brief inside the window.
            # Why: get_brief is how a resumed Cursor chat refreshes, and a repeat
            # inside brief_refresh_hours should not rebuild or reset the clock.
            # Outcome: a one-line notice, with the previous timestamp left in place.
            if not should_deliver_brief(
                delivery_state.last_delivered_at(conversation),
                refresh_hours=float(config.brief_refresh_hours),
                force=False,
            ):
                hours = f"{float(config.brief_refresh_hours):g}"
                return (
                    "Brief already delivered for this conversation within the last "
                    f"{hours} hours.\n"
                )
            pending_delivery = (delivery_store, delivery_state, conversation)

        knowledge = KnowledgeClient(client, active_project.external_id)
        search = SearchClient(client, active_project.external_id)
        directory = DirectoryClient(client, active_project.external_id)
        now = datetime.now(timezone.utc)
        decision_after = (now - timedelta(days=config.brief_decision_days)).isoformat()

        sections: list[BriefSection] = []

        state = await _optional_excerpt(knowledge, config.brief_state_note)
        if state:
            sections.append(BriefSection("Current state", state))

        decision_lines, _decision_total = await _search_lines(
            search,
            SearchQuery(
                note_types=["decision"],
                after_date=decision_after,
                entity_types=[SearchItemType.ENTITY],
                retrieval_mode=SearchRetrievalMode.FTS,
            ),
            page_size=_LIST_LIMIT,
        )
        sections.append(
            BriefSection(
                f"Open decisions ({config.brief_decision_days}d)",
                "\n".join(decision_lines) or "(none)",
            )
        )

        inbox_count = await _count_inbox_files(directory, config.brief_inbox_folder)
        sections.append(
            BriefSection("Inbox", f"{inbox_count} note(s) in {config.brief_inbox_folder}/")
        )

        # Trigger: brief_include_profile is on.
        # Why: the profile excerpt is personal. It stays out unless the owner opts in.
        # Outcome: the Profile section is omitted when the flag is false.
        if config.brief_include_profile:
            profile = await _optional_excerpt(knowledge, config.brief_profile_note)
            if profile:
                sections.append(BriefSection("Profile", profile))

        rendered = render_brief(sections, token_budget=budget)
        text = f"{rendered}\nproject: {active_project.name}\n"
        if pending_delivery is not None:
            store, state, conversation_key = pending_delivery
            state.record(conversation_key, datetime.now(timezone.utc))
            store.save(state)
        return text


@mcp.tool(
    title="Get Brief",
    description=(
        "Return a short briefing: current state, recent decision titles, an inbox "
        "file count, and the profile note when those notes exist and "
        "brief_include_profile is on. Call this at the start of a chat that has no "
        "brief in context. Cursor does not inject a brief when an old chat is "
        "resumed. Pass conversation_id when you have one: a repeat within "
        "brief_refresh_hours (default 6) returns a short already-delivered line."
    ),
    tags={"navigation", "notes"},
    annotations={
        "title": "Get Brief",
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
    },
)
async def get_brief(
    project: str | None = None,
    project_id: str | None = None,
    token_budget: int | None = None,
    conversation_id: str | None = None,
    context: Context | None = None,
) -> str:
    """Bounded project briefing for hookless clients.

    Includes the current-state note when present (`brief_state_note`, default
    `project/state`), decision note titles from the last `brief_decision_days`,
    a count of markdown files in `brief_inbox_folder` (default `inbox/`), and
    the profile note excerpt when present (`brief_profile_note`, default
    `me/profile`) if `brief_include_profile` is true (off by default). Missing
    profile or state notes are omitted with no error text.
    `token_budget` overrides `brief_token_budget` (default 1500). Roughly four
    characters per token; later sections are dropped first.

    `conversation_id`, when set, is recorded in the project's brief-delivery
    store. A later call for the same id inside `brief_refresh_hours` (default
    6) does not rebuild the brief.
    """
    return await build_brief(
        project=project,
        project_id=project_id,
        token_budget=token_budget,
        context=context,
        conversation_id=conversation_id,
    )
