"""Visibility policies fail closed when a policy exists and the client is unknown."""

from basic_memory.shared_memory.privacy import (
    ClientVisibilityPolicy,
    access_for,
    note_is_visible,
)


def _policies() -> dict[str, ClientVisibilityPolicy]:
    return {
        "chatgpt": ClientVisibilityPolicy(
            deny_visibility=["private"],
            deny_path_prefixes=["personal", "work/secret"],
        )
    }


def test_no_policy_leaves_every_note_visible() -> None:
    access = access_for({}, None)
    assert note_is_visible(access, visibility="private", file_path="personal/me.md")
    assert note_is_visible(access, visibility=None, file_path=None)


def test_named_client_policy_hides_private_and_a_folder() -> None:
    access = access_for(_policies(), "chatgpt")
    assert not note_is_visible(access, visibility="private", file_path="notes/a.md")
    assert not note_is_visible(access, visibility=None, file_path="notes/a.md")
    assert note_is_visible(access, visibility="shareable", file_path="notes/a.md")
    assert note_is_visible(access, visibility="work", file_path="notes/a.md")
    assert not note_is_visible(access, visibility="shareable", file_path="personal/secret.md")
    assert not note_is_visible(access, visibility="shareable", file_path="work/secret/plan.md")
    assert note_is_visible(access, visibility="shareable", file_path="work/public.md")


def test_unknown_client_is_denied_private_and_work() -> None:
    access = access_for(_policies(), None)
    assert not note_is_visible(access, visibility="private", file_path="notes/a.md")
    assert not note_is_visible(access, visibility="work", file_path="notes/a.md")
    assert not note_is_visible(access, visibility="nope", file_path="notes/a.md")
    assert note_is_visible(access, visibility="shareable", file_path="notes/a.md")
    assert not note_is_visible(access, visibility="shareable", file_path="personal/a.md")


def test_client_with_an_empty_policy_can_read() -> None:
    policies = {"cursor": ClientVisibilityPolicy()}
    access = access_for(policies, "cursor")
    assert note_is_visible(access, visibility="private", file_path="personal/a.md")
