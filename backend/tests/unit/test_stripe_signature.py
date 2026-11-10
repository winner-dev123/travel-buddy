"""Stripe webhook signatures and state mapping (BL-3.14; ADR-0012)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.modules.billing.domain import SubscriptionStatus
from app.modules.billing.stripe import map_status, sign, verify_signature

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
SECRET = "whsec_unit"


def test_valid_signatures_pass_and_tampering_fails() -> None:
    body = b'{"id": "evt_1"}'
    verify_signature(body, sign(body, SECRET, at=NOW), SECRET, now=NOW)
    # Several v1 values (secret rotation): any match is enough.
    rotated = sign(body, "whsec_old", at=NOW) + "," + sign(body, SECRET, at=NOW).split(",")[1]
    verify_signature(body, rotated, SECRET, now=NOW)
    for header, payload in (
        (sign(body, SECRET, at=NOW), b'{"id": "evt_2"}'),  # body changed
        (sign(body, "whsec_other", at=NOW), body),  # wrong secret
        (sign(body, SECRET, at=NOW - timedelta(minutes=6)), body),  # outside tolerance
        ("v1=deadbeef", body),  # no timestamp
        (None, body),
    ):
        with pytest.raises(AppError):
            verify_signature(payload, header, SECRET, now=NOW)


@pytest.mark.parametrize(
    ("stripe", "ours"),
    [
        ("active", SubscriptionStatus.ACTIVE),
        ("trialing", SubscriptionStatus.ACTIVE),
        ("past_due", SubscriptionStatus.IN_GRACE_PERIOD),
        ("paused", SubscriptionStatus.PAUSED),
        ("canceled", SubscriptionStatus.EXPIRED),
        ("unpaid", SubscriptionStatus.EXPIRED),
        ("incomplete_expired", SubscriptionStatus.EXPIRED),
    ],
)
def test_status_mapping(stripe: str, ours: SubscriptionStatus) -> None:
    assert map_status(stripe) is ours
