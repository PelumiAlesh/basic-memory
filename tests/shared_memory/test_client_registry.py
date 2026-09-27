"""In-process MCP client sightings."""

from basic_memory.shared_memory.client_registry import (
    ClientRegistry,
    format_client_report,
)


def test_touch_and_record_write() -> None:
    registry = ClientRegistry()
    registry.touch("cursor")
    registry.touch("cursor")
    registry.record_write("cursor", title="Hello", permalink="hello")
    registry.touch("chatgpt")
    snap = registry.snapshot()
    assert [item.client for item in snap] == ["chatgpt", "cursor"]
    cursor = snap[1]
    assert cursor.request_count == 3
    assert cursor.last_write_title == "Hello"
    assert cursor.last_write_permalink == "hello"
    report = format_client_report(snap)
    assert "cursor" in report
    assert "Hello" in report
    assert "secret" not in report
    assert "bearer" not in report.lower()


def test_empty_report() -> None:
    assert "No MCP clients" in format_client_report([])
