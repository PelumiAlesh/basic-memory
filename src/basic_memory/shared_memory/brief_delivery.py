"""Per-conversation brief delivery timestamps under the project tree."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol


def project_delivery_path(project_path: Path) -> Path:
    """Default JSON store: ``<project>/.basic-memory/brief-delivery.json``."""
    return project_path / ".basic-memory" / "brief-delivery.json"


def should_deliver_brief(
    last_delivered_at: datetime | None,
    *,
    refresh_hours: float,
    force: bool,
    now: datetime | None = None,
) -> bool:
    """Return whether a new brief should be printed for this conversation."""
    if force:
        return True
    if last_delivered_at is None:
        return True
    clock = now or datetime.now(timezone.utc)
    if last_delivered_at.tzinfo is None:
        last_delivered_at = last_delivered_at.replace(tzinfo=timezone.utc)
    return clock - last_delivered_at >= timedelta(hours=refresh_hours)


@dataclass(slots=True)
class BriefDeliveryState:
    conversations: dict[str, str]

    @classmethod
    def empty(cls) -> BriefDeliveryState:
        return cls(conversations={})

    def last_delivered_at(self, conversation_id: str) -> datetime | None:
        raw = self.conversations.get(conversation_id)
        if not raw:
            return None
        return datetime.fromisoformat(raw)

    def record(self, conversation_id: str, when: datetime) -> None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        self.conversations[conversation_id] = when.isoformat()


class BriefDeliveryStore(Protocol):
    def load(self) -> BriefDeliveryState: ...

    def save(self, state: BriefDeliveryState) -> None: ...


class JsonBriefDeliveryStore:
    """JSON file store; callers may substitute another BriefDeliveryStore implementation."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> BriefDeliveryState:
        if not self._path.is_file():
            return BriefDeliveryState.empty()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        conversations = data.get("conversations", {})
        if not isinstance(conversations, dict):
            return BriefDeliveryState.empty()
        return BriefDeliveryState(
            conversations={str(key): str(value) for key, value in conversations.items()}
        )

    def save(self, state: BriefDeliveryState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"conversations": state.conversations}
        self._path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
