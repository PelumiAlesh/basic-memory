"""The session-start hook carries the get_brief project briefing inside its budget."""

from basic_memory.cli.commands import hook as hook_module


def _fake_brief(text: str):
    async def fake(primary: str, token_budget: int) -> str | None:
        fake.calls.append((primary, token_budget))  # type: ignore[attr-defined]
        return text

    fake.calls = []  # type: ignore[attr-defined]
    return fake


def test_project_brief_is_appended_and_fenced(monkeypatch) -> None:
    fake = _fake_brief("# Brief\n\n## Profile\nAda builds memory systems.\n")
    monkeypatch.setattr(hook_module, "_project_brief_text", fake)
    base = "# Basic Memory — session context\n\n`````text\ndata\n`````\n\n---\nrecall"
    result = hook_module._append_project_brief(base, "main", {})
    assert result.startswith(base)
    assert "## Project brief" in result
    assert "Ada builds memory systems." in result
    assert result.count("`````") >= 4
    assert fake.calls and fake.calls[0][0] == "main"
    assert 0 < fake.calls[0][1] <= 1500


def test_project_brief_skipped_without_project_or_when_disabled(monkeypatch) -> None:
    fake = _fake_brief("should not appear")
    monkeypatch.setattr(hook_module, "_project_brief_text", fake)
    base = "# Basic Memory"
    assert hook_module._append_project_brief(base, "", {}) == base
    assert hook_module._append_project_brief(base, "main", {"projectBrief": False}) == base
    assert fake.calls == []


def test_project_brief_stays_inside_the_hook_budget(monkeypatch) -> None:
    fake = _fake_brief("line\n" * 5000)
    monkeypatch.setattr(hook_module, "_project_brief_text", fake)
    base = "x" * (hook_module.MAX_BRIEF_CHARS - 2000)
    result = hook_module._append_project_brief(base, "main", {"briefTokenBudget": 100000})
    assert len(result) <= hook_module.MAX_BRIEF_CHARS
    # The closing fence survives the caller's slice.
    assert result.rstrip().endswith("`````")
    assert "[truncated]" in result


def test_project_brief_skipped_when_no_room(monkeypatch) -> None:
    fake = _fake_brief("brief")
    monkeypatch.setattr(hook_module, "_project_brief_text", fake)
    base = "x" * (hook_module.MAX_BRIEF_CHARS - 100)
    assert hook_module._append_project_brief(base, "main", {}) == base
    assert fake.calls == []


def test_project_brief_failure_leaves_brief_unchanged(monkeypatch) -> None:
    async def failing(primary: str, token_budget: int) -> str | None:
        return None

    monkeypatch.setattr(hook_module, "_project_brief_text", failing)
    base = "# Basic Memory"
    assert hook_module._append_project_brief(base, "main", {}) == base
