"""Staff console endpoints (ADR-0032): account search, overview, ledger and staff roles."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.modules.admin.grant_role import grant
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth, _id_token, _register
from tests.integration.test_moderation import _admin, _report, _staff
from tests.integration.test_posts import _create, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _member(live: LiveApp, email: str | None = None) -> tuple[str, str]:
    token = _id_token(live, email=email or f"{uuid.uuid4().hex[:10]}@example.com")
    registered = _register(live, token)
    assert registered.status_code == 201, registered.text
    body = registered.json()
    return str(body["tokens"]["access_token"]), str(body["user"]["account"]["id"])


def _ledger(live: LiveApp, user_id: str | None, **row: object) -> str:
    values = {
        "provider": "stripe",
        "environment": "sandbox",
        "kind": "payment",
        "status": "succeeded",
        "amount_minor": 1190,
        "currency": "BRL",
        "reason": "purchase",
        **row,
    }
    return str(
        db_scalar(
            live.db_url,
            "INSERT INTO billing_transactions (id, user_id, provider, environment, kind, status, "
            "provider_reference, amount_minor, currency, reason, occurred_at) VALUES "
            "(gen_random_uuid(), :u, :provider, :environment, :kind, :status, :ref, :amount_minor, "
            ":currency, :reason, now()) RETURNING id",
            u=uuid.UUID(user_id) if user_id else None,
            ref=f"pi_test_{uuid.uuid4().hex[:12]}",
            **values,
        )
    )


@pytest.mark.req("ADM-003", "ADM-007", "ADM-009")
def test_staff_find_accounts_by_email_id_and_name(app: LiveApp) -> None:  # noqa: F811
    support, _ = _staff(app, "support")
    member, _ = _user(app)
    email = f"find.{uuid.uuid4().hex[:8]}@example.com"
    _, target_id = _member(app, email)
    handle = app.client.get(f"/v1/admin/users/{target_id}", headers=_admin(support)).json()[
        "handle"
    ]

    _problem(app.client.get("/v1/admin/users", headers=_auth(member)), 403, "forbidden")
    _problem(
        app.client.get("/v1/admin/users", headers=_admin(support, None)),
        400,
        "justification_required",
    )
    # The full handle: the shared CI database holds many "ana.souza…" accounts, and a handle
    # prefix search lists matches in handle order, the exact handle first.
    for query in (email.upper(), target_id, f"@{handle}"):
        found = app.client.get(
            "/v1/admin/users", params={"q": query, "limit": 5}, headers=_admin(support)
        )
        assert found.status_code == 200, found.text
        assert_matches_contract(found.json(), "AdminUserSummaryPage")
        assert target_id in [row["id"] for row in found.json()["data"]], query
        assert all("email" not in row for row in found.json()["data"])
    nobody = app.client.get(
        "/v1/admin/users", params={"q": "nobody@nowhere.example"}, headers=_admin(support)
    )
    assert nobody.json()["data"] == []
    searched = db_scalar(
        app.db_url,
        "SELECT count(*) FROM audit_logs WHERE action = 'users.searched' AND actor_id = :a",
        a=uuid.UUID(
            str(app.client.get("/v1/users/me", headers=_auth(support)).json()["account"]["id"])
        ),
    )
    assert searched == 4


@pytest.mark.req("ADM-003", "ADM-002")
def test_account_lists_filter_and_page(app: LiveApp) -> None:  # noqa: F811
    moderator, _ = _staff(app, "moderator")
    _, first = _user(app)
    _, second = _user(app)
    assert (
        app.client.post(
            f"/v1/admin/users/{first}/suspend",
            headers=_admin(moderator),
            json={"reason_code": "spam", "notes": "Repeated spam links", "until": None},
        ).status_code
        == 200
    )
    suspended = app.client.get(
        "/v1/admin/users", params={"status": "suspended", "limit": 100}, headers=_admin(moderator)
    ).json()["data"]
    assert first in [row["id"] for row in suspended]
    assert second not in [row["id"] for row in suspended]
    assert {row["status"] for row in suspended} == {"suspended"}

    staff_rows = app.client.get(
        "/v1/admin/users", params={"staff": "true", "limit": 100}, headers=_admin(moderator)
    ).json()["data"]
    assert staff_rows
    assert all(row["roles"] for row in staff_rows)

    page = app.client.get("/v1/admin/users", params={"limit": 1}, headers=_admin(moderator))
    assert page.json()["page"]["has_more"] is True
    following = app.client.get(
        "/v1/admin/users",
        params={"limit": 1, "cursor": page.json()["page"]["next_cursor"]},
        headers=_admin(moderator),
    )
    assert following.status_code == 200, following.text
    assert following.json()["data"][0]["id"] != page.json()["data"][0]["id"]
    _problem(
        app.client.get(
            "/v1/admin/users",
            params={"limit": 1, "status": "active", "cursor": page.json()["page"]["next_cursor"]},
            headers=_admin(moderator),
        ),
        400,
        "invalid_cursor",
    )


@pytest.mark.req("ADM-006", "ADM-007")
def test_overview_shows_real_counts_and_money_only_to_admins(app: LiveApp) -> None:  # noqa: F811
    admin, _ = _staff(app, "admin")
    moderator, _ = _staff(app, "moderator")
    author, author_id = _user(app)
    reporter, _ = _user(app)
    post = _create(app, author).json()
    assert _report(
        app, reporter, target_type="post", target_id=post["id"], reason="spam"
    ).status_code in (200, 202)
    _ledger(app, author_id, amount_minor=1990)
    _ledger(app, author_id, kind="refund", amount_minor=500, reason="partial_refund")

    seen = app.client.get("/v1/admin/metrics/overview", headers=_admin(moderator, None))
    assert seen.status_code == 200, seen.text
    assert_matches_contract(seen.json(), "AdminOverview")
    assert seen.json()["revenue_30d"] is None
    assert seen.json()["open_data_requests"] is None
    assert seen.json()["users"]["total"] >= 4
    assert seen.json()["posts_7d"] >= 1
    assert seen.json()["moderation"]["open_reports"] >= 1

    full = app.client.get("/v1/admin/metrics/overview", headers=_admin(admin, None)).json()
    assert_matches_contract(full, "AdminOverview")
    assert full["open_data_requests"] is not None
    brl = [r for r in full["revenue_30d"] if r["currency"] == "BRL"]
    assert brl
    assert brl[0]["environment"] == "sandbox"
    assert brl[0]["amount_minor"] >= 1490
    member, _ = _user(app)
    _problem(app.client.get("/v1/admin/metrics/overview", headers=_auth(member)), 403, "forbidden")


@pytest.mark.req("ADM-005", "BILL-011", "ADM-009")
def test_staff_read_the_ledger(app: LiveApp) -> None:  # noqa: F811
    admin, _ = _staff(app, "admin")
    moderator, _ = _staff(app, "moderator")
    _, buyer = _user(app)
    paid = _ledger(app, buyer)
    failed = _ledger(app, buyer, status="failed")
    _problem(
        app.client.get("/v1/admin/billing/transactions", headers=_admin(moderator)),
        403,
        "forbidden",
    )
    mine = app.client.get(
        "/v1/admin/billing/transactions", params={"user_id": buyer}, headers=_admin(admin)
    )
    assert mine.status_code == 200, mine.text
    assert_matches_contract(mine.json(), "AdminBillingTransactionPage")
    assert {row["id"] for row in mine.json()["data"]} == {paid, failed}
    only_failed = app.client.get(
        "/v1/admin/billing/transactions",
        params={"user_id": buyer, "status": "failed"},
        headers=_admin(admin),
    ).json()["data"]
    assert [row["id"] for row in only_failed] == [failed]
    first = app.client.get(
        "/v1/admin/billing/transactions",
        params={"user_id": buyer, "limit": 1},
        headers=_admin(admin),
    ).json()
    rest = app.client.get(
        "/v1/admin/billing/transactions",
        params={"user_id": buyer, "limit": 1, "cursor": first["page"]["next_cursor"]},
        headers=_admin(admin),
    ).json()
    assert {first["data"][0]["id"], rest["data"][0]["id"]} == {paid, failed}
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM audit_logs WHERE action = 'billing_transactions.viewed' "
            "AND resource_id = :u",
            u=buyer,
        )
        == 4
    )


@pytest.mark.req("ADM-007", "ADM-009")
def test_superadmins_give_and_take_staff_roles(live_app: LiveApp) -> None:
    root, root_id = _staff(live_app, "superadmin")
    admin, _ = _staff(live_app, "admin")
    member, member_id = _member(live_app)
    url = f"/v1/admin/users/{member_id}/roles/moderator"

    _problem(live_app.client.put(url, headers=_admin(admin)), 403, "forbidden")
    _problem(live_app.client.put(url, headers=_admin(root, None)), 400, "justification_required")
    given = live_app.client.put(url, headers=_admin(root))
    assert given.status_code == 200, given.text
    assert_matches_contract(given.json(), "AdminUser")
    assert given.json()["roles"] == ["moderator"]
    again = live_app.client.put(url, headers=_admin(root))
    assert again.json()["roles"] == ["moderator"]
    assert (
        db_scalar(
            live_app.db_url,
            "SELECT count(*) FROM audit_logs WHERE action = 'staff_role.granted' "
            "AND resource_id = :u",
            u=member_id,
        )
        == 1
    )

    assert live_app.client.get("/v1/users/me", headers=_auth(member)).status_code == 200

    # Taking a role away ends the staff session at once, before the token expires.
    moderator, moderator_id = _staff(live_app, "moderator")
    queue = "/v1/admin/reports"
    assert live_app.client.get(queue, headers=_admin(moderator)).status_code == 200
    taken = live_app.client.delete(
        f"/v1/admin/users/{moderator_id}/roles/moderator", headers=_admin(root)
    )
    assert taken.status_code == 200, taken.text
    assert taken.json()["roles"] == []
    _problem(live_app.client.get(queue, headers=_admin(moderator)), 401, "unauthenticated")
    # Given back later, the old assignment row is reused.
    again = live_app.client.put(
        f"/v1/admin/users/{moderator_id}/roles/moderator", headers=_admin(root)
    )
    assert again.json()["roles"] == ["moderator"]

    # The last superadmin can't lose the role; with a second one, it can go.
    last = f"/v1/admin/users/{root_id}/roles/superadmin"
    _problem(live_app.client.delete(last, headers=_admin(root)), 409, "conflict")
    second, _ = _staff(live_app, "superadmin")
    assert live_app.client.delete(last, headers=_admin(second)).json()["roles"] == []

    # Suspended accounts get no role.
    _, suspended_id = _member(live_app)
    db_scalar(
        live_app.db_url,
        "UPDATE users SET status = 'suspended' WHERE id = :u RETURNING 1",
        u=uuid.UUID(suspended_id),
    )
    _problem(
        live_app.client.put(
            f"/v1/admin/users/{suspended_id}/roles/support", headers=_admin(second)
        ),
        409,
        "conflict",
    )


@pytest.mark.req("ADM-007")
def test_grant_role_command_sets_up_the_first_superadmin(live_app: LiveApp) -> None:
    email = f"owner.{uuid.uuid4().hex[:8]}@example.com"
    _, owner_id = _member(live_app, email)

    async def run(apply: bool, address: str = email) -> str:
        engine = create_async_engine(live_app.db_url)
        try:
            sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with sessions() as session, session.begin():
                return await grant(
                    session,
                    email=address,
                    role="superadmin",
                    reason="First staff account",
                    apply=apply,
                    now=live_app.clock.now(),
                )
        finally:
            await engine.dispose()

    assert asyncio.run(run(False, "missing@example.com")).startswith("No account")
    assert asyncio.run(run(False)).startswith("Would give")
    assert email not in asyncio.run(run(False))
    assert (
        db_scalar(
            live_app.db_url,
            "SELECT count(*) FROM admin_role_assignments WHERE user_id = :u",
            u=uuid.UUID(owner_id),
        )
        == 0
    )
    assert asyncio.run(run(True)).startswith("Gave")
    assert asyncio.run(run(True)).endswith("already has the superadmin role.")
    assert (
        db_scalar(
            live_app.db_url,
            "SELECT actor_type FROM audit_logs WHERE action = 'staff_role.granted' "
            "AND resource_id = :u",
            u=owner_id,
        )
        == "system"
    )


def test_browsers_may_send_the_audit_justification_header() -> None:
    application = create_app(
        make_settings(cors_allowed_origins=["https://admin.example.com"]),
        identity_settings=make_identity_settings(),
    )
    with TestClient(application) as client:
        preflight = client.options(
            "/v1/admin/users",
            headers={
                "Origin": "https://admin.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-audit-justification",
            },
        )
    assert preflight.status_code == 200, preflight.text
    allowed = preflight.headers["access-control-allow-headers"].lower()
    assert "x-audit-justification" in allowed
    assert preflight.headers["access-control-allow-origin"] == "https://admin.example.com"


@pytest.mark.req("ADM-001", "SAFE-003")
def test_reports_name_the_author_so_staff_can_act_on_the_account(app: LiveApp) -> None:  # noqa: F811
    moderator, _ = _staff(app, "moderator")
    author, author_id = _user(app)
    reporter, _ = _user(app)
    post = _create(app, author).json()
    receipt = _report(app, reporter, target_type="post", target_id=post["id"], reason="scam")
    assert receipt.status_code == 202, receipt.text
    report = app.client.get(f"/v1/admin/reports/{receipt.json()['id']}", headers=_admin(moderator))
    assert report.status_code == 200, report.text
    assert_matches_contract(report.json(), "AdminReport")
    assert report.json()["target_author"]["id"] == author_id
