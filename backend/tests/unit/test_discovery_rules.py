"""Discovery matching and ordering (BL-2.03; DISC-005, DISC-008, T-LOC-04)."""

from __future__ import annotations

import random
from datetime import date

import pytest

from app.modules.discovery.domain import (
    WEIGHTS,
    Traits,
    bucket,
    date_overlap,
    jaccard,
    order,
    score,
)

pytestmark = pytest.mark.req("DISC-005")


def test_weights_are_documented_and_sum_to_one() -> None:
    assert WEIGHTS == {"interests": 0.40, "travel_styles": 0.25, "languages": 0.20, "dates": 0.15}
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_overlaps() -> None:
    assert jaccard(frozenset({"food", "art"}), frozenset({"food", "hiking"})) == pytest.approx(
        1 / 3
    )
    assert jaccard(frozenset(), frozenset()) == 0.0
    a = Traits(start=date(2026, 12, 1), end=date(2026, 12, 10))
    b = Traits(start=date(2026, 12, 8), end=date(2026, 12, 20))
    assert date_overlap(a, b) == pytest.approx(3 / 10)
    assert date_overlap(a, Traits(start=date(2027, 1, 1), end=date(2027, 1, 2))) == 0.0
    assert date_overlap(a, Traits()) == 0.0


def test_identical_travellers_score_high_and_strangers_low() -> None:
    twin = Traits(
        interests=frozenset({"food"}),
        travel_styles=frozenset({"backpacking"}),
        languages=frozenset({"en"}),
        start=date(2026, 12, 1),
        end=date(2026, 12, 5),
    )
    assert score(twin, twin) == pytest.approx(1.0)
    assert bucket(score(twin, twin)) == "high"
    assert bucket(score(twin, Traits(languages=frozenset({"en"})))) == "medium"
    assert bucket(score(twin, Traits(interests=frozenset({"golf"})))) == "low"


@pytest.mark.req("DISC-008")
def test_bands_then_shuffle_with_declined_last() -> None:
    items = [("h1", 0.9), ("h2", 0.8), ("m1", 0.3), ("l1", 0.0), ("declined-high", 0.95)]
    ordered = order(
        items,
        score_of=lambda i: i[1],
        deprioritized=lambda i: i[0].startswith("declined"),
        rng=random.Random(7),  # noqa: S311 - ordering only
    )
    names = [i[0] for i in ordered]
    assert set(names[:2]) == {"h1", "h2"}
    assert names[2:] == ["m1", "l1", "declined-high"]


def test_order_within_a_band_does_not_leak_ranking() -> None:
    items = [(f"h{i}", 0.5 + i / 100) for i in range(8)]
    orders = {
        tuple(
            i[0]
            for i in order(
                items,
                score_of=lambda i: i[1],
                deprioritized=lambda _: False,
                rng=random.Random(s),  # noqa: S311
            )
        )
        for s in range(10)
    }
    assert len(orders) > 1  # shuffled per request, not sorted by the hidden score
