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
    entry = merged["mcpServers"]["basic-memory"]
    assert entry["command"] == "/tmp/bm"
    assert entry["env"] == {"BASIC_MEMORY_NO_PROMOS": "1"}


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
    hooks = json.loads(paths.cursor_hooks_path().read_text())
    assert len(hooks["hooks"]["sessionStart"]) == 1
    assert "stop" not in hooks["hooks"]

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
    assert "beforeSubmitPrompt" not in hooks["hooks"]
    assert "stop" in hooks["hooks"]

    claude_mcp = json.loads(paths.claude_code_mcp_path().read_text())
    assert claude_mcp["mcpServers"]["basic-memory"]["command"] == str(binary)
    claude_settings = json.loads(paths.claude_code_settings_path().read_text())
    assert "mcpServers" not in claude_settings
    assert "UserPromptSubmit" in claude_settings["hooks"]
    assert "Stop" in claude_settings["hooks"]

    config = ConfigManager().config
    assert config.auto_update is False
    assert config.logfire_enabled is False
    assert config.logfire_send_to_logfire is False
    assert config.cloud_promo_opt_out is True
    assert config.session_capture_enabled is True
    assert config.projects["research"].path == str((tmp_path / "vault").resolve())
    for mcp_path in (
        paths.cursor_mcp_path(),
        paths.claude_desktop_mcp_path(),
        paths.claude_code_mcp_path(),
    ):
        entry = json.loads(mcp_path.read_text())["mcpServers"]["basic-memory"]
        assert entry["env"]["BASIC_MEMORY_NO_PROMOS"] == "1"
    rule = paths.cursor_user_rule_path().read_text(encoding="utf-8")
    assert "alwaysApply: true" in rule
    assert "get_brief" in rule
    assert "6 hours" in rule
    assert "not guaranteed" in rule
    plist = (bm_home / "basic-memory-mcp.plist").read_text(encoding="utf-8")
    assert "BASIC_MEMORY_NO_PROMOS" in plist
    assert "<string>1</string>" in plist


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
    assert "not guaranteed" in result.stdout
    assert "get_brief" in result.stdout
    assert not (tmp_path / "vault").exists()
    assert not paths.cursor_user_rule_path().exists()


def test_uninstall_restores_created_and_existing_files(
    bm_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "bm"
    binary.write_text("", encoding="utf-8")
    settings = paths.claude_code_settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    original_settings = '{"permissions":{"allow":["Bash"]},"hooks":{}}\n'
    settings.write_text(original_settings, encoding="utf-8")
    hooks_path = paths.cursor_hooks_path()
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    original_hooks = '{"version":1,"hooks":{"sessionStart":[{"command":"echo user-hook"}]}}\n'
    hooks_path.write_text(original_hooks, encoding="utf-8")

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
    assert paths.claude_code_mcp_path().is_file()
    assert "basic-memory" in json.loads(paths.claude_code_mcp_path().read_text())["mcpServers"]
    assert "echo user-hook" in hooks_path.read_text(encoding="utf-8")
    assert "fork-cursor-session-start" in hooks_path.read_text(encoding="utf-8")

    run_uninstall()
    assert settings.read_text(encoding="utf-8") == original_settings
    assert hooks_path.read_text(encoding="utf-8") == original_hooks
    assert not paths.claude_code_mcp_path().exists()
    assert not paths.cursor_user_rule_path().exists()
    assert not (bm_home / "basic-memory-mcp.plist").exists()
    assert not (bm_home / "config.json").exists()


def test_claude_user_prompt_emits_additional_context(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from basic_memory.setup.fork_hooks import run_claude_user_prompt

    monkeypatch.setattr(
        "basic_memory.setup.fork_hooks._read_stdin_json",
        lambda: {"session_id": "s1", "prompt": "secret prompt"},
    )
    monkeypatch.setattr("basic_memory.setup.fork_hooks._should_deliver", lambda _cid: True)
    monkeypatch.setattr(
        "basic_memory.setup.fork_hooks._render_brief_text", lambda: "# Brief\n\nhello\n"
    )
    monkeypatch.setattr("basic_memory.setup.fork_hooks._maybe_record_delivery", lambda _cid: None)
    monkeypatch.setattr("basic_memory.setup.fork_hooks._log_hook_metadata", lambda *a, **k: None)

    run_claude_user_prompt()
    output = capsys.readouterr().out
    payload = json.loads(output)
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == "UserPromptSubmit"
    assert "hello" in specific["additionalContext"]
    assert "additionalContext" not in payload
    assert "secret prompt" not in output


def test_hook_brief_uses_shared_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    from basic_memory.setup.fork_hooks import _render_brief_text

    monkeypatch.setattr(
        "basic_memory.cli.commands.brief.render_brief_for_project",
        lambda name: f"brief:{name}",
    )
    monkeypatch.setattr("basic_memory.setup.fork_hooks._primary_project", lambda: "main")
    assert _render_brief_text() == "brief:main"


def test_uninstall_restores_cursor_rule_and_logfire(
    bm_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "bm"
    binary.write_text("", encoding="utf-8")
    rule = paths.cursor_user_rule_path()
    rule.parent.mkdir(parents=True, exist_ok=True)
    rule.write_text("owner rule\n", encoding="utf-8")

    monkeypatch.setattr("basic_memory.setup.launchd.install_launchd", lambda **_: None)
    monkeypatch.setattr("basic_memory.setup.launchd.uninstall_launchd", lambda *a, **k: None)
    monkeypatch.setattr("basic_memory.cli.commands.hook._hook_launcher", lambda: str(binary))

    manager = ConfigManager()
    config = manager.load_config()
    config.logfire_enabled = True
    config.logfire_send_to_logfire = True
    config.cloud_promo_opt_out = False
    manager.save_config(config)

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
    saved = ConfigManager().load_config()
    assert saved.logfire_enabled is False
    assert saved.logfire_send_to_logfire is False
    assert saved.cloud_promo_opt_out is True
    assert "get_brief" in rule.read_text(encoding="utf-8")

    run_uninstall()
    assert rule.read_text(encoding="utf-8") == "owner rule\n"
    restored = ConfigManager().load_config()
    assert restored.logfire_enabled is True
    assert restored.logfire_send_to_logfire is True
    assert restored.cloud_promo_opt_out is False


def test_resolve_cli_binary_requires_existing_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        resolve_cli_binary(tmp_path / "missing")
