"""Editorial launch content (BL-1.23, FEED-001): seeded idempotently, visible in the fallback
feed of a brand-new user and on destination pages."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.social.seeding import SeedResult, load_editorial, read_document
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _user, app  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.req("FEED-001")]


def _seed(db_url: str) -> SeedResult:
    async def run() -> SeedResult:
        engine = create_async_engine(db_url)
        try:
            async with async_sessionmaker(engine)() as session, session.begin():
                return await load_editorial(session, read_document())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_editorial_content_is_seeded_once_and_reaches_new_users(app: LiveApp) -> None:  # noqa: F811
    total = len(read_document()["posts"])
    db_scalar(
        app.db_url,
        "DELETE FROM users WHERE id = '0193a7f0-0000-7000-8000-00000000ed17' RETURNING 1",
    )
    first = _seed(app.db_url)
    assert (first.account_created, first.created, first.skipped) == (True, total, 0)
    again = _seed(app.db_url)
    assert (again.account_created, again.created, again.skipped) == (False, 0, total)

    newcomer, _ = _user(app)
    feed = app.client.get("/v1/feed", headers=_auth(newcomer), params={"limit": 10})
    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert_matches_contract(body, "FeedPage")
    assert body["data"], "a brand-new user sees editorial posts through the global fallback"
    assert {item["author"]["handle"] for item in body["data"]} == {"travelbuddy"}

    lisbon = app.client.get("/v1/destinations/lookup", params={"path": "portugal/lisbon"}).json()
    stories = app.client.get("/v1/public/posts", params={"destination_id": lisbon["id"]}).json()
    bodies = [p["body"] for p in stories["data"]]
    assert any("pastéis de nata" in b for b in bodies)
    assert any("fado" in b for b in bodies)  # Alfama posts roll up to Lisbon
    assert all(p["indexable"] for p in stories["data"])
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM authentication_identities "
            "WHERE user_id = '0193a7f0-0000-7000-8000-00000000ed17'",
        )
        == 0
    )  # nobody can sign in as the editorial account
    # Leave the shared test database as other feed tests expect it.
    db_scalar(
        app.db_url,
        "DELETE FROM users WHERE id = '0193a7f0-0000-7000-8000-00000000ed17' RETURNING 1",
    )
