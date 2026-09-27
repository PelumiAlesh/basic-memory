"""memory://_brief/{project} — the same text as get_brief, for clients that read resources."""

from fastmcp import Context

from basic_memory.mcp.server import mcp
from basic_memory.mcp.tools.brief import build_brief


@mcp.resource(
    uri="memory://_brief/{project}",
    name="brief",
    description=(
        "A bounded project briefing: profile, current state, recent decisions, "
        "open questions, and recently updated notes. Same content as get_brief."
    ),
)
async def project_brief(project: str, context: Context | None = None) -> str:
    return await build_brief(
        project=project,
        project_id=None,
        token_budget=None,
        context=context,
    )
