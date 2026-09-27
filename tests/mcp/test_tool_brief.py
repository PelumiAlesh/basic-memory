"""get_brief end-to-end behavior."""

import logging
from pathlib import Path

import pytest

from basic_memory.config import BasicMemoryConfig
from basic_memory.mcp.tools.brief import get_brief
from basic_memory.mcp.tools.write_note import write_note
from basic_memory.shared_memory.brief_delivery import project_delivery_path


@pytest.mark.asyncio
async def test_get_brief_omits_missing_profile_without_error_text(client, test_project) -> None:
    await write_note(
        project=test_project.name,
        title="state",
        directory="project",
        content="# State\n\nActive work.",
        note_type="state",
    )
    await write_note(
        project=test_project.name,
        title="one",
        directory="inbox",
        content="# One\n",
    )
    await write_note(
        project=test_project.name,
        title="two",
        directory="inbox",
        content="# Two\n",
    )

    text = await get_brief(project=test_project.name)
    assert "(no note at" not in text
    assert "me/profile" not in text
    assert "Inbox" in text
    assert "2 note(s)" in text
    assert "Current state" in text


@pytest.mark.asyncio
async def test_get_brief_includes_profile_when_present(client, test_project) -> None:
    await write_note(
        project=test_project.name,
        title="profile",
        directory="me",
        content="# Profile\n\nHuman-reviewed summary.",
    )
    text = await get_brief(project=test_project.name)
    assert "## Profile" in text
    assert "Human-reviewed summary" in text


@pytest.mark.asyncio
async def test_get_brief_does_not_log_note_bodies(
    client, test_project, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "SECRET_BRIEF_BODY_MARKER_7f3a"
    await write_note(
        project=test_project.name,
        title="profile",
        directory="me",
        content=f"# Profile\n\n{secret}",
    )
    with caplog.at_level(logging.DEBUG):
        await get_brief(project=test_project.name)
    joined = "\n".join(record.message for record in caplog.records)
    assert secret not in joined


def test_brief_config_defaults() -> None:
    config = BasicMemoryConfig()
    assert config.brief_refresh_hours == 6.0
    assert config.brief_include_profile is True


@pytest.mark.asyncio
async def test_get_brief_can_omit_profile(client, test_project, app_config, config_manager) -> None:
    from basic_memory import config as config_module

    await write_note(
        project=test_project.name,
        title="profile",
        directory="me",
        content="# Profile\n\nLeave this out.",
    )
    app_config.brief_include_profile = False
    config_module._CONFIG_CACHE = app_config
    stat = config_manager.config_file.stat()
    config_module._CONFIG_MTIME = stat.st_mtime
    config_module._CONFIG_SIZE = stat.st_size
    try:
        text = await get_brief(project=test_project.name)
    finally:
        app_config.brief_include_profile = True
        config_module._CONFIG_CACHE = app_config
    assert "Leave this out." not in text
    assert "## Profile" not in text


@pytest.mark.asyncio
async def test_get_brief_records_conversation_and_throttles(client, test_project) -> None:
    await write_note(
        project=test_project.name,
        title="profile",
        directory="me",
        content="# Profile\n\nThrottle marker.",
    )
    first = await get_brief(project=test_project.name, conversation_id="chat-1")
    assert "Throttle marker." in first
    store = project_delivery_path(Path(test_project.path))
    assert "chat-1" in store.read_text(encoding="utf-8")

    second = await get_brief(project=test_project.name, conversation_id="chat-1")
    assert "already delivered" in second
    assert "Throttle marker." not in second
    assert "6 hours" in second
