"""App Store purchases and Server Notifications v2 verified against a pinned root (BL-6.01;
BILL-003, BILL-007, BILL-008). A stand-in chain plays Apple's role."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.time import FixedClock
from app.main import create_app
from tests.apple_chain import AppleChain, transaction
from tests.conftest import make_identity_settings, make_settings
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import CRON, MONTHLY, _seed_products, _verify
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _user

pytestmark = pytest.mark.integration

BUNDLE = "app.travelbuddy.test"
CHAIN = AppleChain.create()


@pytest.fixture
def apple(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
    async def ok() -> bool:
        return True

    _seed_products(catalog)
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    application = create_app(
        make_settings(
            database_url=catalog,
            dev_idp_enabled=True,
            cron_secret=SecretStr(CRON),
            apple_bundle_id=BUNDLE,
            apple_root_ca_sha256=f"aa:bb, {CHAIN.root_fingerprint}",
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog)


def _notify(live: LiveApp, kind: str, subtype: str | None, original: str, **extra: Any) -> Any:
    payload: dict[str, Any] = {
        "notificationType": kind,
        "notificationUUID": str(uuid.uuid4()),
        "data": {
            "bundleId": BUNDLE,
            "environment": "Sandbox",
            "signedTransactionInfo": CHAIN.sign(
                transaction(bundle_id=BUNDLE, product_id=MONTHLY, original_transaction_id=original)
            ),
        },
        "version": "2.0",
        "signedDate": int(datetime.now(tz=UTC).timestamp() * 1000),
        **extra,
    }
    if subtype is not None:
        payload["subtype"] = subtype
    return live.client.post(
        "/v1/billing/webhooks/apple", json={"signedPayload": CHAIN.sign(payload)}
    ), payload


def _premium(live: LiveApp, token: str) -> bool:
    features = live.client.get("/v1/billing/entitlements", headers=_auth(token)).json()["features"]
    return bool(features.get("groups.create"))


@pytest.mark.req("BILL-003", "BILL-007", "BILL-008")
def test_app_store_purchase_and_notifications_drive_the_subscription(apple: LiveApp) -> None:
    token, _ = _user(apple)
    original = f"2000{uuid.uuid4().int % 10**10}"
    signed = CHAIN.sign(
        transaction(bundle_id=BUNDLE, product_id=MONTHLY, original_transaction_id=original)
    )
    verified = _verify(apple, token, signed)
    assert verified.status_code == 200, verified.text
    assert _premium(apple, token)

    (off, _) = _notify(apple, "DID_CHANGE_RENEWAL_STATUS", "AUTO_RENEW_DISABLED", original)
    assert (off.status_code, off.json()) == (200, {"status": "processed"})
    assert (
        db_scalar(
            apple.db_url,
            "SELECT auto_renew_enabled FROM subscriptions WHERE original_transaction_id = :o",
            o=original,
        )
        is False
    )
    (price, _) = _notify(apple, "PRICE_INCREASE", "PENDING", original)
    assert price.json() == {"status": "ignored"}  # changes nothing

    (refund, sent) = _notify(apple, "REFUND", None, original)
    assert refund.json() == {"status": "processed"}
    assert not _premium(apple, token)
    again = apple.client.post(
        "/v1/billing/webhooks/apple", json={"signedPayload": CHAIN.sign(sent)}
    )
    assert again.json() == {"status": "processed"}  # stored once per notificationUUID
    assert (
        db_scalar(
            apple.db_url,
            "SELECT count(*) FROM billing_events WHERE provider_event_id = :e",
            e=sent["notificationUUID"],
        )
        == 1
    )


@pytest.mark.req("BILL-003", "BILL-007")
def test_unsigned_or_foreign_app_store_data_is_refused(apple: LiveApp) -> None:
    token, _ = _user(apple)
    impostor = AppleChain.create()
    forged = impostor.sign(
        transaction(bundle_id=BUNDLE, product_id=MONTHLY, original_transaction_id="1")
    )
    _problem(_verify(apple, token, forged), 422, "purchase_invalid")
    _problem(
        apple.client.post("/v1/billing/webhooks/apple", json={"signedPayload": forged}),
        400,
        "bad_request",
    )
    other_app = CHAIN.sign(
        {
            "notificationType": "REFUND",
            "notificationUUID": str(uuid.uuid4()),
            "data": {"bundleId": "com.someone.else"},
            "signedDate": 0,
        }
    )
    _problem(
        apple.client.post("/v1/billing/webhooks/apple", json={"signedPayload": other_app}),
        400,
        "bad_request",
    )
