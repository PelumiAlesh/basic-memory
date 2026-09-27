"""Local usage and debug event log (fork).

Non-blocking queue for the long-running MCP server; hooks use usage_log_fast instead.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, override

import mcp.types as mt
from fastmcp import Context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from loguru import logger

from basic_memory.config_models import CONFIG_FILE_MODE, resolve_data_dir
from basic_memory.shared_memory.clients import request_client
from basic_memory.shared_memory.usage_log_fast import (
    FILE_MODE,
    daily_log_path,
    ensure_log_dir,
    prune_expired_logs,
)

SALT_FILE_NAME = "usage_log_query_salt"
META_EVENT = "meta"
DROP_REASON = "dropped"
QUEUE_MAX = 4096
FLUSH_INTERVAL_SECONDS = 1.0
FLUSH_BATCH_SIZE = 100
BENCHMARK_BOUND_SECONDS = 0.001

READ_TOOL_NAMES = frozenset(
    {
        "read_note",
        "read_content",
        "view_note",
        "search_notes",
        "search",
        "fetch",
        "build_context",
        "recent_activity",
        "list_directory",
        "get_brief",
    }
)
WRITE_TOOL_NAMES = frozenset({"write_note", "edit_note", "move_note", "delete_note"})
HTTP_INFER_IDLE_MINUTES = 30


@dataclass(slots=True)
class UsageEvent:
    event: str
    name: str
    client: str | None = None
    project: str | None = None
    duration_ms: float | None = None
    ok: bool | None = None
    error_code: str | None = None
    result_count: int | None = None
    bytes_written: int | None = None
    permalinks: list[str] | None = None
    brief_tokens: int | None = None
    conversation_id: str | None = None
    mcp_session_id: str | None = None
    reason: str | None = None
    query_len: int | None = None
    query_hash: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload: dict[str, Any] = {"ts": ts, "event": self.event, "name": self.name}
        for key, value in (
            ("client", self.client),
            ("project", self.project),
            ("duration_ms", self.duration_ms),
            ("ok", self.ok),
            ("error_code", self.error_code),
            ("result_count", self.result_count),
            ("bytes_written", self.bytes_written),
            ("brief_tokens", self.brief_tokens),
            ("conversation_id", self.conversation_id),
            ("mcp_session_id", self.mcp_session_id),
            ("reason", self.reason),
            ("query_len", self.query_len),
            ("query_hash", self.query_hash),
        ):
            if value is not None:
                payload[key] = value
        if self.permalinks:
            payload["permalinks"] = self.permalinks
        payload.update(self.extra)
        return payload


class _UsageLogWriter:
    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[Path, dict[str, Any]]] = queue.Queue(maxsize=QUEUE_MAX)
        self._drops = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="usage-log-writer", daemon=True)
        self._thread.start()
        atexit.register(self.shutdown)

    def enqueue(self, project_home: Path, event: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait((project_home, event))
        except queue.Full:
            with self._lock:
                self._drops += 1

    def shutdown(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._flush_drops()

    def _run(self) -> None:
        batch: list[tuple[Path, dict[str, Any]]] = []
        last_flush = time.monotonic()
        while not self._stop.is_set():
            timeout = max(0.0, FLUSH_INTERVAL_SECONDS - (time.monotonic() - last_flush))
            try:
                item = self._queue.get(timeout=timeout)
                batch.append(item)
                if len(batch) >= FLUSH_BATCH_SIZE:
                    self._write_batch(batch)
                    batch = []
                    last_flush = time.monotonic()
                    self._flush_drops()
            except queue.Empty:
                if batch:
                    self._write_batch(batch)
                    batch = []
                last_flush = time.monotonic()
                self._flush_drops()
        if batch:
            self._write_batch(batch)
        self._flush_drops()

    def _flush_drops(self) -> None:
        with self._lock:
            drops = self._drops
            self._drops = 0
        if drops <= 0:
            return
        try:
            from basic_memory.config import ConfigManager

            config = ConfigManager().config
            if not config.usage_log_enabled or config.is_test_env:
                return
            home = _default_project_home(config)
            log_dir = ensure_log_dir(home)
            line = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "event": META_EVENT,
                "name": DROP_REASON,
                "count": drops,
            }
            _append_line(daily_log_path(log_dir), line)
        except Exception as exc:
            logger.debug(f"usage log drop counter failed: {exc}")

    def _write_batch(self, batch: list[tuple[Path, dict[str, Any]]]) -> None:
        by_file: dict[Path, list[dict[str, Any]]] = {}
        for project_home, event in batch:
            log_dir = ensure_log_dir(project_home)
            path = daily_log_path(log_dir)
            by_file.setdefault(path, []).append(event)
        for path, events in by_file.items():
            try:
                for event in events:
                    _append_line(path, event)
            except OSError as exc:
                logger.debug(f"usage log write failed for {path}: {exc}")


_writer: _UsageLogWriter | None = None


def _get_writer() -> _UsageLogWriter:
    global _writer
    if _writer is None:
        _writer = _UsageLogWriter()
    return _writer


def _append_line(path: Path, event: dict[str, Any]) -> None:
    line = json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
    encoded = line.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(path, flags, FILE_MODE if os.name != "nt" else 0o666)
    try:
        if os.name != "nt":
            os.chmod(path, FILE_MODE)
        os.write(fd, encoded)
    finally:
        os.close(fd)


def _default_project_home(config: Any) -> Path:
    name = config.default_project
    if name and name in config.projects:
        return Path(config.projects[name].path).resolve()
    if config.projects:
        first = next(iter(config.projects.values()))
        return Path(first.path).resolve()
    return Path.home() / "basic-memory"


def _query_salt() -> bytes:
    path = resolve_data_dir() / SALT_FILE_NAME
    if path.exists():
        try:
            raw = path.read_bytes()
            if raw:
                return raw
        except OSError:
            pass
    salt = secrets.token_bytes(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(salt)
    if os.name != "nt":
        os.chmod(path, CONFIG_FILE_MODE)
    return salt


def query_hash(query: str) -> str:
    digest = hashlib.sha256(_query_salt() + query.encode("utf-8")).hexdigest()
    return digest[:12]


def log_usage_event(
    event: UsageEvent,
    *,
    project_home: Path | None = None,
) -> None:
    """Enqueue one event when logging is enabled; never raises."""
    try:
        from basic_memory.config import ConfigManager

        config = ConfigManager().config
        if not config.usage_log_enabled or config.is_test_env:
            return
        home = project_home or _default_project_home(config)
        _get_writer().enqueue(home.resolve(), event.to_dict())
    except Exception as exc:
        logger.debug(f"usage log enqueue failed: {exc}")


def apply_retention(project_home: Path, retention_days: int) -> int:
    """Delete events-*.jsonl older than retention_days. Returns files removed."""
    return prune_expired_logs(project_home, retention_days)


def maybe_apply_retention() -> None:
    try:
        from basic_memory.config import ConfigManager

        config = ConfigManager().config
        if not config.usage_log_enabled:
            return
        days = config.usage_log_retention_days
        for entry in config.projects.values():
            root = Path(entry.path)
            if root.is_absolute():
                apply_retention(root.resolve(), days)
    except Exception as exc:
        logger.debug(f"usage log retention failed: {exc}")


def _project_home_from_context(context: Context | None) -> Path | None:
    if context is None:
        return None
    request_context = context.request_context
    if request_context is None or request_context.request is None:
        return None
    project = request_context.request.headers.get("x-basic-memory-project")
    if project:
        try:
            from basic_memory.config import ConfigManager

            config = ConfigManager().config
            if project in config.projects:
                return Path(config.projects[project].path).resolve()
        except Exception:
            return None
    return None


def _session_id_from_context(context: Context | None) -> str | None:
    if context is None or context.request_context is None:
        return None
    session = context.request_context.session
    session_id = getattr(session, "session_id", None) or getattr(session, "id", None)
    return str(session_id) if session_id else None


def _summarize_tool_result(tool_name: str, result: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if not isinstance(result, dict):
        return summary
    if tool_name in WRITE_TOOL_NAMES:
        permalink = result.get("permalink") or result.get("file_path")
        if isinstance(permalink, str):
            summary["permalinks"] = [permalink]
        content = result.get("content")
        if isinstance(content, str):
            summary["bytes_written"] = len(content.encode("utf-8"))
    if tool_name in {"search_notes", "search"}:
        results = result.get("results")
        if isinstance(results, list):
            summary["result_count"] = len(results)
    return summary


class UsageLogMiddleware(Middleware):
    """Record MCP tool calls without blocking the handler."""

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        started = time.perf_counter()
        tool_name = context.message.name
        ok = True
        error_code: str | None = None
        result: Any = None
        try:
            result = await call_next(context)
        except Exception as exc:
            ok = False
            error_code = type(exc).__name__
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            fastmcp_context = context.fastmcp_context
            client = await request_client(fastmcp_context)
            project_home = _project_home_from_context(fastmcp_context)
            summary = _summarize_tool_result(tool_name, result)
            query_len: int | None = None
            query_hash_value: str | None = None
            arguments = context.message.arguments or {}
            if tool_name in {"search_notes", "search"}:
                query = arguments.get("query")
                if isinstance(query, str):
                    query_len = len(query)
                    query_hash_value = query_hash(query)
            event = UsageEvent(
                event="tool",
                name=tool_name,
                client=client,
                duration_ms=round(duration_ms, 3),
                ok=ok,
                error_code=error_code,
                mcp_session_id=_session_id_from_context(fastmcp_context),
                query_len=query_len,
                query_hash=query_hash_value,
                permalinks=summary.get("permalinks"),
                bytes_written=summary.get("bytes_written"),
                result_count=summary.get("result_count"),
            )
            if project_home is not None:
                log_usage_event(event, project_home=project_home)
            else:
                log_usage_event(event)
        return result


def start_usage_log_background() -> None:
    """Start writer thread and schedule retention on MCP lifespan."""
    _get_writer()
    maybe_apply_retention()
