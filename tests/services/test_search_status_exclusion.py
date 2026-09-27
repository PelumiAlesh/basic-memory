"""Excluded frontmatter statuses reach the SQL that runs, on SQLite and Postgres.

The first version of this filter was prepared and then dropped on the way to the
repository, so no search ever hid anything. These tests run the real statement through
``SearchService`` and check which notes come back, which only passes if the exclusion
survives every handoff down to the query.
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from basic_memory import db
from basic_memory.models.knowledge import Entity
from basic_memory.repository.search_filters import (
    SQLITE_FILTER_DIALECT,
    shared_filter_conditions,
)
from basic_memory.repository.search_index_row import SearchIndexRow
from basic_memory.repository.search_query import PreparedSearchQuery
from basic_memory.repository.search_scope import ProjectScope
from basic_memory.schemas.search import SearchItemType, SearchQuery

EXCLUDED = ["superseded", "archived"]


async def _index_note(
    search_repository,
    session_maker,
    title: str,
    metadata: dict[str, object],
    *,
    observation: str | None = None,
) -> Entity:
    slug = "-".join(title.lower().split())
    now = datetime.now(timezone.utc)
    async with db.scoped_session(session_maker) as session:
        entity = Entity(
            project_id=search_repository.project_id,
            title=title,
            note_type="decision",
            permalink=f"decisions/{slug}",
            file_path=f"decisions/{slug}.md",
            content_type="text/markdown",
            entity_metadata=metadata,
            created_at=now,
            updated_at=now,
        )
        session.add(entity)
        await session.flush()

    rows = [
        SearchIndexRow(
            project_id=search_repository.project_id,
            id=entity.id,
            type=SearchItemType.ENTITY.value,
            title=entity.title,
            content_stems=f"lighthouse {title}",
            content_snippet=f"lighthouse {title}",
            permalink=entity.permalink,
            file_path=entity.file_path,
            entity_id=entity.id,
            metadata={"note_type": entity.note_type},
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
    ]
    if observation is not None:
        rows.append(
            SearchIndexRow(
                project_id=search_repository.project_id,
                id=entity.id,
                type=SearchItemType.OBSERVATION.value,
                title=f"decision: {observation}",
                content_stems=observation,
                content_snippet=observation,
                permalink=f"{entity.permalink}/observations/decision/{slug}",
                file_path=entity.file_path,
                entity_id=entity.id,
                category="decision",
                metadata={"tags": []},
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
        )
    await search_repository.bulk_index_items(rows)
    return entity


@pytest_asyncio.fixture
async def notes(search_repository, session_maker) -> dict[str, Entity]:
    """One note per status shape the exclusion has to tell apart."""
    return {
        "active": await _index_note(
            search_repository, session_maker, "Keep the light on", {"status": "active"}
        ),
        "none": await _index_note(search_repository, session_maker, "Paint the tower", {}),
        "superseded": await _index_note(
            search_repository, session_maker, "Use oil lamps", {"status": "superseded"}
        ),
        "archived": await _index_note(
            search_repository, session_maker, "Hire a keeper", {"status": "archived"}
        ),
        "capitalized": await _index_note(
            search_repository, session_maker, "Ring the bell", {"status": "Superseded"}
        ),
    }


def _ids(rows) -> set[int]:
    return {row.id for row in rows}


@pytest.mark.asyncio
async def test_default_search_returns_every_status(search_service, notes) -> None:
    query = SearchQuery(text="lighthouse", entity_types=[SearchItemType.ENTITY])

    assert _ids(await search_service.search(query)) == {note.id for note in notes.values()}
    assert await search_service.count(query) == len(notes)


@pytest.mark.asyncio
async def test_excluded_statuses_drop_out_of_text_search_and_count(search_service, notes) -> None:
    # A text query compiles to FTS MATCH on SQLite, which refuses a correlated
    # subquery beside it; this is the shape the exclusion must compose with.
    query = SearchQuery(
        text="lighthouse", entity_types=[SearchItemType.ENTITY], exclude_statuses=EXCLUDED
    )

    assert _ids(await search_service.search(query)) == {
        notes["active"].id,
        notes["none"].id,
    }
    assert await search_service.count(query) == 2


@pytest.mark.asyncio
async def test_exclusion_composes_with_metadata_filters(
    search_repository, session_maker, search_service, notes
) -> None:
    kept = await _index_note(
        search_repository, session_maker, "Log the storms", {"status": "open", "area": "log"}
    )
    await _index_note(
        search_repository,
        session_maker,
        "Log by candle",
        {"status": "archived", "area": "log"},
    )
    query = SearchQuery(
        text="lighthouse",
        metadata_filters={"area": "log"},
        exclude_statuses=EXCLUDED,
    )

    assert _ids(await search_service.search(query)) == {kept.id}
    assert await search_service.count(query) == 1


@pytest.mark.asyncio
async def test_excluded_note_takes_its_observations_with_it(
    search_repository, session_maker, search_service
) -> None:
    kept = await _index_note(
        search_repository,
        session_maker,
        "Beam north",
        {"status": "open"},
        observation="point the beam north",
    )
    await _index_note(
        search_repository,
        session_maker,
        "Beam south",
        {"status": "superseded"},
        observation="point the beam south",
    )
    query = SearchQuery(
        text="beam",
        entity_types=[SearchItemType.OBSERVATION],
        exclude_statuses=EXCLUDED,
    )

    assert {row.entity_id for row in await search_service.search(query)} == {kept.id}


@pytest.mark.asyncio
async def test_exclusion_reaches_the_full_text_backend(
    search_repository, search_service, notes, monkeypatch
) -> None:
    """The prepared exclusion is what the backend compiles, not a service-side copy."""
    seen: list[PreparedSearchQuery] = []
    backend_search = search_repository._fts.search
    backend_count = search_repository._fts.count

    async def recording_search(scope, query, **kwargs):
        seen.append(query)
        return await backend_search(scope, query, **kwargs)

    async def recording_count(scope, query, **kwargs):
        seen.append(query)
        return await backend_count(scope, query, **kwargs)

    monkeypatch.setattr(search_repository._fts, "search", recording_search)
    monkeypatch.setattr(search_repository._fts, "count", recording_count)
    query = SearchQuery(text="lighthouse", exclude_statuses=["Archived", "superseded"])

    await search_service.search(query)
    await search_service.count(query)

    assert [prepared.exclude_statuses for prepared in seen] == [
        ("archived", "superseded"),
        ("archived", "superseded"),
    ]


def test_search_query_normalizes_excluded_statuses() -> None:
    query = SearchQuery(text="x", exclude_statuses=[" Superseded ", "archived", "", "SUPERSEDED"])

    assert query.exclude_statuses == ["superseded", "archived"]
    assert SearchQuery(text="x", exclude_statuses=[]).exclude_statuses is None
    # An exclusion narrows a search; on its own it asks for nothing.
    assert SearchQuery(exclude_statuses=["archived"]).no_criteria()


def test_unfiltered_query_compiles_no_status_predicate() -> None:
    """With no exclusion the shared WHERE clause is exactly what it was before."""
    params: dict[str, object] = {}
    conditions = shared_filter_conditions(
        ProjectScope.single(1),
        params,
        dialect=SQLITE_FILTER_DIALECT,
        query=PreparedSearchQuery(search_text="lighthouse"),
        candidate_keys=None,
    )

    assert conditions == ["search_index.project_id IN (:scope_0)"]
    assert params == {"scope_0": 1}


def test_exclusion_counts_as_a_filter_for_semantic_retrieval() -> None:
    # Vector and hybrid search only run their structured-filter pass when this is true.
    assert PreparedSearchQuery(search_text="x", exclude_statuses=("archived",)).has_filters
    assert not PreparedSearchQuery(search_text="x").has_filters
