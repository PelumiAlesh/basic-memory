"""Install fork per-turn hooks into Cursor and Claude Code."""

from __future__ import annotations

import re
from typing import Any

from basic_memory.cli.commands.hook import _load_hook_config, _write_hook_config
from basic_memory.setup.paths import claude_code_settings_path, cursor_hooks_path

SETUP_OWNED_HOOK_RE = re.compile(
    r"\bhook\s+fork-(?:cursor-session-start|cursor-before-prompt|cursor-stop|"
    r"claude-user-prompt|claude-stop)\b"
)


def _is_owned_setup_hook(hook: Any) -> bool:
    return (
        isinstance(hook, dict)
        and isinstance(hook.get("command"), str)
        and SETUP_OWNED_HOOK_RE.search(hook["command"]) is not None
    )


def _strip_setup_hooks(groups: list[Any]) -> list[Any]:
    kept: list[Any] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            kept.append(group)
            continue
        remaining = [hook for hook in group["hooks"] if not _is_owned_setup_hook(hook)]
        if remaining:
            kept.append({**group, "hooks": remaining})
    return kept


def _command(launcher: str, verb: str) -> str:
    return f"{launcher} hook {verb}"


def cursor_hook_entries(launcher: str) -> dict[str, list[dict[str, Any]]]:
    """Cursor hooks.json schema (version 1)."""

    def entry(verb: str, timeout: int = 15) -> dict[str, Any]:
        return {
            "command": _command(launcher, verb),
            "timeout": timeout,
        }

    return {
        "sessionStart": [entry("fork-cursor-session-start", 25)],
        "beforeSubmitPrompt": [entry("fork-cursor-before-prompt", 10)],
        "stop": [entry("fork-cursor-stop", 30)],
    }


def claude_hook_entries(launcher: str) -> dict[str, list[dict[str, Any]]]:
    def group(verb: str, timeout: int) -> dict[str, Any]:
        return {
            "hooks": [
                {
                    "type": "command",
                    "command": _command(launcher, verb),
                    "timeout": timeout,
                }
            ]
        }

    return {
        "UserPromptSubmit": [group("fork-claude-user-prompt", 25)],
        "Stop": [group("fork-claude-stop", 30)],
    }


def install_cursor_hooks(launcher: str) -> None:
    path = cursor_hooks_path()
    data = _load_hook_config(path) if path.exists() else {"version": 1, "hooks": {}}
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: hooks must be an object")
    for event, entries in cursor_hook_entries(launcher).items():
        existing = hooks.get(event)
        if existing is not None and not isinstance(existing, list):
            raise ValueError(f"{path}: hooks.{event} must be a list")
        merged = _strip_setup_hooks(existing or [])
        merged.extend(entries)
        hooks[event] = merged
    data["version"] = 1
    _write_hook_config(path, data)


def remove_cursor_hooks() -> None:
    path = cursor_hooks_path()
    if not path.exists():
        return
    data = _load_hook_config(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    changed = False
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        stripped = _strip_setup_hooks(groups)
        if stripped != groups:
            changed = True
            if stripped:
                hooks[event] = stripped
            else:
                del hooks[event]
    if changed:
        _write_hook_config(path, data)


def install_claude_hooks(launcher: str) -> None:
    path = claude_code_settings_path()
    data = _load_hook_config(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: hooks must be an object")
    for event, groups in claude_hook_entries(launcher).items():
        existing = hooks.get(event)
        if existing is not None and not isinstance(existing, list):
            raise ValueError(f"{path}: hooks.{event} must be a list")
        merged = _strip_owned_claude(existing or [])
        merged.extend(groups)
        hooks[event] = merged
    _write_hook_config(path, data)


def _strip_owned_claude(groups: list[Any]) -> list[Any]:
    kept: list[Any] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            kept.append(group)
            continue
        remaining = [hook for hook in group["hooks"] if not _is_owned_setup_hook(hook)]
        if remaining:
            kept.append({**group, "hooks": remaining})
    return kept


def remove_claude_hooks() -> None:
    path = claude_code_settings_path()
    if not path.exists():
        return
    data = _load_hook_config(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    changed = False
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        stripped = _strip_owned_claude(groups)
        if stripped != groups:
            changed = True
            if stripped:
                hooks[event] = stripped
            else:
                del hooks[event]
    if changed:
        _write_hook_config(path, data)
