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

    # Typer 0.26's group is not click.Group. Read the command map by attribute.
    commands = getattr(get_command(cli_app), "commands", None)
    assert isinstance(commands, dict)
    params = getattr(commands["brief"], "params", None)
    assert isinstance(params, list)
    option_names: list[str] = []
    for param in params:
        opts = getattr(param, "opts", None)
        assert isinstance(opts, list)
        option_names.extend(opt for opt in opts if isinstance(opt, str))
    assert "--conversation" in option_names
    assert "--conversation-id" in option_names
