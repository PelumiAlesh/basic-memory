"""Single shared MCP process claim under the config directory.

When `mcp_shared_server` is on, the HTTP transport is the one long-running
server. A second process that would open the same SQLite database and write
the same vault must not start: it either finds the living claim and fails
with a clear message, or takes over a stale (dead) claim.

Stdio without the flag is unchanged. Tokens are never stored in the claim.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from basic_memory.config import CONFIG_DIR_MODE, CONFIG_FILE_MODE, resolve_data_dir

CLAIM_FILE_NAME = "mcp-shared.json"
LOCK_FILE_NAME = "mcp-shared.lock"


@dataclass(frozen=True, slots=True)
class SharedServerClaim:
    """What a living shared MCP process wrote under the config dir."""

    pid: int
    transport: str
    host: str
    port: int
    path: str
    started: str

    @property
    def url(self) -> str:
        host = self.host if self.host not in {"0.0.0.0", "::"} else "127.0.0.1"
        return f"http://{host}:{self.port}{self.path}"


class SharedServerConflict(RuntimeError):
    """Another living process already owns the shared MCP claim."""

    def __init__(self, claim: SharedServerClaim) -> None:
        self.claim = claim
        super().__init__(
            f"A shared MCP server is already running (pid {claim.pid}, "
            f"{claim.transport} at {claim.url}). Point clients at that URL "
            f"with the bearer token; do not start a second process against "
            f"the same vault. Set mcp_shared_server=false to allow separate "
            f"stdio processes (not recommended for multi-client use)."
        )


def claim_path() -> Path:
    return resolve_data_dir() / CLAIM_FILE_NAME


def lock_path() -> Path:
    return resolve_data_dir() / LOCK_FILE_NAME


def _secure_dir(path: Path) -> None:
    if os.name != "nt":
        path.chmod(CONFIG_DIR_MODE)


def _secure_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(CONFIG_FILE_MODE)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it — treat as living.
        return True
    return True


def read_claim() -> SharedServerClaim | None:
    """Parse the claim file when present and well-formed; else None."""
    path = claim_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return SharedServerClaim(
            pid=int(raw["pid"]),
            transport=str(raw["transport"]),
            host=str(raw["host"]),
            port=int(raw["port"]),
            path=str(raw.get("path") or "/mcp"),
            started=str(raw["started"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def living_claim() -> SharedServerClaim | None:
    """Return the claim only when its pid is still alive."""
    claim = read_claim()
    if claim is None or not _pid_alive(claim.pid):
        return None
    return claim


def _write_claim(claim: SharedServerClaim) -> None:
    directory = resolve_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _secure_dir(directory)
    payload: dict[str, Any] = {
        "pid": claim.pid,
        "transport": claim.transport,
        "host": claim.host,
        "port": claim.port,
        "path": claim.path,
        "started": claim.started,
    }
    target = claim_path()
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _secure_file(tmp)
    os.replace(tmp, target)


def acquire_shared_claim(
    *,
    transport: str,
    host: str,
    port: int,
    path: str = "/mcp",
) -> FileLock:
    """Claim this process as the shared MCP server, or raise SharedServerConflict.

    Holds a non-blocking file lock for the process lifetime. Callers keep the
    returned lock object alive so the OS releases it on exit.
    """
    existing = living_claim()
    if existing is not None and existing.pid != os.getpid():
        raise SharedServerConflict(existing)

    directory = resolve_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    _secure_dir(directory)
    lock = FileLock(str(lock_path()), timeout=0)
    try:
        lock.acquire()
    except Timeout as exc:
        # Another process holds the lock; re-read the claim for the message.
        again = living_claim()
        if again is not None:
            raise SharedServerConflict(again) from exc
        raise SharedServerConflict(
            SharedServerClaim(
                pid=0,
                transport="unknown",
                host=host,
                port=port,
                path=path,
                started="",
            )
        ) from exc

    claim = SharedServerClaim(
        pid=os.getpid(),
        transport=transport,
        host=host,
        port=port,
        path=path,
        started=datetime.now(tz=timezone.utc).isoformat(),
    )
    _write_claim(claim)
    return lock


def refuse_if_shared_server_running(*, transport: str) -> None:
    """Fail clear when shared mode is on and another living claim exists.

    Used by stdio (and a second HTTP attempt) so two processes never open the
    same vault. Does not acquire the lock — the living HTTP owner already has it.
    """
    claim = living_claim()
    if claim is None:
        return
    if claim.pid == os.getpid():
        return
    # Stdio must not start alongside the shared HTTP server.
    if transport == "stdio" or claim.pid != os.getpid():
        raise SharedServerConflict(claim)


def release_shared_claim(lock: FileLock | None) -> None:
    """Drop the claim file when it still names this pid, then release the lock."""
    claim = read_claim()
    if claim is not None and claim.pid == os.getpid():
        try:
            claim_path().unlink(missing_ok=True)
        except OSError:
            pass
    if lock is not None and lock.is_locked:
        lock.release()
