"""Process-local single-writer gate for canonical MCP note writes.

SQLite WAL already allows concurrent readers. This gate only serializes the
MCP write/edit/move/delete path inside one shared server process so two
clients cannot interleave materialization of the same note. It does not take
database row locks and does not wrap derived-state transactions.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

_write_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


@asynccontextmanager
async def canonical_write_slot(*, enabled: bool) -> AsyncIterator[None]:
    """Hold the process write lock when shared-server mode is on; else no-op."""
    if not enabled:
        yield
        return
    async with _lock():
        yield
