"""Track the last captured turn per harness conversation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from basic_memory.config_models import _secure_config_file


@dataclass(slots=True)
class CaptureState:
    conversations: dict[str, str]

    @classmethod
    def empty(cls) -> CaptureState:
        return cls(conversations={})

    def last_turn(self, conversation_id: str) -> str | None:
        return self.conversations.get(conversation_id)

    def record_turn(self, conversation_id: str, turn_id: str) -> None:
        self.conversations[conversation_id] = turn_id


def state_path(project_path: Path) -> Path:
    return project_path / ".basic-memory" / "session-capture-state.json"


class JsonCaptureStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> CaptureState:
        if not self._path.is_file():
            return CaptureState.empty()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        conversations = data.get("conversations", {})
        if not isinstance(conversations, dict):
            return CaptureState.empty()
        return CaptureState(conversations={str(k): str(v) for k, v in conversations.items()})

    def save(self, state: CaptureState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"conversations": state.conversations}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _secure_config_file(self._path)
