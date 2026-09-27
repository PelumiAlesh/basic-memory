"""Recency weighting and the care classifier."""

from datetime import date, datetime, timezone
from pathlib import Path

from basic_memory.shared_memory.care import classify_note, render_care_report, scan_tree
from basic_memory.shared_memory.recency import apply_recency, recency_factor, weighted_score


class _Row:
    def __init__(self, score: float, updated_at: datetime) -> None:
        self.score = score
        self.updated_at = updated_at


def test_weight_zero_does_not_reorder() -> None:
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    older = _Row(0.9, datetime(2020, 1, 1, tzinfo=timezone.utc))
    newer = _Row(0.4, now)
    ranked = apply_recency([older, newer], weight=0, half_life_days=30, now=now)
    assert ranked[0] is older
    assert older.score == 0.9


def test_weight_pulls_a_newer_note_up() -> None:
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    older = _Row(0.8, datetime(2020, 1, 1, tzinfo=timezone.utc))
    newer = _Row(0.7, now)
    ranked = apply_recency([older, newer], weight=1, half_life_days=30, now=now)
    assert ranked[0] is newer
    assert recency_factor(now, now=now, half_life_days=30) == 1.0
    assert weighted_score(1.0, 0.5, weight=0) == 1.0
    assert weighted_score(1.0, 0.5, weight=1) == 0.5


def test_classify_note_flags_past_review_missing_provenance_and_size() -> None:
    finding = classify_note(
        path="notes/old.md",
        size=200,
        frontmatter={"review_by": "2020-01-01"},
        today=date(2026, 9, 27),
        oversized_bytes=100,
    )
    assert finding is not None
    assert any(reason.startswith("review_by") for reason in finding.reasons)
    assert any("provenance" in reason for reason in finding.reasons)
    assert any("oversized" in reason for reason in finding.reasons)


def test_classify_note_ignores_a_healthy_note() -> None:
    assert (
        classify_note(
            path="notes/ok.md",
            size=10,
            frontmatter={"source_client": "cursor", "review_by": "2099-01-01"},
            today=date(2026, 9, 27),
            oversized_bytes=100,
        )
        is None
    )


def test_scan_tree_reads_markdown(tmp_path: Path) -> None:
    note = tmp_path / "plain.md"
    note.write_text("# Hello\n", encoding="utf-8")
    findings = scan_tree(tmp_path, today=date(2026, 9, 27), oversized_bytes=1000)
    assert len(findings) == 1
    assert findings[0].path == "plain.md"
    report = render_care_report(findings, orphans=["other.md"], orphan_error=None)
    assert "plain.md" in report
    assert "orphans: 1" in report
    assert "bm doctor" in report
