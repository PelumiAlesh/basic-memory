"""list_clients: which MCP clients have used this shared server process."""

from __future__ import annotations

from basic_memory.mcp.server import mcp
from basic_memory.shared_memory.client_registry import client_registry, format_client_report
from basic_memory.shared_memory.process_guard import living_claim, read_claim


@mcp.tool(
    title="List Clients",
    tags={"diagnostics", "shared"},
    annotations={
        "title": "List Clients",
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
    },
    output_schema=None,
)
def list_clients() -> str:
    """List MCP clients seen by this process and the shared-server claim, if any.

    Reports client slugs from bearer-token identity or clientInfo, last-seen
    times, and the last note each client wrote. Never includes tokens.
    """
    lines = [format_client_report(client_registry().snapshot()).rstrip(), ""]
    claim = living_claim() or read_claim()
    if claim is not None:
        alive = living_claim() is not None
        lines.extend(
            [
                "# Shared server claim",
                f"- pid: {claim.pid}",
                f"- transport: {claim.transport}",
                f"- url: {claim.url}",
                f"- started: {claim.started}",
                f"- alive: {alive}",
            ]
        )
    else:
        lines.append("# Shared server claim")
        lines.append("- none (mcp_shared_server is off, or this process has not claimed it)")
    return "\n".join(lines) + "\n"
