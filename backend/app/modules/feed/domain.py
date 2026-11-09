"""Pure feed ranking (FEED-006, FEED-020): versioned weights, features, score, diversity.

All features are normalized to [0, 1]. The formula and weights are the PRD's v1:

    score = 0.30·destination_match + 0.20·recency + 0.15·interest_overlap
          + 0.12·engagement_quality + 0.08·content_quality + 0.07·author_trust
          + 0.05·language_match + 0.03·geo_proximity
          - 0.40·negative_feedback - 0.25·report_signal

Location relevance comes from post destination metadata only (POST-003): there is no feature for
the author's nationality, residence or IP.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Weights:
    version: str = "v1"
    destination_match: float = 0.30
    recency: float = 0.20
    interest_overlap: float = 0.15
    engagement_quality: float = 0.12
    content_quality: float = 0.08
    author_trust: float = 0.07
    language_match: float = 0.05
    geo_proximity: float = 0.03
    negative_feedback: float = 0.40
    report_signal: float = 0.25
    recency_half_life_hours: float = 72.0


WEIGHTS_V1 = Weights()
DIVERSITY_WINDOW = 20
MAX_PER_AUTHOR = 2
_ENGAGEMENT_SATURATION = 50.0
_DEFAULT_AUTHOR_TRUST = 0.5  # until trust signals exist (verified badges, report history)


class Rankable(Protocol):
    @property
    def post_id(self) -> object: ...
    @property
    def author_id(self) -> object: ...
    @property
    def published_at(self) -> datetime: ...
    @property
    def language(self) -> str: ...
    @property
    def body_length(self) -> int: ...
    @property
    def body_digest(self) -> str: ...
    @property
    def location_precision(self) -> str: ...
    @property
    def match_depth(self) -> int | None: ...
    @property
    def reactions(self) -> int: ...
    @property
    def comments(self) -> int: ...
    @property
    def bookmarks(self) -> int: ...
    @property
    def shares(self) -> int: ...
    @property
    def helpful(self) -> int: ...
    @property
    def tags(self) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class ViewerSignals:
    interests: frozenset[str]
    languages: frozenset[str]  # base language codes, e.g. {"pt", "en"}
    see_less_authors: frozenset[object] = frozenset()
    reported_posts: frozenset[object] = frozenset()


def destination_match(depth: int | None) -> float:
    """1.0 exact, 0.8 tagged to a descendant (neighborhood within the city), 0.5 tagged to a
    parent; 0 when the feed has no target destination (following, global)."""
    if depth is None:
        return 0.0
    if depth == 0:
        return 1.0
    return 0.8 if depth > 0 else 0.5


def recency(age_hours: float, half_life_hours: float) -> float:
    return float(0.5 ** (max(age_hours, 0.0) / half_life_hours))


def interest_overlap(tags: Iterable[str], interests: frozenset[str]) -> float:
    tag_set = {t.lower() for t in tags}
    if not tag_set or not interests:
        return 0.0
    return min(1.0, len(tag_set & interests) / min(len(tag_set), 3))


def engagement_quality(item: Rankable) -> float:
    """Helpful-weighted engagement, log-saturating (views are not tracked yet)."""
    raw = item.reactions + 2 * item.helpful + 1.5 * item.comments + item.bookmarks + item.shares
    return min(1.0, math.log1p(raw) / math.log1p(_ENGAGEMENT_SATURATION))


def content_quality(item: Rankable) -> float:
    return (
        0.5 * min(1.0, item.body_length / 280)
        + 0.25 * (1.0 if item.tags else 0.0)
        + 0.25 * (1.0 if item.location_precision != "none" else 0.0)
    )


def language_match(language: str, languages: frozenset[str]) -> float:
    if not languages:
        return 1.0
    return 1.0 if language.split("-", 1)[0].lower() in languages else 0.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def geo_proximity(distance_km: float | None, radius_km: float | None) -> float:
    if distance_km is None or not radius_km:
        return 0.0
    return max(0.0, 1.0 - distance_km / radius_km)


def score(
    item: Rankable,
    *,
    now: datetime,
    viewer: ViewerSignals,
    weights: Weights = WEIGHTS_V1,
    distance_km: float | None = None,
    radius_km: float | None = None,
) -> float:
    age_hours = (now - item.published_at).total_seconds() / 3600
    return (
        weights.destination_match * destination_match(item.match_depth)
        + weights.recency * recency(age_hours, weights.recency_half_life_hours)
        + weights.interest_overlap * interest_overlap(item.tags, viewer.interests)
        + weights.engagement_quality * engagement_quality(item)
        + weights.content_quality * content_quality(item)
        + weights.author_trust * _DEFAULT_AUTHOR_TRUST
        + weights.language_match * language_match(item.language, viewer.languages)
        + weights.geo_proximity * geo_proximity(distance_km, radius_km)
        - weights.negative_feedback * (1.0 if item.author_id in viewer.see_less_authors else 0.0)
        - weights.report_signal * (1.0 if item.post_id in viewer.reported_posts else 0.0)
    )


def diversify[T: Rankable](
    ranked: Sequence[T], *, window: int = DIVERSITY_WINDOW, per_author: int = MAX_PER_AUTHOR
) -> list[T]:
    """Near-duplicate suppression, then at most ``per_author`` items per author in every
    consecutive ``window`` (a page at the default size), keeping rank order otherwise. When only
    capped authors remain, they fill the remaining slots rather than leaving holes."""
    seen_digests: set[str] = set()
    remaining: list[T] = []
    for item in ranked:
        if item.body_digest in seen_digests:
            continue
        seen_digests.add(item.body_digest)
        remaining.append(item)
    result: list[T] = []
    while remaining:
        counts: Counter[object] = Counter()
        page: list[T] = []
        rest: list[T] = []
        for item in remaining:
            if len(page) < window and counts[item.author_id] < per_author:
                page.append(item)
                counts[item.author_id] += 1
            else:
                rest.append(item)
        if len(page) < window and rest and not any(counts[i.author_id] < per_author for i in rest):
            # Only capped authors left: fill instead of producing a short page.
            fill = window - len(page)
            page += rest[:fill]
            rest = rest[fill:]
        result += page
        remaining = rest
    return result
