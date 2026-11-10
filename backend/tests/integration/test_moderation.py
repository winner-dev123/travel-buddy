"""Reports, moderation queue, enforcement and staff hardening (BL-1.14, BL-1.26; SAFE-002/003,
ADM-001/002/007/008/009, SAFE-007)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth, _id_token, _register
from tests.integration.test_posts import _create, _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

WHY = "Reviewing a reported post for the moderation queue"


def _staff(live: LiveApp, role: str = "moderator", *, mfa: bool = True) -> tuple[str, str]:
    """A user with a platform role, signed in again so the token carries the role and amr."""
    sub = f"staff-{uuid.uuid4()}"
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    registered = _register(live, _id_token(live, sub=sub, email=email))
    assert registered.status_code == 201, registered.text
    user_id = registered.json()["user"]["account"]["id"]
    db_scalar(
        live.db_url,
        "INSERT INTO admin_role_assignments (user_id, role) VALUES (:u, :r) RETURNING 1",
        u=uuid.UUID(user_id),
        r=role,
    )
    login = live.client.post(
        "/v1/auth/login",
        json={"id_token": _id_token(live, sub=sub, email=email, mfa=mfa), "client": "web"},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["tokens"]["access_token"]), user_id


def _admin(token: str, justification: str | None = WHY, **extra: str) -> dict[str, str]:
    headers = {**_auth(token), **extra}
    if justification is not None:
        headers["X-Audit-Justification"] = justification
    return headers


def _report(live: LiveApp, token: str, **body: Any) -> Any:
    return live.client.post("/v1/reports", headers=_auth(token), json=body)


# ─────────────────────────────── user reports ───────────────────────────────


@pytest.mark.req("SAFE-002")
def test_reports_capture_evidence_and_deduplicate(app: LiveApp) -> None:  # noqa: F811
    author, author_id = _user(app)
    reporter, _ = _user(app)
    post = _create(app, author, body="Buy followers cheap!!!").json()
    first = _report(app, reporter, target_type="post", target_id=post["id"], reason="spam")
    assert first.status_code == 202, first.text
    assert_matches_contract(first.json(), "ReportReceipt")
    again = _report(app, reporter, target_type="post", target_id=post["id"], reason="spam")
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    evidence = db_scalar(
        app.db_url,
        "SELECT evidence->>'body' FROM content_reports WHERE id = :i",
        i=uuid.UUID(first.json()["id"]),
    )
    assert evidence == "Buy followers cheap!!!"
    assert (
        db_scalar(
            app.db_url,
            "SELECT target_author_id::text FROM content_reports WHERE id = :i",
            i=uuid.UUID(first.json()["id"]),
        )
        == author_id
    )


@pytest.mark.req("SAFE-002", "SAFE-001")
def test_report_and_block_in_one_request(app: LiveApp) -> None:  # noqa: F811
    _, harasser_id = _user(app)
    target, _ = _user(app)
    response = _report(
        app, target, target_type="user", target_id=harasser_id, reason="harassment", also_block=True
    )
    assert response.status_code == 202
    blocked = app.client.get("/v1/users/me/blocks", headers=_auth(target)).json()
    assert [u["id"] for u in blocked["data"]] == [harasser_id]


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (
            {"target_type": "post", "target_id": str(uuid.uuid4()), "reason": "spam"},
            404,
            "not_found",
        ),
        (
            {"target_type": "challenge", "target_id": str(uuid.uuid4()), "reason": "spam"},
            422,
            "validation_failed",
        ),
        (
            {"target_type": "post", "target_id": str(uuid.uuid4()), "reason": "rude"},
            422,
            "validation_failed",
        ),
    ],
)
def test_invalid_reports(app: LiveApp, body: dict[str, Any], status: int, code: str) -> None:  # noqa: F811
    reporter, _ = _user(app)
    _problem(_report(app, reporter, **body), status, code)


@pytest.mark.security
def test_cannot_report_content_you_cannot_see(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    snoop, _ = _user(app)
    private = _create(app, author, visibility="private").json()
    _problem(
        _report(app, snoop, target_type="post", target_id=private["id"], reason="spam"),
        404,
        "not_found",
    )


# ─────────────────────────────── staff hardening ───────────────────────────────


@pytest.mark.req("ADM-007")
@pytest.mark.security
def test_admin_routes_require_role_and_mfa(app: LiveApp) -> None:  # noqa: F811
    regular, _ = _user(app)
    _problem(app.client.get("/v1/admin/reports", headers=_admin(regular)), 403, "forbidden")
    no_mfa, _ = _staff(app, mfa=False)
    _problem(app.client.get("/v1/admin/reports", headers=_admin(no_mfa)), 403, "mfa_required")
    moderator, _ = _staff(app)
    listing = app.client.get("/v1/admin/reports", headers=_admin(moderator))
    assert listing.status_code == 200, listing.text
    assert_matches_contract(listing.json(), "AdminReportPage")


@pytest.mark.req("ADM-009")
@pytest.mark.security
def test_sensitive_routes_require_a_justification(app: LiveApp) -> None:  # noqa: F811
    moderator, _ = _staff(app)
    _, author_id = _user(app)
    for headers in (_admin(moderator, None), _admin(moderator, "too short")):
        _problem(
            app.client.get(f"/v1/admin/users/{author_id}", headers=headers),
            400,
            "justification_required",
        )


@pytest.mark.req("ADM-008")
@pytest.mark.security
def test_idle_staff_sessions_must_reauthenticate(app: LiveApp) -> None:  # noqa: F811
    moderator, moderator_id = _staff(app)
    assert app.client.get("/v1/admin/reports", headers=_admin(moderator)).status_code == 200
    db_scalar(
        app.db_url,
        "UPDATE user_sessions SET last_admin_activity_at = now() - interval '31 minutes' "
        "WHERE user_id = :u RETURNING 1",
        u=uuid.UUID(moderator_id),
    )
    _problem(
        app.client.get("/v1/admin/reports", headers=_admin(moderator)),
        401,
        "reauthentication_required",
    )


# ─────────────────────────────── queue & enforcement ───────────────────────────────


@pytest.mark.req("SAFE-003", "ADM-002", "SAFE-007", "SAFE-012")
def test_queue_priority_and_resolution_with_removal(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    reporter, _ = _user(app)
    spam_post = _create(app, author, body="Spam spam spam").json()
    minor_post = _create(app, author, body="Something concerning").json()
    _report(app, reporter, target_type="post", target_id=spam_post["id"], reason="spam")
    urgent = _report(
        app, reporter, target_type="post", target_id=minor_post["id"], reason="minor_safety"
    ).json()

    moderator, moderator_id = _staff(app)
    queue = app.client.get("/v1/admin/reports", headers=_admin(moderator)).json()
    priorities = [r["priority"] for r in queue["data"]]
    assert priorities == sorted(priorities, reverse=True)
    assert queue["data"][0]["reason"] == "minor_safety"

    detail = app.client.get(f"/v1/admin/reports/{urgent['id']}", headers=_admin(moderator))
    assert detail.status_code == 200
    assert_matches_contract(detail.json(), "AdminReport")
    assigned = app.client.post(
        f"/v1/admin/reports/{urgent['id']}/assign",
        headers=_admin(moderator),
        json={"assignee_id": moderator_id},
    )
    assert assigned.json()["status"] == "in_review"
    resolved = app.client.post(
        f"/v1/admin/reports/{urgent['id']}/resolve",
        headers=_admin(moderator),
        json={
            "status": "actioned",
            "resolution_note": "Removed under the minor safety policy",
            "action": {
                "target_type": "post",
                "target_id": minor_post["id"],
                "action": "remove_content",
                "reason_code": "minor_safety",
            },
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "actioned"
    again = app.client.post(
        f"/v1/admin/reports/{urgent['id']}/resolve",
        headers=_admin(moderator),
        json={"status": "dismissed", "resolution_note": "Duplicate"},
    )
    _problem(again, 409, "conflict")

    # Removed content: gone for others, still visible to its author.
    viewer, _ = _user(app)
    _problem(
        app.client.get(f"/v1/posts/{minor_post['id']}", headers=_auth(viewer)), 404, "not_found"
    )
    own = app.client.get(f"/v1/posts/{minor_post['id']}", headers=_auth(author)).json()
    assert own["moderation_state"] == "removed"
    audits = db_scalar(
        app.db_url,
        "SELECT string_agg(action, ',' ORDER BY action) FROM audit_logs WHERE actor_id = :u",
        u=uuid.UUID(moderator_id),
    )
    # Resolution writes its rows in one transaction (same now()), so compare as a set.
    assert audits == "moderation.remove_content,report.actioned,report.assigned,report.viewed"
    justification = db_scalar(
        app.db_url,
        "SELECT metadata->>'justification' FROM audit_logs WHERE actor_id = :u LIMIT 1",
        u=uuid.UUID(moderator_id),
    )
    assert justification == WHY
    history = app.client.get(
        "/v1/admin/moderation-actions",
        headers=_admin(moderator),
        params={"target_type": "post", "target_id": minor_post["id"]},
    ).json()
    assert_matches_contract(history, "ModerationActionPage")
    assert [a["action"] for a in history["data"]] == ["remove_content"]


@pytest.mark.req("ADM-002")
def test_moderation_actions_are_idempotent_and_restore_works(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    post = _create(app, author).json()
    moderator, _ = _staff(app)
    key = str(uuid.uuid4())
    body = {
        "target_type": "post",
        "target_id": post["id"],
        "action": "limit_visibility",
        "reason_code": "borderline",
    }
    first = app.client.post(
        "/v1/admin/moderation-actions",
        headers=_admin(moderator, **{"Idempotency-Key": key}),
        json=body,
    )
    assert first.status_code == 201, first.text
    assert_matches_contract(first.json(), "ModerationAction")
    replay = app.client.post(
        "/v1/admin/moderation-actions",
        headers=_admin(moderator, **{"Idempotency-Key": key}),
        json=body,
    )
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json()["id"] == first.json()["id"]
    limited = db_scalar(
        app.db_url, "SELECT moderation_state FROM posts WHERE id = :p", p=uuid.UUID(post["id"])
    )
    assert limited == "limited"
    restore = {**body, "action": "restore_content", "reason_code": "appeal_upheld"}
    restored = app.client.post(
        "/v1/admin/moderation-actions",
        headers=_admin(moderator, **{"Idempotency-Key": str(uuid.uuid4())}),
        json=restore,
    )
    assert restored.status_code == 201
    assert (
        db_scalar(
            app.db_url, "SELECT moderation_state FROM posts WHERE id = :p", p=uuid.UUID(post["id"])
        )
        == "approved"
    )
    wrong = {**body, "target_type": "user", "target_id": post["id"], "action": "remove_content"}
    _problem(
        app.client.post(
            "/v1/admin/moderation-actions",
            headers=_admin(moderator, **{"Idempotency-Key": str(uuid.uuid4())}),
            json=wrong,
        ),
        422,
        "validation_failed",
    )


@pytest.mark.req("ADM-002", "ADM-003")
@pytest.mark.security
def test_suspension_revokes_sessions_and_reinstatement_restores_access(app: LiveApp) -> None:  # noqa: F811
    sub, email = f"offender-{uuid.uuid4()}", f"{uuid.uuid4().hex[:10]}@example.com"
    registered = _register(app, _id_token(app, sub=sub, email=email))
    offender_id = registered.json()["user"]["account"]["id"]

    def login() -> Any:
        return app.client.post(
            "/v1/auth/login",
            json={"id_token": _id_token(app, sub=sub, email=email), "client": "web"},
        )

    moderator, moderator_id = _staff(app)
    view = app.client.get(f"/v1/admin/users/{offender_id}", headers=_admin(moderator))
    assert view.status_code == 200
    assert_matches_contract(view.json(), "AdminUser")
    assert view.json()["status"] == "active"

    suspended = app.client.post(
        f"/v1/admin/users/{offender_id}/suspend",
        headers=_admin(moderator),
        json={"reason_code": "harassment", "notes": "Repeated harassment", "until": None},
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["moderation_action_count"] == 1
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM user_sessions WHERE user_id = :u AND revoked_at IS NULL",
            u=uuid.UUID(offender_id),
        )
        == 0
    )
    _problem(login(), 403, "account_suspended")
    _problem(
        app.client.post(
            f"/v1/admin/users/{moderator_id}/suspend",
            headers=_admin(moderator),
            json={"reason_code": "x", "notes": "self", "until": None},
        ),
        422,
        "validation_failed",
    )

    reinstated = app.client.post(
        f"/v1/admin/users/{offender_id}/reinstate",
        headers=_admin(moderator),
        json={"notes": "Appeal accepted"},
    )
    assert reinstated.json()["status"] == "active"
    assert login().status_code == 200


# ─────────────────────────────── restrictions (BL-1.28) ───────────────────────────────


def _act(live: LiveApp, staff_token: str, **body: Any) -> Any:
    return live.client.post(
        "/v1/admin/moderation-actions",
        headers=_admin(staff_token, **{"Idempotency-Key": str(uuid.uuid4())}),
        json=body,
    )


@pytest.mark.req("SAFE-013", "ADM-002")
def test_restrictions_are_shown_enforced_and_lifted(app: LiveApp) -> None:  # noqa: F811
    offender, offender_id = _user(app)
    moderator, _ = _staff(app)
    base = {"target_type": "user", "target_id": offender_id, "reason_code": "spam"}
    _problem(_act(app, moderator, **base, action="restrict"), 422, "validation_failed")
    _problem(
        _act(app, moderator, **base, action="warn", restriction_kind="posting_limited"),
        422,
        "validation_failed",
    )
    restricted = _act(app, moderator, **base, action="restrict", restriction_kind="posting_limited")
    assert restricted.status_code == 201, restricted.text
    assert_matches_contract(restricted.json(), "ModerationAction")
    assert restricted.json()["restriction_kind"] == "posting_limited"

    me = app.client.get("/v1/users/me", headers=_auth(offender)).json()
    assert_matches_contract(me, "Me")
    assert me["account"]["restrictions"] == [
        {"kind": "posting_limited", "reason_code": "spam", "until": None, "appealable": True}
    ]
    _problem(_create(app, offender), 403, "account_restricted")
    author, _ = _user(app)
    post = _create(app, author).json()
    comment = app.client.post(
        f"/v1/posts/{post['id']}/comments",
        headers={**_auth(offender), "Idempotency-Key": str(uuid.uuid4())},
        json={"body": "Commenting is still allowed"},
    )
    assert comment.status_code == 201, comment.text

    _tick(app)
    notices = app.client.get(
        "/v1/notifications", headers={**_auth(offender), "Accept-Language": "en"}
    ).json()["data"]
    assert [(n["type"], n["data"].get("restriction_kind")) for n in notices] == [
        ("moderation_notice", "posting_limited")
    ]

    lifted = _act(app, moderator, **base, action="reinstate")
    assert lifted.status_code == 201, lifted.text
    me = app.client.get("/v1/users/me", headers=_auth(offender)).json()
    assert me["account"]["restrictions"] == []
    assert _create(app, offender).status_code == 201


@pytest.mark.req("SAFE-013")
def test_expired_restrictions_no_longer_apply(app: LiveApp) -> None:  # noqa: F811
    offender, offender_id = _user(app)
    moderator, _ = _staff(app)
    restricted = _act(
        app,
        moderator,
        target_type="user",
        target_id=offender_id,
        reason_code="harassment",
        action="restrict",
        restriction_kind="commenting_limited",
    )
    assert restricted.status_code == 201
    db_scalar(
        app.db_url,
        "UPDATE moderation_actions SET expires_at = now() - interval '1 minute' "
        "WHERE id = :i RETURNING 1",
        i=uuid.UUID(restricted.json()["id"]),
    )
    me = app.client.get("/v1/users/me", headers=_auth(offender)).json()
    assert me["account"]["restrictions"] == []
    author, _ = _user(app)
    post = _create(app, author).json()
    comment = app.client.post(
        f"/v1/posts/{post['id']}/comments",
        headers={**_auth(offender), "Idempotency-Key": str(uuid.uuid4())},
        json={"body": "Back to normal"},
    )
    assert comment.status_code == 201, comment.text
