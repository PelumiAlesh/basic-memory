"""Classify notes for `bm care`.

The report is a read of the markdown files plus the orphan list from the
existing knowledge API. It does not rewrite notes. `bm doctor` remains the
file-to-database consistency check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from basic_memory.file_utils import ParseError, has_frontmatter, parse_frontmatter

_SKIP_DIRS = frozenset({".git", ".obsidian", "node_modules", ".venv", "__pycache__"})


@dataclass(frozen=True, slots=True)
class CareFinding:
    path: str
    reasons: tuple[str, ...]


def _review_by_date(value: object, today: date) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed: date | None = None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return "review_by is not a date"
    if parsed < today:
        return f"review_by {parsed.isoformat()} is past"
    return None


def classify_note(
    *,
    path: str,
    size: int,
    frontmatter: Mapping[str, object] | None,
    today: date,
    oversized_bytes: int,
) -> CareFinding | None:
    """One note's health reasons, or None when nothing is wrong."""
    reasons: list[str] = []
    meta = frontmatter or {}
    review = _review_by_date(meta.get("review_by"), today)
    if review is not None:
        reasons.append(review)
    source = meta.get("source_client")
    if not isinstance(source, str) or not source.strip():
        reasons.append("missing provenance (source_client)")
    if size > oversized_bytes:
        reasons.append(f"oversized ({size} bytes)")
    if not reasons:
        return None
    return CareFinding(path=path, reasons=tuple(reasons))


def scan_tree(root: Path, *, today: date | None = None, oversized_bytes: int) -> list[CareFinding]:
    """Walk markdown files under a project and classify each one."""
    current = today or datetime.now(timezone.utc).date()
    findings: list[CareFinding] = []
    if not root.is_dir():
        return findings
    for path in sorted(root.rglob("*.md")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(CareFinding(str(path.relative_to(root)), ("unreadable",)))
            continue
        frontmatter: dict[str, object] | None = None
        if has_frontmatter(text):
            try:
                frontmatter = parse_frontmatter(text)
            except ParseError:
                frontmatter = None
                findings.append(
                    CareFinding(str(path.relative_to(root)), ("frontmatter did not parse",))
                )
                continue
        size = path.stat().st_size
        finding = classify_note(
            path=str(path.relative_to(root)),
            size=size,
            frontmatter=frontmatter,
            today=current,
            oversized_bytes=oversized_bytes,
        )
        if finding is not None:
            findings.append(finding)
    return findings


def render_care_report(
    findings: list[CareFinding],
    *,
    orphans: list[str],
    orphan_error: str | None,
    limit: int = 50,
) -> str:
    """Plain-text report. Long lists are capped so a large vault stays readable."""
    lines = ["# Care", ""]
    lines.append(f"notes flagged: {len(findings)}")
    shown = findings[:limit]
    for finding in shown:
        lines.append(f"- {finding.path}: {'; '.join(finding.reasons)}")
    if len(findings) > limit:
        lines.append(f"- … {len(findings) - limit} more")
    lines.append("")
    if orphan_error:
        lines.append(f"orphans: unavailable ({orphan_error})")
    else:
        lines.append(f"orphans: {len(orphans)}")
        for path in orphans[:limit]:
            lines.append(f"- {path}")
        if len(orphans) > limit:
            lines.append(f"- … {len(orphans) - limit} more")
    lines.append("")
    lines.append("File/database consistency is `bm doctor`, not this report.")
    return "\n".join(lines) + "\n"
