"""Tests for ``bm setup`` (fork first-run bootstrap)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from basic_memory.cli.commands.setup_cmd import (
    apply_fork_config,
    build_setup_plan,
    merge_mcp_servers,
    mcp_stdio_entry,
    resolve_cli_binary,
    routing_document,
    run_setup,
)
from basic_memory.cli.main import app as cli_app
from basic_memory.config import ConfigManager

runner = CliRunner()


@pytest.fixture
def bm_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "config-home"
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(home))
    monkeypatch.setenv("BASIC_MEMORY_HOME", str(home / "data"))
    return home


def test_routing_document_pins_primary_project() -> None:
    assert routing_document("main") == {"primaryProject": "main"}


def test_merge_mcp_servers_preserves_other_entries() -> None:
    existing = {"mcpServers": {"other": {"command": "echo"}}}
    merged = merge_mcp_servers(existing, mcp_stdio_entry(Path("/tmp/bm")))
    assert merged["mcpServers"]["other"]["command"] == "echo"
    assert merged["mcpServers"]["basic-memory"]["command"] == "/tmp/bm"


def test_apply_fork_config_writes_project_and_tokens(bm_home: Path, tmp_path: Path) -> None:
    binary = tmp_path / "basic-memory"
    binary.write_text("", encoding="utf-8")
    manager = ConfigManager()
    plan = build_setup_plan(
        project_name="research",
        project_path=tmp_path / "vault",
        binary=binary,
        mcp_port=8123,
        config_dir=manager.config_dir,
    )
    apply_fork_config(manager, plan, dry_run=False)

    config = ConfigManager().config
    assert config.auto_update is False
    assert config.verify_writes is True
    assert config.mcp_http_token == plan.shared_token
    assert config.mcp_http_client_tokens["cursor"] == plan.client_tokens["cursor"]
    assert config.projects["research"].path == str((tmp_path / "vault").resolve())
    assert config.default_project == "research"


def test_run_setup_writes_routing_and_mcp(
    bm_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "bm"
    binary.write_text("", encoding="utf-8")
    cursor_dir = tmp_path / ".cursor"
    codex_dir = tmp_path / ".codex"
    monkeypatch.setattr("basic_memory.cli.commands.setup_cmd.Path.home", lambda: tmp_path)

    plan = run_setup(
        project_name="research",
        project_path=tmp_path / "vault",
        binary=binary,
        mcp_port=9000,
        install_hooks=False,
        dry_run=False,
    )

    assert json.loads(plan.cursor_routing.read_text()) == {"primaryProject": "research"}
    assert json.loads(plan.codex_routing.read_text()) == {"primaryProject": "research"}
    mcp = json.loads(plan.cursor_mcp.read_text())
    assert mcp["mcpServers"]["basic-memory"]["args"] == ["mcp"]


def test_setup_cli_dry_run(bm_home: Path, tmp_path: Path) -> None:
    binary = tmp_path / "basic-memory"
    binary.write_text("", encoding="utf-8")
    result = runner.invoke(
        cli_app,
        [
            "setup",
            "--path",
            str(tmp_path / "vault"),
            "--binary",
            str(binary),
            "--dry-run",
            "--no-install-hooks",
        ],
    )
    assert result.exit_code == 0
    assert "dry run" in result.stdout
    assert not (tmp_path / "vault").exists()


def test_resolve_cli_binary_requires_existing_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        resolve_cli_binary(tmp_path / "missing")
