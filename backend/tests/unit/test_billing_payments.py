"""Payments phase 1 (BL-3.15; ADR-0031): periods, passes, Stripe modes and object parsing, offer
validation and the traveller's plan notices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import AppEnv
from app.modules.billing.domain import add_period, period_length
from app.modules.billing.entitlements import Grant, GrantSource, evaluate
from app.modules.billing.schemas import CreateProductRequest, UpdateProductRequest
from app.modules.billing.stripe import (
    key_livemode,
    parse_charge,
    parse_checkout,
    parse_dispute,
    parse_invoice,
)
from app.modules.notifications.domain import render
from tests.conftest import ed25519_test_pem, make_settings

T0 = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


@pytest.mark.req("BILL-010")
def test_periods_follow_the_calendar() -> None:
    assert add_period(T0, "P1M") == datetime(2026, 2, 28, 12, 0, tzinfo=UTC)
    assert add_period(datetime(2028, 1, 31, tzinfo=UTC), "P1M") == datetime(2028, 2, 29, tzinfo=UTC)
    assert add_period(datetime(2028, 2, 29, tzinfo=UTC), "P1Y") == datetime(2029, 2, 28, tzinfo=UTC)
    assert add_period(T0, "P3M") == datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    assert add_period(T0, "P14M") == datetime(2027, 3, 31, 12, 0, tzinfo=UTC)
    assert add_period(T0, "P7D") == T0 + timedelta(days=7)
    assert add_period(T0, "P2W") == T0 + timedelta(weeks=2)
    for bad in ("P0M", "P1H", "1M", "P1000D", "", "PT1M"):
        with pytest.raises(ValueError, match="period"):
            add_period(T0, bad)


def test_store_fallback_lengths_stay_as_before() -> None:
    assert period_length("P1M") == timedelta(days=30)
    assert period_length("P1Y") == timedelta(days=365)
    assert period_length(None) == timedelta(days=30)
    assert period_length("P3M") == timedelta(days=90)


def _premium(start: datetime, end: datetime | None, *, revoked: datetime | None = None) -> Grant:
    return Grant(
        entitlement_key="premium",
        source_type=GrantSource.PURCHASE,
        starts_at=start,
        ends_at=end,
        revoked_at=revoked,
    )


@pytest.mark.req("BILL-010")
def test_premium_until_runs_through_stacked_passes() -> None:
    first_end = add_period(T0, "P1M")
    second_end = add_period(first_end, "P1M")
    stacked = [_premium(T0, first_end), _premium(first_end, second_end)]
    assert evaluate(stacked, at=T0 + timedelta(days=1)).premium_until == second_end
    # A gap ends the run; a revoked follower doesn't count; an open-ended one means no end.
    gap = [_premium(T0, first_end), _premium(first_end + timedelta(days=1), second_end)]
    assert evaluate(gap, at=T0).premium_until == first_end
    revoked = [_premium(T0, first_end), _premium(first_end, second_end, revoked=first_end)]
    assert evaluate(revoked, at=T0).premium_until == first_end
    endless = [_premium(T0, first_end), _premium(first_end, None)]
    assert evaluate(endless, at=T0).premium_until is None


@pytest.mark.req("BILL-012")
def test_key_modes() -> None:
    assert key_livemode("sk_live_abc") is True
    assert key_livemode("rk_live_abc") is True
    assert key_livemode("sk_test_abc") is False
    assert key_livemode("rk_test_abc") is False
    assert key_livemode(None) is None
    assert key_livemode("pk_live_abc") is None


def _production(**overrides: object) -> object:
    values: dict[str, object] = {
        "app_env": AppEnv.PRODUCTION,
        "cursor_signing_key": SecretStr("s" * 48),
        "platform_jwt_private_key": SecretStr(ed25519_test_pem()),
    }
    values.update(overrides)
    return make_settings(**values)


@pytest.mark.req("BILL-012")
@pytest.mark.security
def test_test_and_live_money_never_mix() -> None:
    _production(stripe_secret_key=SecretStr("rk_live_123"))
    make_settings(stripe_secret_key=SecretStr("sk_test_123"))
    with pytest.raises(ValidationError, match="live key in production"):
        _production(stripe_secret_key=SecretStr("sk_test_123"))
    for env in (AppEnv.TEST, AppEnv.DEVELOPMENT, AppEnv.STAGING):
        with pytest.raises(ValidationError, match="test key outside production"):
            make_settings(
                app_env=env,
                cursor_signing_key=SecretStr("s" * 48),
                platform_jwt_private_key=SecretStr(ed25519_test_pem()),
                stripe_secret_key=SecretStr("sk_live_123"),
            )
    with pytest.raises(ValidationError, match="secret or restricted key"):
        make_settings(stripe_secret_key=SecretStr("pk_test_123"))
    with pytest.raises(ValidationError, match="stripe_api_version"):
        make_settings(stripe_api_version="latest")


def test_stripe_objects_are_read_in_either_api_shape() -> None:
    newer = parse_invoice(
        {
            "id": "in_1",
            "customer": {"id": "cus_1"},
            "parent": {"subscription_details": {"subscription": "sub_1"}},
            "status": "paid",
            "amount_paid": 990,
            "amount_due": 990,
            "currency": "brl",
            "billing_reason": "subscription_cycle",
            "status_transitions": {"paid_at": 1_800_000_000},
            "created": 1_800_000_000,
        }
    )
    assert (newer.customer, newer.subscription, newer.currency) == ("cus_1", "sub_1", "BRL")
    assert newer.paid_at == datetime.fromtimestamp(1_800_000_000, tz=UTC)
    checkout = parse_checkout(
        {
            "id": "cs_1",
            "mode": "payment",
            "status": "complete",
            "payment_status": "paid",
            "customer": "cus_1",
            "payment_intent": {"id": "pi_1"},
            "line_items": {"data": [{"price": {"id": "price_pass"}}]},
            "amount_total": 1490,
            "currency": "brl",
            "client_reference_id": "user-1",
            "created": 1_800_000_000,
        }
    )
    assert (checkout.payment_intent, checkout.price_id, checkout.user_id) == (
        "pi_1",
        "price_pass",
        "user-1",
    )
    partial = parse_charge({"id": "ch_1", "amount": 1000, "amount_refunded": 400})
    full = parse_charge({"id": "ch_2", "amount": 1000, "amount_refunded": 1000})
    assert (partial.fully_refunded, full.fully_refunded) == (False, True)
    assert parse_dispute({"id": "dp_1", "status": "needs_response"}).outcome == "open"
    assert parse_dispute({"id": "dp_2", "status": "lost"}).outcome == "lost"


@pytest.mark.req("BILL-010")
def test_offers_are_validated() -> None:
    offer = CreateProductRequest(
        sku="price_pass_week",
        platform="web",
        kind="non_renewing",
        plan_key="premium",
        period="P7D",
        entitlement_keys=["premium"],
        title={"en": " Week pass ", "pt-BR": "Passe semanal"},
    )
    assert offer.title == {"en": "Week pass", "pt-BR": "Passe semanal"}
    for bad in (
        {"period": "P1H"},
        {"title": {"it": "Pass"}},
        {"title": {"en": ""}},
        {"description": {"en": "x" * 301}},
    ):
        with pytest.raises(ValidationError):
            CreateProductRequest.model_validate({**offer.model_dump(), **bad})
    assert UpdateProductRequest(sort_order=5).title is None


def test_plan_notices_read_as_the_travellers_own() -> None:
    title, body = render("subscription_notice", {"variant": "expiring"}, actor=None, locale="pt-BR")
    assert title == "Seu Premium"
    assert body.startswith("Seu Premium termina")
    title, _ = render(
        "subscription_notice",
        {"variant": "group_premium_lapsed", "group_name": "Porto"},
        actor=None,
        locale="en",
    )
    assert title == "Group premium"
