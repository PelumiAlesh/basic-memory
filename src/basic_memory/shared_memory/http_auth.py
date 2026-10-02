"""Bearer-token gate for the MCP HTTP and SSE transports.

An HTTP transport listens on a TCP port, so without a gate any local process (and,
bound wider than loopback, any host that reaches the port) could read and rewrite
the notes. The gate applies these rules in order:

1. A path with a `..` segment is refused before routing, however it is encoded.
2. The exact OAuth discovery path answers without a token. There is no OAuth here,
   so the answer is a plain 404, which tells a probing MCP client to use the
   Authorization header it was configured with.
3. Every other HTTP request and every WebSocket needs `Authorization: Bearer <token>`
   matching a configured token. With no token configured nothing gets through, and
   `basic-memory mcp` refuses to start (see `mcp_http_middleware`).

FastMCP's Host/Origin guard runs after the gate in strict mode, for SSE as well as
streamable HTTP. Stdio never passes through here. Tokens are compared in constant
time and are never logged or echoed.
"""

import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import unquote

from fastmcp.server.http import HostOriginGuardMiddleware
from loguru import logger
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from basic_memory.config_models import BasicMemoryConfig
from basic_memory.shared_memory.clients import BEARER_CLIENT_SCOPE_KEY, client_slug

OAUTH_PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource"
MIN_TOKEN_LENGTH = 16
MISSING_TOKEN_MESSAGE = (
    "The MCP HTTP and SSE transports need a bearer token, and none is configured.\n"
    "Set BASIC_MEMORY_MCP_HTTP_TOKEN (or mcp_http_token in config.json) to a random "
    f"string of at least {MIN_TOKEN_LENGTH} characters, for example the output of\n"
    "  python3 -c 'import secrets; print(secrets.token_urlsafe(32))'\n"
    "and have each app send `Authorization: Bearer <token>`."
)
WWW_AUTHENTICATE = 'Bearer realm="basic-memory"'

# RFC 6455 section 7.4.1: close code for a message that violates the server's policy.
_WEBSOCKET_POLICY_VIOLATION = 1008
_SEGMENT_SEPARATOR = re.compile(r"[/\\]")
# Each round undoes one layer of percent-encoding. A path that is still changing after
# this many rounds is refused instead of decoded further.
_MAX_DECODE_ROUNDS = 4


@dataclass(frozen=True, slots=True)
class BearerToken:
    """One accepted token. `client` is None for the shared token, which names no app."""

    secret: bytes
    client: str | None


def configured_bearer_tokens(config: BasicMemoryConfig) -> tuple[BearerToken, ...]:
    """The tokens the gate accepts. A ValueError names the bad setting, never the token."""
    tokens: list[BearerToken] = []
    if config.mcp_http_token and config.mcp_http_token.strip():
        tokens.append(_bearer_token("mcp_http_token", None, config.mcp_http_token))
    for name, token in config.mcp_http_client_tokens.items():
        client = client_slug(name)
        if client is None:
            raise ValueError(
                f"mcp_http_client_tokens: client name {name!r} has no letters or digits."
            )
        tokens.append(_bearer_token(f"mcp_http_client_tokens[{name!r}]", client, token))

    # One token for two apps would attribute both apps' writes to whichever is listed.
    if len({token.secret for token in tokens}) < len(tokens):
        raise ValueError(
            "The same bearer token is configured more than once. Give each app its own."
        )
    return tuple(tokens)


def _bearer_token(setting: str, client: str | None, token: str) -> BearerToken:
    secret = token.strip()
    if len(secret) < MIN_TOKEN_LENGTH:
        raise ValueError(f"{setting} is shorter than {MIN_TOKEN_LENGTH} characters.")
    return BearerToken(secret=secret.encode(), client=client)


def mcp_http_middleware(config: BasicMemoryConfig) -> list[Middleware]:
    """The gate, then the strict Host/Origin guard. ValueError when no token is configured."""
    tokens = configured_bearer_tokens(config)
    if not tokens:
        raise ValueError(MISSING_TOKEN_MESSAGE)
    return [
        Middleware(BearerTokenGate, tokens=tokens),
        # FastMCP adds this guard to streamable HTTP only. Listing it here covers SSE
        # too, so the server must run with host_origin_protection=False to avoid a copy.
        Middleware(
            HostOriginGuardMiddleware,
            allowed_hosts=config.mcp_http_allowed_hosts,
            allowed_origins=config.mcp_http_allowed_origins,
            mode="strict",
        ),
    ]


class BearerTokenGate:
    """ASGI middleware that admits a request only with a configured bearer token."""

    def __init__(self, app: ASGIApp, tokens: Sequence[BearerToken]) -> None:
        self.app = app
        self.tokens = tuple(tokens)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] not in ("http", "websocket"):
            raise ValueError(f"Unsupported ASGI scope type: {scope['type']!r}")

        if _has_parent_segment(scope):
            logger.info("Refused MCP HTTP request with a '..' path segment")
            await _refuse(scope, receive, send, status_code=400, error="invalid_path")
            return

        if scope["type"] == "http" and _is_discovery_request(scope):
            await self.app(scope, receive, send)
            return

        token = self._matching_token(scope)
        if token is None:
            logger.info(f"Refused MCP HTTP request without a valid bearer token: {scope['path']}")
            await _refuse(scope, receive, send, status_code=401, error="unauthorized")
            return

        scope[BEARER_CLIENT_SCOPE_KEY] = token.client
        await self.app(scope, receive, send)

    def _matching_token(self, scope: Scope) -> BearerToken | None:
        presented = _presented_token(scope)
        if presented is None:
            return None
        # Compare against every token so the timing does not reveal which one matched.
        matched = None
        for token in self.tokens:
            if secrets.compare_digest(presented, token.secret):
                matched = token
        return matched


def _presented_token(scope: Scope) -> bytes | None:
    values = [value for name, value in scope["headers"] if name == b"authorization"]
    # Two Authorization headers are ambiguous, so exactly one is required.
    if len(values) != 1:
        return None
    scheme, _, credentials = values[0].partition(b" ")
    if scheme.lower() != b"bearer":
        return None
    return credentials.strip() or None


def _is_discovery_request(scope: Scope) -> bool:
    """Exactly the OAuth discovery path, with no prefix, suffix, or re-encoding of it."""
    raw_path = scope.get("raw_path")
    return scope["path"] == OAUTH_PROTECTED_RESOURCE_PATH and (
        raw_path is None or raw_path == OAUTH_PROTECTED_RESOURCE_PATH.encode()
    )


def _has_parent_segment(scope: Scope) -> bool:
    """Whether the decoded or raw path has a `..` segment at any encoding depth."""
    paths = [scope["path"]]
    if raw_path := scope.get("raw_path"):
        paths.append(raw_path.decode("latin-1"))
    return any(_climbs(path) for path in paths)


def _climbs(path: str) -> bool:
    for _ in range(_MAX_DECODE_ROUNDS):
        if ".." in _SEGMENT_SEPARATOR.split(path):
            return True
        decoded = unquote(path)
        if decoded == path:
            return False
        path = decoded
    return True


async def _refuse(
    scope: Scope, receive: Receive, send: Send, *, status_code: int, error: str
) -> None:
    if scope["type"] == "websocket":
        # Closing before accepting makes the server answer the handshake with 403.
        await send({"type": "websocket.close", "code": _WEBSOCKET_POLICY_VIOLATION})
        return
    headers = {"WWW-Authenticate": WWW_AUTHENTICATE} if status_code == 401 else None
    response = JSONResponse({"error": error}, status_code=status_code, headers=headers)
    await response(scope, receive, send)
