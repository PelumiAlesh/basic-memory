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
from basic_memory.shared_memory.briefing import BriefSection, render_brief
from basic_memory.shared_memory.request_client import remember_mcp_client

_EXCERPT_CHARS = 800
_LIST_LIMIT = 8


def _hit_line(title: str | None, permalink: str | None) -> str:
    name = title or permalink or "(untitled)"
    if permalink:
        return f"- {name} (`{permalink}`)"
    return f"- {name}"


async def _excerpt(knowledge: Any, identifier: str) -> str | None:
    try:
        entity_id = await knowledge.resolve_entity(identifier, strict=True)
        entity = await knowledge.get_entity(entity_id)
    except ToolError:
        return None
    body = (entity.content or "").strip()
    if len(body) > _EXCERPT_CHARS:
        body = body[:_EXCERPT_CHARS].rstrip() + "…"
    return f"**{entity.title}**\n\n{body}" if body else f"**{entity.title}**"


async def _search_lines(
    search: Any, query: SearchQuery, *, page_size: int
) -> tuple[list[str], int]:
    response = await search.search(query.model_dump(mode="json"), page=1, page_size=page_size)
    lines = [_hit_line(hit.title, hit.permalink) for hit in response.results]
    return lines, response.total


async def build_brief(
    *,
    project: str | None,
    project_id: str | None,
    token_budget: int | None,
    context: Context | None,
) -> str:
    """Assemble the brief for one project. Shared by the tool and the resource."""
    await remember_mcp_client(context)
    config = ConfigManager().config
    budget = token_budget if token_budget is not None else config.brief_token_budget
    if budget < 1:
        raise ValueError("token_budget must be >= 1")

    async with get_project_client(project, context=context, project_id=project_id) as (
        client,
        active_project,
    ):
        from basic_memory.mcp.clients import KnowledgeClient, SearchClient

        knowledge = KnowledgeClient(client, active_project.external_id)
        search = SearchClient(client, active_project.external_id)
        now = datetime.now(timezone.utc)
        decision_after = (now - timedelta(days=config.brief_decision_days)).isoformat()
        recent_after = (now - timedelta(days=7)).isoformat()

        sections: list[BriefSection] = []
        profile = await _excerpt(knowledge, config.brief_profile_note)
        sections.append(
            BriefSection(
                "Profile",
                profile or f"(no note at `{config.brief_profile_note}`)",
            )
        )
        state = await _excerpt(knowledge, config.brief_state_note)
        sections.append(
            BriefSection(
                "Current state",
                state or f"(no note at `{config.brief_state_note}`)",
            )
        )

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
                f"Decisions ({config.brief_decision_days}d)",
                "\n".join(decision_lines) or "(none)",
            )
        )

        question_lines, question_total = await _search_lines(
            search,
            SearchQuery(
                note_types=["question"],
                entity_types=[SearchItemType.ENTITY],
                retrieval_mode=SearchRetrievalMode.FTS,
            ),
            page_size=_LIST_LIMIT,
        )
        _inbox_lines, inbox_total = await _search_lines(
            search,
            SearchQuery(
                status="unreviewed",
                entity_types=[SearchItemType.ENTITY],
                retrieval_mode=SearchRetrievalMode.FTS,
            ),
            page_size=1,
        )
        question_body = "\n".join(question_lines) or "(none)"
        sections.append(
            BriefSection(
                "Open questions and inbox",
                f"questions: {question_total}\nunreviewed: {inbox_total}\n{question_body}",
            )
        )

        recent_lines, _recent_total = await _search_lines(
            search,
            SearchQuery(
                after_date=recent_after,
                entity_types=[SearchItemType.ENTITY],
                retrieval_mode=SearchRetrievalMode.FTS,
            ),
            page_size=_LIST_LIMIT,
        )
        sections.append(BriefSection("Recently updated", "\n".join(recent_lines) or "(none)"))
        rendered = render_brief(sections, token_budget=budget)
        return f"{rendered}\nproject: {active_project.name}\n"


@mcp.tool(
    annotations={
        "title": "Get Brief",
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
    }
)
async def get_brief(
    project: str | None = None,
    project_id: str | None = None,
    token_budget: int | None = None,
    context: Context | None = None,
) -> str:
    """Return a short briefing for clients that do not run session hooks.

    Includes the profile note (`brief_profile_note`, default `me/profile`),
    the current-state note (`brief_state_note`, default `project/state`),
    decision notes from the last `brief_decision_days`, open question and
    unreviewed counts, and notes updated in the last seven days. `token_budget`
    overrides `brief_token_budget` (default 1500). Roughly four characters per
    token; later sections are dropped first.
    """
    return await build_brief(
        project=project,
        project_id=project_id,
        token_budget=token_budget,
        context=context,
    )
