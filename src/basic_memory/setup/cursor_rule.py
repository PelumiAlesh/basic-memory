"""Machine-local Cursor rule that reminds the model to call get_brief.

Cursor's rules reference documents global user rules only as text entered in
Customize → Rules. Those rules sync with the account, and there is no file API
for them. The help page also says files in ``~/.cursor/rules`` stay on the
machine. Setup writes that file and prints the same text. Following it is up
to the model.
"""

from __future__ import annotations

from pathlib import Path


def cursor_brief_rule_body(refresh_hours: float = 6) -> str:
    """Plain instruction. This is what Customize → Rules accepts."""
    hours = f"{refresh_hours:g}"
    return (
        "At the start of a turn, if you have not called the Basic Memory tool "
        f"get_brief in this conversation within the last {hours} hours, call "
        "get_brief before answering. Pass conversation_id when you have one. "
        "Cursor does not inject a brief when an old chat is resumed. This is a "
        "reminder for the model. Following it is not guaranteed.\n"
    )


def cursor_brief_rule_file(refresh_hours: float = 6) -> str:
    """``.mdc`` file with ``alwaysApply`` so a rules loader can include it."""
    return (
        "---\n"
        "description: Call Basic Memory get_brief when this chat has no recent brief\n"
        "alwaysApply: true\n"
        "---\n"
        "\n" + cursor_brief_rule_body(refresh_hours)
    )


def cursor_rule_install_notice(refresh_hours: float, rule_path: Path) -> str:
    """Tell the owner what was written, and the text to paste if the file is ignored."""
    return "\n".join(
        [
            "Cursor does not inject a brief when you reopen an old chat.",
            f"Machine-local rule file: {rule_path}",
            "https://cursor.com/docs/rules defines global user rules only in "
            "Customize → Rules. Those sync with the Cursor account, and there is "
            "no documented file API for them.",
            "https://cursor.com/help/customization/rules also says user rule files "
            "in ~/.cursor/rules stay on this machine and do not sync. Setup writes "
            "that file. It does not install a project rule, because a project rule "
            "applies only inside one repository.",
            "Whether the model calls get_brief is not guaranteed.",
            "If the file is not applied, paste the paragraph under the frontmatter "
            "into Customize → Rules.",
            "bm setup --uninstall removes or restores the file only. A rule you "
            "paste into Customize → Rules stays until you delete it there.",
            "",
            cursor_brief_rule_file(refresh_hours).rstrip(),
        ]
    )
