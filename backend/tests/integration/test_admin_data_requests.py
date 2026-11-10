"""Staff handling of data subject requests (BL-6.03; SAFE-010, AUTH-011, ADM-007)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _record(live: LiveApp, token: str, user_id: str, body: dict[str, Any]) -> Any:
    return live.client.post(
        f"/v1/admin/users/{user_id}/data-requests", headers=_admin(token), json=body
    )


def _queue(live: LiveApp, token: str, **params: str) -> dict[str, Any]:
    response = live.client.get("/v1/admin/data-requests", headers=_admin(token), params=params)
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "AdminDataRequestPage")
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.req("SAFE-010", "ADM-007", "ADM-008")
def test_rectification_by_email_is_recorded_worked_and_closed(app: LiveApp) -> None:  # noqa: F811
    admin, admin_id = _staff(app, "admin")
    moderator, _ = _staff(app, "moderator")
    member, member_id = _user(app)
    body = {
        "kind": "rectification",
        "channel": "email",
        "details": "My home city on the profile is wrong; it should be Porto.",
    }
    _problem(_record(app, moderator, member_id, body), 403, "forbidden")  # admins only
    _problem(
        app.client.post(
            f"/v1/admin/users/{member_id}/data-requests", headers=_admin(admin, None), json=body
        ),
        400,
        "justification_required",
    )
    _problem(
        _record(app, admin, member_id, {"kind": "rectification", "channel": "email"}),
        422,
        "validation_failed",
    )
    _problem(_record(app, admin, member_id, {**body, "kind": "deletion"}), 422, "validation_failed")
    _problem(_record(app, admin, str(uuid.uuid4()), body), 404, "not_found")

    recorded = _record(app, admin, member_id, body)
    assert recorded.status_code == 201, recorded.text
    assert_matches_contract(recorded.json(), "AdminDataRequest")
    request = recorded.json()
    assert (request["kind"], request["status"], request["channel"]) == (
        "rectification",
        "received",
        "email",
    )
    assert request["overdue"] is False
    assert request["handled_by"] is None

    # The user sees it in the app too (transparency), without staff fields.
    mine = app.client.get("/v1/users/me/data-requests", headers=_auth(member)).json()["data"]
    assert [(r["id"], r["status"]) for r in mine] == [(request["id"], "received")]
    assert "handled_by" not in mine[0]

    open_ids = [r["id"] for r in _queue(app, admin, user_id=member_id)["data"]]
    assert open_ids == [request["id"]]

    resolve = f"/v1/admin/data-requests/{request['id']}/resolve"
    outcome = {"status": "completed", "resolution": "Home city corrected to Porto."}
    _problem(app.client.post(resolve, headers=_admin(moderator), json=outcome), 403, "forbidden")
    resolved = app.client.post(resolve, headers=_admin(admin), json=outcome)
    assert resolved.status_code == 200, resolved.text
    assert_matches_contract(resolved.json(), "AdminDataRequest")
    assert resolved.json()["status"] == "completed"
    assert resolved.json()["handled_by"] == admin_id
    assert resolved.json()["resolution"] == outcome["resolution"]
    assert resolved.json()["completed_at"] is not None
    _problem(app.client.post(resolve, headers=_admin(admin), json=outcome), 409, "conflict")

    assert _queue(app, admin, user_id=member_id)["data"] == []
    closed = _queue(app, admin, user_id=member_id, state="closed")["data"]
    assert [r["id"] for r in closed] == [request["id"]]
    actions = db_scalar(
        app.db_url,
        "SELECT string_agg(action, ',' ORDER BY occurred_at) FROM audit_logs "
        "WHERE resource_id = :r",
        r=request["id"],
    )
    assert actions == "data_request.recorded,data_request.resolved"
    viewed = db_scalar(
        app.db_url,
        "SELECT count(*) FROM audit_logs WHERE action = 'data_requests.viewed' AND actor_id = :a",
        a=uuid.UUID(admin_id),
    )
    assert isinstance(viewed, int)
    assert viewed >= 3  # every queue read is audited


@pytest.mark.req("AUTH-011", "SAFE-010")
def test_export_on_behalf_runs_the_in_app_export_once(app: LiveApp) -> None:  # noqa: F811
    admin, _ = _staff(app, "admin")
    member, member_id = _user(app)
    body = {"kind": "export", "channel": "email"}
    recorded = _record(app, admin, member_id, body)
    assert recorded.status_code == 201, recorded.text
    _problem(_record(app, admin, member_id, body), 409, "conflict")  # one export at a time
    _problem(
        app.client.post(
            "/v1/users/me/data-exports",
            headers={**_auth(member), "Idempotency-Key": str(uuid.uuid4())},
        ),
        409,
        "conflict",
    )
    _problem(
        app.client.post(
            f"/v1/admin/data-requests/{recorded.json()['id']}/resolve",
            headers=_admin(admin),
            json={"status": "rejected", "resolution": "Not needed."},
        ),
        409,
        "conflict",  # exports complete by themselves
    )

    _tick(app)  # builds the archive
    _tick(app)
    _tick(app)
    [export] = app.client.get("/v1/users/me/data-requests", headers=_auth(member)).json()["data"]
    assert export["status"] == "completed"
    assert export["download"] is not None  # the link reaches the user in the app


@pytest.mark.req("SAFE-010")
def test_queue_is_oldest_first_and_flags_overdue_requests(app: LiveApp) -> None:  # noqa: F811
    admin, _ = _staff(app, "admin")
    _, first_id = _user(app)
    _, second_id = _user(app)
    body = {"kind": "rectification", "channel": "other", "details": "Wrong birth year."}
    older = _record(app, admin, first_id, body).json()
    newer = _record(app, admin, second_id, body).json()
    for request, days in ((older, 31), (newer, 2)):
        db_scalar(
            app.db_url,
            "UPDATE data_subject_requests SET requested_at = now() - make_interval(days => :d) "
            "WHERE id = :i RETURNING 1",
            d=days,
            i=uuid.UUID(request["id"]),
        )
    ours = {older["id"], newer["id"]}
    page = _queue(app, admin, kind="rectification", limit="100")
    mine = [r for r in page["data"] if r["id"] in ours]
    assert [r["id"] for r in mine] == [older["id"], newer["id"]]
    assert [r["overdue"] for r in mine] == [True, False]
    assert mine[0]["due_at"] < app.clock.now().isoformat()

    # Paging keeps the query: a cursor cannot be replayed with other filters.
    first = _queue(app, admin, kind="rectification", limit="1")
    cursor = first["page"]["next_cursor"]
    assert cursor is not None
    second = _queue(app, admin, kind="rectification", limit="1", cursor=cursor)
    assert second["data"][0]["id"] != first["data"][0]["id"]
    _problem(
        app.client.get(
            "/v1/admin/data-requests",
            headers=_admin(admin),
            params={"kind": "export", "cursor": cursor},
        ),
        400,
        "invalid_cursor",
    )
