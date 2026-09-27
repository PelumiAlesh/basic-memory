"""Tests for ``bm setup`` (fork first-run bootstrap)."""

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from basic_memory.cli.commands.setup_cmd import (
    merge_mcp_servers,
    mcp_stdio_entry,
    resolve_cli_binary,
    routing_document,
    run_setup,
    run_uninstall,
)
from basic_memory.cli.main import app as cli_app
from basic_memory.config import ConfigManager
from basic_memory.setup import manifest, paths, tokens
from basic_memory.setup.hooks import SETUP_OWNED_HOOK_RE

runner = CliRunner()


@pytest.fixture
def bm_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "config-home"
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(home))
    monkeypatch.setenv("BASIC_MEMORY_HOME", str(home / "data"))
    monkeypatch.setattr("basic_memory.setup.paths.Path.home", lambda: tmp_path)
    return home


def test_routing_document_pins_primary_project() -> None:
    assert routing_document("main") == {"primaryProject": "main"}


def test_merge_mcp_servers_preserves_other_entries() -> None:
    existing = {"mcpServers": {"other": {"command": "echo"}}}
    merged = merge_mcp_servers(existing, mcp_stdio_entry(Path("/tmp/bm")))
    assert merged["mcpServers"]["other"]["command"] == "echo"
    assert merged["mcpServers"]["basic-memory"]["command"] == "/tmp/bm"


def test_run_setup_idempotent_tokens(
    bm_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "basic-memory"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr("basic_memory.setup.launchd.install_launchd", lambda **_: None)
    monkeypatch.setattr("basic_memory.cli.commands.hook._hook_launcher", lambda: str(binary))

    from basic_memory.cli.commands import setup_cmd as setup_mod

    plan = setup_mod.SetupPlan(
        project_name="main",
        project_path=tmp_path / "vault",
        binary=binary,
        mcp_port=8123,
        config_dir=bm_home,
        session_capture=False,
        install_launchd=False,
    )
    run_setup(plan, dry_run=False)
    first = tokens.load_tokens(bm_home)
    assert first is not None
    run_setup(plan, dry_run=False)
    second = tokens.load_tokens(bm_home)
    assert second == first

    token_path = tokens.token_file_path(bm_home)
    assert token_path.is_file()
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_run_setup_writes_client_configs(
    bm_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "bm"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr("basic_memory.setup.launchd.install_launchd", lambda **_: None)
    monkeypatch.setattr("basic_memory.cli.commands.hook._hook_launcher", lambda: str(binary))

    from basic_memory.cli.commands import setup_cmd as setup_mod

    plan = setup_mod.SetupPlan(
        project_name="research",
        project_path=tmp_path / "vault",
        binary=binary,
        mcp_port=9000,
        config_dir=bm_home,
        session_capture=True,
        install_launchd=False,
    )
    run_setup(plan, dry_run=False)

    assert json.loads(paths.cursor_routing_path().read_text()) == {"primaryProject": "research"}
    mcp = json.loads(paths.cursor_mcp_path().read_text())
    assert mcp["mcpServers"]["basic-memory"]["command"] == str(binary)
    desktop = json.loads(paths.claude_desktop_mcp_path().read_text())
    assert desktop["mcpServers"]["basic-memory"]["args"] == ["mcp"]

    hooks = json.loads(paths.cursor_hooks_path().read_text())
    command = hooks["hooks"]["sessionStart"][0]["command"]
    assert SETUP_OWNED_HOOK_RE.search(command)

    config = ConfigManager().config
    assert config.auto_update is False
    assert config.session_capture_enabled is True
    assert config.projects["research"].path == str((tmp_path / "vault").resolve())


def test_uninstall_restores_backed_up_file(
    bm_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "bm"
    binary.write_text("", encoding="utf-8")
    cursor_mcp = paths.cursor_mcp_path()
    cursor_mcp.parent.mkdir(parents=True, exist_ok=True)
    cursor_mcp.write_text('{"mcpServers":{"other":{"command":"keep"}}}\n', encoding="utf-8")

    monkeypatch.setattr("basic_memory.setup.launchd.install_launchd", lambda **_: None)
    monkeypatch.setattr("basic_memory.setup.launchd.uninstall_launchd", lambda *a, **k: None)
    monkeypatch.setattr("basic_memory.cli.commands.hook._hook_launcher", lambda: str(binary))

    from basic_memory.cli.commands import setup_cmd as setup_mod

    plan = setup_mod.SetupPlan(
        project_name="main",
        project_path=tmp_path / "vault",
        binary=binary,
        mcp_port=8000,
        config_dir=bm_home,
        session_capture=False,
        install_launchd=False,
    )
    run_setup(plan, dry_run=False)
    assert "basic-memory" in json.loads(cursor_mcp.read_text())["mcpServers"]

    run_uninstall()
    restored = json.loads(cursor_mcp.read_text())
    assert restored == {"mcpServers": {"other": {"command": "keep"}}}
    assert not manifest.manifest_path(bm_home).exists()


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
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "dry run" in result.stdout
    assert not (tmp_path / "vault").exists()


def test_resolve_cli_binary_requires_existing_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        resolve_cli_binary(tmp_path / "missing")
