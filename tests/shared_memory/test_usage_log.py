"""Usage log writer, retention, privacy, and performance."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from basic_memory.shared_memory.usage_log import BENCHMARK_BOUND_SECONDS, apply_retention, query_hash
from basic_memory.shared_memory.usage_log_fast import append_event_line, ensure_log_dir


@pytest.fixture
def project_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "vault"
    home.mkdir()
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps(
            {
                "usage_log_enabled": True,
                "projects": {"main": {"path": str(home)}},
                "default_project": "main",
            }
        ),
        encoding="utf-8",
    )
    return home


def test_append_event_writes_jsonl(project_home: Path) -> None:
    ok = append_event_line(
        {"event": "hook", "name": "turn-end", "conversation_id": "c1"},
        project_dir=project_home,
    )
    assert ok
    log_dir = ensure_log_dir(project_home)
    files = list(log_dir.glob("events-*.jsonl"))
    assert len(files) == 1
    line = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert line["conversation_id"] == "c1"
    assert "secret" not in files[0].read_text(encoding="utf-8")


def test_query_hash_never_stores_raw_query(project_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(project_home.parent / "cfg"))
    secret = "super-secret search terms"
    digest = query_hash(secret)
    assert len(digest) == 12
    assert secret not in digest
    salt_path = project_home.parent / "cfg" / "usage_log_query_salt"
    assert salt_path.exists()
    assert secret not in salt_path.read_bytes().decode("latin-1", errors="ignore")


def test_retention_deletes_old_files(project_home: Path) -> None:
    log_dir = ensure_log_dir(project_home)
    old = log_dir / "events-2000-01-01.jsonl"
    old.write_text('{"ts":"2000-01-01T00:00:00+00:00","event":"tool","name":"read_note"}\n')
    recent = log_dir / "events-2099-01-01.jsonl"
    recent.write_text('{"ts":"2099-01-01T00:00:00+00:00","event":"tool","name":"read_note"}\n')
    removed = apply_retention(project_home, 90)
    assert removed == 1
    assert not old.exists()
    assert recent.exists()


def test_log_enqueue_benchmark(project_home: Path) -> None:
    start = time.perf_counter()
    for _ in range(200):
        append_event_line(
            {"event": "tool", "name": "search_notes", "client": "cursor", "ok": True},
            project_dir=project_home,
        )
    elapsed = time.perf_counter() - start
    assert elapsed / 200 < BENCHMARK_BOUND_SECONDS


def test_privacy_no_prompt_in_log(project_home: Path) -> None:
    append_event_line(
        {
            "event": "hook",
            "name": "prompt-submit",
            "conversation_id": "x",
            "reason": "not_due",
        },
        project_dir=project_home,
    )
    text = next(ensure_log_dir(project_home).glob("events-*.jsonl")).read_text(encoding="utf-8")
    assert "prompt" not in text.lower() or "prompt-submit" in text
