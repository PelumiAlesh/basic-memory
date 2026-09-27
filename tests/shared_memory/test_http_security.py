"""Bearer-token parsing and the HTTP bind default. Tokens must not appear in errors."""

import pytest
from loguru import logger

from basic_memory.config_models import BasicMemoryConfig
from basic_memory.shared_memory.http_security import (
    HttpAuthRejected,
    client_for_authorization,
    host_origin_settings,
    http_auth_config,
    is_loopback_host,
    protected_resource_metadata,
    resolve_bind_host,
    www_authenticate,
)


def _config(**overrides: object) -> BasicMemoryConfig:
    return BasicMemoryConfig.model_validate(overrides)


def test_bind_host_defaults_to_loopback() -> None:
    assert resolve_bind_host(None, "127.0.0.1") == "127.0.0.1"
    assert resolve_bind_host("", "127.0.0.1") == "127.0.0.1"
    assert resolve_bind_host("0.0.0.0", "127.0.0.1") == "0.0.0.0"
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")


def test_single_token_maps_to_named_client() -> None:
    auth = http_auth_config(_config(mcp_http_token="secret-token", mcp_http_token_client="chatgpt"))
    assert client_for_authorization("Bearer secret-token", auth) == "chatgpt"
    assert auth.required


def test_client_token_pairs_and_rejection_do_not_echo_the_secret() -> None:
    secret = "super-secret-value"
    auth = http_auth_config(_config(mcp_http_clients=f"cursor:{secret},claude-code:other"))
    assert client_for_authorization(f"Bearer {secret}", auth) == "cursor"
    assert client_for_authorization("Bearer other", auth) == "claude-code"
    with pytest.raises(HttpAuthRejected):
        client_for_authorization("Bearer wrong", auth)
    with pytest.raises(HttpAuthRejected):
        client_for_authorization(None, auth)
    with pytest.raises(ValueError, match="client:token pairs") as raised:
        http_auth_config(_config(mcp_http_clients=secret))
    assert secret not in str(raised.value)


def test_host_origin_guard_is_strict_with_allow_lists() -> None:
    settings = host_origin_settings(
        _config(
            mcp_http_allowed_hosts="memory.example.com, tunnel.example.net",
            mcp_http_allowed_origins="https://chat.openai.com",
        )
    )
    assert settings["host_origin_protection"] is True
    assert settings["allowed_hosts"] == ["memory.example.com", "tunnel.example.net"]
    assert settings["allowed_origins"] == ["https://chat.openai.com"]
    default = host_origin_settings(_config())
    assert default["host_origin_protection"] is True
    assert default["allowed_hosts"] == []
    assert default["allowed_origins"] == []


@pytest.mark.asyncio
async def test_fastmcp_guard_rejects_unlisted_host_and_origin() -> None:
    from fastmcp.server.http import HostOriginGuardMiddleware

    statuses: list[int] = []

    async def app(scope, receive, send):  # noqa: ANN001
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    settings = host_origin_settings(_config(mcp_http_allowed_hosts="memory.example.com"))
    guard = HostOriginGuardMiddleware(
        app,
        allowed_hosts=settings["allowed_hosts"],  # type: ignore[arg-type]
        allowed_origins=settings["allowed_origins"],  # type: ignore[arg-type]
        mode="strict",
    )

    def scope_for(host: bytes, origin: bytes | None = None) -> dict:
        headers = [(b"host", host)]
        if origin is not None:
            headers.append((b"origin", origin))
        return {
            "type": "http",
            "path": "/mcp",
            "headers": headers,
            "server": ("127.0.0.1", 8000),
            "scheme": "http",
        }

    await guard(scope_for(b"127.0.0.1:8000"), receive, send)
    await guard(scope_for(b"memory.example.com"), receive, send)
    await guard(scope_for(b"evil.example.org"), receive, send)
    await guard(scope_for(b"127.0.0.1:8000", b"https://attacker.example"), receive, send)
    assert statuses == [200, 200, 421, 403]


def test_open_when_no_token_configured() -> None:
    auth = http_auth_config(_config())
    assert client_for_authorization(None, auth) is None
    assert not auth.required


def test_www_authenticate_has_no_token() -> None:
    secret = "super-secret-value"
    auth = http_auth_config(_config(mcp_http_token=secret, mcp_oauth_issuer="https://auth.example"))
    challenge = www_authenticate(auth)
    assert secret not in challenge
    assert "resource_metadata" in challenge
    metadata = protected_resource_metadata(
        resource="http://127.0.0.1:8000/mcp", issuer=auth.oauth_issuer
    )
    assert metadata["authorization_servers"] == ["https://auth.example"]
    assert secret not in str(metadata)


def test_middleware_rejects_without_logging_the_token() -> None:
    from basic_memory.mcp.http_auth import BearerAuthMiddleware

    secret = "middleware-secret-token"
    captured: list[str] = []
    sink = logger.add(lambda message: captured.append(str(message)), level="INFO")

    async def app(scope, receive, send):  # noqa: ANN001
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    import asyncio

    middleware = BearerAuthMiddleware(app)

    async def run(header: bytes | None) -> int:
        status = {"code": 0}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]

        headers = []
        if header is not None:
            headers.append((b"authorization", header))
        scope = {"type": "http", "path": "/mcp", "headers": headers}
        # Config is read live. Set the token via the model the manager returns
        # by patching http_auth_config's caller through the environment.
        await middleware(scope, receive, send)
        return status["code"]

    import os

    import basic_memory.config as config_module

    os.environ["BASIC_MEMORY_MCP_HTTP_TOKEN"] = secret
    config_module._CONFIG_CACHE = None
    try:
        code = asyncio.run(run(b"Bearer not-the-token"))
        assert code == 401
        code_ok = asyncio.run(run(f"Bearer {secret}".encode()))
        assert code_ok == 200
    finally:
        logger.remove(sink)
        os.environ.pop("BASIC_MEMORY_MCP_HTTP_TOKEN", None)
        config_module._CONFIG_CACHE = None

    logged = "\n".join(captured)
    assert secret not in logged
    assert "not-the-token" not in logged
