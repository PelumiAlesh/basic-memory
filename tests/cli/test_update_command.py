"""Tests for `bm update` command."""

from typing import Any

from typer.testing import CliRunner

import basic_memory
from basic_memory.cli.app import app
from basic_memory.cli.auto_update import (
    AutoUpdateResult,
    AutoUpdateStatus,
    InstallSource,
    is_fork_build,
)


def _result(
    status: AutoUpdateStatus,
    *,
    message: str | None,
    error: str | None = None,
) -> AutoUpdateResult:
    return AutoUpdateResult(
        status=status,
        source=InstallSource.UV_TOOL,
        checked=True,
        update_available=status in {AutoUpdateStatus.UPDATE_AVAILABLE, AutoUpdateStatus.UPDATED},
        updated=status == AutoUpdateStatus.UPDATED,
        latest_version="9.9.9",
        message=message,
        error=error,
        restart_recommended=status == AutoUpdateStatus.UPDATED,
    )


def test_update_command_applies_upgrade(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        "basic_memory.cli.commands.update.run_auto_update",
        lambda **kwargs: _result(
            AutoUpdateStatus.UPDATED,
            message="Basic Memory was updated successfully.",
        ),
    )

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "updated successfully" in result.stdout.lower()


def test_update_command_check_only_shows_available(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        "basic_memory.cli.commands.update.run_auto_update",
        lambda **kwargs: _result(
            AutoUpdateStatus.UPDATE_AVAILABLE,
            message="Update available (latest: 9.9.9). Run `uv tool upgrade basic-memory --prerelease=allow`.",
        ),
    )

    result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0
    assert "update available" in result.stdout.lower()


def test_update_command_reports_up_to_date(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        "basic_memory.cli.commands.update.run_auto_update",
        lambda **kwargs: _result(
            AutoUpdateStatus.UP_TO_DATE,
            message="Basic Memory is up to date.",
        ),
    )

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0
    assert "up to date" in result.stdout.lower()


def test_update_command_failure_exits_nonzero(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        "basic_memory.cli.commands.update.run_auto_update",
        lambda **kwargs: _result(
            AutoUpdateStatus.FAILED,
            message="Automatic update failed.",
            error="network timeout",
        ),
    )

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "automatic update failed" in result.stdout.lower()


def test_installed_version_is_a_fork_build():
    assert is_fork_build(basic_memory.__version__)


def test_update_command_refuses_fork_build_without_network(monkeypatch):
    # The real updater runs here; only the network and subprocess edges are fenced.
    def _unexpected(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("bm update on a fork build must not reach PyPI or uv")

    monkeypatch.setattr("basic_memory.cli.auto_update._check_pypi_update_available", _unexpected)
    monkeypatch.setattr("basic_memory.cli.auto_update._run_subprocess", _unexpected)

    for args in (["update"], ["update", "--check"]):
        result = CliRunner().invoke(app, args)

        assert result.exit_code == 1
        assert "fork build" in result.stdout
        assert "git+https://github.com/PelumiAlesh/basic-memory" in result.stdout


def test_update_command_force_replaces_fork(monkeypatch):
    received: dict[str, Any] = {}

    def _fake_run_auto_update(**kwargs: Any) -> AutoUpdateResult:
        received.update(kwargs)
        return _result(AutoUpdateStatus.UPDATED, message="Basic Memory was updated successfully.")

    monkeypatch.setattr("basic_memory.cli.commands.update.run_auto_update", _fake_run_auto_update)

    result = CliRunner().invoke(app, ["update", "--force"])

    assert result.exit_code == 0
    assert received["replace_fork"] is True
