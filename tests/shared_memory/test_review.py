"""Review-inbox decisions. The feature stays off until configured."""

import pytest

from basic_memory.shared_memory.review import (
    inbox_directory,
    mark_unreviewed_on_create,
    status_for_action,
)


def test_inbox_is_off_by_default() -> None:
    assert inbox_directory("", enabled=False, mode="folder", folder="inbox") == ""
    assert inbox_directory("decisions", enabled=True, mode="folder", folder="inbox") == "decisions"
    assert inbox_directory("", enabled=True, mode="status", folder="inbox") == ""
    assert inbox_directory("/", enabled=True, mode="folder", folder="inbox") == "inbox"
    assert inbox_directory("", enabled=True, mode="folder", folder="inbox") == "inbox"


def test_unreviewed_only_on_create_without_a_caller_status() -> None:
    assert not mark_unreviewed_on_create(None, enabled=False, mode="status")
    assert not mark_unreviewed_on_create({"status": "open"}, enabled=True, mode="status")
    assert not mark_unreviewed_on_create(None, enabled=True, mode="folder")
    assert mark_unreviewed_on_create(None, enabled=True, mode="status")
    assert mark_unreviewed_on_create({"tags": ["a"]}, enabled=True, mode="status")


def test_status_for_action() -> None:
    assert status_for_action("promote") == "reviewed"
    assert status_for_action("merge") == "merged"
    assert status_for_action("discard") is None
    with pytest.raises(ValueError):
        status_for_action("archive")
