"""Challenge rules (pure): answer normalization, reward policy, lifecycle, attempts, AI verdicts
and winner selection (BL-5.01..5.05; CHAL-002, CHAL-003, CHAL-005..007, CHAL-009, CHAL-010,
CHAL-012..014)."""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

STATUSES: Final = ("draft", "scheduled", "active", "judging", "completed", "cancelled")
EDITABLE: Final = frozenset({"draft", "scheduled"})
REVIEWED_REWARDS: Final = frozenset({"discount_code", "promotional"})

# Leading articles removed when a locale is listed in `strip_articles` (CHAL-006).
ARTICLES: Final[Mapping[str, tuple[str, ...]]] = {
    "en": ("the", "an", "a"),
    "pt": ("os", "as", "um", "uma", "o", "a"),
    "es": ("los", "las", "una", "un", "el", "la"),
    "fr": ("les", "une", "un", "le", "la"),
    "de": ("der", "die", "das", "den", "dem", "des", "eine", "einen", "ein"),
    "it": ("gli", "uno", "una", "il", "lo", "la", "le", "un", "i"),
}
_RIGHT_QUOTE = chr(0x2019)  # typographic apostrophe
_ELISION = re.compile(f"^(l|d)['{_RIGHT_QUOTE}]", re.IGNORECASE)  # French/Italian l', d'


@dataclass(frozen=True, slots=True)
class Normalization:
    case_fold: bool = True
    strip_accents: bool = True
    strip_punctuation: bool = True
    collapse_whitespace: bool = True
    strip_articles: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> Normalization:
        raw = raw or {}
        return cls(
            case_fold=bool(raw.get("case_fold", True)),
            strip_accents=bool(raw.get("strip_accents", True)),
            strip_punctuation=bool(raw.get("strip_punctuation", True)),
            collapse_whitespace=bool(raw.get("collapse_whitespace", True)),
            strip_articles=tuple(raw.get("strip_articles") or ()),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "case_fold": self.case_fold,
            "strip_accents": self.strip_accents,
            "strip_punctuation": self.strip_punctuation,
            "collapse_whitespace": self.collapse_whitespace,
            "strip_articles": list(self.strip_articles),
        }


def normalize(answer: str, rules: Normalization) -> str:
    """The comparable form of an answer: Unicode NFKC, then the configured folds."""
    text = unicodedata.normalize("NFKC", answer).strip()
    if rules.case_fold:
        text = text.casefold()
    if rules.strip_accents:
        decomposed = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in decomposed if not unicodedata.combining(c))
    languages = {tag.split("-", 1)[0].lower() for tag in rules.strip_articles}
    if languages & {"fr", "it"}:
        text = _ELISION.sub("", text)
    if rules.strip_punctuation:
        text = "".join(" " if unicodedata.category(c).startswith(("P", "S")) else c for c in text)
    if rules.collapse_whitespace or rules.strip_punctuation:
        text = " ".join(text.split())
    for language in sorted(languages):
        for article in ARTICLES.get(language, ()):
            if text.casefold().startswith(article + " "):
                text = text[len(article) + 1 :].lstrip()
                break
    return text


def matches(answer: str, accepted: Sequence[str], rules: Normalization) -> bool:
    candidate = normalize(answer, rules)
    return bool(candidate) and candidate in set(accepted)


# Cash, cash equivalents, paid entry and random draws are never allowed (CHAL-013). Rewards are
# limited to badges, achievements, discount codes and documented non-cash promotions.
_PROHIBITED: Final = re.compile(
    r"(\$|€|£|¥|r\$)\s?\d"
    r"|\d+([.,]\d+)?\s?(usd|eur|brl|gbp|reais|dollars?|euros?|pesos)\b"
    r"|\b(cash|money|dinheiro|efectivo|argent|bargeld|gift ?cards?|cart[aã]o[- ]presente"
    r"|tarjeta regalo|carte cadeau|gutschein|paypal|pix|venmo|bitcoin|crypto"
    r"|raffle|lottery|sorteio|sorteo|tirage au sort|verlosung|random draw"
    r"|entry fee|taxa de inscri[cç][aã]o|cuota de inscripci[oó]n|wager|bet|aposta|apuesta)\b",
    re.IGNORECASE,
)


def prohibited_prize(*texts: str | None) -> bool:
    return any(text and _PROHIBITED.search(text) for text in texts)


@dataclass(frozen=True, slots=True)
class RewardInput:
    reward_type: str
    title: str
    description: str | None
    badge_key: str | None
    sponsor_name: str | None
    quantity: int
    eligibility_rules: str | None
    terms_url: str | None
    fulfillment_owner: str


def reward_problems(reward: RewardInput) -> list[str]:
    problems = []
    if reward.reward_type == "badge" and not reward.badge_key:
        problems.append("badge rewards need a badge_key")
    if reward.reward_type in REVIEWED_REWARDS and not (reward.eligibility_rules or "").strip():
        problems.append(f"{reward.reward_type} rewards need eligibility_rules")
    return problems


def next_attempt_at(
    last_attempt_at: datetime | None, cooldown_seconds: int, now: datetime
) -> datetime | None:
    """When the cooldown after the last attempt ends, or ``None`` if it already has."""
    if last_attempt_at is None or cooldown_seconds <= 0:
        return None
    ready = last_attempt_at + timedelta(seconds=cooldown_seconds)
    return ready if ready > now else None


def attempt_block(
    *,
    max_attempts: int,
    cooldown_seconds: int,
    attempts_used: int,
    last_attempt_at: datetime | None,
    now: datetime,
) -> tuple[str, datetime | None] | None:
    """Why another attempt is refused right now (CHAL-005): ``attempts_exhausted`` or
    ``attempt_cooldown`` with the time it ends; ``None`` when the attempt may go ahead."""
    if attempts_used >= max_attempts:
        return "attempts_exhausted", None
    ready = next_attempt_at(last_attempt_at, cooldown_seconds, now)
    if ready is not None:
        return "attempt_cooldown", ready
    return None


def first_evaluation(validation_method: str, matched: bool) -> tuple[str, str | None]:
    """``(evaluation_status, evaluator)`` at submission time (CHAL-006).

    A normalized exact match is decided at once (also for ``ai_assisted``, where the AI only
    looks at answers that do not match). Everything else waits for an admin or the AI judge.
    """
    if matched and validation_method in ("exact", "ai_assisted"):
        return "correct", "exact"
    if validation_method == "exact":
        return "incorrect", "exact"
    return "pending", None


def winner_slots(policy: str, max_winners: int) -> int | None:
    """How many winners the system may pick by itself (CHAL-010); ``None`` means no limit.
    ``admin_selects`` leaves every pick to the judges."""
    if policy == "first_correct":
        return 1
    if policy == "first_n_correct":
        return max_winners
    if policy == "all_correct":
        return None
    return 0


# An AI verdict settles an answer only at this confidence or above (CHAL-007).
AI_SURE: Final = 0.8


@dataclass(frozen=True, slots=True)
class AIVerdict:
    matches: bool
    confidence: float
    rationale: str


def ai_outcome(verdict: AIVerdict | None, *, badge_only: bool) -> str:
    """The evaluation an AI verdict leads to (CHAL-007). A confident match decides alone only when
    every reward is a badge; a confident mismatch is incorrect; anything else (no verdict, low
    confidence, real-world rewards) goes to the judges as ``needs_review``."""
    if verdict is None or verdict.confidence < AI_SURE:
        return "needs_review"
    if verdict.matches:
        return "correct" if badge_only else "needs_review"
    return "incorrect"


Recipient = tuple[str, uuid.UUID]  # ("user", id) or ("team", id)


def pick_winners(
    correct: Sequence[tuple[Recipient, uuid.UUID]],
    *,
    slots: int | None,
    confirmed: frozenset[Recipient] = frozenset(),
    revoked: frozenset[Recipient] = frozenset(),
) -> list[tuple[Recipient, uuid.UUID]]:
    """Winners from correct submissions in submission order (CHAL-009, CHAL-010): each
    recipient's first correct submission counts; confirmed winners keep their place and use a
    slot; revoked ones stay out; provisional winners fill the remaining slots in order, so an
    earlier answer judged later still wins ahead of a later one."""
    firsts: list[tuple[Recipient, uuid.UUID]] = []
    seen: set[Recipient] = set()
    for recipient, submission_id in correct:
        if recipient in seen or recipient in revoked:
            continue
        seen.add(recipient)
        firsts.append((recipient, submission_id))
    budget = None if slots is None else slots - sum(1 for r, _ in firsts if r in confirmed)
    chosen: list[tuple[Recipient, uuid.UUID]] = []
    for recipient, submission_id in firsts:
        if recipient not in confirmed:
            if budget is not None and budget <= 0:
                continue
            if budget is not None:
                budget -= 1
        chosen.append((recipient, submission_id))
    return chosen


def status_at(status: str, starts_at: datetime, ends_at: datetime, now: datetime) -> str:
    """What the scheduler moves a published challenge to (CHAL-003)."""
    if status == "scheduled" and starts_at <= now:
        status = "active"
    if status == "active" and ends_at <= now:
        status = "judging"
    return status
