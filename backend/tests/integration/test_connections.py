"""Connection requests and connections end to end (BL-2.04; CONN-001..009, SAFE-001)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _send(live: LiveApp, token: str, recipient: str, key: str | None = None, **body: Any) -> Any:
    return live.client.post(
        "/v1/connections/requests",
        headers={**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())},
        json={"recipient_id": recipient, "context": "profile", **body},
    )


def _inbox(
    live: LiveApp, token: str, direction: str = "incoming", **params: str
) -> list[dict[str, Any]]:
    response = live.client.get(
        "/v1/connections/requests", headers=_auth(token), params={"direction": direction, **params}
    )
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "ConnectionRequestPage")
    data: list[dict[str, Any]] = response.json()["data"]
    return data


def _connections(live: LiveApp, token: str) -> list[str]:
    response = live.client.get("/v1/connections", headers=_auth(token))
    assert response.status_code == 200
    assert_matches_contract(response.json(), "ConnectionPage")
    return [c["user"]["id"] for c in response.json()["data"]]


def _relationship(live: LiveApp, token: str, user_id: str) -> tuple[str, bool]:
    body = live.client.get(f"/v1/users/{user_id}", headers=_auth(token)).json()
    return body["relationship"], body["can_request_connection"]


@pytest.mark.req("CONN-001", "CONN-002", "CONN-003", "CONN-008")
def test_request_inbox_accept_and_remove(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id = _user(app)
    bo, bo_id = _user(app)
    assert _relationship(app, ana, bo_id) == ("none", True)
    key = str(uuid.uuid4())
    sent = _send(app, ana, bo_id, key, note="Met at the Lisbon walking tour!")
    assert sent.status_code == 201, sent.text
    assert_matches_contract(sent.json(), "ConnectionRequest")
    assert sent.json()["status"] == "pending"
    replay = _send(app, ana, bo_id, key, note="Met at the Lisbon walking tour!")
    assert replay.headers.get("Idempotent-Replayed") == "true"

    assert _relationship(app, ana, bo_id) == ("request_pending", False)
    assert _relationship(app, bo, ana_id) == ("request_received", False)
    assert _connections(app, ana) == []  # a request never connects anyone by itself
    [incoming] = _inbox(app, bo)
    assert incoming["requester"]["id"] == ana_id
    assert incoming["note"] == "Met at the Lisbon walking tour!"
    assert [r["id"] for r in _inbox(app, ana, "outgoing")] == [incoming["id"]]

    _tick(app)
    notice = app.client.get(
        "/v1/notifications", headers={**_auth(bo), "Accept-Language": "en"}
    ).json()
    assert [n["type"] for n in notice["data"]] == ["connection_request"]

    _problem(
        app.client.post(f"/v1/connections/requests/{incoming['id']}/accept", headers=_auth(ana)),
        404,
        "not_found",
    )  # only the recipient accepts
    accepted = app.client.post(
        f"/v1/connections/requests/{incoming['id']}/accept", headers=_auth(bo)
    )
    assert accepted.status_code == 200, accepted.text
    assert_matches_contract(accepted.json(), "Connection")
    assert accepted.json()["user"]["id"] == ana_id
    assert _connections(app, ana) == [bo_id]
    assert _connections(app, bo) == [ana_id]
    assert _relationship(app, ana, bo_id) == ("connected", False)
    _problem(_send(app, ana, bo_id), 409, "already_connected")
    _problem(
        app.client.post(f"/v1/connections/requests/{incoming['id']}/decline", headers=_auth(bo)),
        409,
        "conflict",
    )
    _tick(app)
    ana_notices = app.client.get("/v1/notifications", headers=_auth(ana)).json()["data"]
    assert [n["type"] for n in ana_notices] == ["connection_accepted"]

    assert app.client.delete(f"/v1/connections/{bo_id}", headers=_auth(ana)).status_code == 204
    assert app.client.delete(f"/v1/connections/{bo_id}", headers=_auth(ana)).status_code == 204
    assert _connections(app, bo) == []
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM notifications WHERE user_id = :u AND type LIKE 'connection%'",
            u=uuid.UUID(bo_id),
        )
        == 1
    )  # removal is silent


@pytest.mark.req("CONN-003", "CONN-006")
def test_decline_cooldown_cancel_and_crossed_requests(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id = _user(app)
    bo, bo_id = _user(app)
    request_id = _send(app, ana, bo_id).json()["id"]
    _problem(_send(app, ana, bo_id), 409, "conflict")  # one pending request per pair
    _problem(_send(app, bo, ana_id), 409, "conflict")  # they should accept instead
    assert (
        app.client.post(
            f"/v1/connections/requests/{request_id}/decline", headers=_auth(bo)
        ).status_code
        == 204
    )
    assert _relationship(app, ana, bo_id) == ("declined", False)
    _problem(_send(app, ana, bo_id), 409, "connection_request_cooldown")
    assert _inbox(app, ana, "outgoing", status="declined")[0]["status"] == "declined"

    db_scalar(
        app.db_url,
        "UPDATE connection_requests SET responded_at = now() - interval '31 days' "
        "WHERE id = :i RETURNING 1",
        i=uuid.UUID(request_id),
    )
    again = _send(app, ana, bo_id)
    assert again.status_code == 201
    cancel = app.client.post(
        f"/v1/connections/requests/{again.json()['id']}/cancel", headers=_auth(ana)
    )
    assert cancel.status_code == 204
    assert _inbox(app, bo) == []


@pytest.mark.req("CONN-004")
@pytest.mark.security
def test_recipient_policy_and_blocks_get_the_same_generic_refusal(app: LiveApp) -> None:  # noqa: F811
    ana, _ = _user(app)
    picky, picky_id = _user(app)
    app.client.patch(
        "/v1/users/me/privacy", headers=_auth(picky), json={"connection_requests_from": "nobody"}
    )
    nobody = _problem(_send(app, ana, picky_id), 403, "connection_request_not_allowed")
    assert _relationship(app, ana, picky_id) == ("none", False)

    shy, shy_id = _user(app)
    app.client.patch(
        "/v1/users/me/privacy",
        headers=_auth(shy),
        json={"connection_requests_from": "shared_context"},
    )
    _problem(_send(app, ana, shy_id), 403, "connection_request_not_allowed")
    lisbon = app.client.get("/v1/destinations/lookup", params={"path": "portugal/lisbon"}).json()[
        "id"
    ]
    # Private signals never count: browsing the same city or a trip shared with nobody. They
    # would otherwise leak through `can_request_connection` on the profile (T-LOC-03/08).
    private_trips: list[tuple[str, str]] = []
    for token in (ana, shy):
        app.client.put(
            "/v1/users/me/browse-destination", headers=_auth(token), json={"destination_id": lisbon}
        )
        trip = app.client.post(
            "/v1/users/me/upcoming-destinations",
            headers=_auth(token),
            json={"destination_id": lisbon},
        )
        assert trip.status_code == 201, trip.text
        private_trips.append((token, trip.json()["id"]))
    _problem(_send(app, ana, shy_id), 403, "connection_request_not_allowed")
    assert _relationship(app, ana, shy_id) == ("none", False)
    for token, trip_id in private_trips:
        removed = app.client.delete(
            f"/v1/users/me/upcoming-destinations/{trip_id}", headers=_auth(token)
        )
        assert removed.status_code == 204, removed.text
    # Both sharing a trip to Lisbon for discovery (which needs their consent) is a shared context.
    for token in (ana, shy):
        consent = app.client.post(
            "/v1/users/me/consents",
            headers=_auth(token),
            json={
                "consent_type": "traveler_discovery",
                "version": "2026-11-01",
                "granted": True,
                "source": "prompt",
            },
        )
        assert consent.status_code == 201, consent.text
        shared = app.client.post(
            "/v1/users/me/upcoming-destinations",
            headers=_auth(token),
            json={"destination_id": lisbon, "share_for_discovery": True},
        )
        assert shared.status_code in (200, 201), shared.text
    assert _relationship(app, ana, shy_id) == ("none", True)
    assert _send(app, ana, shy_id).status_code == 201

    _, blocker_id = _user(app)
    app.client.put(f"/v1/users/{blocker_id}/block", headers=_auth(ana))
    blocked = _problem(_send(app, ana, blocker_id), 403, "connection_request_not_allowed")
    assert blocked["detail"] == nobody["detail"]  # nothing reveals which rule applied
    _problem(_send(app, ana, str(uuid.uuid4())), 404, "not_found")


@pytest.mark.req("CONN-009", "SAFE-001")
@pytest.mark.security
def test_blocking_ends_connections_and_pending_requests(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id = _user(app)
    bo, bo_id = _user(app)
    cy, _ = _user(app)
    accepted = _send(app, ana, bo_id).json()["id"]
    app.client.post(f"/v1/connections/requests/{accepted}/accept", headers=_auth(bo))
    pending = _send(app, cy, ana_id).json()["id"]
    assert app.client.put(f"/v1/users/{bo_id}/block", headers=_auth(ana)).status_code == 204
    assert app.client.put(f"/v1/users/{ana_id}/block", headers=_auth(cy)).status_code == 204
    assert _connections(app, ana) == []
    assert _connections(app, bo) == []
    status = db_scalar(
        app.db_url, "SELECT status FROM connection_requests WHERE id = :i", i=uuid.UUID(pending)
    )
    assert status == "cancelled"
    assert _inbox(app, ana) == []


@pytest.mark.req("CONN-005")
@pytest.mark.security
def test_new_accounts_send_a_few_requests_a_day(app: LiveApp) -> None:  # noqa: F811
    sender, _ = _user(app)
    for _ in range(5):
        _, other = _user(app)
        assert _send(app, sender, other).status_code == 201
    _, sixth = _user(app)
    _problem(_send(app, sender, sixth), 429, "rate_limited")


@pytest.mark.req("CONN-007")
def test_requests_expire_after_thirty_days(app: LiveApp) -> None:  # noqa: F811
    ana, _ = _user(app)
    bo, bo_id = _user(app)
    request_id = _send(app, ana, bo_id).json()["id"]
    db_scalar(
        app.db_url,
        "UPDATE connection_requests SET expires_at = now() - interval '1 day' "
        "WHERE id = :i RETURNING 1",
        i=uuid.UUID(request_id),
    )
    assert _inbox(app, bo) == []
    _problem(
        app.client.post(f"/v1/connections/requests/{request_id}/accept", headers=_auth(bo)),
        409,
        "conflict",
    )
    status = db_scalar(
        app.db_url, "SELECT status FROM connection_requests WHERE id = :i", i=uuid.UUID(request_id)
    )
    assert status == "expired"
    assert _send(app, ana, bo_id).status_code == 201  # a fresh request is possible


def test_invalid_requests(app: LiveApp) -> None:  # noqa: F811
    me, me_id = _user(app)
    _problem(_send(app, me, me_id), 422, "validation_failed")
    _problem(_send(app, me, str(uuid.uuid4()), context="nowhere"), 422, "validation_failed")
    unverified, _ = _user(app, verified=False)
    _, other = _user(app)
    _problem(_send(app, unverified, other), 403, "email_unverified")
