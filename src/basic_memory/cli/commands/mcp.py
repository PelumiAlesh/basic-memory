"""MCP server command with streamable HTTP transport."""

import os
import threading
from typing import TYPE_CHECKING, Any, Optional

import typer
from loguru import logger

from basic_memory.cli.app import app
from basic_memory.cli.auto_update import AutoUpdateStatus, run_auto_update
from basic_memory.config import ConfigManager, init_mcp_logging

if TYPE_CHECKING:  # pragma: no cover
    from starlette.middleware import Middleware


class _DeferredMcpServer:
    def run(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        from basic_memory.mcp.server import mcp as live_mcp_server

        live_mcp_server.run(*args, **kwargs)


# Keep module-level attribute for tests/monkeypatching while deferring heavy import.
mcp_server = _DeferredMcpServer()


@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="Transport type: stdio, streamable-http, or sse"),
    host: Optional[str] = typer.Option(
        None,
        help=(
            "Host for HTTP transports (default: mcp_http_host, 127.0.0.1). "
            "Every HTTP request needs a bearer token, whatever the host."
        ),
    ),
    port: int = typer.Option(8000, help="Port for HTTP transports"),
    path: str = typer.Option("/mcp", help="Path prefix for streamable-http transport"),
    project: Optional[str] = typer.Option(None, help="Restrict MCP server to single project"),
):  # pragma: no cover
    """Run the MCP server with configurable transport options.

    This command starts an MCP server using one of three transport options:

    - stdio: Standard I/O (good for local usage)
    - streamable-http: Recommended for web deployments
    - sse: Server-Sent Events (for compatibility with existing clients)

    The HTTP transports refuse to start without a bearer token (mcp_http_token or
    mcp_http_client_tokens) and bind to loopback unless told otherwise.

    Initialization, file indexing, and cleanup are handled by the MCP server's lifespan.

    Note: This command is available regardless of cloud mode setting.
    Users who have cloud mode enabled can still use local MCP for Claude Code
    and Claude Desktop while using cloud MCP for web and mobile access.
    """
    # --- HTTP authentication ---
    # Trigger: an HTTP or SSE transport, which listens on a TCP port.
    # Why: any process that reaches the port could otherwise read and rewrite notes.
    # Outcome: no usable bearer token, no server (and no side effects); the message
    #          says how to set one.
    http_middleware: list[Middleware] = []
    if transport in ("streamable-http", "sse"):
        from basic_memory.shared_memory.http_auth import mcp_http_middleware

        try:
            http_middleware = mcp_http_middleware(ConfigManager().config)
        except ValueError as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(1)

    # --- Routing setup ---
    # Trigger: MCP server command invocation.
    # Why: HTTP/SSE transports serve as local API endpoints and must never
    #      route through cloud. Stdio is a client-facing protocol that
    #      should honor per-project routing (local or cloud).
    # Outcome: HTTP/SSE get explicit local override; stdio passes through
    #          whatever env vars are already set (honoring external overrides)
    #          and defaults to per-project routing resolution.
    if transport in ("streamable-http", "sse"):
        os.environ["BASIC_MEMORY_FORCE_LOCAL"] = "true"
        os.environ.pop("BASIC_MEMORY_FORCE_CLOUD", None)
        os.environ["BASIC_MEMORY_EXPLICIT_ROUTING"] = "true"
    # stdio: no env var manipulation — per-project routing applies by default,
    # and externally-set env vars (e.g. BASIC_MEMORY_FORCE_CLOUD) are honored.

    # Import mcp tools/prompts to register them with the server
    import basic_memory.mcp.tools  # noqa: F401  # pragma: no cover
    import basic_memory.mcp.prompts  # noqa: F401  # pragma: no cover
    import basic_memory.mcp.resources  # noqa: F401  # pragma: no cover

    # Initialize logging for MCP (file only, stdout breaks protocol)
    init_mcp_logging()

    # Validate and set project constraint if specified
    if project:
        config_manager = ConfigManager()
        project_name, _ = config_manager.get_project(project)
        if not project_name:
            typer.echo(f"No project found named: {project}", err=True)
            raise typer.Exit(1)

        # Set env var with validated project name
        os.environ["BASIC_MEMORY_MCP_PROJECT"] = project_name
        logger.info(f"MCP server constrained to project: {project_name}")

    def _run_background_auto_update() -> None:
        result = run_auto_update(force=False, check_only=False, silent=True)
        if result.restart_recommended:
            logger.info(
                "A newer Basic Memory version was installed and will apply on next restart."
            )
        elif result.status == AutoUpdateStatus.FAILED and result.error:
            logger.warning(f"MCP background auto-update failed: {result.error}")

    # Trigger: stdio transport corresponds to local user installs.
    # Why: server transports (HTTP/SSE) run in managed environments where
    # package-manager self-upgrades are inappropriate.
    # Outcome: background auto-update runs only for local stdio MCP sessions.
    if transport == "stdio":
        threading.Thread(target=_run_background_auto_update, daemon=True).start()

    # Trigger: MCP server startup on the Postgres backend, before the transport
    # creates its event loop.
    # Why: the watcher/lifespan path runs startup migrations + engine.dispose() on
    # asyncpg, which races stdlib asyncio teardown and crashes the container loop
    # (#831/#877). uvloop's C scheduler structurally avoids that race and must own
    # the loop policy before the loop is created. No-op for SQLite.
    # Outcome: `basic-memory mcp` on Postgres runs on uvloop. (The CLI callback also
    # installs it; this keeps the server startup seam explicit and self-contained.)
    from basic_memory.db import maybe_install_uvloop

    maybe_install_uvloop(ConfigManager().config)

    # Run the MCP server (blocks)
    # Lifespan handles: initialization, migrations, file indexing, cleanup
    logger.info(f"Starting MCP server with {transport.upper()} transport")

    if transport == "stdio":
        mcp_server.run(
            transport=transport,
        )
    elif transport == "streamable-http" or transport == "sse":
        mcp_server.run(
            transport=transport,
            host=host or ConfigManager().config.mcp_http_host,
            port=port,
            path=path,
            log_level="INFO",
            middleware=http_middleware,
            # The strict Host/Origin guard is already in http_middleware.
            host_origin_protection=False,
        )
