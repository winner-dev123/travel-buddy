"""Subscription lifecycle (pure; docs/07 §4): normalized states and the grant each state yields.

Each transition rewrites the subscription's grant in the same transaction. A grant is active at
``t`` iff ``starts_at ≤ t < ends_at`` (no end = open) and it is not revoked by ``t``, so expiry
needs no job and past instants stay auditable.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    IN_GRACE_PERIOD = "in_grace_period"
    IN_BILLING_RETRY = "in_billing_retry"
    PAUSED = "paused"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ProviderName(StrEnum):
    APPLE = "apple"
    GOOGLE = "google"
    STRIPE = "stripe"
    DEV = "dev"


class ProductKind(StrEnum):
    AUTO_RENEWABLE = "auto_renewable"
    # A pass: paid once, Premium for a fixed period, never renews (BILL-010).
    NON_RENEWING = "non_renewing"
    NON_CONSUMABLE = "non_consumable"


class StoreEvent(StrEnum):
    """Normalized store notifications (Apple, Google, Stripe and dev map onto these)."""

    RENEWED = "renewed"
    GRACE = "grace"
    BILLING_RETRY = "billing_retry"
    RECOVERED = "recovered"
    PAUSED = "paused"
    RESUMED = "resumed"
    AUTO_RENEW_OFF = "auto_renew_off"
    AUTO_RENEW_ON = "auto_renew_on"
    EXPIRED = "expired"
    REFUNDED = "refunded"


PERIODS = {"P1M": timedelta(days=30), "P1Y": timedelta(days=365)}
GRACE = timedelta(days=16)  # the stores' maximum billing grace

# ISO 8601 periods a product may have: a count of days, weeks, months or years (BILL-010).
PERIOD_PATTERN = r"^P[1-9][0-9]{0,2}[DWMY]$"
_PERIOD = re.compile(PERIOD_PATTERN)
_APPROX_DAYS = {"D": 1, "W": 7, "M": 30, "Y": 365}


def _split(period: str) -> tuple[int, str]:
    if not _PERIOD.fullmatch(period):
        raise ValueError(f"not a supported period: {period!r}")
    return int(period[1:-1]), period[-1]


def period_length(period: str | None) -> timedelta:
    """A fixed length for a period (a month is 30 days, a year 365). Only a fallback for store
    subscriptions until the store reports its own period end."""
    count, unit = _split(period or "P1M")
    return timedelta(days=count * _APPROX_DAYS[unit])


def add_period(start: datetime, period: str) -> datetime:
    """``start`` plus a period on the calendar: "P1M" from 31 January is 28 or 29 February, and
    "P1Y" from 29 February is 28 February. Passes end exactly when the traveller expects."""
    count, unit = _split(period)
    if unit == "D":
        return start + timedelta(days=count)
    if unit == "W":
        return start + timedelta(weeks=count)
    months = count if unit == "M" else count * 12
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


# Store-side events allowed from each state (anything else is recorded and ignored).
_TRANSITIONS: dict[StoreEvent, dict[SubscriptionStatus, SubscriptionStatus]] = {
    StoreEvent.RENEWED: dict.fromkeys(SubscriptionStatus, SubscriptionStatus.ACTIVE),
    StoreEvent.RECOVERED: {
        SubscriptionStatus.IN_GRACE_PERIOD: SubscriptionStatus.ACTIVE,
        SubscriptionStatus.IN_BILLING_RETRY: SubscriptionStatus.ACTIVE,
    },
    StoreEvent.GRACE: {SubscriptionStatus.ACTIVE: SubscriptionStatus.IN_GRACE_PERIOD},
    StoreEvent.BILLING_RETRY: {
        SubscriptionStatus.ACTIVE: SubscriptionStatus.IN_BILLING_RETRY,
        SubscriptionStatus.IN_GRACE_PERIOD: SubscriptionStatus.IN_BILLING_RETRY,
    },
    StoreEvent.PAUSED: {SubscriptionStatus.ACTIVE: SubscriptionStatus.PAUSED},
    StoreEvent.RESUMED: {SubscriptionStatus.PAUSED: SubscriptionStatus.ACTIVE},
    StoreEvent.EXPIRED: {
        SubscriptionStatus.ACTIVE: SubscriptionStatus.EXPIRED,
        SubscriptionStatus.IN_GRACE_PERIOD: SubscriptionStatus.EXPIRED,
        SubscriptionStatus.IN_BILLING_RETRY: SubscriptionStatus.EXPIRED,
        SubscriptionStatus.PAUSED: SubscriptionStatus.EXPIRED,
    },
    StoreEvent.REFUNDED: {
        SubscriptionStatus.ACTIVE: SubscriptionStatus.REVOKED,
        SubscriptionStatus.IN_GRACE_PERIOD: SubscriptionStatus.REVOKED,
        SubscriptionStatus.IN_BILLING_RETRY: SubscriptionStatus.REVOKED,
        SubscriptionStatus.PAUSED: SubscriptionStatus.REVOKED,
        SubscriptionStatus.EXPIRED: SubscriptionStatus.REVOKED,
    },
}


def next_status(current: SubscriptionStatus, event: StoreEvent) -> SubscriptionStatus | None:
    """The state after ``event``; None when the event doesn't apply (it is recorded as ignored).
    Auto-renew changes keep the state."""
    if event in (StoreEvent.AUTO_RENEW_OFF, StoreEvent.AUTO_RENEW_ON):
        return current
    return _TRANSITIONS[event].get(current)


@dataclass(frozen=True, slots=True)
class GrantWindow:
    ends_at: datetime | None
    revoked_at: datetime | None


def grant_window(
    status: SubscriptionStatus,
    *,
    starts_at: datetime,
    current_period_end: datetime | None,
    grace_period_ends_at: datetime | None,
    now: datetime,
) -> GrantWindow:
    """The materialized grant for a subscription in ``status`` (docs/07 §4 table)."""
    if status is SubscriptionStatus.ACTIVE:
        return GrantWindow(ends_at=current_period_end, revoked_at=None)
    if status is SubscriptionStatus.IN_GRACE_PERIOD:
        return GrantWindow(ends_at=grace_period_ends_at or current_period_end, revoked_at=None)
    if status is SubscriptionStatus.REVOKED:
        return GrantWindow(ends_at=current_period_end, revoked_at=now)
    # in_billing_retry, paused, expired: premium stopped (at the period end or now).
    end = min(current_period_end, now) if current_period_end else now
    return GrantWindow(ends_at=max(end, starts_at + timedelta(seconds=1)), revoked_at=None)


def management(provider: str) -> str:
    """Where a subscription is managed (``Entitlements.active_subscription.management``)."""
    return {"google": "google_play", "stripe": "stripe_portal"}.get(provider, "app_store")
