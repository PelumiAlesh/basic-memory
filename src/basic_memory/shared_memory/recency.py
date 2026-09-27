"""Optional recency weighting for search scores.

Weight 0 leaves ranking untouched. A positive weight pulls newer notes up
inside the candidate window the search already retrieved. It does not rescore
the whole project.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Scored(Protocol):
    score: float | None
    updated_at: datetime


def recency_factor(updated_at: datetime, *, now: datetime, half_life_days: float) -> float:
    """1.0 for a note updated now, 0.5 at one half-life, approaching 0 as it ages."""
    if half_life_days <= 0:
        return 1.0
    moment = (
        updated_at if updated_at.tzinfo is not None else updated_at.replace(tzinfo=timezone.utc)
    )
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (current - moment).total_seconds()) / 86400
    return 0.5 ** (age_days / half_life_days)


def weighted_score(score: float, factor: float, *, weight: float) -> float:
    """Blend the original score with its recency-scaled copy.

    Weight 0 returns the score. Weight 1 multiplies by the recency factor.
    """
    bounded = min(max(weight, 0.0), 1.0)
    return score * ((1.0 - bounded) + bounded * factor)


def apply_recency[T: Scored](
    rows: list[T],
    *,
    weight: float,
    half_life_days: float,
    now: datetime | None = None,
) -> list[T]:
    """Re-rank rows. The objects are mutated in place and returned sorted."""
    if weight <= 0 or not rows:
        return rows
    moment = now or datetime.now(timezone.utc)
    for row in rows:
        base = row.score or 0.0
        factor = recency_factor(row.updated_at, now=moment, half_life_days=half_life_days)
        row.score = weighted_score(base, factor, weight=weight)
    rows.sort(key=lambda row: row.score or 0.0, reverse=True)
    return rows
