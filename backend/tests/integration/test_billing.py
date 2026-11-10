"""Billing end to end with the dev store (BL-3.01/3.02; BILL-001..008, docs/07)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.time import FixedClock
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import CRON, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

MONTHLY = "com.travelbuddy.premium.monthly"
ANNUAL_ANDROID = "premium_annual"
GUIDE = "com.travelbuddy.guide.lisbon"


def _seed_products(db_url: str) -> None:
    db_scalar(
        db_url,
        "INSERT INTO products (id, sku, platform, kind, plan_key, period, entitlement_keys) VALUES "  # noqa: S608
        f"(gen_random_uuid(), '{MONTHLY}', 'ios', 'auto_renewable', 'premium', 'P1M', "
        "ARRAY['premium']), "
        f"(gen_random_uuid(), '{ANNUAL_ANDROID}', 'android', 'auto_renewable', 'premium', 'P1Y', "
        "ARRAY['premium']), "
        f"(gen_random_uuid(), '{GUIDE}', 'ios', 'non_consumable', NULL, NULL, "
        "ARRAY['content:guide:lisbon']) "
        "ON CONFLICT (platform, sku) DO NOTHING RETURNING 1",
    )


@pytest.fixture
def store(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
    async def ok() -> bool:
        return True

    _seed_products(catalog)
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    application = create_app(
        make_settings(
            database_url=catalog,
            dev_idp_enabled=True,
            dev_billing_enabled=True,
            cron_secret=SecretStr(CRON),
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog)


def _verify(live: LiveApp, token: str, payload: str, key: str | None = None) -> Any:
    return live.client.post(
        "/v1/billing/purchases/verify",
        headers={**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())},
        json={"provider": "apple", "signed_transaction": payload},
    )


def _entitlements(live: LiveApp, token: str) -> dict[str, Any]:
    response = live.client.get("/v1/billing/entitlements", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert_matches_contract(response.json(), "Entitlements")
    body: dict[str, Any] = response.json()
    return body


def _event(live: LiveApp, token: str, transaction: str, event: str, **extra: Any) -> str:
    live.clock.set(live.clock.now() + timedelta(minutes=1))  # store events arrive over time
    response = live.client.post(
        "/v1/dev/billing/events",
        headers=_auth(token),
        json={"original_transaction_id": transaction, "event": event, **extra},
    )
    assert response.status_code == 200, response.text
    outcome: str = response.json()["outcome"]
    return outcome


@pytest.mark.req("BILL-001")
def test_products_are_listed_per_platform(store: LiveApp) -> None:
    response = store.client.get("/v1/billing/products", params={"platform": "ios"})
    assert response.status_code == 200, response.text
    skus = {p["sku"]: p for p in response.json()["data"]}
    assert MONTHLY in skus
    assert skus[MONTHLY]["provider"] == "apple"
    for product in response.json()["data"]:
        assert_matches_contract(product, "Product")
    android = store.client.get("/v1/billing/products", params={"platform": "android"}).json()
    assert ANNUAL_ANDROID in {p["sku"] for p in android["data"]}


@pytest.mark.req("BILL-002", "BILL-003", "BILL-004", "BILL-007")
def test_verified_purchase_grants_premium_once_and_only_to_its_account(store: LiveApp) -> None:
    token, _ = _user(store)
    free = _entitlements(store, token)
    assert (free["plan"], free["status"], free["features"]["groups.create"]) == (
        "free",
        "none",
        False,
    )

    transaction = f"tx-{uuid.uuid4().hex[:8]}"
    key = str(uuid.uuid4())
    verified = _verify(store, token, f"dev:{MONTHLY}:{transaction}", key)
    assert verified.status_code == 200, verified.text
    assert_matches_contract(verified.json(), "VerifyPurchaseResult")
    body = verified.json()
    assert body["purchase"]["kind"] == "subscription_purchase"
    assert body["entitlements"]["plan"] == "premium"
    assert body["entitlements"]["features"]["groups.create"] is True
    assert body["entitlements"]["active_subscription"]["management"] == "app_store"
    assert verified.headers["cache-control"] == "no-store"
    replay = _verify(store, token, f"dev:{MONTHLY}:{transaction}", key)
    assert replay.json() == body
    me = store.client.get("/v1/users/me", headers=_auth(token)).json()
    assert me["entitlements"]["plan"] == "premium"  # one evaluator for every surface

    # Receipt sharing: the same store transaction can't unlock a second account.
    other, _ = _user(store)
    _problem(_verify(store, other, f"dev:{MONTHLY}:{transaction}"), 409, "purchase_already_linked")
    assert _entitlements(store, other)["plan"] == "free"

    _problem(_verify(store, token, "dev:unknown.sku:tx-1"), 422, "purchase_invalid")
    _problem(_verify(store, token, "not-a-dev-transaction"), 422, "purchase_invalid")


@pytest.mark.req("BILL-005", "BILL-006", "BILL-008")
def test_store_events_drive_the_subscription_state_machine(store: LiveApp) -> None:
    token, _ = _user(store)
    transaction = f"tx-{uuid.uuid4().hex[:8]}"
    assert _verify(store, token, f"dev:{MONTHLY}:{transaction}").status_code == 200

    assert _event(store, token, transaction, "grace", event_id=f"{transaction}-1") == "processed"
    grace = _entitlements(store, token)
    assert (grace["plan"], grace["status"]) == ("premium", "in_grace_period")
    assert grace["store_grace_until"] is not None
    # A redelivered notification is applied once.
    assert _event(store, token, transaction, "renewed", event_id=f"{transaction}-1") == "processed"
    assert _entitlements(store, token)["status"] == "in_grace_period"

    assert _event(store, token, transaction, "billing_retry") == "processed"
    retry = _entitlements(store, token)
    assert (retry["plan"], retry["status"]) == ("free", "in_billing_retry")
    assert retry["features"]["groups.create"] is False

    assert _event(store, token, transaction, "recovered") == "processed"
    assert _entitlements(store, token)["plan"] == "premium"

    # An older notification than the last one applied is recorded and ignored.
    stale = (store.clock.now() - timedelta(days=3)).isoformat()
    assert _event(store, token, transaction, "expired", signed_date=stale) == "ignored"
    assert _entitlements(store, token)["plan"] == "premium"

    assert _event(store, token, transaction, "auto_renew_off") == "processed"
    cancelled = _entitlements(store, token)
    assert cancelled["plan"] == "premium"  # until the end of the paid period
    assert cancelled["active_subscription"]["auto_renew"] is False

    assert _event(store, token, transaction, "refunded") == "processed"
    refunded = _entitlements(store, token)
    assert (refunded["plan"], refunded["status"]) == ("free", "revoked")
    assert _event(store, token, "unknown-transaction", "renewed") == "ignored"
    assert (
        db_scalar(
            store.db_url,
            "SELECT count(*) FROM billing_events WHERE payload IS NOT NULL "
            "AND provider = 'dev' AND processing_status = 'ignored'",
        )
        or 0
    ) >= 2


@pytest.mark.req("BILL-006")
def test_restore_rebinds_only_my_purchases_and_content_is_permanent(store: LiveApp) -> None:
    token, _ = _user(store)
    other, _ = _user(store)
    theirs = f"tx-{uuid.uuid4().hex[:8]}"
    assert _verify(store, other, f"dev:{MONTHLY}:{theirs}").status_code == 200
    mine = f"tx-{uuid.uuid4().hex[:8]}"
    restored = store.client.post(
        "/v1/billing/purchases/restore",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "provider": "apple",
            "signed_transactions": [f"dev:{MONTHLY}:{theirs}", f"dev:{GUIDE}:{mine}"],
        },
    )
    assert restored.status_code == 200, restored.text
    assert_matches_contract(restored.json(), "Entitlements")
    assert restored.json()["plan"] == "free"  # the other account's subscription stays theirs
    grants = db_scalar(
        store.db_url,
        "SELECT count(*) FROM subscription_entitlements e JOIN purchases p ON p.id = e.source_id "
        "WHERE e.entitlement_key = 'content:guide:lisbon' AND e.ends_at IS NULL "
        "AND p.transaction_id LIKE :t",
        t=f"{mine}:%",
    )
    assert grants == 1

    google = store.client.post(
        "/v1/billing/purchases/verify",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "provider": "google",
            "product_sku": ANNUAL_ANDROID,
            "purchase_token": f"dev:{ANNUAL_ANDROID}:gp-{uuid.uuid4().hex[:8]}",
            "package_name": "com.travelbuddy.app",
        },
    )
    assert google.status_code == 200, google.text
    assert google.json()["entitlements"]["plan"] == "premium"


@pytest.mark.req("BILL-003")
def test_without_store_credentials_verification_is_unavailable(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    _problem(_verify(app, token, f"dev:{MONTHLY}:tx-1"), 503, "service_unavailable")
    simulated = app.client.post(
        "/v1/dev/billing/events",
        headers=_auth(token),
        json={"original_transaction_id": "tx-1", "event": "renewed"},
    )
    assert simulated.status_code == 404
