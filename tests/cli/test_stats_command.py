"""`bm stats` aggregation and JSON privacy."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

import basic_memory.cli.commands.stats  # noqa: F401 — register `bm stats`
from basic_memory.cli.app import app
from basic_memory.shared_memory.stats import compute_stats, load_events, report_to_json
from basic_memory.shared_memory.usage_log_fast import append_event_line


def _write_event(home: Path, payload: dict[str, Any]) -> None:
    append_event_line(payload, project_dir=home)


def test_stats_math_and_json_privacy(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "vault"
    home.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(cfg))
    (cfg / "config.json").write_text(
        json.dumps(
            {
                "usage_log_enabled": True,
                "projects": {"main": {"path": str(home)}},
                "default_project": "main",
            }
        ),
        encoding="utf-8",
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conv = "conv-stats-1"
    _write_event(
        home,
        {
            "ts": now,
            "event": "hook",
            "name": "prompt-submit",
            "conversation_id": conv,
            "reason": "ok",
            "brief_tokens": 10,
        },
    )
    _write_event(
        home,
        {
            "ts": now,
            "event": "hook",
            "name": "post-mcp-tool",
            "conversation_id": conv,
            "tool": "read_note",
        },
    )
    _write_event(
        home,
        {
            "ts": now,
            "event": "hook",
            "name": "turn-end",
            "conversation_id": conv,
        },
    )
    _write_event(
        home,
        {
            "ts": now,
            "event": "tool",
            "name": "search_notes",
            "client": "chatgpt",
            "duration_ms": 10,
            "ok": True,
            "mcp_session_id": "s1",
        },
    )
    events = load_events([home], 7)
    report = compute_stats(events, days=7)
    assert report.turn_memory_read_pct == 100.0
    assert report.resumed_brief_pct == 100.0
    assert conv not in json.dumps(report_to_json(report))
    assert len(report.inferred_http_sessions) == 1
    assert report.inferred_http_sessions[0]["label"] == "INFERRED"


def test_stats_cli_json(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "vault"
    home.mkdir()
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(cfg))
    (cfg / "config.json").write_text(
        json.dumps(
            {
                "usage_log_enabled": True,
                "projects": {"main": {"path": str(home)}},
                "default_project": "main",
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["stats", "--json", "--days", "1"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "conversation_id" not in result.stdout
    assert payload["days"] == 1
