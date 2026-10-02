"""Hook fixtures log conversation id and fail open."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import basic_memory.cli.commands.hook  # noqa: F401 — registers usage-log hook verbs
from basic_memory.cli.app import app
from basic_memory.shared_memory.usage_log_fast import ensure_log_dir

FIXTURES = Path(__file__).resolve().parents[1] / "hooks" / "fixtures"


def _invoke(verb: str, harness: str, fixture: str, project_home: Path) -> None:
    payload = (FIXTURES / fixture).read_text(encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["hook", verb, "--harness", harness, "--project-dir", str(project_home)],
        input=payload,
    )
    assert result.exit_code == 0


def test_hook_fixtures_log_conversation(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "vault"
    home.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(cfg))
    (cfg / "config.json").write_text(
        json.dumps({"usage_log_enabled": True, "projects": {"main": {"path": str(home)}}}),
        encoding="utf-8",
    )
    _invoke("prompt-submit", "claude", "claude_user_prompt_submit.json", home)
    _invoke("turn-end", "claude", "claude_stop.json", home)
    _invoke("post-mcp-tool", "claude", "claude_post_tool_use.json", home)
    _invoke("prompt-submit", "cursor", "cursor_before_submit.json", home)
    _invoke("turn-end", "cursor", "cursor_stop.json", home)
    _invoke("post-mcp-tool", "cursor", "cursor_after_mcp.json", home)
    log_text = next(ensure_log_dir(home).glob("events-*.jsonl")).read_text(encoding="utf-8")
    assert "claude-session-abc" in log_text
    assert "cursor-conv-123" in log_text
    assert "search_notes" in log_text
    assert "secret prompt" not in log_text
    assert "user text that must not" not in log_text


def test_hook_fail_open_bad_json(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "vault"
    home.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(cfg))
    (cfg / "config.json").write_text("{}", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["hook", "prompt-submit", "--harness", "cursor", "--project-dir", str(home)],
        input="{not json",
    )
    assert result.exit_code == 0
