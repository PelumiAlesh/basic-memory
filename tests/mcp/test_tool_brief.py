"""get_brief end-to-end behavior."""

import logging

import pytest

from basic_memory.mcp.tools.brief import get_brief
from basic_memory.mcp.tools.write_note import write_note


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
