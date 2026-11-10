"""Identity flows end-to-end against PostgreSQL: register, login, refresh rotation, sessions, me.

Every successful response is validated against the normative OpenAPI contract.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar

pytestmark = pytest.mark.integration

TERMS = "2026-11-01"


def _id_token(
    live: LiveApp, *, sub: str | None = None, name: str | None = "Ana Souza", **kw: Any
) -> str:
    body = {
        "sub": sub or f"user-{uuid.uuid4()}",
        "email": kw.pop("email", f"{uuid.uuid4().hex[:10]}@example.com"),
    }
    if name:
        body["name"] = name
    body.update(kw)
    response = live.client.post("/v1/dev/idp/token", json=body)
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "DevIdpToken")
    return str(response.json()["id_token"])


def _register(live: LiveApp, id_token: str, **overrides: Any) -> Any:
    body = {
        "id_token": id_token,
        "client": "ios",
        "birth_date": "1995-05-17",
        "accepted_terms_version": TERMS,
        "accepted_privacy_version": TERMS,
        "locale": "pt-BR",
        "device": {
            "device_id": "install-abc-123",
            "device_name": "Ana's iPhone",
            "app_version": "0.1.0",
        },
    }
    body.update(overrides)
    return live.client.post(
        "/v1/auth/register", json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────── register ───────────────────────────────────


@pytest.mark.req("AUTH-001", "AUTH-009", "PROF-001", "PROF-002", "DISC-001", "PROF-008")
def test_register_creates_account_profile_consents_and_session(live_app: LiveApp) -> None:
    response = _register(live_app, _id_token(live_app, email="ana.souza1987@example.com"))

    assert response.status_code == 201, response.text
    body = response.json()
    assert_matches_contract(body, "AuthResult")
    assert body["is_new_user"] is True
    user = body["user"]
    # Privacy by default.
    assert user["privacy"]["discovery_enabled"] is False
    assert user["privacy"]["search_engine_indexing"] is False
    assert user["privacy"]["show_trips_on_profile"] is False
    # Public identifiers never leak the email local part (PROF-005).
    assert "1987" not in user["profile"]["handle"]
    assert user["profile"]["handle"].startswith("ana.souza")
    assert user["profile"]["display_name"] == "Ana Souza"
    assert user["preferences"]["ui_locale"] == "pt-BR"
    assert user["entitlements"]["plan"] == "free"
    assert user["onboarding_completed"] is False

    user_id = user["account"]["id"]
    consents = db_scalar(
        live_app.db_url,
        "SELECT count(*) FROM consent_records WHERE user_id = :u",
        u=uuid.UUID(user_id),
    )
    assert consents == 2


@pytest.mark.req("AUTH-008")
def test_only_birth_year_is_stored(live_app: LiveApp) -> None:
    response = _register(live_app, _id_token(live_app))
    user_id = uuid.UUID(response.json()["user"]["account"]["id"])
    assert (
        db_scalar(live_app.db_url, "SELECT birth_year FROM users WHERE id = :u", u=user_id) == 1995
    )
    columns = db_scalar(
        live_app.db_url,
        "SELECT string_agg(column_name, ',') FROM information_schema.columns "
        "WHERE table_name = 'users'",
    )
    assert "birth_date" not in str(columns)


@pytest.mark.req("AUTH-008")
def test_under_age_registration_is_rejected_and_nothing_is_stored(live_app: LiveApp) -> None:
    today = live_app.clock.now().date()
    seventeen = today.replace(year=today.year - 17).isoformat()
    response = _register(live_app, _id_token(live_app), birth_date=seventeen)

    assert response.status_code == 403
    assert response.json()["code"] == "age_restricted"
    assert db_scalar(live_app.db_url, "SELECT count(*) FROM users") == 0


@pytest.mark.req("AUTH-009")
def test_outdated_consent_versions_are_rejected(live_app: LiveApp) -> None:
    response = _register(live_app, _id_token(live_app), accepted_terms_version="2020-01-01")
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "consent_required"
    assert body["terms_version"] == TERMS


def test_registering_twice_conflicts(live_app: LiveApp) -> None:
    sub = f"user-{uuid.uuid4()}"
    assert _register(live_app, _id_token(live_app, sub=sub)).status_code == 201
    again = _register(live_app, _id_token(live_app, sub=sub))
    assert again.status_code == 409
    assert again.json()["code"] == "conflict"


def test_register_requires_idempotency_key(live_app: LiveApp) -> None:
    response = live_app.client.post("/v1/auth/register", json={"id_token": "x" * 30})
    assert response.status_code == 422


@pytest.mark.security
@pytest.mark.req("AUTH-001")
def test_forged_identity_token_is_rejected(live_app: LiveApp) -> None:
    token = _id_token(live_app)
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload}.{'A' * len(signature)}"
    response = _register(live_app, forged)
    assert response.status_code == 401
    assert response.json()["code"] == "token_invalid"


# ───────────────────────────────────── login ─────────────────────────────────────


def test_login_unknown_identity_is_not_found(live_app: LiveApp) -> None:
    response = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app), "client": "web"}
    )
    assert response.status_code == 404


@pytest.mark.req("AUTH-006")
def test_login_opens_another_session(live_app: LiveApp) -> None:
    sub = f"user-{uuid.uuid4()}"
    _register(live_app, _id_token(live_app, sub=sub))
    response = live_app.client.post(
        "/v1/auth/login",
        json={"id_token": _id_token(live_app, sub=sub), "client": "web"},
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Chrome/130.0 Safari/537"
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_contract(body, "AuthResult")
    assert body["is_new_user"] is False

    sessions = live_app.client.get(
        "/v1/users/me/sessions", headers=_auth(body["tokens"]["access_token"])
    )
    assert sessions.status_code == 200
    assert_matches_contract(sessions.json(), "SessionList")
    data = sessions.json()["data"]
    assert len(data) == 2
    current = [s for s in data if s["is_current"]]
    assert len(current) == 1
    assert current[0]["platform"] == "web"
    assert current[0]["device_name"] == "Chrome on macOS"


@pytest.mark.req("ADM-002")
def test_suspended_account_cannot_sign_in(live_app: LiveApp) -> None:
    sub = f"user-{uuid.uuid4()}"
    registered = _register(live_app, _id_token(live_app, sub=sub)).json()
    user_id = uuid.UUID(registered["user"]["account"]["id"])
    db_scalar(
        live_app.db_url,
        "UPDATE users SET status = 'suspended' WHERE id = :u RETURNING 1",
        u=user_id,
    )

    login = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app, sub=sub), "client": "ios"}
    )
    assert login.status_code == 403
    assert login.json()["code"] == "account_suspended"
    refresh = live_app.client.post(
        "/v1/auth/refresh", json={"refresh_token": registered["tokens"]["refresh_token"]}
    )
    assert refresh.status_code == 401
    assert refresh.json()["code"] == "session_revoked"


@pytest.mark.req("AUTH-010")
def test_login_during_deletion_grace_cancels_deletion(live_app: LiveApp) -> None:
    sub = f"user-{uuid.uuid4()}"
    user_id = uuid.UUID(
        _register(live_app, _id_token(live_app, sub=sub)).json()["user"]["account"]["id"]
    )
    db_scalar(
        live_app.db_url,
        "UPDATE users SET status = 'pending_deletion', deletion_requested_at = now() "
        "WHERE id = :u RETURNING 1",
        u=user_id,
    )
    login = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app, sub=sub), "client": "ios"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["account"]["status"] == "active"
    assert (
        db_scalar(live_app.db_url, "SELECT status FROM users WHERE id = :u", u=user_id) == "active"
    )


# ───────────────────────────────────── me ─────────────────────────────────────


def test_me_requires_authentication(live_app: LiveApp) -> None:
    response = live_app.client.get("/v1/users/me")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_me_returns_contract_shape(live_app: LiveApp) -> None:
    tokens = _register(live_app, _id_token(live_app)).json()["tokens"]
    response = live_app.client.get("/v1/users/me", headers=_auth(tokens["access_token"]))
    assert response.status_code == 200
    assert_matches_contract(response.json(), "Me")
    assert response.json()["roles"] == []
    assert response.json()["permissions"] == []


@pytest.mark.security
def test_tampered_access_token_is_rejected(live_app: LiveApp) -> None:
    access = _register(live_app, _id_token(live_app)).json()["tokens"]["access_token"]
    header, payload, signature = access.split(".")
    response = live_app.client.get(
        "/v1/users/me", headers=_auth(f"{header}.{payload}x.{signature}")
    )
    assert response.status_code == 401
    assert response.json()["code"] == "token_invalid"


def test_expired_access_token_is_rejected(live_app: LiveApp) -> None:
    access = _register(live_app, _id_token(live_app)).json()["tokens"]["access_token"]
    live_app.clock.set(live_app.clock.now() + timedelta(minutes=16))
    response = live_app.client.get("/v1/users/me", headers=_auth(access))
    assert response.status_code == 401
    assert response.json()["code"] == "token_expired"


# ─────────────────────────────── refresh rotation ───────────────────────────────


def _refresh(live: LiveApp, token: str) -> Any:
    return live.client.post("/v1/auth/refresh", json={"refresh_token": token})


@pytest.mark.req("AUTH-007")
def test_refresh_rotates_tokens(live_app: LiveApp) -> None:
    r0 = _register(live_app, _id_token(live_app)).json()["tokens"]["refresh_token"]
    response = _refresh(live_app, r0)
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "SessionTokens")
    r1 = response.json()["refresh_token"]
    assert r1 != r0
    me = live_app.client.get("/v1/users/me", headers=_auth(response.json()["access_token"]))
    assert me.status_code == 200


@pytest.mark.req("AUTH-007")
def test_previous_token_within_leeway_returns_same_successor(live_app: LiveApp) -> None:
    r0 = _register(live_app, _id_token(live_app)).json()["tokens"]["refresh_token"]
    r1 = _refresh(live_app, r0).json()["refresh_token"]
    live_app.clock.set(live_app.clock.now() + timedelta(seconds=20))
    replay = _refresh(live_app, r0)
    assert replay.status_code == 200
    assert replay.json()["refresh_token"] == r1  # identical successor, nothing revoked
    assert _refresh(live_app, r1).status_code == 200


@pytest.mark.security
@pytest.mark.req("AUTH-007")
def test_previous_token_after_leeway_revokes_the_family(live_app: LiveApp) -> None:
    r0 = _register(live_app, _id_token(live_app)).json()["tokens"]["refresh_token"]
    r1 = _refresh(live_app, r0).json()["refresh_token"]
    live_app.clock.set(live_app.clock.now() + timedelta(seconds=31))

    reuse = _refresh(live_app, r0)
    assert reuse.status_code == 401
    assert reuse.json()["code"] == "refresh_token_reused"
    after = _refresh(live_app, r1)  # the legitimate holder is signed out too
    assert after.status_code == 401
    assert after.json()["code"] == "session_revoked"


@pytest.mark.security
@pytest.mark.req("AUTH-007")
def test_older_ancestor_token_is_detected_as_reuse(live_app: LiveApp) -> None:
    r0 = _register(live_app, _id_token(live_app)).json()["tokens"]["refresh_token"]
    r1 = _refresh(live_app, r0).json()["refresh_token"]
    r2 = _refresh(live_app, r1).json()["refresh_token"]
    reuse = _refresh(live_app, r0)  # two generations back: never valid, even within the leeway
    assert reuse.status_code == 401
    assert reuse.json()["code"] == "refresh_token_reused"
    assert _refresh(live_app, r2).json()["code"] == "session_revoked"


def test_unknown_and_expired_refresh_tokens(live_app: LiveApp) -> None:
    assert _refresh(live_app, "x" * 43).json()["code"] == "token_invalid"
    r0 = _register(live_app, _id_token(live_app)).json()["tokens"]["refresh_token"]
    live_app.clock.set(live_app.clock.now() + timedelta(days=61))
    expired = _refresh(live_app, r0)
    assert expired.status_code == 401
    assert expired.json()["code"] == "token_expired"


# ─────────────────────────────── sessions & logout ───────────────────────────────


@pytest.mark.req("AUTH-006")
def test_revoke_another_session(live_app: LiveApp) -> None:
    sub = f"user-{uuid.uuid4()}"
    first = _register(live_app, _id_token(live_app, sub=sub)).json()["tokens"]
    second = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app, sub=sub), "client": "android"}
    ).json()["tokens"]

    revoke = live_app.client.delete(
        f"/v1/users/me/sessions/{first['session_id']}", headers=_auth(second["access_token"])
    )
    assert revoke.status_code == 204
    assert _refresh(live_app, first["refresh_token"]).json()["code"] == "session_revoked"
    assert _refresh(live_app, second["refresh_token"]).status_code == 200
    missing = live_app.client.delete(
        f"/v1/users/me/sessions/{uuid.uuid4()}", headers=_auth(second["access_token"])
    )
    assert missing.status_code == 404


@pytest.mark.req("AUTH-005")
@pytest.mark.security
def test_signing_in_from_a_recovery_link_ends_older_sessions(live_app: LiveApp) -> None:
    sub = f"user-{uuid.uuid4()}"
    phone = _register(live_app, _id_token(live_app, sub=sub)).json()["tokens"]
    laptop = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app, sub=sub), "client": "web"}
    ).json()["tokens"]
    stranger = _register(live_app, _id_token(live_app)).json()["tokens"]
    live_app.clock.set(live_app.clock.now() + timedelta(minutes=5))

    recovery = _id_token(live_app, sub=sub, recovered=True)
    # Someone signs in with the old password while the owner is still on the reset form.
    live_app.clock.set(live_app.clock.now() + timedelta(minutes=1))
    intruder = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app, sub=sub), "client": "android"}
    ).json()["tokens"]
    after = live_app.client.post("/v1/auth/login", json={"id_token": recovery, "client": "web"})
    assert after.status_code == 200, after.text
    fresh = after.json()["tokens"]
    for old in (phone, laptop, intruder):
        assert _refresh(live_app, old["refresh_token"]).json()["code"] == "session_revoked"
    reasons = db_scalar(
        live_app.db_url,
        "SELECT string_agg(DISTINCT revoked_reason, ',') FROM user_sessions "
        "WHERE id IN (:a, :b, :c)",
        a=uuid.UUID(phone["session_id"]),
        b=uuid.UUID(laptop["session_id"]),
        c=uuid.UUID(intruder["session_id"]),
    )
    assert reasons == "password_changed"
    assert (
        _refresh(live_app, stranger["refresh_token"]).status_code == 200
    )  # other users unaffected

    # A later sign-in with a token from the same recovery keeps the sessions opened since then.
    live_app.clock.set(live_app.clock.now() + timedelta(minutes=1))
    again = live_app.client.post("/v1/auth/login", json={"id_token": recovery, "client": "ios"})
    assert again.status_code == 200, again.text
    assert _refresh(live_app, fresh["refresh_token"]).status_code == 200


@pytest.mark.security
def test_cannot_revoke_someone_elses_session(live_app: LiveApp) -> None:
    alice = _register(live_app, _id_token(live_app)).json()["tokens"]
    bob = _register(live_app, _id_token(live_app)).json()["tokens"]
    response = live_app.client.delete(
        f"/v1/users/me/sessions/{alice['session_id']}", headers=_auth(bob["access_token"])
    )
    assert response.status_code == 404
    assert _refresh(live_app, alice["refresh_token"]).status_code == 200


def test_logout_current_and_all_sessions(live_app: LiveApp) -> None:
    sub = f"user-{uuid.uuid4()}"
    first = _register(live_app, _id_token(live_app, sub=sub)).json()["tokens"]
    second = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app, sub=sub), "client": "web"}
    ).json()["tokens"]

    assert (
        live_app.client.post("/v1/auth/logout", headers=_auth(first["access_token"])).status_code
        == 204
    )
    assert _refresh(live_app, first["refresh_token"]).json()["code"] == "session_revoked"
    assert _refresh(live_app, second["refresh_token"]).status_code == 200

    third = live_app.client.post(
        "/v1/auth/login", json={"id_token": _id_token(live_app, sub=sub), "client": "ios"}
    ).json()["tokens"]
    out = live_app.client.post(
        "/v1/auth/logout", json={"all_sessions": True}, headers=_auth(third["access_token"])
    )
    assert out.status_code == 204
    sessions = db_scalar(
        live_app.db_url,
        "SELECT count(*) FROM user_sessions s "
        "JOIN authentication_identities i ON i.user_id = s.user_id "
        "WHERE i.subject = :sub AND s.revoked_at IS NULL",
        sub=sub,
    )
    assert sessions == 0


def test_dev_idp_accepts_reserved_test_domains(live_app: LiveApp) -> None:
    token = _id_token(live_app, email="fixture@example.test")
    assert _register(live_app, token).status_code == 201
    bad = live_app.client.post("/v1/dev/idp/token", json={"sub": "x", "email": "not-an-email"})
    assert bad.status_code == 422


def test_dev_idp_jwks_matches_contract(live_app: LiveApp) -> None:
    response = live_app.client.get("/v1/dev/idp/jwks.json")
    assert response.status_code == 200
    assert_matches_contract(response.json(), "Jwks")
