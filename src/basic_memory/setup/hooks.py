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


def _strip_flat_owned(entries: list[Any]) -> list[Any]:
    """Drop setup-owned hooks from Cursor's flat ``hooks.<event>`` list."""
    kept: list[Any] = []
    for entry in entries:
        if _is_owned_setup_hook(entry):
            continue
        if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
            remaining = [hook for hook in entry["hooks"] if not _is_owned_setup_hook(hook)]
            if remaining:
                kept.append({**entry, "hooks": remaining})
            continue
        kept.append(entry)
    return kept


def _command(launcher: str, verb: str) -> str:
    return f"{launcher} hook {verb}"


def cursor_hook_entries(launcher: str, *, session_capture: bool) -> dict[str, list[dict[str, Any]]]:
    """Cursor hooks.json schema (version 1): a flat list of ``{command, timeout}``.

    ``beforeSubmitPrompt`` is not installed. Its output cannot add context, and the
    hook would start this CLI on every send. ``sessionStart`` runs only when a new
    composer conversation is created.
    """

    def entry(verb: str, timeout: int = 15) -> dict[str, Any]:
        return {
            "command": _command(launcher, verb),
            "timeout": timeout,
        }

    entries = {
        "sessionStart": [entry("fork-cursor-session-start", 25)],
    }
    # Trigger: the user opted into session capture.
    # Why: a Stop hook that is always installed still runs when capture is off.
    # Outcome: the stop command is registered only while capture is on.
    if session_capture:
        entries["stop"] = [entry("fork-cursor-stop", 30)]
    return entries


def claude_hook_entries(launcher: str, *, session_capture: bool) -> dict[str, list[dict[str, Any]]]:
    """Claude Code settings shape: event -> matcher groups -> command hooks."""

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

    entries = {
        "UserPromptSubmit": [group("fork-claude-user-prompt", 25)],
    }
    if session_capture:
        entries["Stop"] = [group("fork-claude-stop", 30)]
    return entries


def install_cursor_hooks(launcher: str, *, session_capture: bool) -> None:
    path = cursor_hooks_path()
    data = _load_hook_config(path) if path.exists() else {"version": 1, "hooks": {}}
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: hooks must be an object")
    desired = cursor_hook_entries(launcher, session_capture=session_capture)
    # Re-runs replace our events. A capture stop hook from an earlier run is removed
    # when this run has capture off, without touching anyone else's commands.
    for event in ("sessionStart", "beforeSubmitPrompt", "stop"):
        existing = hooks.get(event)
        if existing is None:
            continue
        if not isinstance(existing, list):
            raise ValueError(f"{path}: hooks.{event} must be a list")
        stripped = _strip_flat_owned(existing)
        if event in desired:
            stripped.extend(desired[event])
        if stripped:
            hooks[event] = stripped
        else:
            del hooks[event]
    for event, entries in desired.items():
        if event not in hooks:
            hooks[event] = list(entries)
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
        stripped = _strip_flat_owned(groups)
        if stripped != groups:
            changed = True
            if stripped:
                hooks[event] = stripped
            else:
                del hooks[event]
    if changed:
        _write_hook_config(path, data)


def install_claude_hooks(launcher: str, *, session_capture: bool) -> None:
    path = claude_code_settings_path()
    data = _load_hook_config(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: hooks must be an object")
    desired = claude_hook_entries(launcher, session_capture=session_capture)
    for event in ("UserPromptSubmit", "Stop"):
        existing = hooks.get(event)
        if existing is None:
            continue
        if not isinstance(existing, list):
            raise ValueError(f"{path}: hooks.{event} must be a list")
        stripped = _strip_owned_claude(existing)
        if event in desired:
            stripped.extend(desired[event])
        if stripped:
            hooks[event] = stripped
        else:
            del hooks[event]
    for event, groups in desired.items():
        if event not in hooks:
            hooks[event] = list(groups)
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
