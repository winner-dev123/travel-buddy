"""Pure post rules (POST-001/002/008/009) and post web-cache mapping (SAFE-012)."""

from __future__ import annotations

import pytest

from app.modules.social.domain import (
    ViewerRelation,
    can_view,
    clean_body,
    clean_tags,
    effective_visibility,
    is_indexable,
    is_publicly_listed,
    kind_violations,
)
from app.modules.web_cache.domain import revalidation_for

AUTHOR = ViewerRelation(is_author=True)
STRANGER = ViewerRelation(is_author=False)
FOLLOWER = ViewerRelation(is_author=False, is_follower=True)
CONNECTION = ViewerRelation(is_author=False, is_connected=True)


def test_body_is_normalized() -> None:
    assert clean_body("  Hi‮ there \r\n\r\n\r\n\r\nBye  ") == "Hi there\n\nBye"


@pytest.mark.req("POST-009")
def test_tags_are_normalized_and_capped() -> None:
    assert clean_tags(["#Street  Food", "street food", "  ", "Beaches"]) == [
        "street food",
        "beaches",
    ]
    with pytest.raises(ValueError, match="at most 40"):
        clean_tags(["x" * 41])
    with pytest.raises(ValueError, match="at most 10"):
        clean_tags([f"t{i}" for i in range(11)])


@pytest.mark.req("POST-001")
@pytest.mark.parametrize(
    ("kwargs", "codes"),
    [
        (
            {"kind": "review", "rating": None, "location_precision": "destination"},
            ["/rating:required"],
        ),
        ({"kind": "text", "rating": 4}, ["/rating:not_allowed"]),
        ({"kind": "restaurant_recommendation"}, ["/location_precision:required"]),
        ({"kind": "photo"}, ["/media_ids:required"]),
        ({"kind": "itinerary_summary"}, ["/trip_id:required"]),
        ({"kind": "text", "body": ""}, ["/body:required"]),
        ({"kind": "review", "rating": 5, "location_precision": "destination"}, []),
        ({"kind": "tip"}, []),
    ],
)
def test_kind_requirements(kwargs: dict[str, object], codes: list[str]) -> None:
    values: dict[str, object] = {
        "kind": "text",
        "body": "Hello",
        "media_count": 0,
        "location_precision": "none",
        "rating": None,
        "trip_id": None,
    }
    values.update(kwargs)
    problems = kind_violations(**values)  # type: ignore[arg-type]
    assert [f"{p.field}:{p.code}" for p in problems] == codes


@pytest.mark.req("POST-008", "PROF-004")
@pytest.mark.parametrize(
    ("visibility", "account_private", "relation", "expected"),
    [
        ("public", False, STRANGER, True),
        ("public", True, STRANGER, False),  # private account: followers only
        ("public", True, FOLLOWER, True),
        ("followers", False, STRANGER, False),
        ("followers", False, FOLLOWER, True),
        ("connections", False, FOLLOWER, False),
        ("connections", False, CONNECTION, True),
        ("private", False, FOLLOWER, False),
        ("private", False, AUTHOR, True),
    ],
)
def test_visibility_matrix(
    visibility: str, account_private: bool, relation: ViewerRelation, expected: bool
) -> None:
    assert (
        can_view(
            visibility=visibility,
            status="published",
            moderation_state="approved",
            account_private=account_private,
            relation=relation,
        )
        is expected
    )


@pytest.mark.security
def test_deleted_and_removed_posts() -> None:
    common = {"visibility": "public", "account_private": False}
    assert not can_view(status="deleted", moderation_state="approved", relation=AUTHOR, **common)
    assert not can_view(status="published", moderation_state="removed", relation=STRANGER, **common)
    assert can_view(status="published", moderation_state="removed", relation=AUTHOR, **common)


def test_listing_and_indexing_flags() -> None:
    assert effective_visibility("public", account_private=True) == "followers"
    assert is_publicly_listed(
        visibility="public", moderation_state="pending", account_private=False
    )
    assert not is_publicly_listed(
        visibility="public", moderation_state="removed", account_private=False
    )
    assert not is_publicly_listed(
        visibility="public", moderation_state="approved", account_private=True
    )
    assert is_indexable(
        visibility="public",
        moderation_state="approved",
        account_private=False,
        author_opted_in=True,
    )
    assert not is_indexable(
        visibility="public", moderation_state="pending", account_private=False, author_opted_in=True
    )
    assert not is_indexable(
        visibility="public",
        moderation_state="approved",
        account_private=False,
        author_opted_in=False,
    )


@pytest.mark.req("SAFE-012")
@pytest.mark.parametrize(
    ("event_type", "data", "reason"),
    [
        ("post.published", {"post_id": "p", "public": True}, "post_published"),
        ("post.published", {"post_id": "p", "public": False}, None),
        ("post.deleted", {"post_id": "p", "was_public": True}, "post_deleted"),
        ("post.deleted", {"post_id": "p", "was_public": False}, None),
        (
            "post.updated",
            {"post_id": "p", "was_public": True, "public": False},
            "post_visibility_changed",
        ),
        ("post.updated", {"post_id": "p", "was_public": True, "public": True}, None),
    ],
)
def test_post_events_purge_story_pages(
    event_type: str, data: dict[str, object], reason: str | None
) -> None:
    decision = revalidation_for(event_type, data)
    if reason is None:
        assert decision is None
    else:
        assert decision is not None
        assert decision.reason == reason
        assert decision.tags == ("story:p", "stories", "sitemap")
