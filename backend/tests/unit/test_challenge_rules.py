"""Challenge answer normalization, prize policy, lifecycle, attempts and winner slots
(BL-5.01..5.03; CHAL-003, CHAL-005, CHAL-006, CHAL-010, CHAL-013)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.challenges.domain import (
    AIVerdict,
    Normalization,
    RewardInput,
    ai_outcome,
    attempt_block,
    first_evaluation,
    matches,
    next_attempt_at,
    normalize,
    pick_winners,
    prohibited_prize,
    reward_problems,
    status_at,
    winner_slots,
)

DEFAULT = Normalization(strip_articles=("en", "pt-BR", "fr"))


@pytest.mark.req("CHAL-006")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  The   Tower of Belém! ", "tower of belem"),
        ("TORRE DE BELÉM", "torre de belem"),
        ("O Cristo Redentor", "cristo redentor"),
        ("A Ponte 25 de Abril", "ponte 25 de abril"),
        ("L'Arc de Triomphe", "arc de triomphe"),
        ("São-Paulo", "sao paulo"),
        ("".join(chr(0xFF21 + ord(c) - ord("A")) for c in "FULLWIDTH"), "fullwidth"),
        ("Theatre", "theatre"),  # only whole leading words are articles
    ],
)
def test_normalization_folds_case_accents_punctuation_spaces_and_articles(
    raw: str, expected: str
) -> None:
    assert normalize(raw, DEFAULT) == expected


@pytest.mark.req("CHAL-006")
def test_options_can_be_turned_off_and_multiple_answers_match() -> None:
    strict = Normalization(case_fold=False, strip_accents=False, strip_punctuation=False)
    assert normalize("Belém!", strict) == "Belém!"
    accepted = [normalize(a, DEFAULT) for a in ("Belém Tower", "Torre de Belém")]
    assert matches("the belem tower", accepted, DEFAULT)
    assert matches("TORRE DE BELEM", accepted, DEFAULT)
    assert not matches("Jerónimos", accepted, DEFAULT)
    assert not matches("   ", accepted, DEFAULT)


@pytest.mark.req("CHAL-013")
@pytest.mark.parametrize(
    "text",
    [
        "Win $50!",
        "R$ 100 em prêmios",
        "A 20 EUR voucher",
        "Amazon gift card",
        "Prize paid via PIX",
        "Raffle among all correct answers",
        "Sorteio entre os participantes",
        "Entry fee of 5",
    ],
)
def test_cash_draws_and_paid_entry_are_prohibited(text: str) -> None:
    assert prohibited_prize(text)


def test_ordinary_prizes_are_allowed() -> None:
    assert not prohibited_prize("Bragging rights and the Explorer badge", None)
    assert not prohibited_prize("10% off your next tour with our partner")


def test_reviewed_rewards_need_eligibility_and_badges_a_key() -> None:
    base = RewardInput("badge", "Explorer", None, None, None, 1, None, None, "platform")
    assert reward_problems(base) == ["badge rewards need a badge_key"]
    discount = RewardInput(
        "discount_code", "10% off", None, None, "Partner", 3, None, None, "sponsor"
    )
    assert reward_problems(discount) == ["discount_code rewards need eligibility_rules"]


@pytest.mark.req("CHAL-003")
def test_lifecycle_moves_scheduled_to_active_to_judging() -> None:
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    start, end = now - timedelta(hours=1), now + timedelta(hours=1)
    assert status_at("scheduled", start, end, now) == "active"
    assert status_at("scheduled", start, start + timedelta(minutes=1), now) == "judging"
    assert status_at("scheduled", now + timedelta(minutes=5), end, now) == "scheduled"
    assert status_at("draft", start, end, now) == "draft"


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@pytest.mark.req("CHAL-005")
def test_attempts_are_limited_and_spaced_by_the_cooldown() -> None:
    def block(used: int, last: datetime | None, cooldown: int = 30) -> object:
        return attempt_block(
            max_attempts=3,
            cooldown_seconds=cooldown,
            attempts_used=used,
            last_attempt_at=last,
            now=NOW,
        )

    assert block(0, None) is None
    assert block(1, NOW - timedelta(seconds=10)) == (
        "attempt_cooldown",
        NOW + timedelta(seconds=20),
    )
    assert block(1, NOW - timedelta(seconds=30)) is None  # the cooldown has just ended
    assert block(1, NOW - timedelta(seconds=1), cooldown=0) is None
    assert block(3, None) == ("attempts_exhausted", None)
    assert block(3, NOW) == ("attempts_exhausted", None)  # exhaustion wins over the cooldown
    assert next_attempt_at(None, 30, NOW) is None
    assert next_attempt_at(NOW, 30, NOW) == NOW + timedelta(seconds=30)


@pytest.mark.req("CHAL-006", "CHAL-007")
@pytest.mark.parametrize(
    ("method", "matched", "expected"),
    [
        ("exact", True, ("correct", "exact")),
        ("exact", False, ("incorrect", "exact")),
        ("ai_assisted", True, ("correct", "exact")),
        ("ai_assisted", False, ("pending", None)),  # the AI judge looks at it later
        ("admin_review", True, ("pending", None)),  # admins decide even on a match
        ("admin_review", False, ("pending", None)),
    ],
)
def test_first_evaluation_by_validation_method(
    method: str, matched: bool, expected: tuple[str, str | None]
) -> None:
    assert first_evaluation(method, matched) == expected


@pytest.mark.req("CHAL-010")
def test_winner_slots_follow_the_policy() -> None:
    assert winner_slots("first_correct", 5) == 1
    assert winner_slots("first_n_correct", 3) == 3
    assert winner_slots("all_correct", 1) is None
    assert winner_slots("admin_selects", 3) == 0


@pytest.mark.req("CHAL-007", "T-CHAL-05")
def test_ai_verdicts_settle_only_confident_badge_level_answers() -> None:
    sure_yes = AIVerdict(matches=True, confidence=0.9, rationale="Same tower.")
    sure_no = AIVerdict(matches=False, confidence=0.95, rationale="Different place.")
    unsure = AIVerdict(matches=True, confidence=0.5, rationale="Could be.")
    assert ai_outcome(sure_yes, badge_only=True) == "correct"
    assert ai_outcome(sure_yes, badge_only=False) == "needs_review"  # real rewards: a human
    assert ai_outcome(sure_no, badge_only=False) == "incorrect"
    assert ai_outcome(unsure, badge_only=True) == "needs_review"
    assert ai_outcome(None, badge_only=True) == "needs_review"  # no verdict: a human decides


@pytest.mark.req("CHAL-009", "CHAL-010")
def test_winners_follow_submission_order_and_judges_decisions() -> None:
    a, b, c, d = (("user", uuid.uuid4()) for _ in range(4))
    s = [uuid.uuid4() for _ in range(5)]
    correct = [(a, s[0]), (b, s[1]), (a, s[2]), (c, s[3]), (d, s[4])]
    assert pick_winners(correct, slots=2) == [(a, s[0]), (b, s[1])]  # first correct per person
    assert pick_winners(correct, slots=None) == [(a, s[0]), (b, s[1]), (c, s[3]), (d, s[4])]
    assert pick_winners(correct, slots=2, revoked=frozenset({b})) == [(a, s[0]), (c, s[3])]
    # A confirmed winner keeps a slot wherever they are in the order.
    assert pick_winners(correct, slots=2, confirmed=frozenset({d})) == [(a, s[0]), (d, s[4])]
    assert pick_winners([], slots=1) == []
