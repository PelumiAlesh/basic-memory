"""Render a bounded session brief from already-fetched sections.

The MCP tool decides what to fetch. This module only fits that text into a
token budget so a client without hooks (ChatGPT, Cursor, Grok) can orient
itself without pulling the whole project.
"""

from __future__ import annotations

from dataclasses import dataclass

# A rough stand-in for a tokenizer. Four characters per token is the usual
# English estimate and is enough to keep a brief inside a caller's budget.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class BriefSection:
    heading: str
    body: str


def render_brief(sections: list[BriefSection], *, token_budget: int) -> str:
    """Fit sections into the budget, in the order given. Later sections drop first."""
    budget = max(1, token_budget) * CHARS_PER_TOKEN
    parts = ["# Brief", ""]
    used = len("\n".join(parts)) + 1
    for section in sections:
        body = section.body.strip() or "(none)"
        block = f"## {section.heading}\n{body}\n"
        if used + len(block) <= budget:
            parts.append(block.rstrip())
            used += len(block)
            continue
        heading_line = f"## {section.heading}\n"
        remaining = budget - used - len(heading_line) - 2
        # Trigger: the next section does not fit whole.
        # Why: a truncated profile is more useful than dropping it for a later list.
        # Outcome: keep a prefix when there is room for a sentence, then stop.
        if remaining >= 80:
            parts.append(heading_line + body[:remaining].rstrip() + "…")
        break
    return "\n".join(parts).strip() + "\n"
