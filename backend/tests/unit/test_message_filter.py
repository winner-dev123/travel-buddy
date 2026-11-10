"""Keyword filter matching for messages from new connections (SAFE-006)."""

from __future__ import annotations

import pytest

from app.modules.trust_safety.domain import (
    DEFAULT_MESSAGE_FILTER_TERMS,
    clean_terms,
    matched_term,
    normalize,
)

pytestmark = pytest.mark.req("SAFE-006")

TERMS = clean_terms(DEFAULT_MESSAGE_FILTER_TERMS)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Hey, send nudes?", "send nudes"),
        ("SEND   NUDES!!!", "send nudes"),
        ("s.e.n.d n.u.d.e.s", "send nudes"),
        ("Buy me a Gift-Card and I'll pay you back", "gift card"),
        ("Passa o código de verificação que chegou", "codigo de verificacao"),
        ("Une carte cadeau ?", "carte cadeau"),
        ("Do you know a good café near the castle?", None),
        ("I love gift cards", None),  # whole words only: "cards" is not "card"
        ("", None),
    ],
)
def test_matches_whole_normalized_words(body: str, expected: str | None) -> None:
    assert matched_term(body, TERMS) == expected


def test_normalize_folds_case_accents_and_punctuation() -> None:
    assert normalize("  Ação—RÁPIDA_já! ") == "acao rapida ja"
    assert normalize("東京 Tokyo 🍣") == "東京 tokyo"


def test_clean_terms_are_unique_normalized_and_sorted() -> None:
    assert clean_terms(["Gift Card", "gift-card", " ", "Ação"]) == ["acao", "gift card"]


def test_an_empty_list_filters_nothing() -> None:
    assert matched_term("send nudes", []) is None
