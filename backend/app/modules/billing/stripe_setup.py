"""Set Stripe up for the launch offers and register them with us (BL-3.16; ADR-0031, docs/11 §1.14).

``python -m app.modules.billing.stripe_setup [--apply] [--catalog PATH] [--webhook-url URL]
[--secret-out PATH] [--stores-only]``

``--stores-only`` registers just the App Store and Google Play rows: no Stripe key needed.

Without ``--apply`` it only reports what it would do. With ``--apply``, idempotently:

1. one Stripe Price per offer (with its Product), found again on later runs by its ``lookup_key``.
   A changed amount creates a new Price that takes the lookup key over, and the old offer row is
   retired;
2. the webhook endpoint for ``--webhook-url``, subscribed to exactly the events the API handles. A
   new endpoint's signing secret is written to ``--secret-out`` and never printed;
3. the Customer Portal: cancel at period end, payment methods, invoices, switching between the
   subscriptions. If the account has no default configuration yet, the new one's id is reported
   for ``STRIPE_PORTAL_CONFIGURATION``;
4. the offers in our ``products`` table: web rows keyed by the Price id, store rows by their SKUs.

It talks to whichever Stripe account ``STRIPE_SECRET_KEY`` belongs to; the settings refuse a live
key outside production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import Product
from app.modules.billing.schemas import (
    EntitlementKey,
    LocalizedText,
    Period,
    ProductKindName,
    _check_localized,
)
from app.modules.billing.stripe import DEFAULT_API_VERSION, HANDLED_EVENTS, StripeClient

DEFAULT_CATALOG = Path(__file__).parent / "seed" / "offers.json"
_INTERVALS = {"D": "day", "W": "week", "M": "month", "Y": "year"}


class Offer(BaseModel):
    """One offer of the catalog, the same on every platform (BILL-010)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    kind: ProductKindName
    period: Period | None = None
    entitlement_keys: list[EntitlementKey] = Field(min_length=1, max_length=10)
    sort_order: int = Field(ge=0, le=1000)
    # Minor units per ISO currency; the first one is the Price's own currency.
    prices: dict[str, int] = Field(min_length=1)
    store_skus: dict[Literal["ios", "android"], str] = Field(default_factory=dict)
    title: LocalizedText
    description: LocalizedText = Field(default_factory=dict)

    @field_validator("prices")
    @classmethod
    def _prices(cls, value: dict[str, int]) -> dict[str, int]:
        for currency, amount in value.items():
            if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
                raise ValueError(f"currency {currency!r} must be an ISO 4217 code")
            if amount <= 0:
                raise ValueError(f"{currency}: the amount must be positive")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: dict[str, str]) -> dict[str, str]:
        checked = _check_localized(value, 80) or {}
        if "en" not in checked:
            raise ValueError("an English title is required (Stripe shows it)")
        return checked

    @field_validator("description")
    @classmethod
    def _description(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_localized(value, 300) or {}

    @property
    def renews(self) -> bool:
        return self.kind == "auto_renewable"

    @property
    def currency(self) -> str:
        return next(iter(self.prices))

    @property
    def amount(self) -> int:
        return self.prices[self.currency]


def load_offers(path: Path = DEFAULT_CATALOG) -> list[Offer]:
    document = json.loads(path.read_text(encoding="utf-8"))
    offers = [Offer.model_validate(raw) for raw in document["offers"]]
    keys = [o.key for o in offers]
    if len(set(keys)) != len(keys):
        raise ValueError("offer keys must be unique")
    for offer in offers:
        timed = offer.kind in ("auto_renewable", "non_renewing")
        if timed != (offer.period is not None):
            raise ValueError(f"{offer.key}: subscriptions and passes need a period, others none")
    return offers


@dataclass
class SetupReport:
    lines: list[str] = field(default_factory=list)
    # offer key -> the Price id that sells it now; and Price ids it replaced
    prices: dict[str, str] = field(default_factory=dict)
    replaced: dict[str, str] = field(default_factory=dict)
    products: dict[str, str] = field(default_factory=dict)
    webhook_secret: str | None = None
    portal_configuration: str | None = None

    def say(self, line: str) -> None:
        self.lines.append(line)


def _price_form(offer: Offer, *, transfer: bool) -> dict[str, str]:
    form = {
        "currency": offer.currency.lower(),
        "unit_amount": str(offer.amount),
        "lookup_key": offer.key,
        "metadata[offer]": offer.key,
        "product_data[name]": offer.title["en"],
        "product_data[metadata][offer]": offer.key,
    }
    for currency, amount in offer.prices.items():
        if currency != offer.currency:
            form[f"currency_options[{currency.lower()}][unit_amount]"] = str(amount)
    if offer.renews and offer.period:
        count, unit = int(offer.period[1:-1]), offer.period[-1]
        form["recurring[interval]"] = _INTERVALS[unit]
        form["recurring[interval_count]"] = str(count)
    if transfer:
        form["transfer_lookup_key"] = "true"
    return form


def _same_price(existing: dict[str, Any], offer: Offer) -> bool:
    recurring = existing.get("recurring") or {}
    options = existing.get("currency_options") or {}
    others_match = all(
        (options.get(currency.lower()) or {}).get("unit_amount") == amount
        for currency, amount in offer.prices.items()
        if currency != offer.currency
    )
    interval_match = (
        bool(recurring) == offer.renews
        if not offer.renews or not offer.period
        else (
            recurring.get("interval") == _INTERVALS[offer.period[-1]]
            and int(recurring.get("interval_count") or 1) == int(offer.period[1:-1])
        )
    )
    return (
        existing.get("unit_amount") == offer.amount
        and str(existing.get("currency", "")).upper() == offer.currency
        and others_match
        and interval_match
    )


async def sync_prices(stripe: StripeClient, offers: Sequence[Offer], *, apply: bool) -> SetupReport:
    report = SetupReport()
    for offer in offers:
        found = await stripe.call(
            "GET",
            "/v1/prices",
            params=[
                ("lookup_keys[]", offer.key),
                ("active", "true"),
                ("expand[]", "data.currency_options"),
            ],
        )
        existing = (found.get("data") or [None])[0]
        if existing is not None and _same_price(existing, offer):
            report.prices[offer.key] = str(existing["id"])
            report.products[offer.key] = str(existing.get("product"))
            report.say(f"price {offer.key}: up to date ({existing['id']})")
            continue
        action = "replace" if existing is not None else "create"
        if not apply:
            report.say(f"price {offer.key}: would {action} ({offer.amount} {offer.currency})")
            continue
        created = await stripe.call(
            "POST",
            "/v1/prices",
            _price_form(offer, transfer=existing is not None),
            idempotency_key=f"tb-price-{offer.key}-{offer.amount}-{offer.currency}-"
            f"{offer.period or 'once'}",
        )
        report.prices[offer.key] = str(created["id"])
        report.products[offer.key] = str(created.get("product"))
        if existing is not None:
            report.replaced[offer.key] = str(existing["id"])
            await stripe.call("POST", f"/v1/prices/{existing['id']}", {"active": "false"})
        report.say(f"price {offer.key}: {action}d ({created['id']})")
    return report


async def sync_webhook(stripe: StripeClient, url: str, report: SetupReport, *, apply: bool) -> None:
    events = sorted(HANDLED_EVENTS)
    form = {f"enabled_events[{i}]": event for i, event in enumerate(events)}
    listed = await stripe.call("GET", "/v1/webhook_endpoints", params=[("limit", "100")])
    endpoint = next((e for e in listed.get("data") or [] if e.get("url") == url), None)
    if endpoint is not None:
        if sorted(endpoint.get("enabled_events") or []) == events and not endpoint.get("disabled"):
            report.say(f"webhook: up to date ({endpoint['id']})")
            return
        if apply:
            await stripe.call(
                "POST", f"/v1/webhook_endpoints/{endpoint['id']}", {**form, "disabled": "false"}
            )
        report.say(f"webhook: {'updated' if apply else 'would update'} ({endpoint['id']})")
        return
    if not apply:
        report.say(f"webhook: would create for {url}")
        return
    created = await stripe.call(
        "POST",
        "/v1/webhook_endpoints",
        {
            **form,
            "url": url,
            "api_version": DEFAULT_API_VERSION,
            "description": "Travel Buddy API (ADR-0031)",
        },
        idempotency_key=f"tb-webhook-{url}",
    )
    report.webhook_secret = created.get("secret")
    report.say(f"webhook: created ({created['id']}); signing secret saved, not shown")


def _portal_form(offers: Sequence[Offer], report: SetupReport) -> dict[str, str]:
    form = {
        "features[customer_update][enabled]": "false",
        "features[invoice_history][enabled]": "true",
        "features[payment_method_update][enabled]": "true",
        "features[subscription_cancel][enabled]": "true",
        "features[subscription_cancel][mode]": "at_period_end",
        "features[subscription_cancel][proration_behavior]": "none",
    }
    switchable = [o for o in offers if o.renews and o.key in report.prices]
    if len(switchable) > 1:
        form["features[subscription_update][enabled]"] = "true"
        form["features[subscription_update][default_allowed_updates][0]"] = "price"
        form["features[subscription_update][proration_behavior]"] = "create_prorations"
        for index, offer in enumerate(switchable):
            prefix = f"features[subscription_update][products][{index}]"
            form[f"{prefix}[product]"] = report.products[offer.key]
            form[f"{prefix}[prices][0]"] = report.prices[offer.key]
    else:
        form["features[subscription_update][enabled]"] = "false"
    return form


async def sync_portal(
    stripe: StripeClient, offers: Sequence[Offer], report: SetupReport, *, apply: bool
) -> None:
    listed = await stripe.call(
        "GET", "/v1/billing_portal/configurations", params=[("is_default", "true"), ("limit", "1")]
    )
    default = (listed.get("data") or [None])[0]
    if not apply:
        report.say("portal: would " + ("update the default" if default else "create one"))
        return
    form = _portal_form(offers, report)
    if default is not None:
        await stripe.call("POST", f"/v1/billing_portal/configurations/{default['id']}", form)
        report.say(f"portal: default updated ({default['id']})")
        return
    created = await stripe.call("POST", "/v1/billing_portal/configurations", form)
    report.portal_configuration = str(created["id"])
    report.say(f"portal: created ({created['id']}); set STRIPE_PORTAL_CONFIGURATION to use it")


async def register_offers(
    session: AsyncSession, offers: Sequence[Offer], report: SetupReport
) -> int:
    """Upsert the offers as products: web rows by Price id, store rows by SKU. Returns rows
    written. Rows of replaced Prices are retired (their buyers keep what they paid for)."""
    rows: list[tuple[str, str, Offer]] = [
        ("web", report.prices[o.key], o) for o in offers if o.key in report.prices
    ]
    rows += [(platform, sku, o) for o in offers for platform, sku in o.store_skus.items()]
    for platform, sku, offer in rows:
        found = await session.scalar(
            select(Product).where(Product.platform == platform, Product.sku == sku)
        )
        values: dict[str, Any] = {
            "kind": offer.kind,
            "plan_key": "premium" if offer.kind != "non_consumable" else None,
            "period": offer.period,
            "entitlement_keys": list(offer.entitlement_keys),
            "title": dict(offer.title),
            "description": dict(offer.description),
            "sort_order": offer.sort_order,
            "active": True,
        }
        if found is None:
            session.add(Product(sku=sku, platform=platform, **values))
        else:
            for name, value in values.items():
                setattr(found, name, value)
    for old in report.replaced.values():
        await session.execute(
            update(Product)
            .where(Product.platform == "web", Product.sku == old)
            .values(active=False)
        )
    await session.flush()
    report.say(f"products: {len(rows)} registered, {len(report.replaced)} retired")
    return len(rows)


async def run_setup(
    stripe: StripeClient,
    offers: Sequence[Offer],
    *,
    webhook_url: str | None,
    apply: bool,
) -> SetupReport:
    report = await sync_prices(stripe, offers, apply=apply)
    if webhook_url:
        await sync_webhook(stripe, webhook_url, report, apply=apply)
    else:
        report.say("webhook: skipped (no --webhook-url)")
    await sync_portal(stripe, offers, report, apply=apply)
    return report


def _write_secret(path: Path, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(secret)
    path.chmod(0o600)


async def _main(args: argparse.Namespace) -> int:
    import httpx

    from app.core.config import get_settings
    from app.core.db import Database

    settings = get_settings()
    offers = load_offers(args.catalog)
    if args.stores_only:
        report = SetupReport()
        if args.apply:
            database = Database.from_settings(settings, pool_size=1, max_overflow=0)
            try:
                async with database.sessionmaker() as session, session.begin():
                    await register_offers(session, offers, report)
            finally:
                await database.dispose()
        else:
            report.say(f"products: would register {sum(len(o.store_skus) for o in offers)}")
        sys.stdout.write("\n".join(report.lines) + "\n")
        return 0
    if settings.stripe_secret_key is None:
        sys.stderr.write("STRIPE_SECRET_KEY is not set.\n")
        return 1
    async with httpx.AsyncClient(follow_redirects=False) as http:
        stripe = StripeClient(
            http,
            secret_key=settings.stripe_secret_key.get_secret_value(),
            webhook_secret=None,
            api_base=settings.stripe_api_base,
            api_version=settings.stripe_api_version,
        )
        report = await run_setup(stripe, offers, webhook_url=args.webhook_url, apply=args.apply)
    if report.webhook_secret:
        if args.secret_out is None:
            sys.stderr.write("A new webhook secret needs --secret-out; delete the endpoint.\n")
            return 1
        _write_secret(args.secret_out, report.webhook_secret)
    if args.apply:
        database = Database.from_settings(settings, pool_size=1, max_overflow=0)
        try:
            async with database.sessionmaker() as session, session.begin():
                await register_offers(session, offers, report)
        finally:
            await database.dispose()
    sys.stdout.write("\n".join(report.lines) + "\n")
    if not args.apply:
        sys.stdout.write("Dry run: nothing changed. Add --apply to make these changes.\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set Stripe up for the Travel Buddy offers")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--webhook-url", default=None)
    parser.add_argument("--secret-out", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--stores-only", action="store_true")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
