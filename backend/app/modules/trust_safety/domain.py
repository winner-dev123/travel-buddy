"""Pure safety rules (no I/O): the keyword filter for messages from new connections (SAFE-006).

Matching is on normalized text: case-folded, accents removed, punctuation and symbols turned
into spaces, so "N.U.D.E.S" does not slip past "nudes" by its dots alone and "Ação" matches
"acao". A term matches whole words (a phrase matches consecutive words), never inside a word:
"class" does not match "classic".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

# How long a connection counts as new (days), and the terms filtered until then. Conservative on
# purpose: clear scam and solicitation phrases in the launch languages. Staff extend the list at
# runtime (``/v1/admin/safety/message-filter``).
DEFAULT_NEW_CONNECTION_DAYS = 7
DEFAULT_MESSAGE_FILTER_TERMS: tuple[str, ...] = (
    # Sexual solicitation
    "send nudes",
    "manda nudes",
    "onlyfans",
    "sugar daddy",
    "sugar baby",
    # Money scams
    "western union",
    "moneygram",
    "gift card",
    "crypto investment",
    "bitcoin investment",
    "investment opportunity",
    "guaranteed profit",
    "double your money",
    "cartao presente",
    "tarjeta regalo",
    "carte cadeau",
    "inversion en cripto",
    "investimento em cripto",
    # Account takeover
    "verification code",
    "codigo de verificacao",
    "codigo de verificacion",
    "code de verification",
    "send me your password",
)
MAX_TERMS = 500
MAX_TERM_LENGTH = 60

_SEPARATORS = re.compile(r"[\W_]+")


def normalize(text: str) -> str:
    """Case-folded, accent-free words separated by single spaces. Letters spelled out with
    punctuation inside one token ("n.u.d.e.s") are joined back into a word."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    # Accents and invisible format characters (zero-width space, soft hyphen, word joiner) go,
    # so "only\u200bfans" can't slip past "onlyfans".
    stripped = "".join(
        c for c in decomposed if not unicodedata.combining(c) and unicodedata.category(c) != "Cf"
    )
    words: list[str] = []
    for token in stripped.split():
        parts = [part for part in _SEPARATORS.split(token) if part]
        if len(parts) > 1 and all(len(part) == 1 for part in parts):
            words.append("".join(parts))
        else:
            words.extend(parts)
    return " ".join(words)


def clean_terms(terms: Iterable[str]) -> list[str]:
    """Normalized, unique, non-empty terms, sorted (what gets stored)."""
    return sorted({normalized for term in terms if (normalized := normalize(term))})


def matched_term(body: str, terms: Sequence[str]) -> str | None:
    """The first filtered term found in ``body`` (whole words), or None."""
    if not terms:
        return None
    padded = f" {normalize(body)} "
    for term in terms:
        if f" {term} " in padded:
            return term
    return None
