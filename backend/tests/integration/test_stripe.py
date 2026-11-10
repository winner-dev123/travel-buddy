"""Web purchases through Stripe (BL-3.14; ADR-0012, BILL-002..006) against a fake Stripe API."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.time import FixedClock
from app.main import create_app
from app.modules.billing.stripe import sign
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import store  # noqa: F401
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import CRON, _problem, _user

pytestmark = pytest.mark.integration

PRICE = "price_premium_monthly"
WEBHOOK_SECRET = "whsec_test_secret"
SITE = "https://web.example"


class FakeStripe:
    def __init__(self) -> None:
        self.customers = 0
        self.last_customer = ""
        self.checkouts: list[dict[str, list[str]]] = []
        self.subscriptions: dict[str, dict[str, Any]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk_test_123"
        path = request.url.path
        form = parse_qs(request.content.decode()) if request.content else {}
        if path == "/v1/customers":
            self.customers += 1
            self.last_customer = f"cus_{uuid.uuid4().hex[:12]}"
            return httpx.Response(200, json={"id": self.last_customer})
        if path == "/v1/checkout/sessions":
            self.checkouts.append(form)
            return httpx.Response(
                200,
                json={
                    "id": "cs_1",
                    "url": "https://checkout.stripe.com/c/pay/cs_1",
                    "expires_at": int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp()),
                },
            )
        if path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/abc"})
        if path.startswith("/v1/subscriptions/"):
            found = self.subscriptions.get(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={})
        return httpx.Response(404, json={})

    def subscription(
        self, sub_id: str, customer: str, user_id: str, status: str, **extra: Any
    ) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        self.subscriptions[sub_id] = {
            "id": sub_id,
            "customer": customer,
            "status": status,
            "cancel_at_period_end": False,
            "livemode": False,
            "metadata": {"user_id": user_id},
            "items": {
                "data": [
                    {
                        "price": {"id": PRICE},
                        "current_period_start": now - 60,
                        "current_period_end": now + 30 * 86400,
                    }
                ]
            },
            **extra,
        }


@pytest.fixture
def web(catalog: str) -> Iterator[tuple[LiveApp, FakeStripe]]:  # noqa: F811
    async def ok() -> bool:
        return True

    db_scalar(
        catalog,
        "INSERT INTO products (id, sku, platform, kind, plan_key, period, entitlement_keys) VALUES "  # noqa: S608
        f"(gen_random_uuid(), '{PRICE}', 'web', 'auto_renewable', 'premium', 'P1M', "
        "ARRAY['premium']) ON CONFLICT (platform, sku) DO NOTHING RETURNING 1",
    )
    fake = FakeStripe()
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    application = create_app(
        make_settings(
            database_url=catalog,
            dev_idp_enabled=True,
            cron_secret=SecretStr(CRON),
            public_site_url=SITE,
            stripe_secret_key=SecretStr("sk_test_123"),
            stripe_webhook_secret=SecretStr(WEBHOOK_SECRET),
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
        http_transport=httpx.MockTransport(fake.handler),
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog), fake


def _product_id(live: LiveApp) -> str:
    products = live.client.get("/v1/billing/products", params={"platform": "web"}).json()["data"]
    [product] = [p for p in products if p["sku"] == PRICE]
    assert product["provider"] == "stripe"
    return str(product["id"])


def _checkout(live: LiveApp, token: str, product_id: str, **paths: str) -> Any:
    return live.client.post(
        "/v1/billing/checkout-sessions",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "product_id": product_id,
            "success_path": "/membership/success",
            "cancel_path": "/pricing",
            **paths,
        },
    )


def _deliver(
    live: LiveApp,
    event: dict[str, Any],
    *,
    secret: str = WEBHOOK_SECRET,
    at: datetime | None = None,
) -> Any:
    payload = json.dumps(event).encode()
    return live.client.post(
        "/v1/billing/webhooks/stripe",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": sign(payload, secret, at=at or live.clock.now()),
        },
    )


def _event(kind: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": kind,
        "created": 1_800_000_000,
        "data": {"object": obj},
    }


def _plan(live: LiveApp, token: str) -> dict[str, Any]:
    body: dict[str, Any] = live.client.get("/v1/billing/entitlements", headers=_auth(token)).json()
    return body


@pytest.mark.req("BILL-002", "BILL-003")
def test_checkout_redirects_to_stripe_and_only_the_webhook_grants(
    web: tuple[LiveApp, FakeStripe],
) -> None:
    live, fake = web
    token, user_id = _user(live)
    product = _product_id(live)
    started = _checkout(live, token, product)
    assert started.status_code == 201, started.text
    assert_matches_contract(started.json(), "RedirectUrl")
    assert started.json()["url"].startswith("https://checkout.stripe.com/")
    assert started.headers["cache-control"] == "no-store"
    [form] = fake.checkouts
    assert form["success_url"] == [f"{SITE}/membership/success"]
    assert form["line_items[0][price]"] == [PRICE]
    assert form["mode"] == ["subscription"]
    assert _plan(live, token)["plan"] == "free"  # returning from Checkout grants nothing

    assert _checkout(live, token, product).status_code == 201
    assert fake.customers == 1  # one Stripe customer per user
    rejected = _checkout(live, token, product, success_path="https://evil.example/steal")
    assert rejected.status_code == 422  # absolute URLs never reach Stripe (no open redirect)

    fake.subscription("sub_1", fake.last_customer, user_id, "active")
    delivered = _deliver(live, _event("customer.subscription.created", {"id": "sub_1"}))
    assert delivered.status_code == 200, delivered.text
    assert delivered.json() == {"status": "processed"}
    premium = _plan(live, token)
    assert premium["plan"] == "premium"
    assert premium["active_subscription"]["management"] == "stripe_portal"
    _problem(_checkout(live, token, product), 409, "conflict")  # never charged twice

    portal = live.client.post(
        "/v1/billing/portal-sessions", headers=_auth(token), json={"return_path": "/account"}
    )
    assert portal.status_code == 201, portal.text
    assert portal.json()["url"].startswith("https://billing.stripe.com/")


@pytest.mark.req("BILL-005", "BILL-006", "BILL-008")
def test_webhooks_are_verified_idempotent_and_follow_stripe_state(
    web: tuple[LiveApp, FakeStripe],
) -> None:
    live, fake = web
    token, user_id = _user(live)
    assert _checkout(live, token, _product_id(live)).status_code == 201
    customer = fake.last_customer
    sub = f"sub_{uuid.uuid4().hex[:8]}"
    fake.subscription(sub, customer, user_id, "active")

    event = _event(
        "checkout.session.completed", {"id": "cs_1", "subscription": sub, "customer": customer}
    )
    _problem(_deliver(live, event, secret="whsec_wrong"), 400, "bad_request")
    _problem(_deliver(live, event, at=live.clock.now() - timedelta(minutes=10)), 400, "bad_request")
    unsigned = live.client.post(
        "/v1/billing/webhooks/stripe", content=b"{}", headers={"Content-Type": "application/json"}
    )
    _problem(unsigned, 400, "bad_request")
    assert _deliver(live, event).json() == {"status": "processed"}
    assert _deliver(live, event).json() == {"status": "duplicate"}
    assert _plan(live, token)["plan"] == "premium"

    fake.subscription(sub, customer, user_id, "past_due")
    _deliver(live, _event("customer.subscription.updated", {"id": sub}))
    grace = _plan(live, token)
    assert (grace["plan"], grace["status"]) == ("premium", "in_grace_period")

    fake.subscription(sub, customer, user_id, "canceled")
    _deliver(live, _event("customer.subscription.deleted", {"id": sub}))
    assert _plan(live, token)["plan"] == "free"

    fake.subscription(sub, customer, user_id, "active")
    _deliver(live, _event("customer.subscription.updated", {"id": sub}))
    assert _plan(live, token)["plan"] == "premium"
    refunded = _deliver(live, _event("charge.refunded", {"id": "ch_1", "customer": customer}))
    assert refunded.json() == {"status": "processed"}
    after = _plan(live, token)
    assert (after["plan"], after["status"]) == ("free", "revoked")
    assert _deliver(live, _event("invoice.created", {"id": "in_1"})).json() == {"status": "ignored"}


@pytest.mark.req("BILL-003")
def test_without_stripe_keys_web_payments_are_unavailable(store: LiveApp) -> None:  # noqa: F811
    token, _ = _user(store)
    _problem(
        store.client.post(
            "/v1/billing/checkout-sessions",
            headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
            json={"product_id": str(uuid.uuid4()), "success_path": "/a", "cancel_path": "/b"},
        ),
        503,
        "service_unavailable",
    )
    _problem(
        store.client.post(
            "/v1/billing/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"}
        ),
        503,
        "service_unavailable",
    )
