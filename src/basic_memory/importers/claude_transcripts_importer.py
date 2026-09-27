"""Import Claude Code session transcripts.

Claude Code keeps one JSONL file per session under
``~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`` and prunes them after
about thirty days (upstream #1527). This importer turns each session into one
conversation note so the history survives the prune. Only human input and
assistant prose are kept; tool calls, tool results, meta frames, and subagent
sidechains are skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, override

from basic_memory.importers.base import Importer
from basic_memory.importers.utils import clean_filename
from basic_memory.markdown.schemas import EntityFrontmatter, EntityMarkdown
from basic_memory.schemas.importer import ChatImportResult

_TEXT_BLOCKS = frozenset({"text", "input_text", "output_text"})
_TITLE_CHARS = 60
_SKIP_PARTS = frozenset({"subagents"})


@dataclass(slots=True)
class ClaudeTranscript:
    """One session's human and assistant turns plus the metadata around them."""

    session_id: str
    cwd: str | None = None
    git_branch: str | None = None
    version: str | None = None
    summary: str | None = None
    started: datetime | None = None
    ended: datetime | None = None
    turns: list[tuple[str, str, datetime | None]] = field(default_factory=list)

    @property
    def title(self) -> str:
        if self.summary:
            return _clip(self.summary, _TITLE_CHARS)
        first_user = next((text for role, text, _ in self.turns if role == "user"), None)
        if first_user:
            return _clip(first_user, _TITLE_CHARS)
        return f"Claude Code session {self.session_id[:8]}"


def _clip(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in _TEXT_BLOCKS:
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_claude_transcript(text: str, *, fallback_session_id: str) -> ClaudeTranscript:
    """Parse one JSONL transcript. Malformed lines are skipped, not fatal."""
    transcript = ClaudeTranscript(session_id=fallback_session_id)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "summary":
            summary = obj.get("summary")
            if isinstance(summary, str) and summary.strip():
                transcript.summary = summary.strip()
            continue
        if obj.get("isSidechain") or obj.get("isMeta") or obj.get("toolUseResult") is not None:
            continue
        session_id = obj.get("sessionId")
        if (
            isinstance(session_id, str)
            and session_id
            and transcript.session_id == fallback_session_id
        ):
            transcript.session_id = session_id
        for key, attr in (("cwd", "cwd"), ("gitBranch", "git_branch"), ("version", "version")):
            value = obj.get(key)
            if isinstance(value, str) and value and getattr(transcript, attr) is None:
                setattr(transcript, attr, value)
        message = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        role = message.get("role") or obj.get("type")
        if role not in ("user", "assistant"):
            continue
        content = _text_of(message.get("content")).strip()
        if not content:
            continue
        moment = _timestamp(obj.get("timestamp"))
        if moment is not None:
            transcript.started = (
                moment if transcript.started is None else min(transcript.started, moment)
            )
            transcript.ended = moment if transcript.ended is None else max(transcript.ended, moment)
        transcript.turns.append((role, content, moment))
    return transcript


def render_transcript(transcript: ClaudeTranscript, *, permalink: str) -> EntityMarkdown:
    """One conversation note. Frontmatter carries the session identity."""
    title = transcript.title
    metadata: dict[str, Any] = {
        "type": "conversation",
        "title": title,
        "source": "claude-code",
        "claude_session_id": transcript.session_id,
        "permalink": permalink,
        "message_count": len(transcript.turns),
    }
    if transcript.cwd:
        metadata["cwd"] = transcript.cwd
    if transcript.git_branch:
        metadata["git_branch"] = transcript.git_branch
    if transcript.started:
        metadata["started"] = transcript.started.isoformat(timespec="seconds")
    if transcript.ended:
        metadata["ended"] = transcript.ended.isoformat(timespec="seconds")

    lines = [f"# {title}", ""]
    if transcript.summary:
        lines += [transcript.summary, ""]
    lines += ["## Session", f"- session: {transcript.session_id}"]
    if transcript.cwd:
        lines.append(f"- cwd: {transcript.cwd}")
    if transcript.git_branch:
        lines.append(f"- branch: {transcript.git_branch}")
    lines += ["", "## Conversation", ""]
    for role, content, moment in transcript.turns:
        stamp = f" ({moment.strftime('%Y-%m-%d %H:%M')})" if moment else ""
        lines += [f"### {role}{stamp}", "", content, ""]
    return EntityMarkdown(
        frontmatter=EntityFrontmatter(metadata=metadata),
        content="\n".join(lines).rstrip() + "\n",
    )


def transcript_files(source: Path) -> list[Path]:
    """Every session transcript under `source`, skipping subagent sidechains."""
    if source.is_file():
        return [source] if source.suffix == ".jsonl" else []
    if not source.is_dir():
        return []
    files = [
        path
        for path in source.rglob("*.jsonl")
        if not any(part in _SKIP_PARTS for part in path.relative_to(source).parts)
    ]
    return sorted(files)


class ClaudeTranscriptsImporter(Importer[ChatImportResult]):
    """Write Claude Code JSONL sessions into the project as conversation notes."""

    @override
    def handle_error(self, message: str, error: Exception | None = None) -> ChatImportResult:
        detail = f"{message}: {error}" if error else message
        return ChatImportResult(import_count={}, success=False, error_message=detail)

    @override
    async def import_data(
        self,
        source_data: Path,
        destination_folder: str = "conversations/claude-code",
        *,
        since_days: int | None = None,
        skip_existing: bool = True,
        **kwargs: object,
    ) -> ChatImportResult:
        source = Path(source_data).expanduser()
        files = transcript_files(source)
        if not files and not source.exists():
            return self.handle_error(f"No Claude Code transcripts at {source}")
        cutoff = None
        if since_days is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - since_days * 86400
        destination = destination_folder.strip("/")
        conversations = 0
        messages = 0
        skipped = 0
        try:
            await self.ensure_folder_exists(destination)
            for path in files:
                if cutoff is not None and path.stat().st_mtime < cutoff:
                    skipped += 1
                    continue
                transcript = parse_claude_transcript(
                    path.read_text(encoding="utf-8"), fallback_session_id=path.stem
                )
                # A session with no human turn is telemetry, not a conversation.
                if not any(role == "user" for role, _, _ in transcript.turns):
                    skipped += 1
                    continue
                date_prefix = (transcript.started or datetime.now(timezone.utc)).strftime("%Y%m%d")
                stem = (
                    f"{date_prefix}-{clean_filename(transcript.title)}-{transcript.session_id[:8]}"
                )
                relative = f"{destination}/{stem}" if destination else stem
                permalink, file_path = self.build_import_paths(relative)
                # Trigger: the note already exists and the caller asked to keep it.
                # Why: a re-run over ~/.claude/projects must not rewrite notes the
                # user has edited or enriched since the first import.
                # Outcome: count it as skipped and move on.
                if skip_existing and await self.file_service.exists(file_path):
                    skipped += 1
                    continue
                await self.write_entity(
                    render_transcript(transcript, permalink=permalink), file_path
                )
                conversations += 1
                messages += len(transcript.turns)
        except (OSError, UnicodeError) as exc:
            return self.handle_error("Failed to import Claude Code transcripts", exc)
        return ChatImportResult(
            import_count={
                "conversations": conversations,
                "messages": messages,
                "skipped": skipped,
            },
            success=True,
            conversations=conversations,
            messages=messages,
        )
