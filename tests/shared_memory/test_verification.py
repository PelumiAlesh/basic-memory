"""Read-back verdicts: bodies compare exactly, and the disk is checked only where it lives."""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastmcp.exceptions import ToolError

from basic_memory.config import BasicMemoryConfig, ProjectEntry, ProjectMode
from basic_memory.mcp import async_client
from basic_memory.schemas.project_info import ProjectItem
from basic_memory.schemas.v2.entity import EntityResponseV2
from basic_memory.shared_memory import verification
from basic_memory.shared_memory.verification import (
    Failed,
    Pending,
    Verified,
    compare_bodies,
    local_project_root,
    note_body,
    replay_edit,
    verification_failure_text,
    verification_line,
    verification_payload,
    verify_deleted_note,
    verify_moved_note,
    verify_saved_note,
)

PLAN = "---\ntitle: Plan\n---\n\n# Plan\n\nShip the parser first.\n"


def _note(
    content: str | None,
    *,
    file_path: str = "notes/plan.md",
    status: str | None = "synced",
    error: str | None = None,
) -> EntityResponseV2:
    now = datetime.now(timezone.utc)
    return EntityResponseV2(
        external_id="n1",
        id=1,
        title="Plan",
        note_type="note",
        file_path=file_path,
        content=content,
        created_at=now,
        updated_at=now,
        file_write_status=status,
        last_materialization_error=error,
    )


def _http_error(status_code: int) -> ToolError:
    request = httpx.Request("GET", "http://test/v2/projects/p/knowledge/entities/n1")
    error = ToolError(f"HTTP {status_code}")
    error.__cause__ = httpx.HTTPStatusError(
        "read back", request=request, response=httpx.Response(status_code, request=request)
    )
    return error


@dataclass
class FakeReader:
    """Answers get_entity with a fixed note, or with the HTTP error the API would raise."""

    note: EntityResponseV2 | None = None
    status_code: int = 404
    calls: int = 0

    async def get_entity(self, entity_id: str) -> EntityResponseV2:
        self.calls += 1
        if self.note is None:
            raise _http_error(self.status_code)
        return self.note


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def stuck_file_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A materialization drain that never finishes, with a wait short enough for tests."""

    async def never_drains() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(verification, "drain_pending_materializations", never_drains)
    monkeypatch.setattr(verification, "DRAIN_TIMEOUT_SECONDS", 0.01)


# --- Comparing bodies ---


def test_note_body_drops_frontmatter_bom_and_spacing() -> None:
    assert note_body("\ufeff" + PLAN) == "# Plan Ship the parser first."
    assert note_body("# Plan\n\n\nShip   it.\n") == "# Plan Ship it."


def test_note_body_keeps_an_unclosed_fence_as_body() -> None:
    assert note_body("---\ntitle: Plan\n\nNo closing fence.") == "--- title: Plan No closing fence."


def test_equal_bodies_pass() -> None:
    assert compare_bodies(expected="a b", stored="a b", inserted="a b") is None


def test_a_superset_is_not_a_match() -> None:
    failure = compare_bodies(expected="Ship it.", stored="Ship it. Extra.", inserted="Ship it.")

    assert failure is not None
    assert failure.reason == "mismatch"


def test_short_inserted_text_written_twice_is_duplicated() -> None:
    failure = compare_bodies(expected="Log: ok", stored="Log: ok ok", inserted="ok")

    assert failure == Failed(
        "duplicated", "the text this call wrote appears 2 times in the stored note instead of 1"
    )


def test_a_cut_short_body_is_truncated() -> None:
    failure = compare_bodies(expected="one two three", stored="one two", inserted="one two three")

    assert failure == Failed("truncated", "the stored body has 7 of the expected 13 characters")


def test_replay_edit_follows_the_edit_and_refuses_a_missing_anchor() -> None:
    edit = {"section": None, "expected_replacements": 1, "replace_subsections": False}

    appended = replay_edit(PLAN, operation="append", content="Then docs.", find_text=None, **edit)
    missing = replay_edit(PLAN, operation="find_replace", content="x", find_text="absent", **edit)

    assert appended is not None
    assert note_body(appended) == "# Plan Ship the parser first. Then docs."
    assert missing is None


# --- Saved notes ---


@pytest.mark.asyncio
async def test_saved_note_that_reads_back_whole_is_verified_in_the_index() -> None:
    reader = FakeReader(_note(PLAN))

    verdict = await verify_saved_note(
        reader,
        "n1",
        expected_markdown="# Plan\n\nShip the parser first.",
        inserted="",
        local_root=None,
    )

    assert verdict == Verified(disk_checked=False)


@pytest.mark.asyncio
async def test_an_empty_body_is_never_verified_and_is_not_read_back() -> None:
    reader = FakeReader(_note("---\ntitle: Plan\n---\n"))

    verdict = await verify_saved_note(
        reader, "n1", expected_markdown="---\ntitle: Plan\n---\n", inserted="", local_root=None
    )

    assert isinstance(verdict, Failed)
    assert verdict.reason == "empty"
    assert reader.calls == 0


@pytest.mark.asyncio
async def test_an_edit_that_cannot_be_replayed_is_a_mismatch() -> None:
    verdict = await verify_saved_note(
        FakeReader(_note(PLAN)), "n1", expected_markdown=None, inserted="x", local_root=None
    )

    assert verdict == Failed(
        "mismatch", "the note changed between the read before this edit and the edit itself"
    )


@pytest.mark.asyncio
async def test_a_note_gone_from_the_index_is_missing() -> None:
    verdict = await verify_saved_note(
        FakeReader(), "n1", expected_markdown=PLAN, inserted=PLAN, local_root=None
    )

    assert isinstance(verdict, Failed)
    assert verdict.reason == "missing"


@pytest.mark.asyncio
async def test_a_read_back_error_is_pending_not_failed() -> None:
    verdict = await verify_saved_note(
        FakeReader(status_code=500), "n1", expected_markdown=PLAN, inserted=PLAN, local_root=None
    )

    assert isinstance(verdict, Pending)
    assert "could not be read back" in verdict.detail


@pytest.mark.asyncio
async def test_the_file_on_disk_must_match_the_accepted_body(tmp_path: Path) -> None:
    restamped = "---\ntitle: Plan\nbm_source_client: cursor\n---\n# Plan\n\nShip the parser first."
    _write(tmp_path, "notes/plan.md", restamped)

    verdict = await verify_saved_note(
        FakeReader(_note(PLAN)), "n1", expected_markdown=PLAN, inserted=PLAN, local_root=tmp_path
    )

    assert verdict == Verified(disk_checked=True)


@pytest.mark.asyncio
async def test_a_differing_file_fails_with_its_write_status(tmp_path: Path) -> None:
    _write(tmp_path, "notes/plan.md", "# Plan\n\nShip the")
    reader = FakeReader(_note(PLAN, status="failed", error="disk full"))

    verdict = await verify_saved_note(
        reader, "n1", expected_markdown=PLAN, inserted=PLAN, local_root=tmp_path
    )

    assert verdict == Failed(
        "file_differs",
        "notes/plan.md on disk differs from the note (file write status: failed, disk full)",
    )


@pytest.mark.asyncio
async def test_a_missing_file_fails(tmp_path: Path) -> None:
    verdict = await verify_saved_note(
        FakeReader(_note(PLAN)), "n1", expected_markdown=PLAN, inserted=PLAN, local_root=tmp_path
    )

    assert verdict == Failed(
        "file_missing", "notes/plan.md is not on disk (file write status: synced)"
    )


@pytest.mark.asyncio
async def test_a_file_still_being_written_is_pending(tmp_path: Path) -> None:
    verdict = await verify_saved_note(
        FakeReader(_note(PLAN, status="writing")),
        "n1",
        expected_markdown=PLAN,
        inserted=PLAN,
        local_root=tmp_path,
    )

    assert isinstance(verdict, Pending)


@pytest.mark.asyncio
async def test_a_file_that_is_not_utf8_differs_instead_of_raising(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/plan.md").write_bytes(b"# Plan\n\n\xff\xfe")

    verdict = await verify_saved_note(
        FakeReader(_note(PLAN)), "n1", expected_markdown=PLAN, inserted=PLAN, local_root=tmp_path
    )

    assert isinstance(verdict, Failed)
    assert verdict.reason == "file_differs"


@pytest.mark.usefixtures("stuck_file_writer")
@pytest.mark.asyncio
async def test_a_stuck_file_writer_bounds_the_wait(tmp_path: Path) -> None:
    verdict = await asyncio.wait_for(
        verify_saved_note(
            FakeReader(_note(PLAN, status="pending")),
            "n1",
            expected_markdown=PLAN,
            inserted=PLAN,
            local_root=tmp_path,
        ),
        timeout=5,
    )

    assert isinstance(verdict, Pending)


# --- Moved notes ---


@pytest.mark.asyncio
async def test_a_move_without_a_prior_read_is_pending() -> None:
    verdict = await verify_moved_note(
        FakeReader(_note(PLAN)), "n1", before=None, destination="notes/plan.md", local_root=None
    )

    assert isinstance(verdict, Pending)


@pytest.mark.asyncio
async def test_a_move_indexed_elsewhere_is_a_mismatch() -> None:
    verdict = await verify_moved_note(
        FakeReader(_note(PLAN, file_path="notes/plan.md")),
        "n1",
        before=_note(PLAN, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=None,
    )

    assert verdict == Failed(
        "mismatch", "the index has the note at notes/plan.md, not archive/plan.md"
    )


@pytest.mark.asyncio
async def test_a_move_that_loses_the_body_is_truncated() -> None:
    verdict = await verify_moved_note(
        FakeReader(_note("# Plan\n", file_path="archive/plan.md")),
        "n1",
        before=_note(PLAN, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=None,
    )

    assert isinstance(verdict, Failed)
    assert verdict.reason == "truncated"


@pytest.mark.asyncio
async def test_a_move_gone_from_the_index_is_missing() -> None:
    verdict = await verify_moved_note(
        FakeReader(),
        "n1",
        before=_note(PLAN, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=None,
    )

    assert isinstance(verdict, Failed)
    assert verdict.reason == "missing"


@pytest.mark.asyncio
async def test_a_move_read_error_is_pending() -> None:
    verdict = await verify_moved_note(
        FakeReader(status_code=503),
        "n1",
        before=_note(PLAN, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=None,
    )

    assert isinstance(verdict, Pending)


@pytest.mark.asyncio
async def test_a_move_that_leaves_the_old_file_is_a_second_copy(tmp_path: Path) -> None:
    _write(tmp_path, "drafts/plan.md", PLAN)
    _write(tmp_path, "archive/plan.md", PLAN)

    verdict = await verify_moved_note(
        FakeReader(_note(PLAN, file_path="archive/plan.md")),
        "n1",
        before=_note(PLAN, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=tmp_path,
    )

    assert verdict == Failed("source_remains", "drafts/plan.md is still on disk after the move")


@pytest.mark.usefixtures("stuck_file_writer")
@pytest.mark.asyncio
async def test_an_old_file_still_there_after_a_timed_out_wait_is_pending(tmp_path: Path) -> None:
    _write(tmp_path, "drafts/plan.md", PLAN)
    _write(tmp_path, "archive/plan.md", PLAN)

    verdict = await verify_moved_note(
        FakeReader(_note(PLAN, file_path="archive/plan.md")),
        "n1",
        before=_note(PLAN, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=tmp_path,
    )

    assert verdict == Pending("drafts/plan.md was still on disk when the check stopped waiting")


@pytest.mark.asyncio
async def test_two_names_for_one_file_are_not_a_leftover(tmp_path: Path) -> None:
    """A hard link stands in for a case-only rename on a case-insensitive filesystem."""
    destination = _write(tmp_path, "notes/Plan.md", PLAN)
    os.link(destination, tmp_path / "notes/plan.md")

    verdict = await verify_moved_note(
        FakeReader(_note(PLAN, file_path="notes/Plan.md")),
        "n1",
        before=_note(PLAN, file_path="notes/plan.md"),
        destination="notes/Plan.md",
        local_root=tmp_path,
    )

    assert verdict == Verified(disk_checked=True)


@pytest.mark.asyncio
async def test_a_moved_note_with_an_empty_body_is_verified(tmp_path: Path) -> None:
    empty = "---\ntitle: Plan\n---\n"
    _write(tmp_path, "archive/plan.md", empty)

    verdict = await verify_moved_note(
        FakeReader(_note(empty, file_path="archive/plan.md")),
        "n1",
        before=_note(empty, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=tmp_path,
    )

    assert verdict == Verified(disk_checked=True)


@pytest.mark.asyncio
async def test_a_moved_image_is_checked_for_presence(tmp_path: Path) -> None:
    image = tmp_path / "archive/chart.png"
    image.parent.mkdir()
    image.write_bytes(b"\x89PNG\r\n\x1a\n\x00")
    reader = FakeReader(_note(None, file_path="archive/chart.png", status=None))
    before = _note(None, file_path="drafts/chart.png", status=None)

    present = await verify_moved_note(
        reader, "n1", before=before, destination="archive/chart.png", local_root=tmp_path
    )
    image.unlink()
    gone = await verify_moved_note(
        reader, "n1", before=before, destination="archive/chart.png", local_root=tmp_path
    )

    assert present == Verified(disk_checked=True)
    assert gone == Failed("file_missing", "archive/chart.png is not on disk")


@pytest.mark.asyncio
async def test_a_cloud_move_is_verified_in_the_index_only() -> None:
    verdict = await verify_moved_note(
        FakeReader(_note(PLAN, file_path="archive/plan.md")),
        "n1",
        before=_note(PLAN, file_path="drafts/plan.md"),
        destination="archive/plan.md",
        local_root=None,
    )

    assert verdict == Verified(disk_checked=False)


# --- Deleted notes ---


@pytest.mark.asyncio
async def test_a_delete_still_in_the_index_fails() -> None:
    verdict = await verify_deleted_note(
        FakeReader(_note(PLAN)), "n1", file_path="notes/plan.md", local_root=None
    )

    assert isinstance(verdict, Failed)
    assert verdict.reason == "still_indexed"


@pytest.mark.asyncio
async def test_a_delete_read_error_is_pending() -> None:
    verdict = await verify_deleted_note(
        FakeReader(status_code=500), "n1", file_path="notes/plan.md", local_root=None
    )

    assert isinstance(verdict, Pending)


@pytest.mark.asyncio
async def test_a_delete_is_verified_in_the_index_and_on_disk(tmp_path: Path) -> None:
    cloud = await verify_deleted_note(
        FakeReader(), "n1", file_path="notes/plan.md", local_root=None
    )
    local = await verify_deleted_note(
        FakeReader(), "n1", file_path="notes/plan.md", local_root=tmp_path
    )

    assert cloud == Verified(disk_checked=False)
    assert local == Verified(disk_checked=True)


@pytest.mark.asyncio
async def test_a_file_left_after_a_delete_fails(tmp_path: Path) -> None:
    _write(tmp_path, "notes/plan.md", PLAN)

    verdict = await verify_deleted_note(
        FakeReader(), "n1", file_path="notes/plan.md", local_root=tmp_path
    )

    assert verdict == Failed("file_remains", "notes/plan.md is still on disk after the delete")


@pytest.mark.asyncio
async def test_a_file_removed_while_waiting_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "notes/plan.md", PLAN)

    async def drain_removes_file() -> None:
        path.unlink()

    monkeypatch.setattr(verification, "drain_pending_materializations", drain_removes_file)

    verdict = await verify_deleted_note(
        FakeReader(), "n1", file_path="notes/plan.md", local_root=tmp_path
    )

    assert verdict == Verified(disk_checked=True)


@pytest.mark.usefixtures("stuck_file_writer")
@pytest.mark.asyncio
async def test_a_file_left_after_a_timed_out_wait_is_pending(tmp_path: Path) -> None:
    _write(tmp_path, "notes/plan.md", PLAN)

    verdict = await verify_deleted_note(
        FakeReader(), "n1", file_path="notes/plan.md", local_root=tmp_path
    )

    assert verdict == Pending("notes/plan.md was still on disk when the check stopped waiting")


# --- Where the files are ---


def _project(path: Path) -> ProjectItem:
    return ProjectItem(id=1, external_id="p1", name="main", path=str(path))


def _config(path: Path, mode: ProjectMode = ProjectMode.LOCAL) -> BasicMemoryConfig:
    return BasicMemoryConfig(
        env="test",
        projects={"main": ProjectEntry(path=str(path), mode=mode)},
        default_project="main",
    )


@pytest.fixture
def default_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(async_client, "_client_factory", None)
    for name in ("BASIC_MEMORY_EXPLICIT_ROUTING", "BASIC_MEMORY_FORCE_LOCAL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("default_routing")
def test_a_local_project_checks_its_configured_folder(tmp_path: Path) -> None:
    assert local_project_root(_project(tmp_path), _config(tmp_path)) == tmp_path


@pytest.mark.usefixtures("default_routing")
def test_the_disk_is_skipped_where_the_files_are_not_here(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    unconfigured = BasicMemoryConfig(env="test", projects={}, default_project=None)
    # Loading a config creates a missing project folder, so remove it afterwards.
    gone = tmp_path / "gone"
    gone_config = _config(gone)
    gone.rmdir()

    assert local_project_root(_project(tmp_path), _config(tmp_path, ProjectMode.CLOUD)) is None
    assert local_project_root(_project(tmp_path), unconfigured) is None
    assert local_project_root(_project(elsewhere), _config(tmp_path)) is None
    assert local_project_root(_project(gone), gone_config) is None


@pytest.mark.usefixtures("default_routing")
def test_a_hosted_or_cloud_routed_call_skips_the_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, config = _project(tmp_path), _config(tmp_path)

    monkeypatch.setenv("BASIC_MEMORY_EXPLICIT_ROUTING", "true")
    cloud_routed = local_project_root(project, config)
    monkeypatch.setenv("BASIC_MEMORY_FORCE_LOCAL", "true")
    local_routed = local_project_root(project, config)
    monkeypatch.setattr(async_client, "_client_factory", lambda **_: None)
    hosted = local_project_root(project, config)

    assert (cloud_routed, local_routed, hosted) == (None, tmp_path, None)


# --- Presenting ---


def test_json_payloads_name_status_and_reason() -> None:
    assert verification_payload(Verified(disk_checked=True)) == {
        "status": "verified",
        "disk_checked": True,
    }
    assert verification_payload(Pending("still writing")) == {
        "status": "pending",
        "detail": "still writing",
    }
    assert verification_payload(Failed("truncated", "cut short")) == {
        "status": "failed",
        "reason": "truncated",
        "detail": "cut short",
    }


def test_text_lines_say_what_was_read() -> None:
    assert (
        verification_line(Verified(disk_checked=True)) == "verification: verified (index and file)"
    )
    assert verification_line(Verified(disk_checked=False)) == (
        "verification: verified (index only; the files are not on this machine)"
    )
    assert verification_line(Pending("still writing")) == "verification: pending (still writing)"


def test_failure_text_is_an_error_that_points_at_the_note() -> None:
    text = verification_failure_text(
        "Error: Write not verified",
        accepted="The write to `notes/plan.md` was accepted",
        failure=Failed("duplicated", "the text appears 2 times"),
        note_ref="main/notes/plan",
    )

    assert text.startswith("# Error: Write not verified\n\n")
    assert "reading it back found a problem: the text appears 2 times." in text
    assert "Do not report this as done" in text
    assert 'read_note("main/notes/plan")' in text
    assert text.endswith("verification: failed (duplicated)")
