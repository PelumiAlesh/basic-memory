"""`basic-memory mcp` over HTTP: no bearer token, no server; with one, loopback and the gate."""

import os
from collections.abc import Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

import basic_memory.cli.commands.mcp as mcp_command
from basic_memory.cli.auto_update import AutoUpdateResult, AutoUpdateStatus, InstallSource
from basic_memory.cli.main import app as cli_app
from basic_memory.shared_memory.http_auth import BearerTokenGate

runner = CliRunner()
TOKEN = "cli-test-token-8b2e4d6f"
ROUTING_VARIABLES = (
    "BASIC_MEMORY_FORCE_LOCAL",
    "BASIC_MEMORY_FORCE_CLOUD",
    "BASIC_MEMORY_EXPLICIT_ROUTING",
)


@pytest.fixture
def server_runs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Record each server start instead of serving, and undo the command's env writes."""
    runs: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp_command.mcp_server, "run", lambda **kwargs: runs.append(kwargs))
    monkeypatch.setattr(mcp_command, "init_mcp_logging", lambda: None)
    monkeypatch.setattr(
        mcp_command,
        "run_auto_update",
        lambda **kwargs: AutoUpdateResult(
            status=AutoUpdateStatus.SKIPPED,
            source=InstallSource.UNKNOWN,
            checked=False,
            update_available=False,
            updated=False,
        ),
    )
    for setting in ("TOKEN", "CLIENT_TOKENS", "HOST"):
        monkeypatch.delenv(f"BASIC_MEMORY_MCP_HTTP_{setting}", raising=False)
    saved = {name: os.environ.get(name) for name in ROUTING_VARIABLES}
    yield runs
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_http_transport_without_a_token_refuses_to_start(
    server_runs: list[dict[str, Any]], transport: str
) -> None:
    result = runner.invoke(cli_app, ["mcp", "--transport", transport])

    assert result.exit_code == 1
    assert "need a bearer token" in result.output
    assert "BASIC_MEMORY_MCP_HTTP_TOKEN" in result.output
    assert server_runs == []
    # Refusing is side-effect free: routing is only forced for a server that starts.
    assert os.environ.get("BASIC_MEMORY_EXPLICIT_ROUTING") != "true"


def test_a_short_token_is_refused_without_being_echoed(
    server_runs: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BASIC_MEMORY_MCP_HTTP_TOKEN", "tok-Q7")

    result = runner.invoke(cli_app, ["mcp", "--transport", "streamable-http"])

    assert result.exit_code == 1
    assert "mcp_http_token is shorter than 16 characters" in result.output
    assert "tok-Q7" not in result.output
    assert server_runs == []


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_http_transport_binds_loopback_behind_the_gate(
    server_runs: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    monkeypatch.setenv("BASIC_MEMORY_MCP_HTTP_TOKEN", TOKEN)

    result = runner.invoke(cli_app, ["mcp", "--transport", transport])

    assert result.exit_code == 0, result.output
    [run] = server_runs
    assert run["host"] == "127.0.0.1"
    assert run["host_origin_protection"] is False
    gate, guard = run["middleware"]
    assert gate.cls is BearerTokenGate
    assert guard.kwargs["mode"] == "strict"
    assert TOKEN not in result.output


def test_host_comes_from_the_flag_then_the_setting(
    server_runs: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BASIC_MEMORY_MCP_HTTP_TOKEN", TOKEN)
    monkeypatch.setenv("BASIC_MEMORY_MCP_HTTP_HOST", "::1")

    from_setting = runner.invoke(cli_app, ["mcp", "--transport", "streamable-http"])
    from_flag = runner.invoke(
        cli_app, ["mcp", "--transport", "streamable-http", "--host", "0.0.0.0"]
    )

    assert from_setting.exit_code == 0, from_setting.output
    assert from_flag.exit_code == 0, from_flag.output
    assert [run["host"] for run in server_runs] == ["::1", "0.0.0.0"]


def test_stdio_needs_no_token(server_runs: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli_app, ["mcp"])

    assert result.exit_code == 0, result.output
    assert server_runs == [{"transport": "stdio"}]
