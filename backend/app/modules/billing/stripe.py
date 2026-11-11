"""Stripe adapter for web purchases (BL-3.14, BL-3.15; ADR-0012, ADR-0031, docs/07 §6).

- Checkout and the Customer Portal are hosted by Stripe; card data never reaches us (SAQ-A).
- Webhooks are verified with the endpoint secret (HMAC-SHA256 over ``"{t}.{raw body}"``, 5-minute
  tolerance) before anything is parsed. Only the event's id, type, mode and object id are read
  from the payload: the object itself is fetched from the API, pinned to ``api_version``, so the
  endpoint's own API version doesn't matter and stale or reordered events can't mislead us.
- A test key (``sk_test_``/``rk_test_``) only accepts test events and a live key only live ones.
- Without ``STRIPE_SECRET_KEY`` (and ``STRIPE_WEBHOOK_SECRET`` for webhooks) every call answers 503.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.errors import AppError, ErrorCode
from app.modules.billing.domain import SubscriptionStatus

TOLERANCE_SECONDS = 300
# Requests and responses use this shape whatever the account's default version is.
DEFAULT_API_VERSION = "2025-02-24.acacia"
PRICE_CACHE_SECONDS = 600
# Events that change entitlements or the ledger; everything else is stored as ignored. Subscribe
# the webhook endpoint to exactly these (docs/07 §6).
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
        "checkout.session.expired",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
        "invoice.paid",
        "invoice.payment_failed",
        "charge.refunded",
        "charge.dispute.created",
        "charge.dispute.closed",
    }
)


def _unavailable() -> AppError:
    return AppError(
        ErrorCode.SERVICE_UNAVAILABLE,
        "Web payments aren't available yet.",
        headers={"Retry-After": "3600"},
    )


def verify_signature(payload: bytes, header: str | None, secret: str, *, now: datetime) -> None:
    """Raise ``400 bad_request`` unless ``Stripe-Signature`` is valid and fresh."""
    if not header:
        raise AppError(ErrorCode.BAD_REQUEST, "Missing signature.")
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError, IndexError):
        raise AppError(ErrorCode.BAD_REQUEST, "Malformed signature.") from None
    if abs(now.timestamp() - timestamp) > TOLERANCE_SECONDS:
        raise AppError(ErrorCode.BAD_REQUEST, "Stale signature.")
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, given) for given in parts.get("v1", [])):
        raise AppError(ErrorCode.BAD_REQUEST, "Invalid signature.")


def sign(payload: bytes, secret: str, *, at: datetime) -> str:
    """A valid ``Stripe-Signature`` (tests and local tooling)."""
    timestamp = int(at.timestamp())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


def key_livemode(key: str | None) -> bool | None:
    """True for a live key, False for a test key, None when the key is missing or unrecognised."""
    if not key:
        return None
    if key.startswith(("sk_live_", "rk_live_")):
        return True
    if key.startswith(("sk_test_", "rk_test_")):
        return False
    return None


def _ts(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def _opt_ts(value: Any) -> datetime | None:
    return _ts(value) if value else None


def _id(value: Any) -> str | None:
    """An object reference, expanded or not."""
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if value else None


def _currency(value: Any) -> str | None:
    return str(value).upper() if value else None


def _amount(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def map_status(status: str) -> SubscriptionStatus:
    """Stripe states onto docs/07 §4 (past_due keeps premium until Stripe's retries end)."""
    if status in ("active", "trialing"):
        return SubscriptionStatus.ACTIVE
    if status == "past_due":
        return SubscriptionStatus.IN_GRACE_PERIOD
    if status == "paused":
        return SubscriptionStatus.PAUSED
    return SubscriptionStatus.EXPIRED  # unpaid, canceled, incomplete, incomplete_expired


@dataclass(frozen=True, slots=True)
class StripeSubscription:
    id: str
    customer: str
    price_id: str
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime
    auto_renew: bool
    user_id: str | None
    livemode: bool
    latest_invoice: str | None = None


def parse_subscription(data: dict[str, Any]) -> StripeSubscription:
    item = (data.get("items") or {}).get("data") or [{}]
    first = item[0] if item else {}
    period_start = first.get("current_period_start", data.get("current_period_start"))
    period_end = first.get("current_period_end", data.get("current_period_end"))
    return StripeSubscription(
        id=str(data["id"]),
        customer=str(_id(data.get("customer"))),
        price_id=str((first.get("price") or {}).get("id", "")),
        status=map_status(str(data.get("status"))),
        current_period_start=_ts(period_start),
        current_period_end=_ts(period_end),
        auto_renew=not bool(data.get("cancel_at_period_end")),
        user_id=(data.get("metadata") or {}).get("user_id"),
        livemode=bool(data.get("livemode")),
        latest_invoice=_id(data.get("latest_invoice")),
    )


@dataclass(frozen=True, slots=True)
class StripeCheckout:
    id: str
    mode: str  # payment | subscription | setup
    status: str  # open | complete | expired
    payment_status: str  # paid | unpaid | no_payment_required
    customer: str | None
    subscription: str | None
    payment_intent: str | None
    price_id: str | None
    amount_total: int | None
    currency: str | None
    user_id: str | None
    livemode: bool
    created: datetime


def parse_checkout(data: dict[str, Any]) -> StripeCheckout:
    items = (data.get("line_items") or {}).get("data") or []
    price = _id((items[0] or {}).get("price")) if items else None
    return StripeCheckout(
        id=str(data["id"]),
        mode=str(data.get("mode") or ""),
        status=str(data.get("status") or ""),
        payment_status=str(data.get("payment_status") or ""),
        customer=_id(data.get("customer")),
        subscription=_id(data.get("subscription")),
        payment_intent=_id(data.get("payment_intent")),
        price_id=price or (data.get("metadata") or {}).get("price_id"),
        amount_total=_amount(data.get("amount_total")),
        currency=_currency(data.get("currency")),
        user_id=data.get("client_reference_id") or (data.get("metadata") or {}).get("user_id"),
        livemode=bool(data.get("livemode")),
        created=_ts(data.get("created") or time.time()),
    )


@dataclass(frozen=True, slots=True)
class StripeInvoice:
    id: str
    customer: str | None
    subscription: str | None
    status: str
    amount_paid: int | None
    amount_due: int | None
    currency: str | None
    billing_reason: str | None
    hosted_invoice_url: str | None
    payment_intent: str | None
    paid_at: datetime | None
    created: datetime
    livemode: bool


def parse_invoice(data: dict[str, Any]) -> StripeInvoice:
    parent = (data.get("parent") or {}).get("subscription_details") or {}
    transitions = data.get("status_transitions") or {}
    return StripeInvoice(
        id=str(data["id"]),
        customer=_id(data.get("customer")),
        subscription=_id(data.get("subscription")) or _id(parent.get("subscription")),
        status=str(data.get("status") or ""),
        amount_paid=_amount(data.get("amount_paid")),
        amount_due=_amount(data.get("amount_due")),
        currency=_currency(data.get("currency")),
        billing_reason=data.get("billing_reason"),
        hosted_invoice_url=data.get("hosted_invoice_url"),
        payment_intent=_id(data.get("payment_intent")),
        paid_at=_opt_ts(transitions.get("paid_at")),
        created=_ts(data.get("created") or time.time()),
        livemode=bool(data.get("livemode")),
    )


@dataclass(frozen=True, slots=True)
class StripeCharge:
    id: str
    customer: str | None
    amount: int
    amount_refunded: int
    currency: str | None
    invoice: str | None
    payment_intent: str | None
    receipt_url: str | None
    created: datetime
    livemode: bool

    @property
    def fully_refunded(self) -> bool:
        return self.amount_refunded >= self.amount > 0


def parse_charge(data: dict[str, Any]) -> StripeCharge:
    return StripeCharge(
        id=str(data["id"]),
        customer=_id(data.get("customer")),
        amount=_amount(data.get("amount")) or 0,
        amount_refunded=_amount(data.get("amount_refunded")) or 0,
        currency=_currency(data.get("currency")),
        invoice=_id(data.get("invoice")),
        payment_intent=_id(data.get("payment_intent")),
        receipt_url=data.get("receipt_url"),
        created=_ts(data.get("created") or time.time()),
        livemode=bool(data.get("livemode")),
    )


@dataclass(frozen=True, slots=True)
class StripeDispute:
    id: str
    charge: str | None
    amount: int | None
    currency: str | None
    status: str
    reason: str | None
    created: datetime
    livemode: bool

    @property
    def outcome(self) -> str:
        """``won``, ``lost`` or still ``open``."""
        return self.status if self.status in ("won", "lost") else "open"


def parse_dispute(data: dict[str, Any]) -> StripeDispute:
    return StripeDispute(
        id=str(data["id"]),
        charge=_id(data.get("charge")),
        amount=_amount(data.get("amount")),
        currency=_currency(data.get("currency")),
        status=str(data.get("status") or ""),
        reason=data.get("reason"),
        created=_ts(data.get("created") or time.time()),
        livemode=bool(data.get("livemode")),
    )


@dataclass(frozen=True, slots=True)
class StripePrice:
    id: str
    unit_amount: int | None
    currency: str | None
    recurring: bool


@dataclass(frozen=True, slots=True)
class CheckoutStart:
    id: str
    url: str
    expires_at: datetime | None


class StripeClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        secret_key: str | None,
        webhook_secret: str | None,
        api_base: str = "https://api.stripe.com",
        api_version: str = DEFAULT_API_VERSION,
        portal_configuration: str | None = None,
    ) -> None:
        self._http = http
        self._portal_configuration = portal_configuration
        self._key = secret_key
        self.webhook_secret = webhook_secret
        self._base = api_base.rstrip("/")
        self._version = api_version
        self._prices: dict[str, tuple[float, StripePrice | None]] = {}

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def expected_livemode(self) -> bool | None:
        """Events from the other mode are refused (a test event never grants in production)."""
        return key_livemode(self._key)

    async def call(
        self,
        method: str,
        path: str,
        form: dict[str, str] | None = None,
        *,
        params: list[tuple[str, str | int | float | bool | None]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Any Stripe API call with the pinned version (operator tooling, e.g. stripe_setup)."""
        return await self._call(method, path, form, params=params, idempotency_key=idempotency_key)

    async def _call(
        self,
        method: str,
        path: str,
        form: dict[str, str] | None = None,
        *,
        params: list[tuple[str, str | int | float | bool | None]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self._key:
            raise _unavailable()
        headers = {"Authorization": f"Bearer {self._key}", "Stripe-Version": self._version}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = await self._http.request(
                method,
                f"{self._base}{path}",
                data=form,
                params=params,
                headers=headers,
                timeout=15.0,
            )
        except httpx.HTTPError:
            raise _unavailable() from None
        if response.status_code >= 500 or response.status_code == 429:
            raise _unavailable()
        if response.status_code >= 400:
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE, "The payment provider refused the request."
            )
        body: dict[str, Any] = response.json()
        return body

    async def create_customer(self, *, user_id: str, idempotency_key: str) -> str:
        customer = await self._call(
            "POST",
            "/v1/customers",
            {"metadata[user_id]": user_id},
            idempotency_key=idempotency_key,
        )
        return str(customer["id"])

    async def create_checkout_session(
        self,
        *,
        customer: str,
        price_id: str,
        mode: str,
        user_id: str,
        product_id: str,
        success_url: str,
        cancel_url: str,
        expires_at: datetime,
        idempotency_key: str,
    ) -> CheckoutStart:
        form = {
            "mode": mode,
            "customer": customer,
            "client_reference_id": user_id,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "expires_at": str(int(expires_at.timestamp())),
            "metadata[user_id]": user_id,
            "metadata[product_id]": product_id,
            "metadata[price_id]": price_id,
        }
        if mode == "subscription":
            form["subscription_data[metadata][user_id]"] = user_id
        else:
            form["payment_intent_data[metadata][user_id]"] = user_id
        session = await self._call(
            "POST", "/v1/checkout/sessions", form, idempotency_key=idempotency_key
        )
        return CheckoutStart(
            id=str(session["id"]),
            url=str(session["url"]),
            expires_at=_opt_ts(session.get("expires_at")),
        )

    async def create_portal_session(self, *, customer: str, return_url: str) -> str:
        form = {"customer": customer, "return_url": return_url}
        if self._portal_configuration:
            form["configuration"] = self._portal_configuration
        session = await self._call("POST", "/v1/billing_portal/sessions", form)
        return str(session["url"])

    async def get_subscription(self, subscription_id: str) -> StripeSubscription:
        return parse_subscription(await self._call("GET", f"/v1/subscriptions/{subscription_id}"))

    async def get_checkout_session(self, session_id: str) -> StripeCheckout:
        data = await self._call(
            "GET", f"/v1/checkout/sessions/{session_id}", params=[("expand[]", "line_items")]
        )
        return parse_checkout(data)

    async def get_invoice(self, invoice_id: str) -> StripeInvoice:
        return parse_invoice(await self._call("GET", f"/v1/invoices/{invoice_id}"))

    async def get_charge(self, charge_id: str) -> StripeCharge:
        return parse_charge(await self._call("GET", f"/v1/charges/{charge_id}"))

    async def get_dispute(self, dispute_id: str) -> StripeDispute:
        return parse_dispute(await self._call("GET", f"/v1/disputes/{dispute_id}"))

    async def cancel_subscription(self, subscription_id: str, *, idempotency_key: str) -> None:
        await self._call(
            "DELETE", f"/v1/subscriptions/{subscription_id}", idempotency_key=idempotency_key
        )

    async def refund(self, payment_intent: str, *, reason: str, idempotency_key: str) -> None:
        await self._call(
            "POST",
            "/v1/refunds",
            {"payment_intent": payment_intent, "reason": reason},
            idempotency_key=idempotency_key,
        )

    async def price(self, price_id: str) -> StripePrice | None:
        """A price for display, cached for a few minutes; None when Stripe can't say."""
        cached = self._prices.get(price_id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        try:
            data = await self._call("GET", f"/v1/prices/{price_id}")
            found: StripePrice | None = StripePrice(
                id=str(data["id"]),
                unit_amount=_amount(data.get("unit_amount")),
                currency=_currency(data.get("currency")),
                recurring=bool(data.get("recurring")),
            )
        except AppError:
            found = None
        self._prices[price_id] = (time.monotonic() + PRICE_CACHE_SECONDS, found)
        return found
