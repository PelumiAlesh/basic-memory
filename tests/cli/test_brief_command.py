"""bm brief CLI helpers."""

from basic_memory.cli.commands.brief import _wrap_harness
from basic_memory.cli.main import app as cli_app


def test_wrap_harness_adds_fence() -> None:
    wrapped = _wrap_harness("# Brief\n\nhello\n")
    assert wrapped.startswith("```basic-memory-brief")
    assert "hello" in wrapped
    assert wrapped.endswith("```\n")


def test_brief_help_accepts_conversation_alias() -> None:
    from typer.main import get_command

    brief = get_command(cli_app).commands["brief"]
    option_names = [name for param in brief.params for name in param.opts]
    assert "--conversation" in option_names
    assert "--conversation-id" in option_names
