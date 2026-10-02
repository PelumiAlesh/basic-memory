"""Excluded statuses reach the semantic retrieval modes too.

Vector and hybrid search rank embeddings and then intersect the candidates with an
FTS-mode pass that carries every structured filter, so an exclusion is honored there
only if it counts as a filter and is forwarded to that pass.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from basic_memory.repository.search_index_row import SearchIndexRow
from basic_memory.repository.search_query import PreparedSearchQuery
from basic_memory.repository.search_reader import CandidateWindow, SemanticSearch, WindowChunk
from basic_memory.repository.search_scope import ProjectScope
from tests.repository.test_hybrid_fusion import (
    HYBRID_QUERY,
    FakeFts,
    FakeRow as HybridFakeRow,
    fake_vector_retrieval,
)
from tests.repository.test_vector_threshold import (
    VECTOR_QUERY,
    FakeRow,
    _make_vector_rows,
    run_vector_only,
    vector_semantic,
)

EXCLUDED = ("superseded", "archived")


@pytest.mark.asyncio
async def test_exclusion_applies_in_vector_mode():
    # Three neighbours; the filter pass admits only entity 2, as if 0 and 1 were superseded.
    filter_pass = FakeFts([FakeRow(id=2)])
    semantic = vector_semantic(fts=filter_pass)

    results = await run_vector_only(
        semantic,
        _make_vector_rows([0.9, 0.8, 0.7]),
        AsyncMock(return_value={("entity", i): FakeRow(id=i) for i in range(3)}),
        query=replace(VECTOR_QUERY, exclude_statuses=EXCLUDED),
    )

    assert [row.id for row in results] == [2]
    assert len(filter_pass.queries) == 1
    assert filter_pass.queries[0].exclude_statuses == EXCLUDED
    assert filter_pass.calls[0]["candidate_keys"] == [("entity", 0), ("entity", 1), ("entity", 2)]


@pytest.mark.asyncio
async def test_exclusion_applies_in_hybrid_mode():
    fts_leg = FakeFts([HybridFakeRow(id=1, score=5.0, title="current")])
    semantic = SemanticSearch(
        cast(Any, None), ProjectScope.single(1), fts_leg, fake_vector_retrieval()
    )
    row = SearchIndexRow(
        project_id=1,
        id=1,
        type="entity",
        file_path="current.md",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        title="current",
        score=0.9,
    )
    seen: list[PreparedSearchQuery] = []

    async def vector_window(
        query: PreparedSearchQuery,
        _candidate_limit: int,
        *,
        trace: object = None,
    ) -> CandidateWindow:
        # Hybrid no longer calls vector_only. The vector leg is this window, and
        # the exclusion has to arrive on the query that builds it.
        seen.append(query)
        key = (row.type, row.id)
        return CandidateWindow(
            similarity_by_key={key: 0.9},
            chunks_by_key={key: [WindowChunk(position=0, similarity=0.9, text="current")]},
            rows={key: row},
            chunk_count=1,
        )

    with patch.object(semantic, "_vector_window", vector_window):
        results = await semantic.hybrid(
            replace(HYBRID_QUERY, exclude_statuses=EXCLUDED), limit=10, offset=0
        )

    assert [row.id for row in results] == [1]
    assert fts_leg.queries[0].exclude_statuses == EXCLUDED
    assert seen, "vector window was never built"
    assert seen[0].exclude_statuses == EXCLUDED
