"""Stripe adapter for web purchases (BL-3.14; ADR-0012, docs/07 §6).

- Checkout and the Customer Portal are hosted by Stripe; card data never reaches us (SAQ-A).
- Webhooks are verified with the endpoint secret (HMAC-SHA256 over ``"{t}.{raw body}"``, 5-minute
  tolerance) before anything is parsed. Processing re-fetches the subscription from the API, since
  Stripe doesn't guarantee event order.
- Without ``STRIPE_SECRET_KEY`` (and ``STRIPE_WEBHOOK_SECRET`` for webhooks) every call answers 503.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.errors import AppError, ErrorCode
from app.modules.billing.domain import SubscriptionStatus

TOLERANCE_SECONDS = 300
# Event types that change entitlements; everything else is stored as ignored.
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
        "charge.refunded",
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


def _ts(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def map_status(status: str) -> SubscriptionStatus:
    """Stripe states onto docs/07 §4 (past_due keeps premium until Stripe's retries end)."""
    if status in ("active", "trialing"):
        return SubscriptionStatus.ACTIVE
    if status == "past_due":
        return SubscriptionStatus.IN_GRACE_PERIOD
    if status == "paused":
        return SubscriptionStatus.PAUSED
    return SubscriptionStatus.EXPIRED  # unpaid, canceled, incomplete, incomplete_expired


def parse_subscription(data: dict[str, Any]) -> StripeSubscription:
    item = (data.get("items") or {}).get("data") or [{}]
    first = item[0] if item else {}
    period_start = first.get("current_period_start", data.get("current_period_start"))
    period_end = first.get("current_period_end", data.get("current_period_end"))
    return StripeSubscription(
        id=str(data["id"]),
        customer=str(data.get("customer")),
        price_id=str((first.get("price") or {}).get("id", "")),
        status=map_status(str(data.get("status"))),
        current_period_start=_ts(period_start),
        current_period_end=_ts(period_end),
        auto_renew=not bool(data.get("cancel_at_period_end")),
        user_id=(data.get("metadata") or {}).get("user_id"),
        livemode=bool(data.get("livemode")),
    )


class StripeClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        secret_key: str | None,
        webhook_secret: str | None,
        api_base: str = "https://api.stripe.com",
    ) -> None:
        self._http = http
        self._key = secret_key
        self.webhook_secret = webhook_secret
        self._base = api_base.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def _call(
        self,
        method: str,
        path: str,
        form: dict[str, str] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self._key:
            raise _unavailable()
        headers = {"Authorization": f"Bearer {self._key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = await self._http.request(
            method, f"{self._base}{path}", data=form, headers=headers, timeout=15.0
        )
        if response.status_code >= 500:
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
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> tuple[str, datetime | None]:
        form = {
            "mode": mode,
            "customer": customer,
            "client_reference_id": user_id,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata[user_id]": user_id,
        }
        if mode == "subscription":
            form["subscription_data[metadata][user_id]"] = user_id
        session = await self._call(
            "POST", "/v1/checkout/sessions", form, idempotency_key=idempotency_key
        )
        expires = session.get("expires_at")
        return str(session["url"]), (_ts(expires) if expires else None)

    async def create_portal_session(self, *, customer: str, return_url: str) -> str:
        session = await self._call(
            "POST", "/v1/billing_portal/sessions", {"customer": customer, "return_url": return_url}
        )
        return str(session["url"])

    async def get_subscription(self, subscription_id: str) -> StripeSubscription:
        return parse_subscription(await self._call("GET", f"/v1/subscriptions/{subscription_id}"))
