"""Pure post rules: per-kind requirements, text/tag normalization and visibility (POST-001/008)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

BODY_MAX = 5000
TAG_MAX = 40
TAGS_MAX = 10

# Kinds that only make sense attached to a place or destination.
_LOCATED_KINDS = frozenset({"attraction_recommendation", "restaurant_recommendation", "review"})
# Kinds that need uploaded media (the media pipeline lands with BL-1.08).
_MEDIA_KINDS = frozenset({"photo", "video", "story"})


@dataclass(frozen=True, slots=True)
class Violation:
    field: str
    code: str
    message: str


def _strip_invisible(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) not in {"Cc", "Cf"} or ch == "\n")


def clean_body(body: str) -> str:
    """Normalize newlines, drop invisible/bidi control characters, trim, cap blank lines."""
    text = _strip_invisible(body.replace("\r\n", "\n").replace("\r", "\n"))
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_tags(tags: list[str]) -> list[str]:
    """``#Street  Food`` -> ``street food``; deduplicated, order kept. Raises on bad input."""
    result: list[str] = []
    for raw in tags:
        tag = " ".join(_strip_invisible(raw).lstrip("#").split()).lower()
        if not tag:
            continue
        if len(tag) > TAG_MAX:
            raise ValueError(f"tags must be at most {TAG_MAX} characters")
        if tag not in result:
            result.append(tag)
    if len(result) > TAGS_MAX:
        raise ValueError(f"at most {TAGS_MAX} tags")
    return result


def kind_violations(
    *,
    kind: str,
    body: str,
    media_count: int,
    location_precision: str,
    rating: int | None,
    trip_id: object | None,
) -> list[Violation]:
    """Field requirements per post kind (POST-001)."""
    problems: list[Violation] = []
    if kind == "review" and rating is None:
        problems.append(Violation("/rating", "required", "Reviews need a rating from 1 to 5."))
    if kind != "review" and rating is not None:
        problems.append(Violation("/rating", "not_allowed", "Only reviews have a rating."))
    if kind in _LOCATED_KINDS and location_precision == "none":
        problems.append(
            Violation("/location_precision", "required", "This kind of post needs a location.")
        )
    if kind in _MEDIA_KINDS and media_count == 0:
        problems.append(Violation("/media_ids", "required", "Add a photo or video."))
    if kind == "itinerary_summary" and trip_id is None:
        problems.append(Violation("/trip_id", "required", "Itinerary summaries need a trip."))
    if not body and media_count == 0:
        problems.append(Violation("/body", "required", "Write something or attach media."))
    return problems


@dataclass(frozen=True, slots=True)
class ViewerRelation:
    is_author: bool
    is_follower: bool = False
    is_connected: bool = False


def effective_visibility(visibility: str, *, account_private: bool) -> str:
    """A private account's public posts are for followers only (PROF-004)."""
    return "followers" if account_private and visibility == "public" else visibility


def can_view(
    *,
    visibility: str,
    status: str,
    moderation_state: str,
    account_private: bool,
    relation: ViewerRelation,
) -> bool:
    """POST-008: deleted posts are gone for everyone; removed ones stay visible to the author."""
    if status != "published":
        return False
    if moderation_state == "removed":
        return relation.is_author
    if relation.is_author:
        return True
    effective = effective_visibility(visibility, account_private=account_private)
    if effective == "public":
        return True
    if effective == "followers":
        return relation.is_follower
    if effective == "connections":
        return relation.is_connected
    return False


def is_publicly_listed(*, visibility: str, moderation_state: str, account_private: bool) -> bool:
    """Shown in feeds to everyone (the denormalized ``post_destinations.visibility_public``)."""
    return effective_visibility(
        visibility, account_private=account_private
    ) == "public" and moderation_state in ("approved", "pending")


def is_indexable(
    *, visibility: str, moderation_state: str, account_private: bool, author_opted_in: bool
) -> bool:
    """Contract ``PostCore.indexable`` (PROF-008)."""
    return (
        author_opted_in
        and moderation_state == "approved"
        and effective_visibility(visibility, account_private=account_private) == "public"
    )
