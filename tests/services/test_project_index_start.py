"""First-index log text names the project before any note is rewritten."""

from pathlib import Path

from basic_memory.config import BasicMemoryConfig, ProjectEntry
from basic_memory.models import Project
from basic_memory.services.initialization import project_index_start_message


def test_first_index_names_a_project_older_builds_skipped(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = BasicMemoryConfig(
        env="test",
        projects={"ai-memory": ProjectEntry(path=str(vault))},
    )
    project = Project(name="AI Memory", path=str(vault), last_scan_timestamp=None)

    message = project_index_start_message(config, project)

    assert "Indexing project for the first time" in message
    assert "AI Memory" in message
    assert "ai-memory" in message
    assert "older builds skipped" in message
    assert "Permalink lines are inserted without rewriting other note bytes" in message
    assert "Pause Obsidian Sync" in message


def test_repeat_index_uses_the_short_message(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = BasicMemoryConfig(
        env="test",
        projects={"main": ProjectEntry(path=str(vault))},
    )
    project = Project(name="main", path=str(vault), last_scan_timestamp=1.0)

    message = project_index_start_message(config, project)

    assert message == "Starting background project index for project: main"
