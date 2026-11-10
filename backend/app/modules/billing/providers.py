"""Billing provider port (ADR-0017) and adapters.

``verify`` turns what the client sent into a normalized :class:`StoreTransaction` confirmed by the
provider; the client's word is never trusted (BILL-003). Apple and Google adapters need store
credentials (App Store Server API key, Play service account) and answer ``503`` until they are
configured. ``DevBillingProvider`` simulates the stores in development and tests only; settings
validation refuses it elsewhere (docs/07 §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.modules.billing.domain import SubscriptionStatus


@dataclass(frozen=True, slots=True)
class StoreTransaction:
    provider: str
    sku: str
    original_transaction_id: str
    transaction_id: str
    purchased_at: datetime
    status: SubscriptionStatus
    auto_renew: bool = True
    environment: str = "production"


@dataclass(frozen=True, slots=True)
class PurchaseClaim:
    """What the client sent, provider-neutral: an Apple JWS or a Google token + SKU."""

    store: str  # "apple" | "google"
    payload: str
    sku: str | None = None
    package_name: str | None = None


class BillingProvider(Protocol):
    def verify(self, claim: PurchaseClaim, *, now: datetime) -> StoreTransaction: ...


class UnconfiguredStore:
    """Apple/Google before their credentials exist: verification is impossible, so say so."""

    def __init__(self, store: str) -> None:
        self._store = store

    def verify(self, claim: PurchaseClaim, *, now: datetime) -> StoreTransaction:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            f"Purchases through {self._store} can't be verified yet. Try again later.",
            headers={"Retry-After": "3600"},
        )


class DevBillingProvider:
    """Development and tests only. Tokens look like ``dev:<sku>:<original transaction id>``
    (Apple ``signed_transaction`` or Google ``purchase_token``), optionally ``:<status>`` to start
    in another state; later store events are simulated through ``/v1/dev/billing/events``."""

    def verify(self, claim: PurchaseClaim, *, now: datetime) -> StoreTransaction:
        parts = claim.payload.split(":")
        if len(parts) < 3 or parts[0] != "dev" or not parts[1] or not parts[2]:
            raise AppError(ErrorCode.PURCHASE_INVALID, "This purchase couldn't be verified.")
        sku = claim.sku or parts[1]
        try:
            status = SubscriptionStatus(parts[3]) if len(parts) > 3 else SubscriptionStatus.ACTIVE
        except ValueError:
            raise AppError(ErrorCode.PURCHASE_INVALID, "Unknown simulated state.") from None
        return StoreTransaction(
            provider="dev",
            sku=sku,
            original_transaction_id=parts[2],
            transaction_id=f"{parts[2]}:{int(now.timestamp())}",
            purchased_at=now,
            status=status,
            environment="sandbox",
        )
