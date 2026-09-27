"""Tests for ``bm brief``."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from basic_memory.cli.main import app as cli_app
from basic_memory.shared_memory.brief_delivery import JsonBriefDeliveryStore, project_delivery_path

runner = CliRunner()


@pytest.fixture
def bm_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "config-home"
    monkeypatch.setenv("BASIC_MEMORY_CONFIG_DIR", str(home))
    monkeypatch.setenv("BASIC_MEMORY_HOME", str(home / "data"))
    return home


def test_brief_skips_inside_refresh_window(
    bm_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from basic_memory.config import ConfigManager, ProjectEntry, ProjectMode

    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ConfigManager()
    config = manager.config.model_copy(deep=True)
    config.default_project = "main"
    config.projects["main"] = ProjectEntry(path=str(vault), mode=ProjectMode.LOCAL)
    manager.save_config(config)

    store = JsonBriefDeliveryStore(project_delivery_path(vault))
    from datetime import datetime, timezone

    from basic_memory.shared_memory.brief_delivery import BriefDeliveryState

    state = BriefDeliveryState.empty()
    state.record("conv-1", datetime.now(timezone.utc))
    store.save(state)

    monkeypatch.setattr(
        "basic_memory.cli.commands.brief.render_brief_for_project",
        lambda _name: "SHOULD NOT PRINT",
    )
    result = runner.invoke(cli_app, ["brief", "--conversation", "conv-1"])
    assert result.exit_code == 0
    assert "SHOULD NOT PRINT" not in result.stdout
