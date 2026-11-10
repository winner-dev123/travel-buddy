"""Google Play purchases and Real-time Developer Notifications end to end (BL-6.01; BILL-002,
BILL-003, BILL-007, BILL-008). The Play Developer API, Google's token endpoint and its OIDC keys
are served by a mock transport; everything else is the real stack."""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.time import FixedClock
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import ANNUAL_ANDROID, CRON, _seed_products
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _user

pytestmark = pytest.mark.integration

PACKAGE = "app.travelbuddy.test"
GUIDE_ANDROID = "guide_lisbon"
AUDIENCE = "https://api.test/v1/billing/webhooks/google"
PUSHER = "rtdn@travelbuddy-test.iam.gserviceaccount.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
BASE = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{PACKAGE}"


class FakePlay:
    def __init__(self) -> None:
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.products: dict[str, dict[str, Any]] = {}
        self.acknowledged: list[str] = []
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://oauth2.googleapis.com/token":
            return httpx.Response(200, json={"access_token": "ya29.t", "expires_in": 3600})
        if url == "https://www.googleapis.com/oauth2/v3/certs":
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
            return httpx.Response(200, json={"keys": [{**jwk, "kid": "k1", "alg": "RS256"}]})
        if self.down:
            return httpx.Response(503)
        if url.endswith(":acknowledge"):
            self.acknowledged.append(url.rsplit("/tokens/", 1)[1].removesuffix(":acknowledge"))
            return httpx.Response(200)
        if url.startswith(f"{BASE}/purchases/subscriptionsv2/tokens/"):
            token = url.rsplit("/", 1)[1]
            found = self.subscriptions.get(token)
            return httpx.Response(200, json=found) if found else httpx.Response(404)
        if url.startswith(f"{BASE}/purchases/products/"):
            token = url.rsplit("/", 1)[1]
            found = self.products.get(token)
            return httpx.Response(200, json=found) if found else httpx.Response(404)
        return httpx.Response(500, json={"unexpected": url})


PLAY = FakePlay()


def _state(state: str, *, ends: datetime, auto_renew: bool = True) -> dict[str, Any]:
    return {
        "subscriptionState": state,
        "startTime": (ends - timedelta(days=365)).isoformat().replace("+00:00", "Z"),
        "latestOrderId": f"GPA.{uuid.uuid4().hex[:12]}",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
        "lineItems": [
            {
                "productId": ANNUAL_ANDROID,
                "expiryTime": ends.isoformat().replace("+00:00", "Z"),
                "autoRenewingPlan": {"autoRenewEnabled": auto_renew},
            }
        ],
        "testPurchase": {},
    }


@pytest.fixture
def google(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
    async def ok() -> bool:
        return True

    _seed_products(catalog)
    db_scalar(
        catalog,
        "INSERT INTO products (id, sku, platform, kind, plan_key, period, entitlement_keys) "  # noqa: S608
        f"VALUES (gen_random_uuid(), '{GUIDE_ANDROID}', 'android', 'non_consumable', NULL, NULL, "
        "ARRAY['content:guide:lisbon']) ON CONFLICT (platform, sku) DO NOTHING RETURNING 1",
    )
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    application = create_app(
        make_settings(
            database_url=catalog,
            dev_idp_enabled=True,
            cron_secret=SecretStr(CRON),
            google_play_package_name=PACKAGE,
            google_play_service_account_json=SecretStr(
                json.dumps(
                    {
                        "client_email": "play@travelbuddy-test.iam.gserviceaccount.com",
                        "private_key": PEM,
                    }
                )
            ),
            google_pubsub_audience=AUDIENCE,
            google_pubsub_service_account=PUSHER,
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
        http_transport=httpx.MockTransport(PLAY.handle),
    )
    PLAY.down = False
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog)


def _verify(live: LiveApp, token: str, sku: str, purchase_token: str) -> Any:
    return live.client.post(
        "/v1/billing/purchases/verify",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "provider": "google",
            "product_sku": sku,
            "purchase_token": purchase_token,
            "package_name": PACKAGE,
        },
    )


def _oidc(**claims: Any) -> str:
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": AUDIENCE,
        "email": PUSHER,
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
        **claims,
    }
    return "Bearer " + jwt.encode(payload, PEM, algorithm="RS256", headers={"kid": "k1"})


def _push(
    live: LiveApp,
    notification: dict[str, Any],
    *,
    message_id: str | None = None,
    auth: str | None = None,
) -> httpx.Response:
    data = base64.b64encode(json.dumps({"packageName": PACKAGE, **notification}).encode()).decode()
    return live.client.post(
        "/v1/billing/webhooks/google",
        headers={"Authorization": auth if auth is not None else _oidc()},
        json={
            "message": {
                "data": data,
                "messageId": message_id or str(uuid.uuid4()),
                "publishTime": live.clock.now().isoformat(),
            },
            "subscription": "projects/tb/subscriptions/rtdn",
        },
    )


def _sub_note(token: str, notification_type: int) -> dict[str, Any]:
    return {
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": notification_type,
            "purchaseToken": token,
            "subscriptionId": ANNUAL_ANDROID,
        }
    }


def _entitlements(live: LiveApp, token: str) -> dict[str, Any]:
    body: dict[str, Any] = live.client.get("/v1/billing/entitlements", headers=_auth(token)).json()
    return body


@pytest.mark.req("BILL-002", "BILL-003", "BILL-007", "BILL-008")
def test_play_purchase_and_notifications_drive_the_subscription(google: LiveApp) -> None:
    member, _ = _user(google)
    purchase = f"tok-{uuid.uuid4().hex}"
    ends = google.clock.now() + timedelta(days=365)
    PLAY.subscriptions[purchase] = _state("SUBSCRIPTION_STATE_ACTIVE", ends=ends)

    verified = _verify(google, member, ANNUAL_ANDROID, purchase)
    assert verified.status_code == 200, verified.text
    assert purchase in PLAY.acknowledged  # unacknowledged purchases are refunded by Google
    me = _entitlements(google, member)
    assert me["plan"] == "premium"
    assert me["active_subscription"]["management"] == "google_play"
    assert me["premium_until"].startswith(ends.date().isoformat())  # Google's own expiry

    # The user cancels in Play: access stays until the expiry, renewal is off.
    PLAY.subscriptions[purchase] = _state(
        "SUBSCRIPTION_STATE_CANCELED", ends=ends, auto_renew=False
    )
    message = str(uuid.uuid4())
    assert _push(google, _sub_note(purchase, 3), message_id=message).status_code == 204
    me = _entitlements(google, member)
    assert (me["plan"], me["active_subscription"]["auto_renew"]) == ("premium", False)
    assert _push(google, _sub_note(purchase, 3), message_id=message).status_code == 204  # dup
    stored = db_scalar(
        google.db_url,
        "SELECT count(*) FROM billing_events WHERE provider = 'google' AND provider_event_id = :m",
        m=message,
    )
    assert stored == 1

    # Refunded and revoked: access ends at once although Play's expiry is months away.
    PLAY.subscriptions[purchase] = _state("SUBSCRIPTION_STATE_EXPIRED", ends=ends, auto_renew=False)
    assert _push(google, _sub_note(purchase, 12)).status_code == 204
    me = _entitlements(google, member)
    assert (me["plan"], me["status"]) == ("free", "revoked")


@pytest.mark.security
@pytest.mark.req("BILL-007")
def test_pushes_without_googles_token_for_this_endpoint_are_refused(google: LiveApp) -> None:
    for auth in (
        "",
        "Bearer nope",
        _oidc(aud="https://evil.example"),
        _oidc(email="x@evil.example"),
    ):
        _problem(_push(google, _sub_note("t", 2), auth=auth), 401, "unauthenticated")
    # Another app's notification is stored and ignored (a 4xx would make Pub/Sub retry forever).
    data = base64.b64encode(json.dumps({"packageName": "com.other", **_sub_note("t", 2)}).encode())
    other = google.client.post(
        "/v1/billing/webhooks/google",
        headers={"Authorization": _oidc()},
        json={
            "message": {
                "data": data.decode(),
                "messageId": str(uuid.uuid4()),
                "publishTime": "2026-11-10T00:00:00Z",
            },
            "subscription": "s",
        },
    )
    assert other.status_code == 204


@pytest.mark.req("BILL-007", "BILL-008")
def test_play_outage_makes_pubsub_retry_and_a_voided_guide_loses_its_content(
    google: LiveApp,
) -> None:
    member, member_id = _user(google)
    purchase = f"tok-{uuid.uuid4().hex}"
    order = f"GPA.{uuid.uuid4().hex[:12]}"
    PLAY.products[purchase] = {
        "purchaseState": 0,
        "purchaseTimeMillis": str(int(google.clock.now().timestamp() * 1000)),
        "orderId": order,
        "acknowledgementState": 0,
        "purchaseType": 0,
    }
    verified = _verify(google, member, GUIDE_ANDROID, purchase)
    assert verified.status_code == 200, verified.text
    owned = (
        "SELECT count(*) FROM subscription_entitlements WHERE user_id = :u "
        "AND entitlement_key = 'content:guide:lisbon' AND revoked_at IS NULL"
    )
    assert db_scalar(google.db_url, owned, u=uuid.UUID(member_id)) == 1

    renewal = f"tok-{uuid.uuid4().hex}"
    PLAY.down = True
    message = str(uuid.uuid4())
    _problem(_push(google, _sub_note(renewal, 2), message_id=message), 503, "service_unavailable")
    stored = db_scalar(
        google.db_url,
        "SELECT count(*) FROM billing_events WHERE provider_event_id = :m",
        m=message,
    )
    assert stored == 0  # nothing kept, so the redelivery is processed
    PLAY.down = False

    voided = {"voidedPurchaseNotification": {"purchaseToken": purchase, "orderId": order}}
    assert _push(google, voided).status_code == 204
    assert db_scalar(google.db_url, owned, u=uuid.UUID(member_id)) == 0
