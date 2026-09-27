"""bm brief CLI helpers."""

from basic_memory.cli.commands.brief import _wrap_harness


def test_wrap_harness_adds_fence() -> None:
    wrapped = _wrap_harness("# Brief\n\nhello\n")
    assert wrapped.startswith("```basic-memory-brief")
    assert "hello" in wrapped
    assert wrapped.endswith("```\n")
