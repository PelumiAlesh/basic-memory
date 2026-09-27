"""Read a write back before reporting it saved.

After write_note, edit_note, move_note, or delete_note the MCP tool reads the note back
from the index and, when this process writes the project's files, from disk. A check
ends verified, pending (the file writer has not caught up, or the note could not be read
back), or failed with a named reason.

Bodies are compared, not whole files: frontmatter is dropped and whitespace collapsed,
because Basic Memory rewrites frontmatter on every write (permalink, provenance) and
formatting is not what goes missing. Everything else has to match exactly.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, assert_never

from fastmcp.exceptions import ToolError
from httpx import HTTPStatusError

from basic_memory.config import BasicMemoryConfig, ProjectMode
from basic_memory.file_utils import has_frontmatter, remove_frontmatter, strip_bom
from basic_memory.index.note_content_materialization import drain_pending_materializations
from basic_memory.mcp.async_client import _explicit_routing, _force_local_mode, is_factory_mode
from basic_memory.schemas.project_info import ProjectItem
from basic_memory.schemas.v2.entity import EntityResponseV2
from basic_memory.services.note_preparation import apply_edit_operation

# Longer than a local file write takes, short enough that a stuck file writer turns into
# a pending verdict instead of a hung tool call.
DRAIN_TIMEOUT_SECONDS = 5.0

_WRITE_IN_PROGRESS = frozenset({"pending", "writing"})

# --- Verdicts ---

type FailureReason = Literal[
    "missing",
    "truncated",
    "duplicated",
    "mismatch",
    "empty",
    "file_missing",
    "file_differs",
    "still_indexed",
    "file_remains",
    "source_remains",
]


@dataclass(frozen=True, slots=True)
class Verified:
    """The note reads back as requested. `disk_checked` is False when its files live
    on another machine, so only the index was read."""

    disk_checked: bool


@dataclass(frozen=True, slots=True)
class Pending:
    """The write was accepted but could not be confirmed yet."""

    detail: str


@dataclass(frozen=True, slots=True)
class Failed:
    """The note does not read back as requested."""

    reason: FailureReason
    detail: str


type Verification = Verified | Pending | Failed


class NoteReader(Protocol):
    async def get_entity(self, entity_id: str) -> EntityResponseV2: ...


# --- Comparing bodies ---


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def note_body(markdown: str) -> str:
    """The body of a note with frontmatter dropped and whitespace collapsed."""
    text = strip_bom(markdown)
    body = remove_frontmatter(text) if has_frontmatter(text) else text
    return collapse_whitespace(body)


def compare_bodies(*, expected: str, stored: str, inserted: str) -> Failed | None:
    """Say how a stored body departs from the expected one, or None when they are equal.

    All three come from note_body. `inserted` is the text this call wrote: the whole
    body for write_note, the new text for an edit, the carried body for a move.
    """
    if stored == expected:
        return None
    if inserted and stored.count(inserted) > expected.count(inserted):
        return Failed(
            "duplicated",
            f"the text this call wrote appears {stored.count(inserted)} times in the "
            f"stored note instead of {expected.count(inserted)}",
        )
    if len(stored) < len(expected) and stored in expected:
        return Failed(
            "truncated",
            f"the stored body has {len(stored)} of the expected {len(expected)} characters",
        )
    return Failed("mismatch", "the stored body is not what this call should have produced")


def replay_edit(
    before_markdown: str,
    *,
    operation: str,
    content: str,
    section: str | None,
    find_text: str | None,
    expected_replacements: int,
    replace_subsections: bool,
) -> str | None:
    """The markdown an edit should produce from the note as read just before it.

    None means the edit does not apply to that text (its section or find_text is not
    there), so the note changed between that read and the edit the API accepted.
    """
    try:
        return apply_edit_operation(
            before_markdown,
            operation,
            content,
            section,
            find_text,
            expected_replacements,
            replace_subsections,
        )
    except ValueError:
        return None


# --- Where the files are ---


def local_project_root(project: ProjectItem, config: BasicMemoryConfig) -> Path | None:
    """The project's directory when this process writes its files, else None.

    A hosted app (client factory), a forced cloud route, or a cloud project keeps the
    files on another machine, so there is no local file to compare.
    """
    if is_factory_mode() or (_explicit_routing() and not _force_local_mode()):
        return None
    entry = config.projects.get(project.name)
    if entry is None or entry.mode is not ProjectMode.LOCAL:
        return None
    # A cloud workspace can hold a project named like a local one. The path the API
    # answered with must be the configured local path, or the files are not here.
    root = Path(entry.path).expanduser()
    if root.resolve() != project.home.resolve() or not root.is_dir():
        return None
    return root


def _file_body(path: Path) -> str | None:
    """The body of the file at `path`, or None when there is no file."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    # Bytes that are not UTF-8 cannot match the accepted note; replacing them keeps the
    # comparison a plain inequality instead of a decode error after an accepted write.
    return note_body(raw.decode("utf-8", errors="replace"))


def _source_remains(root: Path, source: str, destination: str) -> bool:
    """Whether the pre-move file is still on disk as a file separate from the new one.

    A case-only rename on a case-insensitive filesystem (the macOS default) leaves
    both paths naming one file, which is the moved note, not a leftover.
    """
    source_path = root / source
    try:
        return not source_path.samefile(root / destination)
    except FileNotFoundError:
        # One of the two paths is gone: the source remains only if it is the one left.
        return source_path.exists()


async def _drain_materialization() -> bool:
    """Wait for this process's queued file writes; False when the wait ran out."""
    try:
        await asyncio.wait_for(drain_pending_materializations(), DRAIN_TIMEOUT_SECONDS)
    except TimeoutError:
        return False
    return True


# --- Reading back ---


async def _read_back(reader: NoteReader, entity_id: str) -> EntityResponseV2 | None | Pending:
    """The note as the index holds it now, None once it is gone.

    Any other read error is Pending: the write was accepted, and reporting it as failed
    would invite a retry that applies it twice.
    """
    try:
        return await reader.get_entity(entity_id)
    except ToolError as error:
        cause = error.__cause__
        if isinstance(cause, HTTPStatusError) and cause.response.status_code == 404:
            return None
        return Pending(f"the note could not be read back: {error}")


def _file_verdict(note: EntityResponseV2, body: str, root: Path) -> Verification:
    """Compare the note's file with its accepted body after the file writer has run."""
    path = root / note.file_path
    # Images, PDFs, and other non-markdown files come back without text, so the most
    # the check can say about them is that the file is there.
    if note.content is None:
        if path.is_file():
            return Verified(disk_checked=True)
        return Failed("file_missing", f"{note.file_path} is not on disk")
    file_body = _file_body(path)
    if file_body == body:
        return Verified(disk_checked=True)
    if note.file_write_status in _WRITE_IN_PROGRESS:
        return Pending(f"{note.file_path} was still being written when the check stopped waiting")
    status = f"file write status: {note.file_write_status}"
    if note.last_materialization_error:
        status += f", {note.last_materialization_error}"
    if file_body is None:
        return Failed("file_missing", f"{note.file_path} is not on disk ({status})")
    return Failed("file_differs", f"{note.file_path} on disk differs from the note ({status})")


async def verify_saved_note(
    reader: NoteReader,
    entity_id: str,
    *,
    expected_markdown: str | None,
    inserted: str,
    local_root: Path | None,
) -> Verification:
    """Check a write_note or edit_note result against the markdown it should have left.

    `expected_markdown` is None when an edit could not be replayed (see replay_edit).
    """
    if expected_markdown is None:
        return Failed(
            "mismatch",
            "the note changed between the read before this edit and the edit itself",
        )
    expected = note_body(expected_markdown)
    # Trigger: the note should have no body after this call.
    # Why: an empty body is also what a write that lost everything looks like, so a
    #      match would prove nothing.
    # Outcome: never reported as verified.
    if not expected:
        return Failed("empty", "the note body is empty, so there is nothing to check it against")
    if local_root is not None:
        await _drain_materialization()
    note = await _read_back(reader, entity_id)
    if note is None:
        return Failed("missing", "the note is not in the index after the write")
    if isinstance(note, Pending):
        return note
    body = note_body(note.content or "")
    failure = compare_bodies(expected=expected, stored=body, inserted=note_body(inserted))
    if failure is not None:
        return failure
    if local_root is None:
        return Verified(disk_checked=False)
    return _file_verdict(note, body, local_root)


async def verify_moved_note(
    reader: NoteReader,
    entity_id: str,
    *,
    before: EntityResponseV2 | None,
    destination: str,
    local_root: Path | None,
) -> Verification:
    """Check a move: same body at `destination` in the index and on disk, old file gone."""
    if before is None:
        return Pending("the note could not be read before the move, so the move was not checked")
    drained = await _drain_materialization() if local_root is not None else True
    note = await _read_back(reader, entity_id)
    if note is None:
        return Failed("missing", "the note is not in the index after the move")
    if isinstance(note, Pending):
        return note
    if note.file_path != destination:
        return Failed("mismatch", f"the index has the note at {note.file_path}, not {destination}")
    body = note_body(note.content or "")
    expected = note_body(before.content or "")
    failure = compare_bodies(expected=expected, stored=body, inserted=expected)
    if failure is not None:
        return failure
    if local_root is None:
        return Verified(disk_checked=False)
    verdict = _file_verdict(note, body, local_root)
    if isinstance(verdict, Verified) and _source_remains(
        local_root, before.file_path, note.file_path
    ):
        if not drained:
            return Pending(f"{before.file_path} was still on disk when the check stopped waiting")
        return Failed("source_remains", f"{before.file_path} is still on disk after the move")
    return verdict


async def verify_deleted_note(
    reader: NoteReader,
    entity_id: str,
    *,
    file_path: str,
    local_root: Path | None,
) -> Verification:
    """Check a delete: the note is gone from the index and its file from disk."""
    note = await _read_back(reader, entity_id)
    if isinstance(note, Pending):
        return note
    if note is not None:
        return Failed("still_indexed", "the note is still in the index after the delete")
    if local_root is None:
        return Verified(disk_checked=False)
    path = local_root / file_path
    # Local deletes remove the file before the API answers, so the wait below only
    # runs when something is off.
    if not path.exists():
        return Verified(disk_checked=True)
    drained = await _drain_materialization()
    if not path.exists():
        return Verified(disk_checked=True)
    if not drained:
        return Pending(f"{file_path} was still on disk when the check stopped waiting")
    return Failed("file_remains", f"{file_path} is still on disk after the delete")


# --- Presenting ---


def verification_payload(verification: Verification) -> dict[str, str | bool]:
    """The `verification` object in JSON tool output."""
    match verification:
        case Verified(disk_checked=disk_checked):
            return {"status": "verified", "disk_checked": disk_checked}
        case Pending(detail=detail):
            return {"status": "pending", "detail": detail}
        case Failed(reason=reason, detail=detail):
            return {"status": "failed", "reason": reason, "detail": detail}
        case _:  # pragma: no cover - Verification is a closed union
            assert_never(verification)


def verification_line(verification: Verified | Pending) -> str:
    """One summary line for text output when the check did not fail."""
    match verification:
        case Verified(disk_checked=disk_checked):
            checked = (
                "index and file"
                if disk_checked
                else "index only; the files are not on this machine"
            )
            return f"verification: verified ({checked})"
        case Pending(detail=detail):
            return f"verification: pending ({detail})"
        case _:  # pragma: no cover - exhaustive over Verified | Pending
            assert_never(verification)


def verification_failure_text(
    heading: str, *, accepted: str, failure: Failed, note_ref: str
) -> str:
    """Text output for a failed check: an error in its own right, not a footnote."""
    return (
        f"# {heading}\n\n"
        f"{accepted}, but reading it back found a problem: {failure.detail}.\n\n"
        "Do not report this as done, and do not repeat the call blindly: the change may "
        f'be partly applied. Check what is there now with `read_note("{note_ref}")`, '
        "then correct it.\n\n"
        f"verification: failed ({failure.reason})"
    )
