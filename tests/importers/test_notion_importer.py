"""Notion Markdown & CSV import: ids, links, hierarchy, and zip safety."""

import zipfile
from pathlib import Path

import pytest

from basic_memory.importers.notion_importer import (
    NotionImporter,
    clean_relative_path,
    csv_row_notes,
    rewrite_internal_links,
    safe_extract_zip,
    strip_notion_stem,
)
from basic_memory.markdown.schemas import EntityMarkdown


class _Files:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.app_config = None

    async def write_file(self, file_path: str, content: str) -> str:
        self.files[file_path] = content
        return "checksum"

    async def ensure_directory(self, folder: str) -> None:
        return None


class _Processor:
    def to_markdown_string(self, entity: EntityMarkdown) -> str:
        meta = entity.frontmatter.metadata
        lines = ["---", *[f"{key}: {value}" for key, value in meta.items()], "---", ""]
        lines.append(entity.content or "")
        return "\n".join(lines)


def test_strip_notion_id_from_file_and_folder() -> None:
    notion_id = "a" * 32
    assert strip_notion_stem(f"Project Plan {notion_id}") == ("Project Plan", False)
    cleaned, is_all = clean_relative_path(Path(f"Team {notion_id}") / f"Tasks {notion_id}_all.csv")
    assert cleaned == Path("Team") / "Tasks.csv"
    assert is_all


def test_rewrite_internal_links_keeps_external_urls() -> None:
    notion_id = "b" * 32
    text = f"[Plan](Project%20Plan%20{notion_id}.md)\n[Web](https://example.com/a)\n"
    rewritten = rewrite_internal_links(text)
    assert "[[Project Plan]]" in rewritten
    assert "https://example.com/a" in rewritten


def test_csv_rows_become_frontmatter() -> None:
    notes = csv_row_notes("Name,Status\nShip it,open\n", "Tasks")
    assert notes[0][0] == "Ship it"
    assert notes[0][1]["status"] == "open"
    assert notes[0][1]["source"] == "notion"
    assert notes[0][1]["title"] == "Ship it"


@pytest.mark.asyncio
async def test_import_folder_preserves_hierarchy(tmp_path: Path) -> None:
    notion_id = "c" * 32
    folder = tmp_path / "export" / f"Team {notion_id}"
    folder.mkdir(parents=True)
    (folder / f"Plan {notion_id}.md").write_text(
        f"See [Tasks](Tasks%20{notion_id}.csv)\n",
        encoding="utf-8",
    )
    (folder / f"Tasks {notion_id}.csv").write_text(
        "Name,Owner\nAlpha,Ada\n",
        encoding="utf-8",
    )
    (folder / f"Tasks {notion_id}_all.csv").write_text(
        "Name,Owner\nAlpha,Ada\n",
        encoding="utf-8",
    )
    files = _Files()
    importer = NotionImporter(tmp_path, _Processor(), files)  # type: ignore[arg-type]
    result = await importer.import_data(tmp_path / "export", "imports/notion")
    assert result.success
    assert result.csv_rows == 1
    written = "\n".join(files.files.values())
    assert "[[Tasks]]" in written
    assert notion_id not in "\n".join(files.files)
    assert any(path.startswith("imports/notion/Team/") for path in files.files)
    assert any(path.endswith("Alpha.md") for path in files.files)


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "export.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.md", "nope")
    with pytest.raises(ValueError, match="escapes"):
        safe_extract_zip(archive_path, tmp_path / "out")


@pytest.mark.asyncio
async def test_import_zip(tmp_path: Path) -> None:
    notion_id = "d" * 32
    archive_path = tmp_path / "export.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"Hello {notion_id}.md", "# Hello\n")
    files = _Files()
    importer = NotionImporter(tmp_path, _Processor(), files)  # type: ignore[arg-type]
    result = await importer.import_data(archive_path, "imports/notion")
    assert result.success
    assert result.notes == 1
    assert any(path.endswith("Hello.md") for path in files.files)
