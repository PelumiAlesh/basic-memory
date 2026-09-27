"""Token-budget rendering for get_brief."""

from basic_memory.shared_memory.briefing import BriefSection, render_brief


def test_render_brief_keeps_earlier_sections_inside_the_budget() -> None:
    sections = [
        BriefSection("Profile", "Ada builds memory systems."),
        BriefSection("Current state", "Shipping the shared-memory fork."),
        BriefSection("Decisions (14d)", "- use localhost by default"),
        BriefSection("Recently updated", "x" * 5000),
    ]
    rendered = render_brief(sections, token_budget=30)
    assert rendered.startswith("# Brief")
    assert "Profile" in rendered
    assert "Recently updated" not in rendered
    assert len(rendered) <= 30 * 4 + 8


def test_render_brief_truncates_a_section_that_partly_fits() -> None:
    rendered = render_brief(
        [BriefSection("Profile", "word " * 200)],
        token_budget=40,
    )
    assert "Profile" in rendered
    assert "…" in rendered


def test_render_brief_empty_body_is_explicit() -> None:
    rendered = render_brief([BriefSection("Decisions (14d)", "  ")], token_budget=200)
    assert "(none)" in rendered
