"""People: the travel-interest catalog, user search and relationship state (PROF-003, PROF-004,
CONN-001, I18N-003)."""

from __future__ import annotations

import uuid

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_connections import _send
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _destination, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _named(live: LiveApp, display_name: str) -> tuple[str, str, str]:
    """(token, user id, handle) for a user with this display name."""
    token, user_id = _user(live)
    updated = live.client.patch(
        "/v1/users/me", headers=_auth(token), json={"display_name": display_name}
    )
    assert updated.status_code == 200, updated.text
    handle = live.client.get("/v1/users/me", headers=_auth(token)).json()["profile"]["handle"]
    return token, user_id, handle


@pytest.mark.req("PROF-004", "I18N-003")
def test_travel_interest_catalog_is_public_and_localized(app: LiveApp) -> None:  # noqa: F811
    response = app.client.get(
        "/v1/catalog/travel-interests", headers={"Accept-Language": "pt-PT,pt;q=0.9,en;q=0.5"}
    )
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "TravelInterestCatalog")
    styles = {s["code"]: s["label"] for s in response.json()["travel_styles"]}
    assert len(styles) == 9
    assert styles["digital_nomad"] == "Nômade digital"
    hiking = next(i for i in response.json()["interests"] if i["code"] == "hiking")
    assert (hiking["label"], hiking["group"]) == ("Trilhas", "outdoors")
    english = app.client.get("/v1/catalog/travel-interests", headers={"Accept-Language": "ja"})
    assert english.json()["travel_styles"][0]["label"] == "Adventure"


@pytest.mark.req("PROF-003", "SAFE-001")
def test_user_search_matches_names_and_hides_blocked_people(app: LiveApp) -> None:  # noqa: F811
    word = f"Zeph{uuid.uuid4().hex[:8]}"  # users outlive a run in the shared catalog database
    me, _, _ = _named(app, "Searcher")
    _, alba_id, alba_handle = _named(app, f"{word} Alba")
    _, blocked_id, _ = _named(app, f"{word} Blocked")
    blocker, _, _ = _named(app, f"{word} Blocker")
    assert app.client.put(f"/v1/users/{blocked_id}/block", headers=_auth(me)).status_code in (
        200,
        204,
    )
    me_id = app.client.get("/v1/users/me", headers=_auth(me)).json()["account"]["id"]
    assert app.client.put(f"/v1/users/{me_id}/block", headers=_auth(blocker)).status_code in (
        200,
        204,
    )

    found = app.client.get("/v1/users/search", headers=_auth(me), params={"q": word.lower()})
    assert found.status_code == 200, found.text
    assert_matches_contract(found.json(), "UserSummaryPage")
    assert [u["id"] for u in found.json()["data"]] == [alba_id]  # blocked either way: gone
    by_handle = app.client.get(
        "/v1/users/search", headers=_auth(me), params={"q": f"@{alba_handle}"}
    ).json()["data"]
    assert alba_id in [u["id"] for u in by_handle]
    wildcard = app.client.get("/v1/users/search", headers=_auth(me), params={"q": "%%"})
    assert wildcard.status_code == 200
    assert wildcard.json()["data"] == []  # LIKE wildcards are literal
    _problem(
        app.client.get("/v1/users/search", headers=_auth(me), params={"q": "z"}),
        422,
        "validation_failed",
    )


@pytest.mark.req("CONN-001", "SAFE-001")
def test_relationship_reports_requests_follows_and_blocks(app: LiveApp) -> None:  # noqa: F811
    me, me_id = _user(app)
    other, other_id = _user(app)
    url = f"/v1/users/{other_id}/relationship"
    fresh = app.client.get(url, headers=_auth(me))
    assert fresh.status_code == 200, fresh.text
    assert_matches_contract(fresh.json(), "Relationship")
    assert (fresh.json()["state"], fresh.json()["can_message"]) == ("none", False)

    sent = _send(app, me, other_id)
    assert sent.status_code == 201, sent.text
    mine = app.client.get(url, headers=_auth(me)).json()
    assert (mine["state"], mine["pending_request_id"]) == ("request_pending", sent.json()["id"])
    theirs = app.client.get(f"/v1/users/{me_id}/relationship", headers=_auth(other)).json()
    assert theirs["state"] == "request_received"

    assert app.client.put(f"/v1/users/{other_id}/follow", headers=_auth(me)).status_code in (
        200,
        201,
    )
    followed = app.client.get(url, headers=_auth(me)).json()
    assert (followed["is_following"], followed["is_followed_by"]) == (True, False)
    reverse = app.client.get(f"/v1/users/{me_id}/relationship", headers=_auth(other)).json()
    assert (reverse["is_following"], reverse["is_followed_by"]) == (False, True)

    assert app.client.put(f"/v1/users/{other_id}/block", headers=_auth(me)).status_code in (
        200,
        204,
    )
    blocked = app.client.get(url, headers=_auth(me)).json()
    assert (blocked["state"], blocked["can_request_connection"]) == ("blocked", False)
    # The blocked person sees no profile at all, not that they were blocked.
    _problem(
        app.client.get(f"/v1/users/{me_id}/relationship", headers=_auth(other)), 404, "not_found"
    )


@pytest.mark.req("DEST-004", "ADM-007", "ADM-008")
def test_staff_feature_and_hide_destinations_with_an_audit(app: LiveApp) -> None:  # noqa: F811
    staff, _ = _staff(app, "admin")
    member, _ = _user(app)
    destination = _destination(app, "brazil/rio-de-janeiro/copacabana")
    url = f"/v1/admin/destinations/{destination}"
    try:
        featured = app.client.patch(url, headers=_admin(staff), json={"is_featured": True})
        assert featured.status_code == 200, featured.text
        assert_matches_contract(featured.json(), "Destination")
        listed = app.client.get("/v1/destinations/featured").json()["data"]
        assert destination in [d["id"] for d in listed]
        hidden = app.client.patch(url, headers=_admin(staff), json={"status": "hidden"})
        assert hidden.status_code == 200, hidden.text
        _problem(app.client.get(f"/v1/destinations/{destination}"), 404, "not_found")
        _problem(app.client.patch(url, headers=_admin(staff), json={}), 422, "validation_failed")
        _problem(
            app.client.patch(url, headers=_auth(member), json={"is_featured": False}),
            403,
            "forbidden",
        )
        audits = db_scalar(
            app.db_url,
            "SELECT count(*) FROM audit_logs WHERE action = 'destination.updated' "
            "AND resource_id = :d",
            d=destination,
        )
        assert audits == 2
    finally:  # the seeded catalog is shared by other tests
        db_scalar(
            app.db_url,
            "UPDATE destinations SET is_featured = false, status = 'active' WHERE id = :d "
            "RETURNING 1",
            d=uuid.UUID(destination),
        )


@pytest.mark.req("ADM-002", "SAFE-007")
def test_superadmins_query_audit_logs_and_each_query_is_audited(app: LiveApp) -> None:  # noqa: F811
    root, root_id = _staff(app, "superadmin")
    moderator, _ = _staff(app, "moderator")
    url = "/v1/admin/audit-logs"
    _problem(app.client.get(url, headers=_admin(moderator)), 403, "forbidden")
    _problem(app.client.get(url, headers=_admin(root, None)), 400, "justification_required")
    for _ in range(2):  # two audited queries
        assert (
            app.client.get(url, headers=_admin(root), params={"actor_id": root_id}).status_code
            == 200
        )
    page = app.client.get(url, headers=_admin(root), params={"actor_id": root_id, "limit": 1})
    assert page.status_code == 200, page.text
    assert_matches_contract(page.json(), "AuditLogPage")
    [latest] = page.json()["data"]
    assert (latest["action"], latest["actor_id"]) == ("audit_logs.viewed", root_id)
    assert latest["metadata"]["filters"]["actor_id"] == root_id
    assert page.json()["page"]["next_cursor"]
    [older] = app.client.get(
        url,
        headers=_admin(root),
        params={"actor_id": root_id, "limit": 1, "cursor": page.json()["page"]["next_cursor"]},
    ).json()["data"]
    assert older["occurred_at"] < latest["occurred_at"]
