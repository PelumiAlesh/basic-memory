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


def cursor_brief_rule_file(refresh_hours: float = 6, *, inject: bool = False) -> str:
    """``.mdc`` file with ``alwaysApply`` so a rules loader can include it.

    Without ``inject``, the file tells the model not to pull note text on its own.
    The opt-in text is the reminder to call get_brief.
    """
    if inject:
        description = "Call Basic Memory get_brief when this chat has no recent brief"
        body = cursor_brief_rule_body(refresh_hours)
    else:
        description = "Basic Memory brief injection is off"
        body = (
            "Basic Memory brief injection is off. Do not read project notes, "
            "project/state, or me/profile into the prompt unless the user asks.\n"
        )
    return f"---\ndescription: {description}\nalwaysApply: true\n---\n\n" + body


def cursor_rule_install_notice(
    refresh_hours: float, rule_path: Path, *, inject: bool = False
) -> str:
    """Tell the owner what was written, and the text to paste if the file is ignored."""
    if inject:
        opening = "Brief injection is on. Cursor sessionStart can brief a new chat only."
        follow = "Whether the model calls get_brief is not guaranteed."
    else:
        opening = (
            "Brief injection is off. Setup does not install a prompt hook and "
            "does not put note text into Cursor or Claude Code."
        )
        follow = "The model is told not to read notes unless you ask."
    return "\n".join(
        [
            opening,
            f"Machine-local rule file: {rule_path}",
            "https://cursor.com/docs/rules defines global user rules only in "
            "Customize → Rules. Those sync with the Cursor account, and there is "
            "no documented file API for them.",
            "https://cursor.com/help/customization/rules also says user rule files "
            "in ~/.cursor/rules stay on this machine and do not sync. Setup writes "
            "that file. It does not install a project rule, because a project rule "
            "applies only inside one repository.",
            follow,
            "If the file is not applied, paste the paragraph under the frontmatter "
            "into Customize → Rules.",
            "bm setup --uninstall removes or restores the file only. A rule you "
            "paste into Customize → Rules stays until you delete it there.",
            "",
            cursor_brief_rule_file(refresh_hours, inject=inject).rstrip(),
        ]
    )
