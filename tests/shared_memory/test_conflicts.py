"""Conflict flags, supersedes targets, and inactive-status search exclusion."""

from basic_memory.repository.search_filters import (
    SQLITE_FILTER_DIALECT,
    shared_filter_conditions,
)
from basic_memory.repository.search_query import PreparedSearchQuery
from basic_memory.repository.search_scope import ProjectScope
from basic_memory.schemas.search import SearchQuery
from basic_memory.services.search_service import prepare_search_query
from basic_memory.shared_memory.conflicts import (
    format_possible_conflicts,
    supersedes_targets,
    wants_conflict_check,
)


def test_conflict_check_is_only_for_decision_and_preference() -> None:
    assert wants_conflict_check("Decision", enabled=True)
    assert wants_conflict_check("preference", enabled=True)
    assert not wants_conflict_check("note", enabled=True)
    assert not wants_conflict_check("decision", enabled=False)


def test_supersedes_targets_dedupes_metadata_and_content() -> None:
    targets = supersedes_targets(
        {"supersedes": ["old-decision", "other"]},
        {"supersedes": "old-decision"},
    )
    assert targets == ["old-decision", "other"]
    assert supersedes_targets({"supersedes": "  "}) == []
    assert supersedes_targets(None, None) == []


def test_format_possible_conflicts() -> None:
    text = format_possible_conflicts([("Use SQLite", "decisions/sqlite")])
    assert "possible conflict" in text
    assert "Use SQLite" in text
    assert format_possible_conflicts([]) == ""


def test_prepare_search_excludes_inactive_unless_opted_in() -> None:
    prepared = prepare_search_query(SearchQuery(text="memory"))
    assert prepared is not None
    assert prepared.exclude_statuses == ("archived", "superseded")

    opted_in = prepare_search_query(SearchQuery(text="memory", include_inactive=True))
    assert opted_in is not None
    assert opted_in.exclude_statuses is None

    explicit = prepare_search_query(SearchQuery(text="memory", status="superseded"))
    assert explicit is not None
    assert explicit.exclude_statuses is None

    permalink = prepare_search_query(SearchQuery(permalink="decisions/old"))
    assert permalink is not None
    assert permalink.exclude_statuses is None


def test_inactive_exclusion_keeps_null_status() -> None:
    params: dict[str, object] = {}
    conditions = shared_filter_conditions(
        ProjectScope.single(1),
        params,
        dialect=SQLITE_FILTER_DIALECT,
        query=PreparedSearchQuery(
            search_text="memory", exclude_statuses=("archived", "superseded")
        ),
        candidate_keys=None,
    )
    sql = " ".join(conditions)
    assert "NOT EXISTS" in sql
    assert "COALESCE" in sql
    assert "inactive_note" in sql
    assert params["inactive_status_0"] == "archived"
    assert params["inactive_status_1"] == "superseded"
