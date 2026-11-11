"""The launch offers land in ``products`` for every platform (BL-3.16; BILL-010)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.billing.stripe_setup import SetupReport, load_offers, register_offers
from tests.integration.conftest import db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture

pytestmark = [pytest.mark.integration, pytest.mark.req("BILL-010")]


def _register(url: str, report: SetupReport) -> None:
    async def go() -> None:
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session, session.begin():
                await register_offers(session, load_offers(), report)
        finally:
            await engine.dispose()

    asyncio.run(go())


def test_offers_are_registered_on_every_platform_and_replaced_prices_retire(
    catalog: str,  # noqa: F811
) -> None:
    run = uuid.uuid4().hex[:8]
    keys = ("premium_monthly", "premium_annual", "pass_week", "pass_month")
    first = SetupReport(prices={key: f"price_{run}_{key}" for key in keys})
    _register(catalog, first)
    _register(catalog, first)  # idempotent
    week = f"price_{run}_pass_week"
    row = db_scalar(
        catalog,
        "SELECT kind || '|' || period || '|' || (title->>'pt-BR') || '|' || sort_order "  # noqa: S608
        f"FROM products WHERE platform = 'web' AND sku = '{week}'",
    )
    assert row == "non_renewing|P7D|Passe de 7 dias|30"
    stores = db_scalar(
        catalog,
        "SELECT count(*) FROM products WHERE (platform, sku) IN "
        "(('ios', 'com.travelbuddy.pass.week'), ('android', 'pass_week'), "
        "('ios', 'com.travelbuddy.premium.monthly'), ('android', 'premium_annual'))",
    )
    assert stores == 4
    copies = db_scalar(
        catalog,
        f"SELECT count(*) FROM products WHERE sku = '{week}'",  # noqa: S608
    )
    assert copies == 1

    second = SetupReport(
        prices={**first.prices, "pass_week": f"price_{run}_pass_week_v2"},
        replaced={"pass_week": week},
    )
    _register(catalog, second)
    active = db_scalar(
        catalog,
        "SELECT string_agg(sku || ':' || active::text, ',' ORDER BY sku) FROM products "  # noqa: S608
        f"WHERE platform = 'web' AND sku LIKE 'price_{run}_pass_week%'",
    )
    assert active == f"{week}:false,{week}_v2:true"
