"""Parse local usage logs and compute aggregates for `bm stats`."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from basic_memory.shared_memory.usage_log_fast import (
    HTTP_INFER_IDLE_MINUTES,
    LOG_DIR_NAME,
    META_EVENT,
    READ_TOOL_NAMES,
)

HOOK_CLIENTS = frozenset({"cursor", "claude-code", "claude", "codex"})
PROMPT_HOOK_NAMES = frozenset(
    {"prompt-submit", "UserPromptSubmit", "beforeSubmitPrompt", "user-prompt-submit"}
)
TURN_END_NAMES = frozenset({"turn-end", "Stop", "stop"})
POST_TOOL_NAMES = frozenset({"post-mcp-tool", "PostToolUse", "afterMCPExecution", "post-tool-use"})
BRIEF_REASONS = frozenset({"ok", "not_due", "no_pin", "disabled", "error"})


@dataclass
class ParsedEvent:
    raw: dict[str, Any]
    ts: datetime
    event: str
    name: str
    client: str | None
    project: str | None
    duration_ms: float | None
    ok: bool | None
    conversation_id: str | None
    permalinks: list[str]
    result_count: int | None
    bytes_written: int | None
    reason: str | None
    mcp_session_id: str | None


def _parse_ts(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def load_events(project_homes: Iterable[Path], days: int) -> list[ParsedEvent]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    events: list[ParsedEvent] = []
    for home in project_homes:
        log_dir = home / LOG_DIR_NAME
        if not log_dir.is_dir():
            continue
        for path in sorted(log_dir.glob("events-*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                ts_raw = raw.get("ts")
                if not isinstance(ts_raw, str):
                    continue
                try:
                    ts = _parse_ts(ts_raw)
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                permalinks = raw.get("permalinks")
                if isinstance(permalinks, str):
                    perm_list = [permalinks]
                elif isinstance(permalinks, list):
                    perm_list = [str(p) for p in permalinks if p]
                else:
                    perm_list = []
                duration = raw.get("duration_ms")
                events.append(
                    ParsedEvent(
                        raw=raw,
                        ts=ts,
                        event=str(raw.get("event") or ""),
                        name=str(raw.get("name") or ""),
                        client=raw.get("client") if isinstance(raw.get("client"), str) else None,
                        project=raw.get("project") if isinstance(raw.get("project"), str) else None,
                        duration_ms=float(duration) if isinstance(duration, (int, float)) else None,
                        ok=raw.get("ok") if isinstance(raw.get("ok"), bool) else None,
                        conversation_id=raw.get("conversation_id")
                        if isinstance(raw.get("conversation_id"), str)
                        else None,
                        permalinks=perm_list,
                        result_count=raw.get("result_count")
                        if isinstance(raw.get("result_count"), int)
                        else None,
                        bytes_written=raw.get("bytes_written")
                        if isinstance(raw.get("bytes_written"), int)
                        else None,
                        reason=raw.get("reason") if isinstance(raw.get("reason"), str) else None,
                        mcp_session_id=raw.get("mcp_session_id")
                        if isinstance(raw.get("mcp_session_id"), str)
                        else None,
                    )
                )
    events.sort(key=lambda item: item.ts)
    return events


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


@dataclass
class StatsReport:
    days: int
    dropped_events: int = 0
    calls_per_tool_per_client: dict[str, dict[str, int]] = field(default_factory=dict)
    latency_p50_p95: dict[str, dict[str, float | None]] = field(default_factory=dict)
    error_rate: float = 0.0
    writes_per_client: dict[str, int] = field(default_factory=dict)
    most_read_notes: list[tuple[str, int]] = field(default_factory=list)
    never_read_written: list[str] = field(default_factory=list)
    brief_per_conversation: dict[str, int] = field(default_factory=dict)
    inbox_capture_files: int = 0
    turn_memory_read_pct: float | None = None
    resumed_brief_pct: float | None = None
    zero_use_conversations: list[str] = field(default_factory=list)
    writes_per_conversation: dict[str, int] = field(default_factory=dict)
    most_active_conversations: list[tuple[str, int, str | None]] = field(default_factory=list)
    inferred_http_sessions: list[dict[str, Any]] = field(default_factory=list)
    harness_gaps: list[str] = field(default_factory=list)


def _is_hook_client(client: str | None) -> bool:
    return client in HOOK_CLIENTS if client else False


def _is_read_tool_event(event: ParsedEvent) -> bool:
    if event.event == "tool" and event.name in READ_TOOL_NAMES:
        return True
    if event.event == "hook" and event.name in POST_TOOL_NAMES:
        tool = event.raw.get("tool") or event.raw.get("tool_name")
        return isinstance(tool, str) and tool in READ_TOOL_NAMES
    return False


def _is_write_tool_event(event: ParsedEvent) -> bool:
    if event.event == "tool" and event.name in {
        "write_note",
        "edit_note",
        "move_note",
        "delete_note",
    }:
        return True
    if event.event == "hook" and event.name in POST_TOOL_NAMES:
        tool = event.raw.get("tool") or event.raw.get("tool_name")
        return isinstance(tool, str) and tool in {
            "write_note",
            "edit_note",
            "move_note",
            "delete_note",
        }
    return False


def compute_stats(events: list[ParsedEvent], *, days: int) -> StatsReport:
    report = StatsReport(days=days)
    tool_latencies: dict[str, list[float]] = defaultdict(list)
    tool_errors = 0
    tool_calls = 0
    read_counts: Counter[str] = Counter()
    written_permalinks: set[str] = set()
    read_permalinks: set[str] = set()

    turns: list[tuple[str, datetime, datetime, str | None]] = []
    turn_reads: dict[tuple[str, datetime], bool] = {}
    conversation_turns: Counter[str] = Counter()
    conversation_writes: Counter[str] = Counter()
    conversation_memory: Counter[str] = Counter()
    resumed_brief_total = 0
    resumed_brief_ok = 0
    brief_tokens: dict[str, int] = defaultdict(int)

    http_events: list[ParsedEvent] = []

    for event in events:
        if event.event == META_EVENT and event.name == "dropped":
            count = event.raw.get("count")
            if isinstance(count, int):
                report.dropped_events += count
            continue

        if event.event == "tool":
            tool_calls += 1
            client = event.client or "unknown"
            report.calls_per_tool_per_client.setdefault(event.name, {})
            report.calls_per_tool_per_client[event.name][client] = (
                report.calls_per_tool_per_client[event.name].get(client, 0) + 1
            )
            if event.duration_ms is not None:
                tool_latencies[event.name].append(event.duration_ms)
            if event.ok is False:
                tool_errors += 1
            if _is_write_tool_event(event):
                report.writes_per_client[client] = report.writes_per_client.get(client, 0) + 1
            for permalink in event.permalinks:
                if _is_write_tool_event(event):
                    written_permalinks.add(permalink)
                if _is_read_tool_event(event):
                    read_counts[permalink] += 1
                    read_permalinks.add(permalink)
            if event.client and not _is_hook_client(event.client):
                http_events.append(event)
            if event.conversation_id and _is_write_tool_event(event):
                conversation_writes[event.conversation_id] += 1
            continue

        if event.event == "hook":
            if event.name in PROMPT_HOOK_NAMES and event.conversation_id:
                turns.append(("start", event.ts, event.ts, event.conversation_id))
                if event.reason == "ok":
                    resumed_brief_total += 1
                    resumed_brief_ok += 1
                elif event.reason in {"not_due", "no_pin", "disabled"}:
                    resumed_brief_total += 1
                if event.conversation_id and event.reason == "ok":
                    tokens = event.raw.get("brief_tokens")
                    if isinstance(tokens, int):
                        brief_tokens[event.conversation_id] += tokens
            elif event.name in TURN_END_NAMES and event.conversation_id:
                turns.append(("end", event.ts, event.ts, event.conversation_id))
                conversation_turns[event.conversation_id] += 1
            elif event.name in POST_TOOL_NAMES and event.conversation_id:
                conversation_memory[event.conversation_id] += 1
                tool = event.raw.get("tool") or event.raw.get("tool_name")
                if isinstance(tool, str) and tool in READ_TOOL_NAMES:
                    turn_reads[(event.conversation_id, event.ts)] = True
            continue

        if event.event == "cli":
            if event.name in {"write", "search"} and event.client:
                report.writes_per_client[event.client] = (
                    report.writes_per_client.get(event.client, 0) + 1
                )

    for tool, values in tool_latencies.items():
        report.latency_p50_p95[tool] = {
            "p50": _percentile(values, 50),
            "p95": _percentile(values, 95),
        }
    report.error_rate = (tool_errors / tool_calls) if tool_calls else 0.0
    report.most_read_notes = read_counts.most_common(10)
    report.never_read_written = sorted(written_permalinks - read_permalinks)[:20]
    report.brief_per_conversation = dict(brief_tokens)

    # Turn coverage: match prompt-submit to turn-end per conversation
    open_turns: dict[str, datetime] = {}
    turns_with_read = 0
    total_turns = 0
    for kind, ts, _, conv in turns:
        if not conv:
            continue
        if kind == "start":
            open_turns[conv] = ts
        elif kind == "end" and conv in open_turns:
            total_turns += 1
            start = open_turns.pop(conv)
            had_read = any(
                key[0] == conv and start <= key[1] <= ts and turn_reads.get(key)
                for key in turn_reads
            )
            if had_read:
                turns_with_read += 1
    report.turn_memory_read_pct = (turns_with_read / total_turns * 100.0) if total_turns else None
    report.resumed_brief_pct = (
        (resumed_brief_ok / resumed_brief_total * 100.0) if resumed_brief_total else None
    )
    report.zero_use_conversations = [
        conv for conv, count in conversation_turns.items() if conversation_memory.get(conv, 0) == 0
    ][:20]
    report.writes_per_conversation = dict(conversation_writes)
    active = sorted(conversation_turns.items(), key=lambda item: item[1], reverse=True)[:10]
    report.most_active_conversations = [(conv, count, None) for conv, count in active]

    report.inferred_http_sessions = _infer_http_sessions(http_events)
    return report


def _infer_http_sessions(events: list[ParsedEvent]) -> list[dict[str, Any]]:
    if not events:
        return []
    idle = timedelta(minutes=HTTP_INFER_IDLE_MINUTES)
    sessions: list[list[ParsedEvent]] = []
    current: list[ParsedEvent] = []
    last_ts: datetime | None = None
    last_client: str | None = None
    last_session: str | None = None

    for event in events:
        boundary = False
        if last_ts and event.ts - last_ts > idle:
            boundary = True
        if last_client and event.client != last_client:
            boundary = True
        if event.mcp_session_id and last_session and event.mcp_session_id != last_session:
            boundary = True
        if boundary and current:
            sessions.append(current)
            current = []
        current.append(event)
        last_ts = event.ts
        last_client = event.client
        last_session = event.mcp_session_id or last_session
    if current:
        sessions.append(current)

    inferred: list[dict[str, Any]] = []
    for group in sessions:
        first = group[0].name
        first_kind = (
            "get_brief"
            if first == "get_brief"
            else ("search_notes" if first in {"search_notes", "search"} else "other")
        )
        wrote_before_idle = any(_is_write_tool_event(item) for item in group)
        inferred.append(
            {
                "label": "INFERRED",
                "client": group[0].client,
                "tool_calls": len(group),
                "first_call": first_kind,
                "write_before_idle": wrote_before_idle,
            }
        )
    return inferred


def report_to_json(report: StatsReport) -> dict[str, Any]:
    """Privacy-safe aggregates only — no ids, permalinks, or paths."""
    return {
        "days": report.days,
        "dropped_events": report.dropped_events,
        "calls_per_tool_per_client": report.calls_per_tool_per_client,
        "latency_p50_p95_ms": report.latency_p50_p95,
        "error_rate": round(report.error_rate, 4),
        "writes_per_client": report.writes_per_client,
        "most_read_note_count": len(report.most_read_notes),
        "never_read_written_count": len(report.never_read_written),
        "brief_conversation_count": len(report.brief_per_conversation),
        "inbox_capture_files": report.inbox_capture_files,
        "turn_memory_read_pct": report.turn_memory_read_pct,
        "resumed_brief_pct": report.resumed_brief_pct,
        "zero_use_conversation_count": len(report.zero_use_conversations),
        "writes_per_conversation_total": sum(report.writes_per_conversation.values()),
        "most_active_conversation_count": len(report.most_active_conversations),
        "inferred_http_sessions": report.inferred_http_sessions,
        "harness_gaps": report.harness_gaps,
    }
