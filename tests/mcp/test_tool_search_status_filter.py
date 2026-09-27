"""search_exclude_inactive through search_notes and grep: off by default, opt-out per call.

These run real notes through the MCP tools, the API, and the SQL, so a status the
exclusion never reaches would show up as a note that should have been hidden.
"""

import importlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from basic_memory.mcp.tools import grep, read_note, search_notes, write_note
from basic_memory.schemas.search import SearchResponse
from tests.mcp.tools.test_search_notes_multi_project import ALPHA, _install_scoped_search

# `basic_memory.mcp.tools.search` is also the name of the ChatGPT search tool that
# the package re-exports, so reach the module itself through sys.modules.
search_module = sys.modules["basic_memory.mcp.tools.search"]

EVERY_STATUS = {"Current beacon", "Open beacon", "Old beacon", "Retired beacon"}
ACTIVE = {"Current beacon", "Open beacon"}


@pytest.fixture
def exclude_inactive(monkeypatch, app_config):
    """Turn search_exclude_inactive on for the tools, as the MCP container would."""
    config = app_config.model_copy(update={"search_exclude_inactive": True})
    monkeypatch.setattr(search_module, "get_container", lambda: SimpleNamespace(config=config))


@pytest_asyncio.fixture
async def beacons(client, test_project):
    """Four decisions about the same lighthouse, one per status shape."""
    for title, status in (
        ("Current beacon", None),
        ("Open beacon", "open"),
        ("Old beacon", "superseded"),
        ("Retired beacon", "archived"),
    ):
        await write_note(
            project=test_project.name,
            title=title,
            directory="decisions",
            content=f"# {title}\n\nThe harbour lighthouse runs on {title.lower()}.",
            metadata={"status": status} if status else None,
        )
    return test_project


def _titles(response: dict[str, Any] | str) -> set[str]:
    assert isinstance(response, dict), response
    return {row["title"] for row in response["results"]}


async def _search(project: str, **kwargs: Any) -> set[str]:
    kwargs.setdefault("query", "lighthouse")
    kwargs.setdefault("search_type", "text")
    return _titles(await search_notes(project=project, output_format="json", **kwargs))


def test_search_exclude_inactive_is_off_by_default(app_config) -> None:
    assert app_config.search_exclude_inactive is False
    assert search_module.inactive_statuses_to_exclude(include_inactive=False) == ()


@pytest.mark.asyncio
async def test_default_search_returns_every_status(beacons) -> None:
    assert await _search(beacons.name) == EVERY_STATUS


@pytest.mark.asyncio
async def test_default_request_carries_no_exclusion(beacons, monkeypatch) -> None:
    clients_mod = importlib.import_module("basic_memory.mcp.clients")
    payloads: list[dict[str, Any]] = []

    class RecordingSearchClient:
        def __init__(self, *args: Any) -> None:
            pass

        async def search(self, payload: dict[str, Any], page: int, page_size: int):
            payloads.append(payload)
            return SearchResponse(results=[], current_page=page, page_size=page_size)

    monkeypatch.setattr(clients_mod, "SearchClient", RecordingSearchClient)

    await search_notes(project=beacons.name, query="lighthouse", search_type="text")
    await grep(pattern="lighthouse", literal=True, project=beacons.name)

    assert [payload["exclude_statuses"] for payload in payloads] == [None, None]


@pytest.mark.asyncio
async def test_on_hides_superseded_and_archived_notes(beacons, exclude_inactive) -> None:
    assert await _search(beacons.name) == ACTIVE
    assert await _search(beacons.name, search_type="title", query="beacon") == ACTIVE


@pytest.mark.asyncio
async def test_include_inactive_opts_one_search_back_in(beacons, exclude_inactive) -> None:
    assert await _search(beacons.name, include_inactive=True) == EVERY_STATUS


@pytest.mark.asyncio
async def test_status_filters_still_find_inactive_notes(beacons, exclude_inactive) -> None:
    assert await _search(beacons.name, status="superseded") == {"Old beacon"}
    assert await _search(beacons.name, metadata_filters={"status": "archived"}) == {
        "Retired beacon"
    }


@pytest.mark.asyncio
async def test_exact_permalink_still_finds_an_inactive_note(beacons, exclude_inactive) -> None:
    permalink = f"{beacons.name}/decisions/old-beacon"

    assert await _search(beacons.name, query=permalink, search_type="permalink") == {"Old beacon"}


@pytest.mark.asyncio
async def test_grep_follows_the_same_setting(beacons, exclude_inactive) -> None:
    hidden = await grep(pattern="lighthouse", literal=True, project=beacons.name)
    shown = await grep(
        pattern="lighthouse", literal=True, project=beacons.name, include_inactive=True
    )

    assert _titles(hidden) == ACTIVE
    assert _titles(shown) == EVERY_STATUS


@pytest.mark.asyncio
async def test_all_projects_search_sends_the_exclusion(monkeypatch, exclude_inactive) -> None:
    _, calls = _install_scoped_search(
        monkeypatch,
        [ALPHA],
        lambda workspace, project_ids, page, page_size: SearchResponse(
            results=[], current_page=page, page_size=page_size
        ),
    )

    await search_notes(query="lighthouse", search_type="text", search_all_projects=True)
    await search_notes(
        query="lighthouse", search_type="text", search_all_projects=True, include_inactive=True
    )

    assert [call["payload"]["exclude_statuses"] for call in calls] == [
        ["superseded", "archived"],
        None,
    ]


@pytest.mark.asyncio
async def test_supersedes_frontmatter_changes_no_other_note(beacons) -> None:
    """Declaring `supersedes` is only frontmatter: the named note keeps its own status."""
    await write_note(
        project=beacons.name,
        title="Solar beacon",
        directory="decisions",
        content="# Solar beacon\n\nThe harbour lighthouse runs on solar power.",
        metadata={"supersedes": ["Open beacon"], "status": "open"},
    )

    named = await read_note("decisions/open-beacon", project=beacons.name, output_format="json")

    assert isinstance(named, dict)
    assert named["frontmatter"]["status"] == "open"
    assert await _search(beacons.name, status="superseded") == {"Old beacon"}
