"""Web purchases through Stripe (BL-3.14, BL-3.15; ADR-0012, ADR-0031, BILL-002..012) against a
fake Stripe API."""

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
from app.modules.billing.domain import add_period
from app.modules.billing.stripe import DEFAULT_API_VERSION, sign
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import store  # noqa: F401
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import CRON, _problem, _tick, _user

pytestmark = pytest.mark.integration

PRICE = "price_premium_monthly"
PASS_PRICE = "price_premium_pass_month"
GUIDE_PRICE = "price_guide_lisbon"
GUIDE_KEY = "content:guide:lisbon-classic"
WEBHOOK_SECRET = "whsec_test_secret"
SITE = "https://web.example"

PRODUCTS = (
    # sku, kind, plan, period, entitlement, sort, title (en, pt-BR)
    (PRICE, "auto_renewable", "premium", "P1M", "premium", 20, ("Monthly", "Mensal")),
    (PASS_PRICE, "non_renewing", "premium", "P1M", "premium", 10, ("Month pass", "Passe de 1 mês")),
    (GUIDE_PRICE, "non_consumable", None, None, GUIDE_KEY, 30, ("Lisbon guide", "Guia de Lisboa")),
)
AMOUNTS = {PRICE: 990, PASS_PRICE: 1490, GUIDE_PRICE: 1990}


class FakeStripe:
    """The parts of the Stripe API the adapter uses, with objects the tests shape."""

    def __init__(self) -> None:
        self.customers = 0
        self.last_customer = ""
        self.checkouts: list[dict[str, list[str]]] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.invoices: dict[str, dict[str, Any]] = {}
        self.charges: dict[str, dict[str, Any]] = {}
        self.disputes: dict[str, dict[str, Any]] = {}
        self.cancelled: list[str] = []
        self.refunds: list[dict[str, list[str]]] = []
        self.versions: set[str] = set()
        self.price_reads = 0
        # Ids differ per test: the test database outlives one test, as Stripe's ids would.
        self.run = uuid.uuid4().hex[:8]
        self.counter = 0

    def new_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.run}_{self.counter}"

    @property
    def last_session(self) -> str:
        return f"cs_{self.run}_{len(self.checkouts)}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk_test_123"
        self.versions.add(request.headers.get("stripe-version", ""))
        path, method = request.url.path, request.method
        form = parse_qs(request.content.decode()) if request.content else {}
        tail = path.rsplit("/", 1)[-1]
        if path == "/v1/customers":
            self.customers += 1
            self.last_customer = f"cus_{uuid.uuid4().hex[:12]}"
            return httpx.Response(200, json={"id": self.last_customer})
        if path == "/v1/checkout/sessions" and method == "POST":
            self.checkouts.append(form)
            session_id = self.last_session
            price = form["line_items[0][price]"][0]
            self.sessions[session_id] = {
                "id": session_id,
                "object": "checkout.session",
                "url": f"https://checkout.stripe.com/c/pay/{session_id}",
                "mode": form["mode"][0],
                "status": "open",
                "payment_status": "unpaid",
                "customer": form["customer"][0],
                "subscription": None,
                "payment_intent": None,
                "client_reference_id": form["client_reference_id"][0],
                "metadata": {"user_id": form["metadata[user_id]"][0]},
                "line_items": {"data": [{"price": {"id": price}}]},
                "amount_total": AMOUNTS.get(price, 0),
                "currency": "brl",
                "livemode": False,
                "created": int(datetime.now(tz=UTC).timestamp()),
                "expires_at": int(form["expires_at"][0]),
            }
            return httpx.Response(200, json=self.sessions[session_id])
        if path.startswith("/v1/checkout/sessions/"):
            return self._found(self.sessions.get(tail))
        if path.startswith("/v1/subscriptions/") and method == "DELETE":
            self.cancelled.append(tail)
            if tail in self.subscriptions:
                self.subscriptions[tail]["status"] = "canceled"
            return self._found(self.subscriptions.get(tail))
        if path.startswith("/v1/subscriptions/"):
            return self._found(self.subscriptions.get(tail))
        if path.startswith("/v1/invoices/"):
            return self._found(self.invoices.get(tail))
        if path.startswith("/v1/charges/"):
            return self._found(self.charges.get(tail))
        if path.startswith("/v1/disputes/"):
            return self._found(self.disputes.get(tail))
        if path.startswith("/v1/prices/"):
            self.price_reads += 1
            if tail not in AMOUNTS:
                return httpx.Response(404, json={})
            recurring = {"interval": "month"} if tail == PRICE else None
            return httpx.Response(
                200,
                json={
                    "id": tail,
                    "unit_amount": AMOUNTS[tail],
                    "currency": "brl",
                    "recurring": recurring,
                },
            )
        if path == "/v1/refunds":
            self.refunds.append(form)
            return httpx.Response(200, json={"id": f"re_{len(self.refunds)}"})
        if path == "/v1/billing_portal/sessions":
            return httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/abc"})
        return httpx.Response(404, json={})

    @staticmethod
    def _found(found: dict[str, Any] | None) -> httpx.Response:
        return httpx.Response(200, json=found) if found else httpx.Response(404, json={})

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

    def complete(
        self, session_id: str, *, paid: bool = True, subscription: str | None = None
    ) -> dict[str, Any]:
        session = self.sessions[session_id]
        session["status"] = "complete"
        session["payment_status"] = "paid" if paid else "unpaid"
        session["subscription"] = subscription
        if session["mode"] == "payment":
            session["payment_intent"] = f"pi_{session_id}"
        return session

    def invoice(
        self,
        invoice_id: str,
        customer: str,
        subscription: str,
        *,
        paid: bool,
        amount: int = 990,
        reason: str = "subscription_cycle",
    ) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        self.invoices[invoice_id] = {
            "id": invoice_id,
            "customer": customer,
            "subscription": subscription,
            "status": "paid" if paid else "open",
            "amount_paid": amount if paid else 0,
            "amount_due": amount,
            "currency": "brl",
            "billing_reason": reason,
            "hosted_invoice_url": f"https://invoice.stripe.com/i/{invoice_id}",
            "payment_intent": f"pi_{invoice_id}",
            "status_transitions": {"paid_at": now if paid else None},
            "created": now,
            "livemode": False,
        }

    def charge(
        self,
        charge_id: str,
        customer: str,
        *,
        amount: int,
        refunded: int,
        invoice: str | None = None,
        payment_intent: str | None = None,
    ) -> None:
        self.charges[charge_id] = {
            "id": charge_id,
            "customer": customer,
            "amount": amount,
            "amount_refunded": refunded,
            "currency": "brl",
            "invoice": invoice,
            "payment_intent": payment_intent,
            "receipt_url": f"https://pay.stripe.com/receipts/{charge_id}",
            "created": int(datetime.now(tz=UTC).timestamp()),
            "livemode": False,
        }


@pytest.fixture
def web(catalog: str) -> Iterator[tuple[LiveApp, FakeStripe]]:  # noqa: F811
    async def ok() -> bool:
        return True

    for sku, kind, plan, period, key, order, (en, pt) in PRODUCTS:
        plan_sql = f"'{plan}'" if plan else "NULL"
        period_sql = f"'{period}'" if period else "NULL"
        title = json.dumps({"en": en, "pt-BR": pt}, ensure_ascii=True)
        db_scalar(
            catalog,
            "INSERT INTO products (id, sku, platform, kind, plan_key, period, entitlement_keys, "  # noqa: S608
            "title, sort_order) VALUES "
            f"(gen_random_uuid(), '{sku}', 'web', '{kind}', {plan_sql}, {period_sql}, "
            f"ARRAY['{key}'], '{title}'::jsonb, {order}) "
            "ON CONFLICT (platform, sku) DO NOTHING RETURNING 1",
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


def _product_id(live: LiveApp, sku: str = PRICE) -> str:
    products = live.client.get("/v1/billing/products", params={"platform": "web"}).json()["data"]
    [product] = [p for p in products if p["sku"] == sku]
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


def _event(kind: str, obj: dict[str, Any], *, livemode: bool = False) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": kind,
        "created": 1_800_000_000,
        "livemode": livemode,
        "data": {"object": obj},
    }


def _status(live: LiveApp, kind: str, obj_id: str) -> str:
    response = _deliver(live, _event(kind, {"id": obj_id}))
    assert response.status_code == 200, response.text
    return str(response.json()["status"])


def _plan(live: LiveApp, token: str) -> dict[str, Any]:
    body: dict[str, Any] = live.client.get("/v1/billing/entitlements", headers=_auth(token)).json()
    return body


def _history(live: LiveApp, token: str, **params: Any) -> dict[str, Any]:
    response = live.client.get(
        "/v1/billing/transactions",
        headers={**_auth(token), "Accept-Language": "pt-BR"},
        params=params,
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body: dict[str, Any] = response.json()
    assert_matches_contract(body, "BillingTransactionPage")
    return body


def _notices(live: LiveApp, token: str) -> list[str]:
    _tick(live)
    _tick(live)
    rows = live.client.get(
        "/v1/notifications", headers={**_auth(token), "Accept-Language": "en"}
    ).json()["data"]
    return [str(n["body"]) for n in rows if n["type"] == "subscription_notice"]


def _content_grant(live: LiveApp, user_id: str) -> str:
    return str(
        db_scalar(
            live.db_url,
            "SELECT CASE WHEN revoked_at IS NULL THEN 'active' ELSE 'revoked' END "  # noqa: S608
            f"FROM subscription_entitlements WHERE user_id = '{user_id}' "
            f"AND entitlement_key = '{GUIDE_KEY}'",
        )
    )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.req("BILL-002", "BILL-003", "BILL-006")
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
    assert form["metadata[product_id]"] == [product]
    assert fake.versions == {DEFAULT_API_VERSION}  # every call pins the API shape
    assert _plan(live, token)["plan"] == "free"  # returning from Checkout grants nothing

    # A second tab or a retry gets the same open session: never a second payment.
    again = _checkout(live, token, product)
    assert again.status_code == 201
    assert again.json()["url"] == started.json()["url"]
    assert len(fake.checkouts) == 1
    assert fake.customers == 1  # one Stripe customer per user
    rejected = _checkout(live, token, product, success_path="https://evil.example/steal")
    assert rejected.status_code == 422  # absolute URLs never reach Stripe (no open redirect)

    fake.subscription("sub_1", fake.last_customer, user_id, "active")
    assert _status(live, "customer.subscription.created", "sub_1") == "processed"
    premium = _plan(live, token)
    assert premium["plan"] == "premium"
    assert premium["active_subscription"]["management"] == "stripe_portal"
    _problem(_checkout(live, token, product), 409, "conflict")  # never charged twice
    _problem(_checkout(live, token, _product_id(live, PASS_PRICE)), 409, "conflict")

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
    fake.complete(fake.last_session, subscription=sub)

    event = _event("checkout.session.completed", {"id": fake.last_session})
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
    _status(live, "customer.subscription.updated", sub)
    grace = _plan(live, token)
    assert (grace["plan"], grace["status"]) == ("premium", "in_grace_period")

    fake.subscription(sub, customer, user_id, "canceled")
    _status(live, "customer.subscription.deleted", sub)
    assert _plan(live, token)["plan"] == "free"

    fake.subscription(sub, customer, user_id, "active")
    _status(live, "customer.subscription.updated", sub)
    assert _plan(live, token)["plan"] == "premium"
    invoice, charge = fake.new_id("in"), fake.new_id("ch")
    fake.invoice(invoice, customer, sub, paid=True)
    fake.charge(charge, customer, amount=990, refunded=990, invoice=invoice)
    assert _status(live, "charge.refunded", charge) == "processed"
    after = _plan(live, token)
    assert (after["plan"], after["status"]) == ("free", "revoked")
    refund = [t for t in _history(live, token)["data"] if t["kind"] == "refund"]
    assert [(r["amount_minor"], r["currency"], r["reason"]) for r in refund] == [
        (990, "BRL", "refund")
    ]
    assert _status(live, "invoice.created", invoice) == "ignored"


@pytest.mark.req("BILL-010")
def test_offers_come_in_order_with_titles_and_web_prices(
    web: tuple[LiveApp, FakeStripe],
) -> None:
    live, fake = web
    response = live.client.get(
        "/v1/billing/products", params={"platform": "web"}, headers={"Accept-Language": "pt-BR"}
    )
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "ProductList")
    offers = {p["sku"]: p for p in response.json()["data"]}
    ours = [p["sku"] for p in response.json()["data"] if p["sku"] in AMOUNTS]
    assert ours == [PASS_PRICE, PRICE, GUIDE_PRICE]  # sort_order
    assert offers[PASS_PRICE]["kind"] == "non_renewing"
    assert offers[PASS_PRICE]["period"] == "P1M"
    assert offers[PASS_PRICE]["title"] == "Passe de 1 mês"
    assert offers[PRICE]["price"] == {"amount_minor": 990, "currency": "BRL", "recurring": True}
    assert offers[PASS_PRICE]["price"] == {
        "amount_minor": 1490,
        "currency": "BRL",
        "recurring": False,
    }
    reads = fake.price_reads
    live.client.get("/v1/billing/products", params={"platform": "web"})
    assert fake.price_reads == reads  # prices are cached for a few minutes
    english = live.client.get("/v1/billing/products", params={"platform": "web"}).json()["data"]
    assert {p["sku"]: p["title"] for p in english}[PASS_PRICE] == "Month pass"


@pytest.mark.req("BILL-010", "BILL-011")
def test_passes_wait_for_the_money_and_stack(web: tuple[LiveApp, FakeStripe]) -> None:
    live, fake = web
    token, _ = _user(live)
    other, _ = _user(live)
    pass_id = _product_id(live, PASS_PRICE)
    assert _checkout(live, token, pass_id).status_code == 201
    first = fake.last_session
    assert fake.checkouts[-1]["mode"] == ["payment"]

    # Pix or boleto: the session completes before the money arrives.
    fake.complete(first, paid=False)
    assert _status(live, "checkout.session.completed", first) == "processed"
    assert _plan(live, token)["plan"] == "free"
    [pending] = _history(live, token)["data"]
    assert (pending["status"], pending["amount_minor"]) == ("pending", 1490)

    fake.complete(first, paid=True)
    paid_at = live.clock.now()
    assert _status(live, "checkout.session.async_payment_succeeded", first) == "processed"
    premium = _plan(live, token)
    assert premium["plan"] == "premium"
    assert _parse(premium["premium_until"]) == add_period(paid_at, "P1M")
    assert any("payment went through" in body for body in _notices(live, token))

    # A second pass starts when the first one ends.
    assert _checkout(live, token, pass_id).status_code == 201
    second = fake.last_session
    fake.complete(second, paid=True)
    assert _status(live, "checkout.session.completed", second) == "processed"
    extended = _plan(live, token)
    assert _parse(extended["premium_until"]) == add_period(add_period(paid_at, "P1M"), "P1M")
    history = _history(live, token)["data"]
    assert [t["status"] for t in history] == ["succeeded", "succeeded"]
    assert history[0]["product"]["title"] == "Passe de 1 mês"
    assert _history(live, other)["data"] == []  # only my own payments

    # A payment that never arrives tells the traveller.
    assert _checkout(live, token, _product_id(live, GUIDE_PRICE)).status_code == 201
    third = fake.last_session
    fake.complete(third, paid=False)
    assert _status(live, "checkout.session.async_payment_failed", third) == "processed"
    assert _history(live, token)["data"][0]["status"] == "failed"
    assert any("payment didn't go through" in body for body in _notices(live, token))

    # The history pages through, newest first.
    page = _history(live, token, limit=2)
    assert page["page"]["has_more"] is True
    rest = _history(live, token, limit=2, cursor=page["page"]["next_cursor"])
    assert len(rest["data"]) == 1
    assert rest["page"]["has_more"] is False


@pytest.mark.req("BILL-005", "BILL-008", "BILL-011")
def test_refunds_and_disputes_revoke_only_what_they_paid_for(
    web: tuple[LiveApp, FakeStripe],
) -> None:
    live, fake = web
    token, user_id = _user(live)
    assert _checkout(live, token, _product_id(live, GUIDE_PRICE)).status_code == 201
    guide = fake.last_session
    customer = fake.last_customer
    fake.complete(guide, paid=True)
    assert _status(live, "checkout.session.completed", guide) == "processed"
    assert _content_grant(live, user_id) == "active"
    _problem(_checkout(live, token, _product_id(live, GUIDE_PRICE)), 409, "conflict")

    charge = fake.new_id("ch")
    fake.charge(charge, customer, amount=1990, refunded=500, payment_intent=f"pi_{guide}")
    assert _status(live, "charge.refunded", charge) == "processed"
    assert _content_grant(live, user_id) == "active"  # a partial refund keeps the guide
    fake.charge(charge, customer, amount=1990, refunded=1990, payment_intent=f"pi_{guide}")
    assert _status(live, "charge.refunded", charge) == "processed"
    assert _content_grant(live, user_id) == "revoked"
    assert any("refunded" in body for body in _notices(live, token))

    # A chargeback: recorded while open, revokes the subscription when lost.
    sub = f"sub_{uuid.uuid4().hex[:8]}"
    fake.subscription(sub, customer, user_id, "active")
    assert _status(live, "customer.subscription.created", sub) == "processed"
    invoice, charge, dispute_id = fake.new_id("in"), fake.new_id("ch"), fake.new_id("dp")
    fake.invoice(invoice, customer, sub, paid=True, reason="subscription_create")
    fake.charge(charge, customer, amount=990, refunded=0, invoice=invoice)
    dispute = {"id": dispute_id, "charge": charge, "amount": 990, "currency": "brl"}
    fake.disputes[dispute_id] = {**dispute, "status": "needs_response", "reason": "fraudulent"}
    assert _status(live, "charge.dispute.created", dispute_id) == "processed"
    assert _plan(live, token)["plan"] == "premium"
    fake.disputes[dispute_id] = {**dispute, "status": "lost", "reason": "fraudulent"}
    assert _status(live, "charge.dispute.closed", dispute_id) == "processed"
    assert _plan(live, token)["status"] == "revoked"
    disputes = [t for t in _history(live, token)["data"] if t["kind"] == "dispute"]
    assert [(d["status"], d["reason"]) for d in disputes] == [("lost", "fraudulent")]


@pytest.mark.req("BILL-005", "BILL-011")
def test_invoices_fill_the_ledger_and_never_go_backwards(
    web: tuple[LiveApp, FakeStripe],
) -> None:
    live, fake = web
    token, user_id = _user(live)
    assert _checkout(live, token, _product_id(live)).status_code == 201
    customer = fake.last_customer
    sub = f"sub_{uuid.uuid4().hex[:8]}"
    fake.subscription(sub, customer, user_id, "past_due")
    invoice = fake.new_id("in")
    fake.invoice(invoice, customer, sub, paid=False)
    assert _status(live, "invoice.payment_failed", invoice) == "processed"
    [failed] = _history(live, token)["data"]
    assert (failed["status"], failed["reason"], failed["amount_minor"]) == (
        "failed",
        "renewal",
        990,
    )
    assert _plan(live, token)["status"] == "in_grace_period"
    assert any("payment didn't go through" in body for body in _notices(live, token))

    fake.subscription(sub, customer, user_id, "active")
    fake.invoice(invoice, customer, sub, paid=True)
    assert _status(live, "invoice.paid", invoice) == "processed"
    fake.invoice(invoice, customer, sub, paid=False)  # a late, out-of-order failure
    assert _status(live, "invoice.payment_failed", invoice) == "processed"
    [paid] = _history(live, token)["data"]
    assert paid["status"] == "succeeded"
    assert paid["receipt_url"] == f"https://invoice.stripe.com/i/{invoice}"
    assert _plan(live, token)["status"] == "active"


@pytest.mark.req("BILL-012")
@pytest.mark.security
def test_events_from_the_other_mode_are_ignored(web: tuple[LiveApp, FakeStripe]) -> None:
    live, fake = web
    token, user_id = _user(live)
    assert _checkout(live, token, _product_id(live)).status_code == 201
    sub = f"sub_{uuid.uuid4().hex[:8]}"
    fake.subscription(sub, fake.last_customer, user_id, "active")
    live_event = _event("customer.subscription.created", {"id": sub}, livemode=True)
    assert _deliver(live, live_event).json() == {"status": "ignored"}
    assert _plan(live, token)["plan"] == "free"
    error = db_scalar(
        live.db_url,
        f"SELECT error FROM billing_events WHERE provider_event_id = '{live_event['id']}'",  # noqa: S608
    )
    assert error == "wrong_mode"


@pytest.mark.req("BILL-006")
def test_a_second_web_subscription_is_cancelled_and_refunded(
    web: tuple[LiveApp, FakeStripe],
) -> None:
    live, fake = web
    token, user_id = _user(live)
    assert _checkout(live, token, _product_id(live)).status_code == 201
    customer = fake.last_customer
    first, second = f"sub_{uuid.uuid4().hex[:8]}", f"sub_{uuid.uuid4().hex[:8]}"
    fake.subscription(first, customer, user_id, "active")
    assert _status(live, "customer.subscription.created", first) == "processed"
    invoice = fake.new_id("in")
    fake.invoice(invoice, customer, second, paid=True, reason="subscription_create")
    fake.subscription(second, customer, user_id, "active", latest_invoice=invoice)
    assert _status(live, "customer.subscription.created", second) == "processed"
    assert fake.cancelled == [second]
    assert [(r["payment_intent"], r["reason"]) for r in fake.refunds] == [
        ([f"pi_{invoice}"], ["duplicate"])
    ]


@pytest.mark.req("BILL-006", "BILL-010")
def test_daily_jobs_reconcile_web_subscriptions_and_remind_before_premium_ends(
    web: tuple[LiveApp, FakeStripe],
) -> None:
    live, fake = web
    token, user_id = _user(live)
    assert _checkout(live, token, _product_id(live)).status_code == 201
    customer = fake.last_customer
    sub = f"sub_{uuid.uuid4().hex[:8]}"
    fake.subscription(sub, customer, user_id, "active")
    assert _status(live, "customer.subscription.created", sub) == "processed"
    fake.subscription(sub, customer, user_id, "canceled")  # the webhook never came

    reader, _ = _user(live)
    assert _checkout(live, reader, _product_id(live, PASS_PRICE)).status_code == 201
    pass_session = fake.last_session
    fake.complete(pass_session, paid=True)
    assert _status(live, "checkout.session.completed", pass_session) == "processed"
    ends = _parse(_plan(live, reader)["premium_until"])

    start = live.clock.now()
    live.clock.set(ends - timedelta(hours=60))
    for job in ("billing.stripe_reconcile", "billing.expiry_reminders"):
        for _ in range(2):  # the first tick schedules the task, the second runs it
            db_scalar(
                live.db_url,
                "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "  # noqa: S608
                f"WHERE name = '{job}' RETURNING 1",
            )
            _tick(live)
    live.clock.set(start)  # sign-in tokens follow the clock
    status = db_scalar(
        live.db_url,
        f"SELECT status FROM subscriptions WHERE original_transaction_id = '{sub}'",  # noqa: S608
    )
    assert status == "expired"  # re-read from Stripe without a webhook
    reminders = [body for body in _notices(live, reader) if "ends in a few days" in body]
    assert len(reminders) == 1
    open_sessions = db_scalar(
        live.db_url,
        "SELECT count(*) FROM billing_checkout_sessions "  # noqa: S608
        f"WHERE user_id = '{user_id}' AND status = 'open'",
    )
    assert open_sessions == 0  # expired when the hour ran out


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
