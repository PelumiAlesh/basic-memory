"""Session capture tests."""

import json
from pathlib import Path

import pytest

from basic_memory.config import ConfigManager, ProjectEntry, ProjectMode
from basic_memory.session_capture.capture import handle_stop_event
from basic_memory.session_capture.redact import redact_payload
from basic_memory.session_capture.state import JsonCaptureStateStore, state_path


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "cfg"
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(home))
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    manager = ConfigManager()
    config = manager.config.model_copy(deep=True)
    config.session_capture_enabled = True
    config.default_project = "main"
    config.projects["main"] = ProjectEntry(path=str(vault_path), mode=ProjectMode.LOCAL)
    manager.save_config(config)
    return vault_path


def test_redact_truncates_long_tool_output() -> None:
    payload = {"tool_output": "x" * 5_000}
    redacted = redact_payload(payload)
    assert len(redacted["tool_output"]) < 5_000


def test_capture_appends_only_new_turns(vault: Path) -> None:
    payload = {"turn_id": "t1", "status": "completed", "prompt": "hello"}
    handle_stop_event(payload, harness="cursor", conversation_id="conv-a")
    note = vault / "inbox" / "session-conv-a.md"
    assert note.is_file()
    first_size = note.stat().st_size

    handle_stop_event(payload, harness="cursor", conversation_id="conv-a")
    assert note.stat().st_size == first_size

    handle_stop_event({**payload, "turn_id": "t2"}, harness="cursor", conversation_id="conv-a")
    assert note.stat().st_size > first_size

    store = JsonCaptureStateStore(state_path(vault))
    assert store.load().last_turn("conv-a") == "t2"


def test_capture_disabled_is_noop(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ConfigManager()
    config = manager.config.model_copy(deep=True)
    config.session_capture_enabled = False
    manager.save_config(config)
    handle_stop_event({"turn_id": "t1"}, harness="cursor", conversation_id="conv-b")
    assert not (vault / "inbox").exists()
