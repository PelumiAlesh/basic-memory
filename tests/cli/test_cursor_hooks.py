"""Cursor hook install writes the flat hooks.json schema."""

import json
from pathlib import Path

from basic_memory.cli.commands.hook import (
    _cursor_hook_commands,
    _install_cursor_hooks,
    _remove_cursor_hooks,
)


def test_cursor_commands_use_cursor_event_names() -> None:
    commands = _cursor_hook_commands()
    assert set(commands) == {"sessionStart", "preCompact", "stop"}
    session = commands["sessionStart"][0]["command"]
    assert "hook session-start --harness cursor" in session
    assert "hook stop --harness cursor" in commands["stop"][0]["command"]
    assert "hooks" not in commands["sessionStart"][0]


def test_install_and_remove_cursor_hooks(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    _install_cursor_hooks()
    path = home / ".cursor" / "hooks.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["hooks"]["sessionStart"][0]["command"].endswith("--harness cursor")
    # A second install replaces our entry instead of duplicating it.
    data["hooks"]["sessionStart"].append({"command": "echo user-hook"})
    path.write_text(json.dumps(data), encoding="utf-8")
    _install_cursor_hooks()
    again = json.loads(path.read_text(encoding="utf-8"))
    commands = [item["command"] for item in again["hooks"]["sessionStart"]]
    assert commands.count("echo user-hook") == 1
    assert sum("harness cursor" in command for command in commands) == 1
    _remove_cursor_hooks()
    removed = json.loads(path.read_text(encoding="utf-8"))
    assert removed["hooks"]["sessionStart"] == [{"command": "echo user-hook"}]
    assert "preCompact" not in removed["hooks"]
