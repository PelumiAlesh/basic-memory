"""Conversation delivery throttling for bm brief."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from basic_memory.shared_memory.brief_delivery import (
    JsonBriefDeliveryStore,
    should_deliver_brief,
)


def test_should_deliver_when_never_delivered() -> None:
    assert should_deliver_brief(None, refresh_hours=24, force=False)


def test_should_not_deliver_inside_refresh_window() -> None:
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    last = now - timedelta(hours=1)
    assert not should_deliver_brief(last, refresh_hours=24, force=False, now=now)


def test_force_delivers_inside_refresh_window() -> None:
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    last = now - timedelta(minutes=5)
    assert should_deliver_brief(last, refresh_hours=24, force=True, now=now)


def test_json_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "brief-delivery.json"
    store = JsonBriefDeliveryStore(path)
    state = store.load()
    when = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    state.record("conv-1", when)
    store.save(state)
    loaded = store.load()
    assert loaded.last_delivered_at("conv-1") == when
