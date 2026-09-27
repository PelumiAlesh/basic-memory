"""Localhost binding and bearer auth for the MCP HTTP transports.

The token is read from config or the environment and compared with
`secrets.compare_digest`. It is never put in a log line, an error body, or
a WWW-Authenticate challenge.

OAuth 2.1 is not implemented inside the note server. When
`mcp_oauth_issuer` is set, the protected-resource metadata points clients at
that external authorization server. A tunnel (cloudflared, Tailscale) plus
this bearer check is the supported way to reach ChatGPT. See
docs/SHARED_MEMORY.md.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass

from basic_memory.config_models import BasicMemoryConfig

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

_WELL_KNOWN_PREFIX = "/.well-known/"


class HttpAuthRejected(Exception):
    """The request presented a bearer token that does not match, or none at all."""


@dataclass(frozen=True, slots=True)
class HttpAuthConfig:
    """Tokens keyed by client slug. Empty means HTTP auth is not required."""

    tokens_by_client: Mapping[str, str]
    oauth_issuer: str | None

    @property
    def required(self) -> bool:
        return bool(self.tokens_by_client)


def is_loopback_host(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


def resolve_bind_host(cli_host: str | None, configured_host: str) -> str:
    """CLI --host wins. Otherwise the config value, which defaults to 127.0.0.1."""
    if cli_host is not None and cli_host.strip():
        return cli_host.strip()
    configured = configured_host.strip()
    return configured or "127.0.0.1"


def allow_list(raw: str) -> list[str]:
    """Split a comma-separated config value; blanks drop out."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def host_origin_settings(config: BasicMemoryConfig) -> dict[str, object]:
    """Keyword arguments for FastMCP's Host/Origin guard.

    Protection is always on (`strict`): the Host header must be loopback, the
    bound address, or a configured allow-list entry, and a browser Origin must
    be same-origin, loopback, or allow-listed. That is what keeps a DNS-rebinding
    page or a stray reverse proxy from reaching the server (upstream #1578).
    """
    return {
        "host_origin_protection": True,
        "allowed_hosts": allow_list(config.mcp_http_allowed_hosts),
        "allowed_origins": allow_list(config.mcp_http_allowed_origins),
    }


def _pairs(raw: str) -> dict[str, str]:
    """Parse `client:token,client:token` without echoing either side on failure."""
    tokens: dict[str, str] = {}
    if not raw.strip():
        return tokens
    for piece in raw.split(","):
        item = piece.strip()
        if not item:
            continue
        client, separator, token = item.partition(":")
        # Trigger: a pair is missing the colon, the client slug, or the token.
        # Why: a message that included the text would write the secret into
        # the process output the first time config failed to parse.
        # Outcome: a fixed sentence, no values.
        if not separator or not client.strip() or not token:
            raise ValueError("mcp_http_clients must be comma-separated client:token pairs")
        tokens[client.strip().lower()] = token
    return tokens


def http_auth_config(config: BasicMemoryConfig) -> HttpAuthConfig:
    """Collect configured bearer tokens. Blank tokens are ignored."""
    tokens: dict[str, str] = {}
    single = (config.mcp_http_token or "").strip()
    if single:
        client = (config.mcp_http_token_client or "http").strip().lower() or "http"
        tokens[client] = single
    tokens.update(_pairs(config.mcp_http_clients))
    issuer = (config.mcp_oauth_issuer or "").strip() or None
    return HttpAuthConfig(tokens_by_client=tokens, oauth_issuer=issuer)


def client_for_authorization(header: str | None, auth: HttpAuthConfig) -> str | None:
    """Return the client slug for a matching bearer token.

    When no tokens are configured this returns None and the caller allows the
    request (localhost is the default bind). When tokens are configured, a
    missing or unknown token raises HttpAuthRejected.
    """
    if not auth.required:
        return None
    if header is None:
        raise HttpAuthRejected()
    scheme, separator, presented = header.strip().partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not presented or " " in presented:
        raise HttpAuthRejected()
    for client, token in auth.tokens_by_client.items():
        if len(presented) != len(token):
            continue
        if secrets.compare_digest(presented, token):
            return client
    raise HttpAuthRejected()


def authorization_header(scope_headers: list[tuple[bytes, bytes]]) -> str | None:
    for key, value in scope_headers:
        if key.lower() == b"authorization":
            return value.decode("latin-1")
    return None


def www_authenticate(auth: HttpAuthConfig) -> str:
    """Challenge header. Never includes a token or the issuer secret."""
    if auth.oauth_issuer:
        return (
            'Bearer realm="basic-memory", resource_metadata="/.well-known/oauth-protected-resource"'
        )
    return 'Bearer realm="basic-memory"'


def protected_resource_metadata(*, resource: str, issuer: str | None) -> dict[str, object]:
    """OAuth 2.1 protected-resource metadata (RFC 9728), issuer optional.

    `authorization_servers` is present only when an external issuer is
    configured. This process does not mint tokens or validate JWTs.
    """
    payload: dict[str, object] = {
        "resource": resource,
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["notes.read", "notes.write"],
    }
    if issuer:
        payload["authorization_servers"] = [issuer]
    return payload


def is_public_http_path(path: str) -> bool:
    """Discovery documents stay reachable so a client can learn the issuer."""
    return path == "/.well-known/oauth-protected-resource" or path.startswith(_WELL_KNOWN_PREFIX)
