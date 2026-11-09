"""Discovery matching (pure; DISC-005/008, T-LOC-04).

Score = 0.40 x interests + 0.25 x travel styles + 0.20 x languages + 0.15 x travel-date overlap,
each a 0..1 overlap (Jaccard for sets; shared days over the shorter stay for dates). Scores are
bucketed (high >= 0.45, medium >= 0.20, low) and never exposed. Within a bucket the order is
shuffled per request, so position reveals nothing over time; travellers whose requests the viewer
recently declined go last.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

WEIGHTS = {"interests": 0.40, "travel_styles": 0.25, "languages": 0.20, "dates": 0.15}
HIGH, MEDIUM = 0.45, 0.20


@dataclass(frozen=True, slots=True)
class Traits:
    interests: frozenset[str] = field(default_factory=frozenset)
    travel_styles: frozenset[str] = field(default_factory=frozenset)
    languages: frozenset[str] = field(default_factory=frozenset)
    start: date | None = None
    end: date | None = None


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def date_overlap(a: Traits, b: Traits) -> float:
    if not (a.start and a.end and b.start and b.end):
        return 0.0
    shared = (min(a.end, b.end) - max(a.start, b.start)).days + 1
    if shared <= 0:
        return 0.0
    shortest = min((a.end - a.start).days, (b.end - b.start).days) + 1
    return min(1.0, shared / shortest)


def score(viewer: Traits, other: Traits) -> float:
    return round(
        WEIGHTS["interests"] * jaccard(viewer.interests, other.interests)
        + WEIGHTS["travel_styles"] * jaccard(viewer.travel_styles, other.travel_styles)
        + WEIGHTS["languages"] * jaccard(viewer.languages, other.languages)
        + WEIGHTS["dates"] * date_overlap(viewer, other),
        4,
    )


def bucket(value: float) -> str:
    return "high" if value >= HIGH else "medium" if value >= MEDIUM else "low"


def order[T](
    items: Sequence[T],
    *,
    score_of: Callable[[T], float],
    deprioritized: Callable[[T], bool],
    rng: random.Random,
) -> list[T]:
    """High, medium, low; shuffled within each band; deprioritized ones after the rest."""
    bands: dict[tuple[bool, int], list[T]] = {}
    rank = {"high": 0, "medium": 1, "low": 2}
    for item in items:
        bands.setdefault((deprioritized(item), rank[bucket(score_of(item))]), []).append(item)
    result: list[T] = []
    for key in sorted(bands):
        band = bands[key]
        rng.shuffle(band)
        result.extend(band)
    return result
