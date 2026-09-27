"""The bearer gate at the raw ASGI level: which requests reach the app, and what is logged.

The scopes here are built by hand, so the tests control `path` and `raw_path`
separately, which is how a percent-encoded `..` reaches the app.
"""

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from loguru import logger
from starlette.types import Message, Receive, Scope, Send

from basic_memory.config import BasicMemoryConfig
from basic_memory.shared_memory.clients import BEARER_CLIENT_SCOPE_KEY
from basic_memory.shared_memory.http_auth import (
    MISSING_TOKEN_MESSAGE,
    OAUTH_PROTECTED_RESOURCE_PATH,
    WWW_AUTHENTICATE,
    BearerTokenGate,
    configured_bearer_tokens,
    mcp_http_middleware,
)

SHARED_TOKEN = "shared-token-5f0c1b7e2a"
CURSOR_TOKEN = "cursor-token-9d3a4c6b1e"


def _config(**settings: Any) -> BasicMemoryConfig:
    return BasicMemoryConfig(projects={}, **settings)


def _gate_config() -> BasicMemoryConfig:
    return _config(mcp_http_token=SHARED_TOKEN, mcp_http_client_tokens={"Cursor": CURSOR_TOKEN})


class _App:
    """Downstream app that records each scope it is handed."""

    def __init__(self) -> None:
        self.scopes: list[Scope] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.scopes.append(scope)
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def _scope(
    path: str,
    *,
    raw_path: bytes | None = None,
    authorization: list[str] | None = None,
    scope_type: str = "http",
) -> Scope:
    headers = [(b"host", b"127.0.0.1:8000")]
    headers += [(b"authorization", value.encode()) for value in authorization or []]
    return {
        "type": scope_type,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws" if scope_type == "websocket" else "http",
        "method": "GET",
        "path": path,
        "raw_path": raw_path if raw_path is not None else path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 50123),
    }


def _bearer(token: str) -> list[str]:
    return [f"Bearer {token}"]


async def _send_through(gate: BearerTokenGate, scope: Scope) -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        if scope["type"] == "websocket":
            return {"type": "websocket.connect"}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await gate(scope, receive, send)
    return sent


def _status(sent: list[Message]) -> int:
    return next(message["status"] for message in sent if message["type"] == "http.response.start")


def _header(sent: list[Message], name: bytes) -> bytes | None:
    start = next(message for message in sent if message["type"] == "http.response.start")
    return dict(start["headers"]).get(name)


@pytest.fixture(autouse=True)
def no_token_settings_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for setting in (
        "MCP_HTTP_HOST",
        "MCP_HTTP_TOKEN",
        "MCP_HTTP_CLIENT_TOKENS",
        "MCP_HTTP_ALLOWED_HOSTS",
        "MCP_HTTP_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(f"BASIC_MEMORY_{setting}", raising=False)


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def gate(app: _App) -> BearerTokenGate:
    return BearerTokenGate(app, configured_bearer_tokens(_gate_config()))


@pytest.fixture
def log_lines() -> Iterator[list[str]]:
    lines: list[str] = []
    handler_id = logger.add(lambda message: lines.append(str(message)), level="DEBUG")
    yield lines
    logger.remove(handler_id)


# --- Paths that climb out ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "raw_path"),
    [
        ("/.well-known/../mcp", b"/.well-known/../mcp"),
        ("/.well-known/../mcp", b"/.well-known/%2e%2e/mcp"),
        ("/.well-known/../mcp", b"/.well-known/%2E%2E/mcp"),
        ("/.well-known/%2e%2e/mcp", b"/.well-known/%252e%252e/mcp"),
        ("/.well-known/../mcp", b"/.well-known%2f..%2fmcp"),
        ("/.well-known\\..\\mcp", b"/.well-known\\..\\mcp"),
        ("/mcp/..", b"/mcp/.."),
        ("/.well-known/oauth-protected-resource/../../mcp", None),
    ],
)
async def test_parent_segments_are_refused_before_routing_even_with_a_token(
    gate: BearerTokenGate, app: _App, path: str, raw_path: bytes | None
) -> None:
    scope = _scope(path, raw_path=raw_path, authorization=_bearer(SHARED_TOKEN))

    sent = await _send_through(gate, scope)

    assert _status(sent) == 400
    assert app.scopes == []


@pytest.mark.asyncio
async def test_a_path_still_encoded_after_the_decode_limit_is_refused(
    gate: BearerTokenGate, app: _App
) -> None:
    # "%41" is a harmless "A", but after four more layers of encoding the gate
    # cannot tell what it hides without decoding further, so it refuses.
    segment = "%41"
    for _ in range(4):
        segment = quote(segment, safe="")

    sent = await _send_through(
        gate, _scope(f"/notes/{segment}", authorization=_bearer(SHARED_TOKEN))
    )

    assert _status(sent) == 400
    assert app.scopes == []


@pytest.mark.asyncio
async def test_dots_inside_a_segment_are_not_a_parent_segment(
    gate: BearerTokenGate, app: _App
) -> None:
    sent = await _send_through(gate, _scope("/mcp/notes..v2", authorization=_bearer(SHARED_TOKEN)))

    assert _status(sent) == 200
    assert len(app.scopes) == 1


# --- The one unauthenticated path ---


@pytest.mark.asyncio
async def test_exact_discovery_path_needs_no_token(gate: BearerTokenGate, app: _App) -> None:
    sent = await _send_through(gate, _scope(OAUTH_PROTECTED_RESOURCE_PATH))

    assert _status(sent) == 200
    assert len(app.scopes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "raw_path"),
    [
        (f"{OAUTH_PROTECTED_RESOURCE_PATH}/mcp", None),
        (f"{OAUTH_PROTECTED_RESOURCE_PATH}/", None),
        ("/.well-known/openid-configuration", None),
        ("/.well-known/oauth-authorization-server", None),
        (OAUTH_PROTECTED_RESOURCE_PATH, b"/.well-known/oauth-protected-resourc%65"),
    ],
)
async def test_every_other_well_known_path_needs_a_token(
    gate: BearerTokenGate, app: _App, path: str, raw_path: bytes | None
) -> None:
    sent = await _send_through(gate, _scope(path, raw_path=raw_path))

    assert _status(sent) == 401
    assert app.scopes == []


@pytest.mark.asyncio
async def test_discovery_path_is_not_a_websocket_bypass(gate: BearerTokenGate, app: _App) -> None:
    sent = await _send_through(gate, _scope(OAUTH_PROTECTED_RESOURCE_PATH, scope_type="websocket"))

    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert app.scopes == []


# --- Tokens ---


@pytest.mark.asyncio
async def test_a_missing_token_gets_401_with_a_bearer_challenge(
    gate: BearerTokenGate, app: _App
) -> None:
    sent = await _send_through(gate, _scope("/mcp"))

    assert _status(sent) == 401
    assert _header(sent, b"www-authenticate") == WWW_AUTHENTICATE.encode()
    assert app.scopes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    [
        _bearer("not-a-configured-token"),
        _bearer(SHARED_TOKEN[:-1]),
        _bearer(SHARED_TOKEN + "x"),
        [f"Basic {SHARED_TOKEN}"],
        [SHARED_TOKEN],
        ["Bearer "],
        _bearer(SHARED_TOKEN) + _bearer(SHARED_TOKEN),
    ],
)
async def test_anything_but_one_matching_bearer_token_gets_401(
    gate: BearerTokenGate, app: _App, authorization: list[str]
) -> None:
    sent = await _send_through(gate, _scope("/mcp", authorization=authorization))

    assert _status(sent) == 401
    assert app.scopes == []


@pytest.mark.asyncio
async def test_shared_token_is_admitted_without_naming_an_app(
    gate: BearerTokenGate, app: _App
) -> None:
    sent = await _send_through(gate, _scope("/mcp", authorization=[f"bearer {SHARED_TOKEN}"]))

    assert _status(sent) == 200
    assert app.scopes[0][BEARER_CLIENT_SCOPE_KEY] is None


@pytest.mark.asyncio
async def test_per_app_token_is_admitted_and_names_its_app(
    gate: BearerTokenGate, app: _App
) -> None:
    sent = await _send_through(gate, _scope("/mcp", authorization=_bearer(CURSOR_TOKEN)))

    assert _status(sent) == 200
    assert app.scopes[0][BEARER_CLIENT_SCOPE_KEY] == "cursor"


@pytest.mark.asyncio
async def test_with_no_token_configured_every_request_is_refused(app: _App) -> None:
    gate = BearerTokenGate(app, configured_bearer_tokens(_config()))

    for authorization in (None, _bearer(SHARED_TOKEN), ["Bearer "]):
        sent = await _send_through(gate, _scope("/mcp", authorization=authorization))
        assert _status(sent) == 401
    assert app.scopes == []


# --- WebSocket, lifespan, and anything else ---


@pytest.mark.asyncio
async def test_websocket_without_a_token_is_closed_before_the_app(
    gate: BearerTokenGate, app: _App
) -> None:
    sent = await _send_through(gate, _scope("/mcp", scope_type="websocket"))

    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert app.scopes == []


@pytest.mark.asyncio
async def test_websocket_with_a_parent_segment_is_closed(gate: BearerTokenGate, app: _App) -> None:
    scope = _scope(
        "/.well-known/../mcp", scope_type="websocket", authorization=_bearer(SHARED_TOKEN)
    )

    sent = await _send_through(gate, scope)

    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert app.scopes == []


@pytest.mark.asyncio
async def test_websocket_with_a_token_reaches_the_app(gate: BearerTokenGate, app: _App) -> None:
    await _send_through(
        gate, _scope("/mcp", scope_type="websocket", authorization=_bearer(CURSOR_TOKEN))
    )

    assert app.scopes[0][BEARER_CLIENT_SCOPE_KEY] == "cursor"


@pytest.mark.asyncio
async def test_lifespan_passes_through_untouched(gate: BearerTokenGate, app: _App) -> None:
    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

    await _send_through(gate, scope)

    assert app.scopes == [scope]


@pytest.mark.asyncio
async def test_unknown_scope_types_are_rejected(gate: BearerTokenGate, app: _App) -> None:
    with pytest.raises(ValueError, match="Unsupported ASGI scope type"):
        await _send_through(gate, {"type": "webtransport", "path": "/mcp", "headers": []})
    assert app.scopes == []


# --- Logging ---


@pytest.mark.asyncio
async def test_no_token_ever_reaches_the_log(gate: BearerTokenGate, log_lines: list[str]) -> None:
    wrong_token = "wrong-token-3c8e1f0a7b"
    for authorization in (
        _bearer(wrong_token),
        _bearer(SHARED_TOKEN),
        _bearer(CURSOR_TOKEN),
        [f"Basic {CURSOR_TOKEN}"],
        _bearer(CURSOR_TOKEN) + _bearer(wrong_token),
    ):
        await _send_through(gate, _scope("/mcp", authorization=authorization))
        await _send_through(gate, _scope("/.well-known/../mcp", authorization=authorization))

    assert any("Refused MCP HTTP request" in line for line in log_lines)
    for token in (wrong_token, SHARED_TOKEN, CURSOR_TOKEN):
        assert not any(token in line for line in log_lines)


# --- Configuration ---


def test_client_names_are_slugged_and_the_shared_token_names_no_app() -> None:
    config = _config(
        mcp_http_token=f"  {SHARED_TOKEN}  ",
        mcp_http_client_tokens={"Claude Code": CURSOR_TOKEN, "grok-bot": "grok-token-7a1d0c3e9f"},
    )

    tokens = configured_bearer_tokens(config)

    assert [(token.client, token.secret) for token in tokens] == [
        (None, SHARED_TOKEN.encode()),
        ("claude-code", CURSOR_TOKEN.encode()),
        ("grok", b"grok-token-7a1d0c3e9f"),
    ]


def test_blank_shared_token_counts_as_unset() -> None:
    assert configured_bearer_tokens(_config(mcp_http_token="   ")) == ()


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"mcp_http_token": "tok-XYZ"}, "mcp_http_token is shorter than 16 characters"),
        (
            {"mcp_http_client_tokens": {"cursor": "tok-XYZ"}},
            "mcp_http_client_tokens['cursor'] is shorter than 16 characters",
        ),
        (
            {"mcp_http_client_tokens": {"!!!": CURSOR_TOKEN}},
            "client name '!!!' has no letters or digits",
        ),
        (
            {"mcp_http_token": CURSOR_TOKEN, "mcp_http_client_tokens": {"cursor": CURSOR_TOKEN}},
            "configured more than once",
        ),
        (
            {"mcp_http_client_tokens": {"cursor": CURSOR_TOKEN, "chatgpt": f" {CURSOR_TOKEN}"}},
            "configured more than once",
        ),
    ],
)
def test_bad_token_settings_fail_without_echoing_the_token(
    settings: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)) as raised:
        configured_bearer_tokens(_config(**settings))

    assert "tok-XYZ" not in str(raised.value)
    assert CURSOR_TOKEN not in str(raised.value)


def test_middleware_refuses_to_build_without_a_token() -> None:
    with pytest.raises(ValueError) as raised:
        mcp_http_middleware(_config())

    assert str(raised.value) == MISSING_TOKEN_MESSAGE
    assert "BASIC_MEMORY_MCP_HTTP_TOKEN" in MISSING_TOKEN_MESSAGE


def test_middleware_is_the_gate_then_a_strict_host_origin_guard() -> None:
    config = _config(
        mcp_http_token=SHARED_TOKEN,
        mcp_http_allowed_hosts=["memory.lan"],
        mcp_http_allowed_origins=["https://app.example"],
    )

    gate, guard = mcp_http_middleware(config)

    assert gate.cls is BearerTokenGate
    assert [token.secret for token in gate.kwargs["tokens"]] == [SHARED_TOKEN.encode()]
    assert guard.kwargs == {
        "allowed_hosts": ["memory.lan"],
        "allowed_origins": ["https://app.example"],
        "mode": "strict",
    }


def test_token_settings_load_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASIC_MEMORY_MCP_HTTP_TOKEN", SHARED_TOKEN)
    monkeypatch.setenv("BASIC_MEMORY_MCP_HTTP_CLIENT_TOKENS", f'{{"cursor": "{CURSOR_TOKEN}"}}')
    monkeypatch.setenv("BASIC_MEMORY_MCP_HTTP_ALLOWED_HOSTS", '["memory.lan"]')

    config = BasicMemoryConfig(projects={})

    assert config.mcp_http_host == "127.0.0.1"
    assert config.mcp_http_allowed_hosts == ["memory.lan"]
    assert [token.client for token in configured_bearer_tokens(config)] == [None, "cursor"]
