"""ASGI bearer gate for the MCP HTTP and SSE transports.

Stdio does not use this. When no token is configured the gate allows the
request, which is safe only because the bind address defaults to loopback.
"""

from __future__ import annotations

import json

from loguru import logger
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from basic_memory.config import ConfigManager
from basic_memory.mcp.server import mcp
from basic_memory.shared_memory.http_security import (
    HttpAuthRejected,
    authorization_header,
    client_for_authorization,
    http_auth_config,
    is_loopback_host,
    is_public_http_path,
    protected_resource_metadata,
    www_authenticate,
)
from basic_memory.shared_memory.request_client import bind_token_client, reset_token_client


class BearerAuthMiddleware:
    """Reject HTTP requests whose bearer token does not match a configured one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        # Trigger: OAuth discovery, before any token check.
        # Why: a client has to read the metadata to learn where to authenticate.
        # Outcome: well-known paths skip the bearer gate.
        if is_public_http_path(path):
            await self.app(scope, receive, send)
            return

        auth = http_auth_config(ConfigManager().config)
        if not auth.required:
            await self.app(scope, receive, send)
            return

        try:
            client = client_for_authorization(
                authorization_header(list(scope.get("headers") or [])),
                auth,
            )
        except HttpAuthRejected:
            # The header value is not logged. A mismatch and a missing header
            # look the same on purpose.
            logger.info("MCP HTTP bearer authentication rejected")
            body = b'{"error":"unauthorized"}'
            challenge = www_authenticate(auth).encode("ascii")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", challenge),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        token = bind_token_client(client)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_token_client(token)


def http_middleware() -> list[Middleware]:
    return [Middleware(BearerAuthMiddleware)]


def warn_if_http_exposed(host: str) -> None:
    """Log when a non-loopback bind has no bearer token. The host is not a secret."""
    auth = http_auth_config(ConfigManager().config)
    if is_loopback_host(host) or auth.required:
        return
    logger.warning(
        "MCP HTTP is bound to {} without a bearer token. "
        "Set BASIC_MEMORY_MCP_HTTP_TOKEN or bind 127.0.0.1.",
        host,
    )


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(request: Request) -> Response:
    """Advertise bearer auth and, when configured, an external authorization server."""
    auth = http_auth_config(ConfigManager().config)
    resource = str(request.base_url).rstrip("/") + "/mcp"
    payload = protected_resource_metadata(resource=resource, issuer=auth.oauth_issuer)
    return JSONResponse(payload)


def unauthorized_body() -> bytes:
    """Stable JSON body. Kept here so tests can assert it without importing ASGI."""
    return json.dumps({"error": "unauthorized"}).encode("utf-8")
