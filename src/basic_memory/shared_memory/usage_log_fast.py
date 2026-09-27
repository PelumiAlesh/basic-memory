"""Stdlib-only append path for per-turn harness hooks.

Imported from the usage-log hook commands so a turn hook can log one JSON line
without loading the Basic Memory stack. Never import non-stdlib modules here.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR_NAME = ".bm-logs"
GITIGNORE_LINE = "*\n"
DIR_MODE = 0o700
FILE_MODE = 0o600
_CONFIG_FILE = "config.json"
_DATA_DIR_NAME = "basic-memory"


def _config_dir() -> Path:
    if override := os.getenv("BASIC_MEMORY_CONFIG_DIR"):
        return Path(override)
    if xdg := os.getenv("XDG_CONFIG_HOME"):
        return Path(xdg) / _DATA_DIR_NAME
    return Path.home() / f".{_DATA_DIR_NAME}"


def _load_usage_log_enabled() -> bool:
    path = _config_dir() / _CONFIG_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return True
    if not isinstance(data, dict):
        return True
    enabled = data.get("usage_log_enabled")
    return True if enabled is None else bool(enabled)


def _project_home(project_dir: Path | None) -> Path:
    if project_dir is not None:
        return project_dir.resolve()
    if home := os.getenv("BASIC_MEMORY_HOME"):
        return Path(home).resolve()
    entry = _default_project_path()
    if entry is not None:
        return entry
    return (_config_dir().parent / "basic-memory").resolve()


def _default_project_path() -> Path | None:
    path = _config_dir() / _CONFIG_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    default_name = data.get("default_project")
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return None
    if default_name and isinstance(default_name, str) and default_name in projects:
        entry = projects[default_name]
    elif projects:
        entry = next(iter(projects.values()))
    else:
        return None
    if isinstance(entry, str):
        project_path = entry
    elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
        project_path = entry["path"]
    else:
        return None
    resolved = Path(project_path)
    return resolved if project_path else None


def ensure_log_dir(project_home: Path) -> Path:
    log_dir = project_home / LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(log_dir, DIR_MODE)
    gitignore = log_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE_LINE, encoding="utf-8")
        if os.name != "nt":
            os.chmod(gitignore, FILE_MODE)
    return log_dir


def daily_log_path(log_dir: Path) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return log_dir / f"events-{day}.jsonl"


def append_event_line(
    event: dict[str, Any],
    *,
    project_dir: Path | None = None,
) -> bool:
    """Append one JSON event line with O_APPEND. Returns False when logging is off."""
    if not _load_usage_log_enabled():
        return False
    project_home = _project_home(project_dir)
    log_dir = ensure_log_dir(project_home)
    path = daily_log_path(log_dir)
    payload = dict(event)
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
    encoded = line.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(path, flags, FILE_MODE if os.name != "nt" else 0o666)
    try:
        if os.name != "nt":
            os.chmod(path, FILE_MODE)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            pass
        os.write(fd, encoded)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
    return True


def conversation_id_from_payload(harness: str, payload: dict[str, Any]) -> str | None:
    """Extract harness conversation id when present."""
    if harness == "cursor":
        for key in ("conversation_id", "conversationId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return str(value).strip()
        return None
    if harness in {"claude", "claude-code"}:
        value = payload.get("session_id")
        if isinstance(value, str) and value.strip():
            return str(value).strip()
        return None
    value = payload.get("session_id") or payload.get("conversation_id")
    if isinstance(value, str) and value.strip():
        return str(value).strip()
    return None


def tool_name_from_post_mcp_payload(harness: str, payload: dict[str, Any]) -> str | None:
    """Tool name on post-MCP-tool hook payloads."""
    if harness == "cursor":
        for key in ("tool_name", "toolName", "name"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return str(value).strip()
        return None
    if harness in {"claude", "claude-code"}:
        value = payload.get("tool_name")
        if isinstance(value, str) and value.strip():
            return str(value).strip()
        return None
    value = payload.get("tool_name") or payload.get("name")
    if isinstance(value, str) and value.strip():
        return str(value).strip()
    return None
