"""Claude Code JSONL transcripts become conversation notes."""

import json
from pathlib import Path

import pytest

from basic_memory.importers.claude_transcripts_importer import (
    ClaudeTranscriptsImporter,
    parse_claude_transcript,
    render_transcript,
    transcript_files,
)
from basic_memory.markdown.schemas import EntityMarkdown

SESSION = "3f9a2b1c-4d5e-6f70-8a9b-0c1d2e3f4a5b"


def _line(**fields: object) -> str:
    return json.dumps(fields)


def _transcript_text() -> str:
    base = {
        "sessionId": SESSION,
        "cwd": "/Users/dev/vault",
        "gitBranch": "main",
        "version": "1.0.0",
    }
    return "\n".join(
        [
            _line(type="summary", summary="Planning the shared-memory fork", leafUuid="x"),
            _line(
                **base,
                type="user",
                timestamp="2026-09-20T10:00:00Z",
                message={"role": "user", "content": "Let's plan the fork."},
            ),
            _line(
                **base,
                type="assistant",
                timestamp="2026-09-20T10:00:05Z",
                message={
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Here is the plan."},
                        {"type": "tool_use", "name": "Read", "input": {}},
                    ],
                },
            ),
            _line(
                **base,
                type="user",
                isMeta=True,
                message={"role": "user", "content": "<injected system reminder>"},
            ),
            _line(
                **base,
                type="user",
                toolUseResult={"ok": True},
                message={"role": "user", "content": [{"type": "tool_result", "content": "..."}]},
            ),
            _line(
                **base,
                type="assistant",
                isSidechain=True,
                message={"role": "assistant", "content": "subagent chatter"},
            ),
            "not json at all",
            _line(
                **base,
                type="user",
                timestamp="2026-09-20T10:05:00Z",
                message={"role": "user", "content": "Ship it."},
            ),
        ]
    )


def test_parse_keeps_human_and_assistant_prose_only() -> None:
    transcript = parse_claude_transcript(_transcript_text(), fallback_session_id="fallback")
    assert transcript.session_id == SESSION
    assert transcript.summary == "Planning the shared-memory fork"
    assert transcript.cwd == "/Users/dev/vault"
    assert transcript.git_branch == "main"
    assert [role for role, _, _ in transcript.turns] == ["user", "assistant", "user"]
    assert transcript.turns[1][1] == "Here is the plan."
    assert transcript.started is not None and transcript.started.isoformat().startswith(
        "2026-09-20T10:00:00"
    )
    assert transcript.ended is not None and transcript.ended.minute == 5
    assert transcript.title == "Planning the shared-memory fork"


def test_render_transcript_frontmatter_and_body() -> None:
    transcript = parse_claude_transcript(_transcript_text(), fallback_session_id="fallback")
    entity = render_transcript(transcript, permalink="conversations/claude-code/plan")
    meta = entity.frontmatter.metadata
    assert meta["type"] == "conversation"
    assert meta["source"] == "claude-code"
    assert meta["claude_session_id"] == SESSION
    assert meta["message_count"] == 3
    assert meta["git_branch"] == "main"
    assert entity.content is not None
    assert "### user (2026-09-20 10:00)" in entity.content
    assert "subagent chatter" not in entity.content
    assert "<injected system reminder>" not in entity.content


def test_title_falls_back_to_first_user_message() -> None:
    text = _line(
        type="user",
        sessionId="abc",
        message={"role": "user", "content": "A very specific question about SQLite WAL mode"},
    )
    transcript = parse_claude_transcript(text, fallback_session_id="abc")
    assert transcript.title.startswith("A very specific question")


def test_transcript_files_skips_subagents(tmp_path: Path) -> None:
    project = tmp_path / "-Users-dev-vault"
    (project / SESSION / "subagents").mkdir(parents=True)
    (project / f"{SESSION}.jsonl").write_text("{}", encoding="utf-8")
    (project / SESSION / "subagents" / "agent-1.jsonl").write_text("{}", encoding="utf-8")
    (project / "notes.txt").write_text("x", encoding="utf-8")
    assert transcript_files(tmp_path) == [project / f"{SESSION}.jsonl"]
    assert transcript_files(project / f"{SESSION}.jsonl") == [project / f"{SESSION}.jsonl"]
    assert transcript_files(tmp_path / "missing") == []


class _Files:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.app_config = None

    async def write_file(self, file_path: str, content: str) -> str:
        self.files[file_path] = content
        return "checksum"

    async def ensure_directory(self, folder: str) -> None:
        return None

    async def exists(self, path: str) -> bool:
        return path in self.files


class _Processor:
    def to_markdown_string(self, entity: EntityMarkdown) -> str:
        meta = entity.frontmatter.metadata
        lines = ["---", *[f"{key}: {value}" for key, value in meta.items()], "---", ""]
        lines.append(entity.content or "")
        return "\n".join(lines)


@pytest.mark.asyncio
async def test_import_writes_one_note_per_session_and_skips_existing(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "-Users-dev-vault"
    project.mkdir(parents=True)
    (project / f"{SESSION}.jsonl").write_text(_transcript_text(), encoding="utf-8")
    (project / "empty.jsonl").write_text(
        _line(type="assistant", message={"role": "assistant", "content": "no human here"}),
        encoding="utf-8",
    )
    files = _Files()
    importer = ClaudeTranscriptsImporter(tmp_path, _Processor(), files)  # type: ignore[arg-type]
    result = await importer.import_data(tmp_path / "projects", "conversations/claude-code")
    assert result.success
    assert result.conversations == 1
    assert result.messages == 3
    assert result.import_count["skipped"] == 1
    [path] = files.files
    assert path.startswith("conversations/claude-code/20260920-")
    assert path.endswith(f"-{SESSION[:8]}.md")
    assert "Ship it." in files.files[path]

    again = await importer.import_data(tmp_path / "projects", "conversations/claude-code")
    assert again.conversations == 0
    assert again.import_count["skipped"] == 2

    rewritten = await importer.import_data(
        tmp_path / "projects", "conversations/claude-code", skip_existing=False
    )
    assert rewritten.conversations == 1


@pytest.mark.asyncio
async def test_import_missing_source_is_an_error(tmp_path: Path) -> None:
    importer = ClaudeTranscriptsImporter(tmp_path, _Processor(), _Files())  # type: ignore[arg-type]
    result = await importer.import_data(tmp_path / "nope", "conversations")
    assert not result.success
    assert "No Claude Code transcripts" in (result.error_message or "")
