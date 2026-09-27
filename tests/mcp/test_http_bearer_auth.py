"""The bearer gate on a real streamable-HTTP server.

uvicorn serves the FastMCP app with the middleware `basic-memory mcp` installs, so
each request goes through real HTTP parsing: who gets in, what a wrong Host or
Origin gets, and which app a write is attributed to.
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import mcp.types as mt
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

import basic_memory.mcp.tools  # noqa: F401 - registers the tools on the server
from basic_memory.config import BasicMemoryConfig
from basic_memory.file_utils import parse_frontmatter
from basic_memory.index.note_content_materialization import drain_pending_materializations
from basic_memory.mcp.server import mcp
from basic_memory.shared_memory.http_auth import mcp_http_middleware

SHARED_TOKEN = "shared-token-for-http-tests"
CURSOR_TOKEN = "cursor-token-for-http-tests"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@asynccontextmanager
async def _serving(**settings: Any) -> AsyncIterator[str]:
    config = BasicMemoryConfig(
        projects={},
        mcp_http_token=SHARED_TOKEN,
        mcp_http_client_tokens={"cursor": CURSOR_TOKEN},
        **settings,
    )
    app = mcp.http_app(
        path="/mcp", middleware=mcp_http_middleware(config), host_origin_protection=False
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="warning"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            if serving.done():
                raise RuntimeError("uvicorn stopped before it started")
            await asyncio.sleep(0.01)
        host, port = listener.getsockname()
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        await serving
        listener.close()


async def _initialize(base_url: str, headers: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient() as http:
        return await http.post(f"{base_url}/mcp", json=INITIALIZE, headers=MCP_HEADERS | headers)


async def _raw_status(base_url: str, request_target: str) -> int:
    """Send a request line verbatim; httpx would normalize the `..` away first."""
    host, port = base_url.removeprefix("http://").split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    writer.write(
        (
            f"GET {request_target} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Authorization: Bearer {SHARED_TOKEN}\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
    )
    await writer.drain()
    status_line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return int(status_line.split()[1])


async def _write_as(base_url: str, token: str, app_name: str, project: str, title: str) -> None:
    transport = StreamableHttpTransport(f"{base_url}/mcp", auth=token)
    async with Client(
        transport, client_info=mt.Implementation(name=app_name, version="1.0.0")
    ) as session:
        await session.call_tool(
            "write_note",
            {"project": project, "title": title, "directory": "notes", "content": "From HTTP."},
        )


async def _frontmatter(project_path: str, relative_path: str) -> dict[str, Any]:
    await drain_pending_materializations()
    return parse_frontmatter((Path(project_path) / relative_path).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_only_a_configured_token_opens_the_mcp_endpoint(app, test_project) -> None:
    async with _serving() as base_url:
        missing = await _initialize(base_url, {})
        wrong = await _initialize(base_url, {"Authorization": "Bearer not-the-token-at-all"})
        shared = await _initialize(base_url, {"Authorization": f"Bearer {SHARED_TOKEN}"})
        per_app = await _initialize(base_url, {"Authorization": f"Bearer {CURSOR_TOKEN}"})

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == 'Bearer realm="basic-memory"'
    assert wrong.status_code == 401
    assert shared.status_code == 200
    assert per_app.status_code == 200


@pytest.mark.asyncio
async def test_discovery_path_is_the_only_open_door(app, test_project) -> None:
    async with _serving() as base_url:
        async with httpx.AsyncClient() as http:
            discovery = await http.get(f"{base_url}/.well-known/oauth-protected-resource")
            suffixed = await http.get(f"{base_url}/.well-known/oauth-protected-resource/mcp")
        climbing = await _raw_status(base_url, "/.well-known/../mcp")
        encoded = await _raw_status(base_url, "/.well-known/%2e%2e/mcp")

    # No OAuth is served, so the open door leads nowhere; a probing client falls back.
    assert discovery.status_code == 404
    assert suffixed.status_code == 401
    assert climbing == 400
    assert encoded == 400


@pytest.mark.asyncio
async def test_host_and_origin_are_checked_strictly_even_with_a_token(app, test_project) -> None:
    authorized = {"Authorization": f"Bearer {SHARED_TOKEN}"}
    async with _serving(mcp_http_allowed_hosts=["memory.lan"]) as base_url:
        foreign_host = await _initialize(base_url, authorized | {"Host": "evil.example"})
        allowed_host = await _initialize(base_url, authorized | {"Host": "memory.lan"})
        foreign_origin = await _initialize(
            base_url, authorized | {"Origin": "https://evil.example"}
        )

    assert foreign_host.status_code == 421
    assert allowed_host.status_code == 200
    assert foreign_origin.status_code == 403


@pytest.mark.asyncio
async def test_per_app_token_names_the_writer_over_client_info(app, test_project) -> None:
    async with _serving() as base_url:
        await _write_as(base_url, CURSOR_TOKEN, "claude-code", test_project.name, "Token Note")

    frontmatter = await _frontmatter(test_project.path, "notes/Token Note.md")

    assert frontmatter["bm_source_client"] == "cursor"
    assert frontmatter["bm_created_by_client"] == "cursor"


@pytest.mark.asyncio
async def test_shared_token_leaves_attribution_to_client_info(app, test_project) -> None:
    async with _serving() as base_url:
        await _write_as(base_url, SHARED_TOKEN, "claude-code", test_project.name, "Shared Note")

    frontmatter = await _frontmatter(test_project.path, "notes/Shared Note.md")

    assert frontmatter["bm_source_client"] == "claude-code"
