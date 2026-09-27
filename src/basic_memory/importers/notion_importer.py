"""Import a Notion Markdown & CSV export.

Notion appends a 32-character hex id to file and folder names. This importer
strips those, rewrites relative links to wiki links, turns each database CSV
row into a note with frontmatter properties, and keeps the export's hierarchy
under the destination folder.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from typing import override
from urllib.parse import unquote

from basic_memory.file_utils import has_frontmatter, parse_frontmatter, remove_frontmatter
from basic_memory.importers.base import Importer
from basic_memory.markdown.schemas import EntityFrontmatter, EntityMarkdown
from basic_memory.schemas.importer import NotionImportResult

_NOTION_ID = re.compile(r"^(?P<title>.+?) (?P<notion_id>[0-9a-fA-F]{32})(?P<all>_all)?$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_TITLE_KEYS = ("name", "title")
_SKIP_PARTS = frozenset({"__MACOSX", ".DS_Store"})


def strip_notion_stem(stem: str) -> tuple[str, bool]:
    """Return the name without a trailing Notion id, and whether it was an `_all` export."""
    match = _NOTION_ID.match(stem.strip())
    if match is None:
        return stem.strip(), False
    return match.group("title").strip(), bool(match.group("all"))


def clean_relative_path(relative: Path) -> tuple[Path, bool]:
    """Strip Notion ids from every path component. The bool is the file's `_all` flag."""
    parts: list[str] = []
    duplicate = False
    for index, part in enumerate(relative.parts):
        is_file = index == len(relative.parts) - 1 and Path(part).suffix
        if is_file:
            suffix = Path(part).suffix
            stem, is_all = strip_notion_stem(Path(part).stem)
            duplicate = is_all
            parts.append(f"{stem}{suffix}" if stem else part)
        else:
            cleaned, _is_all = strip_notion_stem(part)
            parts.append(cleaned or part)
    return Path(*parts), duplicate


def rewrite_internal_links(markdown: str) -> str:
    """Turn relative markdown links into wiki links. External URLs stay as they are."""

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2).strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return match.group(0)
        path = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not path or path.endswith("/"):
            return match.group(0)
        stem, _is_all = strip_notion_stem(Path(path).stem)
        title = stem or label.strip() or Path(path).stem
        return f"[[{title}]]"

    return _MARKDOWN_LINK.sub(replace, markdown)


def _property_key(header: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_]+", "_", header.strip()).strip("_").lower()
    return key or "property"


def csv_row_notes(csv_text: str, database_title: str) -> list[tuple[str, dict[str, str], str]]:
    """One note per data row: (file stem, frontmatter, body)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        return []
    title_header = next(
        (name for name in reader.fieldnames if name and name.strip().lower() in _TITLE_KEYS),
        reader.fieldnames[0],
    )
    notes: list[tuple[str, dict[str, str], str]] = []
    used: dict[str, int] = {}
    for row in reader:
        if not row or not any((value or "").strip() for value in row.values()):
            continue
        raw_title = (row.get(title_header) or "").strip() or database_title
        properties: dict[str, str] = {}
        for header, value in row.items():
            if header is None:
                continue
            text = (value or "").strip()
            if not text:
                continue
            properties[_property_key(header)] = text
        properties["title"] = raw_title
        properties["type"] = "note"
        properties["source"] = "notion"
        count = used.get(raw_title, 0) + 1
        used[raw_title] = count
        stem = raw_title if count == 1 else f"{raw_title} {count}"
        body_lines = [
            f"- {header}: {value}"
            for header, value in row.items()
            if header and (value or "").strip() and header != title_header
        ]
        body = "\n".join(body_lines)
        notes.append((stem, properties, body))
    return notes


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    """Extract a zip, refusing entries that escape the destination."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Notion export zip contains an entry that escapes the destination")
        archive.extractall(destination)


def _should_skip(path: Path) -> bool:
    return any(part in _SKIP_PARTS or part.startswith(".") for part in path.parts)


class NotionImporter(Importer[NotionImportResult]):
    """Write a Notion export into the project as markdown notes."""

    @override
    def handle_error(self, message: str, error: Exception | None = None) -> NotionImportResult:
        detail = f"{message}: {error}" if error else message
        return NotionImportResult(
            import_count={},
            success=False,
            error_message=detail,
        )

    async def _write_note(self, relative: Path, metadata: dict[str, str], body: str) -> None:
        entity = EntityMarkdown(
            frontmatter=EntityFrontmatter(metadata=metadata),
            content=body,
        )
        await self.write_entity(entity, relative.as_posix())

    def _prepare_markdown(self, text: str, title: str) -> tuple[dict[str, str], str]:
        metadata: dict[str, str] = {}
        body = text
        if has_frontmatter(text):
            parsed = parse_frontmatter(text)
            metadata = {str(key): str(value) for key, value in parsed.items() if value is not None}
            body = remove_frontmatter(text)
        metadata.setdefault("title", title)
        metadata.setdefault("type", "note")
        metadata.setdefault("source", "notion")
        return metadata, rewrite_internal_links(body)

    @override
    async def import_data(
        self,
        source_data: Path,
        destination_folder: str = "imports/notion",
        **kwargs: object,
    ) -> NotionImportResult:
        source = Path(source_data)
        if not source.exists():
            return self.handle_error(f"Notion export not found: {source}")
        temp_root: Path | None = None
        try:
            if source.is_file() and source.suffix.lower() == ".zip":
                import tempfile

                temp_root = Path(tempfile.mkdtemp(prefix="notion-import-"))
                safe_extract_zip(source, temp_root)
                export_root = temp_root
            elif source.is_dir():
                export_root = source
            else:
                return self.handle_error("Notion import expects a .zip or a folder")

            notes = 0
            csv_rows = 0
            skipped = 0
            destination = destination_folder.strip("/")
            csv_candidates = [
                path
                for path in export_root.rglob("*.csv")
                if not _should_skip(path.relative_to(export_root))
            ]
            plain_csvs = {
                clean_relative_path(path.relative_to(export_root))[0]
                for path in csv_candidates
                if not clean_relative_path(path.relative_to(export_root))[1]
            }

            for path in sorted(export_root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(export_root)
                if _should_skip(relative):
                    skipped += 1
                    continue
                cleaned, is_all = clean_relative_path(relative)
                if path.suffix.lower() == ".csv" and is_all and cleaned in plain_csvs:
                    # The `_all` file repeats the same database. Keep the plain CSV.
                    skipped += 1
                    continue
                target_parent = (
                    Path(destination) / cleaned.parent if destination else cleaned.parent
                )
                if path.suffix.lower() == ".md":
                    metadata, body = self._prepare_markdown(
                        path.read_text(encoding="utf-8"),
                        cleaned.stem,
                    )
                    await self._write_note(target_parent / cleaned.name, metadata, body)
                    notes += 1
                elif path.suffix.lower() == ".csv":
                    database = cleaned.stem
                    for stem, properties, body in csv_row_notes(
                        path.read_text(encoding="utf-8"),
                        database,
                    ):
                        filename = f"{stem}.md"
                        await self._write_note(
                            target_parent / database / filename, properties, body
                        )
                        csv_rows += 1
                        notes += 1
            return NotionImportResult(
                import_count={"notes": notes, "csv_rows": csv_rows},
                success=True,
                notes=notes,
                csv_rows=csv_rows,
                skipped=skipped,
            )
        except (OSError, UnicodeError, ValueError, zipfile.BadZipFile, csv.Error) as exc:
            return self.handle_error("Notion import failed", exc)
        finally:
            if temp_root is not None:
                import shutil

                shutil.rmtree(temp_root, ignore_errors=True)
