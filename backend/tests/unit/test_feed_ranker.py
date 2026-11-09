"""Pure feed ranking and diversity (FEED-006, FEED-020)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.feed.domain import (
    WEIGHTS_V1,
    ViewerSignals,
    destination_match,
    diversify,
    haversine_km,
    interest_overlap,
    language_match,
    recency,
    score,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
VIEWER = ViewerSignals(interests=frozenset({"street food"}), languages=frozenset({"en"}))


@dataclass
class Item:
    author_id: object = field(default_factory=uuid.uuid4)
    post_id: object = field(default_factory=uuid.uuid4)
    published_at: datetime = NOW - timedelta(hours=1)
    language: str = "en"
    body_length: int = 200
    body_digest: str = field(default_factory=lambda: uuid.uuid4().hex)
    location_precision: str = "destination"
    match_depth: int | None = 0
    reactions: int = 0
    comments: int = 0
    bookmarks: int = 0
    shares: int = 0
    helpful: int = 0
    tags: list[str] = field(default_factory=list)


def test_weights_are_versioned_v1() -> None:
    assert WEIGHTS_V1.version == "v1"
    assert WEIGHTS_V1.destination_match == 0.30
    assert WEIGHTS_V1.negative_feedback == 0.40


@pytest.mark.req("FEED-020")
def test_feature_shapes() -> None:
    assert [destination_match(d) for d in (0, 1, 2, -1, None)] == [1.0, 0.8, 0.8, 0.5, 0.0]
    assert recency(0, 72) == 1.0
    assert recency(72, 72) == pytest.approx(0.5)
    assert interest_overlap(["Street Food", "museums"], frozenset({"street food"})) == 0.5
    assert language_match("pt-BR", frozenset({"pt"})) == 1.0
    assert language_match("de", frozenset({"pt"})) == 0.0
    assert language_match("de", frozenset()) == 1.0
    assert haversine_km((-22.9068, -43.1729), (38.7223, -9.1393)) == pytest.approx(7700, rel=0.03)


@pytest.mark.req("FEED-020", "POST-003")
def test_ranking_prefers_relevant_fresh_engaging_posts() -> None:
    exact = Item(match_depth=0)
    parent = Item(match_depth=-1)
    old = Item(match_depth=0, published_at=NOW - timedelta(days=10))
    engaged = Item(match_depth=0, reactions=30, helpful=10, comments=5)
    by_score = sorted(
        [old, parent, exact, engaged], key=lambda i: score(i, now=NOW, viewer=VIEWER), reverse=True
    )
    assert by_score[0] is engaged
    assert by_score.index(exact) < by_score.index(parent)
    assert by_score.index(exact) < by_score.index(old)


@pytest.mark.req("FEED-007")
def test_see_less_from_author_is_a_strong_penalty() -> None:
    disliked = Item(reactions=40)
    plain = Item()
    viewer = ViewerSignals(
        interests=frozenset(),
        languages=frozenset(),
        see_less_authors=frozenset({disliked.author_id}),
    )
    assert score(disliked, now=NOW, viewer=viewer) < score(plain, now=NOW, viewer=viewer)


@pytest.mark.req("FEED-006")
def test_at_most_two_posts_per_author_per_page() -> None:
    prolific = uuid.uuid4()
    ranked = [Item(author_id=prolific) for _ in range(6)] + [Item() for _ in range(20)]
    page = diversify(ranked, window=10)[:10]
    assert sum(1 for i in page if i.author_id == prolific) == 2
    assert len(page) == 10


@pytest.mark.req("FEED-006")
def test_near_duplicates_are_suppressed_and_capped_authors_fill_short_pages() -> None:
    same = Item(body_digest="dup")
    ranked = [same, Item(body_digest="dup"), Item()]
    assert len(diversify(ranked)) == 2
    solo = uuid.uuid4()
    only_one_author = [Item(author_id=solo) for _ in range(5)]
    assert len(diversify(only_one_author, window=10)) == 5  # no holes when no one else posts
