"""Public profiles (`GET /v1/users/{id}`, `/v1/users/by-handle/{handle}`; PROF-008, BL-1.27)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _act, _staff
from tests.integration.test_posts import _create, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _profile(live: LiveApp, viewer: str, user_id: str) -> dict[str, Any]:
    response = live.client.get(f"/v1/users/{user_id}", headers=_auth(viewer))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_contract(body, "PublicProfile")
    return body


def _set(live: LiveApp, token: str, path: str, **body: Any) -> None:
    response = live.client.patch(path, headers=_auth(token), json=body)
    assert response.status_code == 200, response.text


@pytest.mark.req("PROF-005", "PROF-008", "PROF-003")
def test_public_profile_with_counts_and_indexing_consent(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id = _user(app)
    viewer, _ = _user(app)
    _set(app, owner, "/v1/users/me", bio="Slow traveller", interests=["food"])
    _create(app, owner)
    app.client.put(f"/v1/users/{owner_id}/follow", headers=_auth(viewer))

    seen = _profile(app, viewer, owner_id)
    assert (seen["bio"], seen["interests"], seen["is_restricted"]) == (
        "Slow traveller",
        ["food"],
        False,
    )
    assert seen["counts"] == {"posts": 1, "followers": 1, "following": 0}
    assert seen["follow_status"] == "following"
    assert seen["indexable"] is False  # indexing is opt-in
    _set(app, owner, "/v1/users/me/privacy", search_engine_indexing=True)
    assert _profile(app, viewer, owner_id)["indexable"] is True

    by_handle = app.client.get(
        f"/v1/users/by-handle/{seen['handle'].upper()}", headers=_auth(viewer)
    )
    assert by_handle.status_code == 200
    assert by_handle.json()["id"] == owner_id


@pytest.mark.req("PROF-004", "PROF-005")
def test_private_accounts_are_restricted_until_followed(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id = _user(app)
    viewer, viewer_id = _user(app)
    _set(app, owner, "/v1/users/me", bio="Secret plans", account_visibility="private")
    _set(app, owner, "/v1/users/me/privacy", search_engine_indexing=True)
    restricted = _profile(app, viewer, owner_id)
    assert restricted["is_restricted"] is True
    assert (restricted["bio"], restricted["counts"], restricted["indexable"]) == (None, None, False)
    app.client.put(f"/v1/users/{owner_id}/follow", headers=_auth(viewer))
    assert _profile(app, viewer, owner_id)["follow_status"] == "requested"
    approved = app.client.post(
        f"/v1/users/me/follow-requests/{viewer_id}/approve", headers=_auth(owner)
    )
    assert approved.status_code == 204
    unlocked = _profile(app, viewer, owner_id)
    assert (unlocked["is_restricted"], unlocked["bio"]) == (False, "Secret plans")
    assert unlocked["indexable"] is False  # private accounts are never indexed
    assert _profile(app, owner, owner_id)["is_restricted"] is False  # own view


@pytest.mark.req("SAFE-001")
@pytest.mark.security
def test_blocked_and_inactive_accounts_are_not_found(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id = _user(app)
    viewer, viewer_id = _user(app)
    app.client.put(f"/v1/users/{viewer_id}/block", headers=_auth(owner))
    _problem(app.client.get(f"/v1/users/{owner_id}", headers=_auth(viewer)), 404, "not_found")
    _problem(app.client.get(f"/v1/users/{viewer_id}", headers=_auth(owner)), 404, "not_found")
    other, _ = _user(app)
    moderator, _ = _staff(app)
    suspended = _act(
        app,
        moderator,
        target_type="user",
        target_id=owner_id,
        action="suspend",
        reason_code="spam",
    )
    assert suspended.status_code == 201, suspended.text
    _problem(app.client.get(f"/v1/users/{owner_id}", headers=_auth(other)), 404, "not_found")
    _problem(
        app.client.get("/v1/users/by-handle/nobody_here", headers=_auth(other)), 404, "not_found"
    )
