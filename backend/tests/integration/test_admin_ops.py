"""Promotional grants and the ops summary (BL-6.02; BILL-009, ADM-006, ADM-007)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _report, _staff
from tests.integration.test_posts import _create, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _premium(live: LiveApp, token: str) -> bool:
    features = live.client.get("/v1/billing/entitlements", headers=_auth(token)).json()["features"]
    return bool(features.get("groups.create"))


@pytest.mark.req("BILL-009", "ADM-007", "ADM-008")
def test_staff_grant_and_revoke_time_limited_premium(app: LiveApp) -> None:  # noqa: F811
    admin, _ = _staff(app, "admin")
    moderator, _ = _staff(app, "moderator")
    member, member_id = _user(app)
    url = f"/v1/admin/users/{member_id}/entitlement-grants"
    body = {
        "entitlement_key": "premium",
        "ends_at": (app.clock.now() + timedelta(days=30)).isoformat(),
        "reason": "Community ambassador programme, month one",
    }
    _problem(app.client.post(url, headers=_admin(moderator), json=body), 403, "forbidden")
    _problem(
        app.client.post(
            url,
            headers=_admin(admin),
            json={**body, "ends_at": (app.clock.now() - timedelta(days=1)).isoformat()},
        ),
        422,
        "validation_failed",
    )
    granted = app.client.post(url, headers=_admin(admin), json=body)
    assert granted.status_code == 201, granted.text
    assert_matches_contract(granted.json(), "EntitlementGrant")
    assert _premium(app, member)
    listed = app.client.get(url, headers=_admin(admin))
    assert_matches_contract(listed.json(), "EntitlementGrantList")
    assert [g["id"] for g in listed.json()["data"]] == [granted.json()["id"]]
    revoked = app.client.post(
        f"/v1/admin/entitlement-grants/{granted.json()['id']}/revoke", headers=_admin(admin)
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None
    assert not _premium(app, member)
    reason = db_scalar(
        app.db_url,
        "SELECT metadata->>'reason' FROM audit_logs WHERE action = 'entitlement.granted' "
        "AND resource_id = :u",
        u=member_id,
    )
    assert reason == body["reason"]


@pytest.mark.req("ADM-006")
def test_ops_summary_shows_the_moderation_queue_and_queues(app: LiveApp) -> None:  # noqa: F811
    admin, _ = _staff(app, "admin")
    moderator, _ = _staff(app, "moderator")
    author, _ = _user(app)
    reporter, _ = _user(app)
    post = _create(app, author).json()
    assert _report(
        app, reporter, target_type="post", target_id=post["id"], reason="spam"
    ).status_code in (201, 202)
    _problem(app.client.get("/v1/admin/ops/summary", headers=_admin(moderator)), 403, "forbidden")
    summary = app.client.get("/v1/admin/ops/summary", headers=_admin(admin))
    assert summary.status_code == 200, summary.text
    assert_matches_contract(summary.json(), "OpsSummary")
    assert summary.json()["moderation"]["open_reports"] >= 1
    assert summary.json()["moderation"]["oldest_open_age_seconds"] is not None
    assert summary.json()["outbox"]["unpublished_events"] >= 0


@pytest.mark.req("ADM-005", "ADM-007")
def test_superadmins_configure_products(app: LiveApp) -> None:  # noqa: F811
    root, _ = _staff(app, "superadmin")
    admin, _ = _staff(app, "admin")
    sku = f"price_test_{uuid.uuid4().hex[:10]}"
    body = {
        "sku": sku,
        "platform": "web",
        "kind": "auto_renewable",
        "plan_key": "premium",
        "period": "P1M",
        "entitlement_keys": ["premium"],
    }
    _problem(
        app.client.post("/v1/admin/products", headers=_admin(admin), json=body), 403, "forbidden"
    )
    _problem(
        app.client.post("/v1/admin/products", headers=_admin(root), json={**body, "period": None}),
        422,
        "validation_failed",
    )
    created = app.client.post("/v1/admin/products", headers=_admin(root), json=body)
    assert created.status_code == 201, created.text
    assert_matches_contract(created.json(), "AdminProduct")
    _problem(
        app.client.post("/v1/admin/products", headers=_admin(root), json=body), 409, "conflict"
    )
    public = app.client.get("/v1/billing/products", params={"platform": "web"}).json()["data"]
    assert sku in [p["sku"] for p in public]
    retired = app.client.patch(
        f"/v1/admin/products/{created.json()['id']}", headers=_admin(root), json={"active": False}
    )
    assert retired.json()["active"] is False
    public = app.client.get("/v1/billing/products", params={"platform": "web"}).json()["data"]
    assert sku not in [p["sku"] for p in public]
    listed = app.client.get("/v1/admin/products", headers=_admin(root)).json()["data"]
    assert sku in [p["sku"] for p in listed]  # staff still see retired products
