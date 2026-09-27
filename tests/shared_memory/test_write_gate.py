"""Process-local write gate."""

import asyncio

import pytest

from basic_memory.shared_memory.write_gate import canonical_write_slot


@pytest.mark.asyncio
async def test_gate_disabled_is_noop() -> None:
    async with canonical_write_slot(enabled=False):
        pass


@pytest.mark.asyncio
async def test_gate_serializes_when_enabled() -> None:
    order: list[int] = []

    async def worker(n: int) -> None:
        async with canonical_write_slot(enabled=True):
            order.append(n)
            await asyncio.sleep(0.01)
            order.append(n)

    await asyncio.gather(worker(1), worker(2))
    # Each worker's enter/exit pair is contiguous when serialized.
    assert order in ([1, 1, 2, 2], [2, 2, 1, 1])
