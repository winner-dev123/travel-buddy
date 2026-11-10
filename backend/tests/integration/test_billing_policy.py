"""Quota limits and the group admin grace, edited at runtime (BL-6.02; ADM-005, BILL-007)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

URL = "/v1/admin/billing/policy"


def _limit(live: LiveApp, token: str, quota: str) -> int:
    body = live.client.get("/v1/billing/entitlements", headers=_auth(token)).json()
    return int(body["quotas"][quota]["limit"])


def _policy(live: LiveApp, token: str) -> dict[str, Any]:
    response = live.client.get(URL, headers=_admin(token))
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "BillingPolicy")
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.req("ADM-005", "BILL-007", "ADM-007", "ADM-008")
def test_staff_change_quotas_and_grace_and_users_get_them_at_once(app: LiveApp) -> None:  # noqa: F811
    root, root_id = _staff(app, "superadmin")
    admin, _ = _staff(app, "admin")
    member, _ = _user(app)
    db_scalar(app.db_url, "DELETE FROM entitlement_policy_overrides RETURNING 1")
    try:
        _problem(app.client.get(URL, headers=_admin(admin)), 403, "forbidden")  # superadmins only
        policy = _policy(app, root)
        assert policy["version"] == 0
        assert policy["updated_by"] is None
        itinerary = next(q for q in policy["quotas"] if q["key"] == "ai.itinerary_generations")
        assert (itinerary["free"], itinerary["premium"], itinerary["period"]) == (5, 60, "monthly")
        assert policy["group_admin_grace_days"] == policy["default_group_admin_grace_days"] == 14
        assert _limit(app, member, "ai.itinerary_generations") == 5

        change = {
            "version": 0,
            "quotas": {"ai.itinerary_generations": {"free": 8, "premium": 80}},
            "group_admin_grace_days": 21,
        }
        _problem(
            app.client.put(URL, headers=_admin(root, None), json=change),
            400,
            "justification_required",
        )
        _problem(
            app.client.put(
                URL,
                headers=_admin(root),
                json={**change, "quotas": {"ai.trip_replans": {"free": 9, "premium": 1}}},
            ),
            422,
            "validation_failed",
        )
        _problem(
            app.client.put(URL, headers=_admin(root), json={**change, "quotas": {"unknown": {}}}),
            422,
            "validation_failed",
        )
        _problem(
            app.client.put(
                URL, headers=_admin(root), json={**change, "group_admin_grace_days": 91}
            ),
            422,
            "validation_failed",
        )

        saved = app.client.put(URL, headers=_admin(root), json=change)
        assert saved.status_code == 200, saved.text
        assert_matches_contract(saved.json(), "BillingPolicy")
        assert saved.json()["version"] == 1
        assert saved.json()["updated_by"] == root_id
        assert saved.json()["group_admin_grace_days"] == 21
        assert _limit(app, member, "ai.itinerary_generations") == 8  # the next request sees it
        assert _limit(app, member, "ai.trip_replans") == 0  # untouched quotas keep the default

        _problem(app.client.put(URL, headers=_admin(root), json=change), 409, "conflict")  # stale

        reset = app.client.put(
            URL, headers=_admin(root), json={"version": 1, "group_admin_grace_days": None}
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["version"] == 2
        assert reset.json()["group_admin_grace_days"] == 14
        assert _limit(app, member, "ai.itinerary_generations") == 5

        audited = db_scalar(
            app.db_url,
            "SELECT string_agg((metadata->'before'->>'version') || '>' || "
            "(metadata->'after'->>'version'), ',' ORDER BY occurred_at) FROM audit_logs "
            "WHERE action = 'billing_policy.updated' AND actor_id = CAST(:a AS uuid)",
            a=root_id,
        )
        assert audited == "0>1,1>2"
    finally:  # the policy row is shared by every test that reads entitlements
        db_scalar(app.db_url, "DELETE FROM entitlement_policy_overrides RETURNING 1")
