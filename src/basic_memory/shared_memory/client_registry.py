"""In-process registry of MCP clients seen by the shared server.

Tracks client slug (bearer token client or clientInfo), last seen time, and
last write title/permalink. Never stores tokens. Used by the `list_clients`
tool and `bm status --shared` surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock

_lock = Lock()


@dataclass
class ClientSighting:
    """One connected or recently active MCP client identity."""

    client: str
    first_seen: str
    last_seen: str
    request_count: int = 0
    last_write_title: str | None = None
    last_write_permalink: str | None = None
    last_write_at: str | None = None


@dataclass
class ClientRegistry:
    """Mutable registry keyed by client slug."""

    _clients: dict[str, ClientSighting] = field(default_factory=dict)

    def touch(self, client: str | None) -> None:
        if not client:
            return
        now = datetime.now(tz=timezone.utc).isoformat()
        with _lock:
            existing = self._clients.get(client)
            if existing is None:
                self._clients[client] = ClientSighting(
                    client=client,
                    first_seen=now,
                    last_seen=now,
                    request_count=1,
                )
                return
            existing.last_seen = now
            existing.request_count += 1

    def record_write(
        self,
        client: str | None,
        *,
        title: str | None = None,
        permalink: str | None = None,
    ) -> None:
        if not client:
            return
        self.touch(client)
        now = datetime.now(tz=timezone.utc).isoformat()
        with _lock:
            sighting = self._clients[client]
            sighting.last_write_at = now
            if title:
                sighting.last_write_title = title
            if permalink:
                sighting.last_write_permalink = permalink

    def snapshot(self) -> list[ClientSighting]:
        with _lock:
            return sorted(
                (
                    ClientSighting(
                        client=item.client,
                        first_seen=item.first_seen,
                        last_seen=item.last_seen,
                        request_count=item.request_count,
                        last_write_title=item.last_write_title,
                        last_write_permalink=item.last_write_permalink,
                        last_write_at=item.last_write_at,
                    )
                    for item in self._clients.values()
                ),
                key=lambda item: item.client,
            )

    def clear(self) -> None:
        with _lock:
            self._clients.clear()


_REGISTRY = ClientRegistry()


def client_registry() -> ClientRegistry:
    return _REGISTRY


def format_client_report(clients: list[ClientSighting]) -> str:
    """Human-readable report; never includes secrets."""
    if not clients:
        return "No MCP clients have connected to this process yet."
    lines = ["# Connected MCP clients", ""]
    for item in clients:
        lines.append(f"## {item.client}")
        lines.append(f"- first_seen: {item.first_seen}")
        lines.append(f"- last_seen: {item.last_seen}")
        lines.append(f"- requests: {item.request_count}")
        if item.last_write_at:
            lines.append(f"- last_write_at: {item.last_write_at}")
        if item.last_write_title:
            lines.append(f"- last_write: {item.last_write_title}")
        if item.last_write_permalink:
            lines.append(f"- last_write_permalink: {item.last_write_permalink}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
