"""Shared MCP process claim and conflict messaging."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from basic_memory.shared_memory.process_guard import (
    SharedServerConflict,
    acquire_shared_claim,
    living_claim,
    read_claim,
    refuse_if_shared_server_running,
    release_shared_claim,
)


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "bm"
    home.mkdir()
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(home))
    return home


def test_acquire_and_release_shared_claim(config_home: Path) -> None:
    lock = acquire_shared_claim(
        transport="streamable-http",
        host="127.0.0.1",
        port=8000,
        path="/mcp",
    )
    claim = living_claim()
    assert claim is not None
    assert claim.pid == os.getpid()
    assert claim.url == "http://127.0.0.1:8000/mcp"
    assert (config_home / "mcp-shared.json").is_file()
    release_shared_claim(lock)
    assert read_claim() is None


def test_refuse_stdio_when_another_pid_holds_claim(config_home: Path) -> None:
    # pid 1 is init/systemd on typical Linux CI images and stays alive.
    (config_home / "mcp-shared.json").write_text(
        json.dumps(
            {
                "pid": 1,
                "transport": "streamable-http",
                "host": "127.0.0.1",
                "port": 8000,
                "path": "/mcp",
                "started": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SharedServerConflict) as excinfo:
        refuse_if_shared_server_running(transport="stdio")
    message = str(excinfo.value)
    assert "already running" in message
    assert "127.0.0.1:8000" in message
    assert "bearer token" in message


def test_stale_claim_is_ignored(config_home: Path) -> None:
    (config_home / "mcp-shared.json").write_text(
        json.dumps(
            {
                "pid": 2_000_000_000,
                "transport": "streamable-http",
                "host": "127.0.0.1",
                "port": 8000,
                "path": "/mcp",
                "started": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    assert living_claim() is None
    refuse_if_shared_server_running(transport="stdio")
