"""Account deletion with a 30-day reversible grace period, then the erasure saga (BL-1.17,
AUTH-010)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth, _id_token, _register
from tests.integration.test_posts import _create, _problem, _tick, _user, app  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.req("AUTH-010")]


class Account:
    def __init__(self, live: LiveApp) -> None:
        self.live = live
        self.sub = f"user-{uuid.uuid4()}"
        self.email = f"{uuid.uuid4().hex[:10]}@example.com"
        body = _register(live, _id_token(live, sub=self.sub, email=self.email)).json()
        self.id = str(body["user"]["account"]["id"])
        self.token = str(body["tokens"]["access_token"])

    def login(self) -> Any:
        return self.live.client.post(
            "/v1/auth/login",
            json={
                "id_token": _id_token(self.live, sub=self.sub, email=self.email),
                "client": "web",
            },
        )

    def request_deletion(self, key: str | None = None, **body: Any) -> Any:
        return self.live.client.post(
            "/v1/users/me/deletion",
            headers={**_auth(self.token), "Idempotency-Key": key or str(uuid.uuid4())},
            json={"confirm": True, **body},
        )

    def me(self) -> dict[str, Any]:
        response = self.live.client.get("/v1/users/me", headers=_auth(self.token))
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


def _sql(live: LiveApp, statement: str, **params: object) -> object:
    return db_scalar(live.db_url, statement, **params)


def test_requesting_deletion_schedules_it_and_signs_out_other_devices(app: LiveApp) -> None:  # noqa: F811
    account = Account(app)
    other_device = account.login().json()["tokens"]["access_token"]
    key = str(uuid.uuid4())
    response = account.request_deletion(key, reason="Taking a break")
    assert response.status_code == 202, response.text
    body = response.json()
    assert_matches_contract(body, "DataSubjectRequest")
    assert (body["kind"], body["status"], body["completed_at"]) == ("deletion", "received", None)
    scheduled = datetime.fromisoformat(body["scheduled_for"])
    requested = datetime.fromisoformat(body["requested_at"])
    assert scheduled - requested == timedelta(days=30)

    replay = account.request_deletion(key, reason="Taking a break")
    assert replay.status_code == 202
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json()["id"] == body["id"]
    _problem(account.request_deletion(), 409, "conflict")

    me = account.me()
    assert me["account"]["status"] == "pending_deletion"
    assert me["account"]["deletion_scheduled_for"] is not None
    assert (
        _sql(
            app,
            "SELECT count(*) FROM user_sessions WHERE user_id = :u AND revoked_at IS NULL",
            u=uuid.UUID(account.id),
        )
        == 1
    )
    assert other_device  # its session is revoked; access tokens lapse within their TTL


def test_cancelling_restores_the_account(app: LiveApp) -> None:  # noqa: F811
    account = Account(app)
    request_id = account.request_deletion().json()["id"]
    cancelled = app.client.delete("/v1/users/me/deletion", headers=_auth(account.token))
    assert cancelled.status_code == 204
    assert account.me()["account"]["status"] == "active"
    assert account.me()["account"]["deletion_scheduled_for"] is None
    status = _sql(
        app, "SELECT status FROM data_subject_requests WHERE id = :i", i=uuid.UUID(request_id)
    )
    assert status == "cancelled"
    _problem(
        app.client.delete("/v1/users/me/deletion", headers=_auth(account.token)), 404, "not_found"
    )


def test_signing_in_during_the_grace_period_cancels_deletion(app: LiveApp) -> None:  # noqa: F811
    account = Account(app)
    account.request_deletion()
    login = account.login()
    assert login.status_code == 200
    assert login.json()["user"]["account"]["status"] == "active"


@pytest.mark.parametrize("body", [{"confirm": False}, {}, {"confirm": True, "extra": 1}])
def test_deletion_requires_explicit_confirmation(app: LiveApp, body: dict[str, Any]) -> None:  # noqa: F811
    account = Account(app)
    response = app.client.post(
        "/v1/users/me/deletion",
        headers={**_auth(account.token), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )
    _problem(response, 422, "validation_failed")


@pytest.mark.security
def test_after_the_grace_period_the_saga_erases_the_account(app: LiveApp) -> None:  # noqa: F811
    account = Account(app)
    friend, friend_id = _user(app)
    post = _create(app, account.token).json()
    app.client.put(f"/v1/users/{friend_id}/follow", headers=_auth(account.token))
    app.client.post(
        f"/v1/posts/{post['id']}/reactions", headers=_auth(friend), json={"reaction": "like"}
    )
    request_id = account.request_deletion().json()["id"]
    _tick(app)
    _sql(
        app,
        "UPDATE users SET deletion_requested_at = now() - interval '31 days' "
        "WHERE id = :u RETURNING 1",
        u=uuid.UUID(account.id),
    )
    _sql(app, "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' RETURNING 1")
    _tick(app)  # enqueues the hourly deletion task
    _tick(app)  # and runs what is left (IdP deletion, cache purge)

    user = uuid.UUID(account.id)
    for table, column in (
        ("users", "id"),
        ("user_profiles", "user_id"),
        ("authentication_identities", "user_id"),
        ("user_sessions", "user_id"),
        ("posts", "author_id"),
        ("follows", "follower_id"),
        ("notifications", "user_id"),
    ):
        count = _sql(app, f"SELECT count(*) FROM {table} WHERE {column} = :u", u=user)  # noqa: S608
        assert count == 0, table
    record = _sql(
        app,
        "SELECT status || ':' || (completed_at IS NOT NULL) FROM data_subject_requests "
        "WHERE id = :i",
        i=uuid.UUID(request_id),
    )
    assert record == "completed:true"
    assert (
        _sql(
            app,
            "SELECT count(*) FROM outbox_events "
            "WHERE event_type = 'user.deleted' AND aggregate_id = :u",
            u=user,
        )
        == 1
    )
    assert (
        _sql(
            app,
            "SELECT status FROM asynchronous_jobs WHERE kind = 'identity.delete_idp_account' "
            "AND payload->>'subject' = :s",
            s=account.sub,
        )
        == "succeeded"
    )
    # The same person can start over with a new account.
    again = _register(app, _id_token(app, sub=account.sub, email=account.email))
    assert again.status_code == 201, again.text
    assert again.json()["user"]["account"]["id"] != account.id
