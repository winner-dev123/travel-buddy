"""Stripe setup for the launch offers (BL-3.16; ADR-0031): dry runs change nothing, applying is
idempotent, changed prices replace the old ones, and the webhook secret is never printed."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.modules.billing.stripe import DEFAULT_API_VERSION, HANDLED_EVENTS, StripeClient
from app.modules.billing.stripe_setup import (
    DEFAULT_CATALOG,
    Offer,
    SetupReport,
    _write_secret,
    load_offers,
    run_setup,
)

pytestmark = pytest.mark.req("BILL-010", "BILL-012")

WEBHOOK = "https://api.example/v1/billing/webhooks/stripe"


class FakeAccount:
    """A Stripe account's prices, webhook endpoints and portal configurations."""

    def __init__(self) -> None:
        self.prices: dict[str, dict[str, Any]] = {}
        self.webhooks: list[dict[str, Any]] = []
        self.portals: list[dict[str, Any]] = []
        self.writes: list[tuple[str, dict[str, str]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["stripe-version"] == DEFAULT_API_VERSION
        path, method = request.url.path, request.method
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if method == "POST":
            self.writes.append((path, form))
        if path == "/v1/prices" and method == "GET":
            key = request.url.params.get("lookup_keys[]")
            found = [p for p in self.prices.values() if p["lookup_key"] == key and p["active"]]
            return httpx.Response(200, json={"data": found})
        if path == "/v1/prices" and method == "POST":
            return httpx.Response(200, json=self._create_price(form))
        if path.startswith("/v1/prices/"):
            self.prices[path.rsplit("/", 1)[-1]]["active"] = form.get("active") != "false"
            return httpx.Response(200, json={})
        if path == "/v1/webhook_endpoints" and method == "GET":
            return httpx.Response(200, json={"data": self.webhooks})
        if path.startswith("/v1/webhook_endpoints"):
            events = sorted(v for k, v in form.items() if k.startswith("enabled_events["))
            if path == "/v1/webhook_endpoints":
                endpoint = {
                    "id": f"we_{len(self.webhooks) + 1}",
                    "url": form["url"],
                    "api_version": form["api_version"],
                    "enabled_events": events,
                    "disabled": False,
                }
                self.webhooks.append(endpoint)
                return httpx.Response(200, json={**endpoint, "secret": "whsec_from_stripe"})
            self.webhooks[0]["enabled_events"] = events
            return httpx.Response(200, json=self.webhooks[0])
        if path == "/v1/billing_portal/configurations" and method == "GET":
            return httpx.Response(200, json={"data": [p for p in self.portals if p["is_default"]]})
        if path.startswith("/v1/billing_portal/configurations"):
            if path == "/v1/billing_portal/configurations":
                config = {"id": f"bpc_{len(self.portals) + 1}", "is_default": False, "form": form}
                self.portals.append(config)
                return httpx.Response(200, json=config)
            self.portals[0]["form"] = form
            return httpx.Response(200, json=self.portals[0])
        return httpx.Response(404, json={})

    def _create_price(self, form: dict[str, str]) -> dict[str, Any]:
        number = len(self.prices) + 1
        if form.get("transfer_lookup_key") == "true":
            for price in self.prices.values():
                if price["lookup_key"] == form["lookup_key"]:
                    price["lookup_key"] = None
        options = {
            key.split("[")[1].rstrip("]"): {"unit_amount": int(value)}
            for key, value in form.items()
            if key.startswith("currency_options[")
        }
        recurring = (
            {
                "interval": form["recurring[interval]"],
                "interval_count": int(form["recurring[interval_count]"]),
            }
            if "recurring[interval]" in form
            else None
        )
        price = {
            "id": f"price_{number}",
            "product": f"prod_{number}",
            "unit_amount": int(form["unit_amount"]),
            "currency": form["currency"],
            "currency_options": {form["currency"]: {"unit_amount": int(form["unit_amount"])}}
            | options,
            "recurring": recurring,
            "lookup_key": form["lookup_key"],
            "active": True,
        }
        self.prices[price["id"]] = price
        return price


def _run(account: FakeAccount, offers: list[Offer], *, apply: bool) -> SetupReport:
    async def go() -> SetupReport:
        async with httpx.AsyncClient(transport=httpx.MockTransport(account.handler)) as http:
            client = StripeClient(http, secret_key="rk_test_123", webhook_secret=None)
            return await run_setup(client, offers, webhook_url=WEBHOOK, apply=apply)

    return asyncio.run(go())


def test_the_launch_catalog_is_valid() -> None:
    offers = load_offers()
    keys = [o.key for o in offers]
    assert keys == ["premium_monthly", "premium_annual", "pass_week", "pass_month"]
    assert {o.kind for o in offers} == {"auto_renewable", "non_renewing"}
    for offer in offers:
        assert set(offer.title) == {"en", "es", "pt-BR", "fr", "de"}
        assert set(offer.prices) == {"USD", "BRL", "EUR"}
        assert set(offer.store_skus) == {"ios", "android"}


def test_a_dry_run_changes_nothing() -> None:
    account = FakeAccount()
    report = _run(account, load_offers(), apply=False)
    assert account.writes == []
    assert "price premium_monthly: would create (499 USD)" in report.lines
    assert f"webhook: would create for {WEBHOOK}" in report.lines
    assert report.prices == {}


def test_applying_sets_stripe_up_once() -> None:
    account = FakeAccount()
    offers = load_offers()
    report = _run(account, offers, apply=True)
    assert len(account.prices) == 4
    monthly = next(p for p in account.prices.values() if p["lookup_key"] == "premium_monthly")
    assert (monthly["unit_amount"], monthly["currency"]) == (499, "usd")
    assert monthly["recurring"] == {"interval": "month", "interval_count": 1}
    assert monthly["currency_options"]["brl"] == {"unit_amount": 1990}
    week = next(p for p in account.prices.values() if p["lookup_key"] == "pass_week")
    assert week["recurring"] is None  # passes are paid once
    [endpoint] = account.webhooks
    assert endpoint["enabled_events"] == sorted(HANDLED_EVENTS)
    assert endpoint["api_version"] == DEFAULT_API_VERSION
    assert report.webhook_secret == "whsec_from_stripe"
    assert not any("whsec" in line for line in report.lines)  # never printed
    [portal] = account.portals
    form = portal["form"]
    assert form["features[subscription_cancel][mode]"] == "at_period_end"
    switchable = {v for k, v in form.items() if k.endswith("[prices][0]")}
    assert switchable == {report.prices["premium_monthly"], report.prices["premium_annual"]}
    assert report.portal_configuration == "bpc_1"

    portal["is_default"] = True
    writes = len(account.writes)
    again = _run(account, offers, apply=True)
    assert len(account.prices) == 4  # found again by lookup key
    assert len(account.webhooks) == 1
    assert "webhook: up to date (we_1)" in again.lines
    assert again.webhook_secret is None
    later = [path for path, _ in account.writes[writes:]]
    assert later == ["/v1/billing_portal/configurations/bpc_1"]
    assert again.prices == report.prices


def test_a_new_price_replaces_the_old_one() -> None:
    account = FakeAccount()
    offers = load_offers()
    first = _run(account, offers, apply=True)
    cheaper = [
        o.model_copy(update={"prices": {**o.prices, "BRL": 990}}) if o.key == "pass_week" else o
        for o in offers
    ]
    second = _run(account, cheaper, apply=True)
    assert second.replaced == {"pass_week": first.prices["pass_week"]}
    assert second.prices["pass_week"] != first.prices["pass_week"]
    assert account.prices[first.prices["pass_week"]]["active"] is False
    assert account.prices[second.prices["pass_week"]]["lookup_key"] == "pass_week"
    created = [form for path, form in account.writes if path == "/v1/prices"][-1]
    assert created["transfer_lookup_key"] == "true"


def test_the_secret_file_is_private(tmp_path: Path) -> None:
    target = tmp_path / "secrets" / "whsec.txt"
    _write_secret(target, "whsec_abc")
    assert target.read_text(encoding="utf-8") == "whsec_abc"


def test_bad_catalogs_are_refused(tmp_path: Path) -> None:
    document = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
    for broken in (
        {**document, "offers": document["offers"] + document["offers"][:1]},
        {"offers": [{**document["offers"][0], "period": None}]},
        {"offers": [{**document["offers"][0], "prices": {"usd": 499}}]},
        {"offers": [{**document["offers"][0], "title": {"pt-BR": "Mensal"}}]},
    ):
        path = tmp_path / "offers.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError):
            load_offers(path)


def test_store_offers_can_be_listed_without_a_stripe_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.modules.billing.stripe_setup import main

    assert main(["--stores-only"]) == 0  # a dry run: no Stripe key, no database
    assert "products: would register 8" in capsys.readouterr().out
