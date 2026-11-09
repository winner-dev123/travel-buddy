"""End-to-end journey (BL-1.24; PROF-001, PROF-002, FEED-001): a newcomer registers, onboards,
picks where they are exploring and gets that destination's stories, explained by the feed's
fallback context. With PostGIS, the device location takes over (CI)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.social.seeding import load_editorial, read_document
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import TERMS, _auth, _id_token
from tests.integration.test_posts import app  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.req("PROF-001", "PROF-002", "FEED-001")]

EDITORS = "0193a7f0-0000-7000-8000-00000000ed17"


def _seed_editorial(db_url: str) -> None:
    async def run() -> None:
        engine = create_async_engine(db_url)
        try:
            async with async_sessionmaker(engine)() as session, session.begin():
                await load_editorial(session, read_document())
        finally:
            await engine.dispose()

    asyncio.run(run())


def _ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def test_newcomer_reaches_a_destination_feed(app: LiveApp) -> None:  # noqa: F811
    db_scalar(app.db_url, f"DELETE FROM users WHERE id = '{EDITORS}' RETURNING 1")  # noqa: S608
    _seed_editorial(app.db_url)
    client = app.client
    try:
        # 1. Sign up (age gate, legal versions) and see that setup is pending.
        registered = _ok(
            client.post(
                "/v1/auth/register",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                json={
                    "id_token": _id_token(app, name="Lea Martin"),
                    "client": "ios",
                    "birth_date": "1994-03-02",
                    "accepted_terms_version": TERMS,
                    "accepted_privacy_version": TERMS,
                    "locale": "fr-FR",
                },
            ),
            201,
        )
        token = registered["tokens"]["access_token"]
        assert registered["user"]["onboarding_completed"] is False
        headers = _auth(token)

        # 2. Onboarding: name, language, interests, where I'm exploring.
        _ok(client.patch("/v1/users/me", headers=headers, json={"display_name": "Léa"}))
        _ok(client.patch("/v1/users/me/preferences", headers=headers, json={"ui_locale": "fr"}))
        _ok(client.patch("/v1/users/me", headers=headers, json={"interests": ["food", "history"]}))
        lisbon = _ok(client.get("/v1/destinations/lookup", params={"path": "portugal/lisbon"}))
        _ok(
            client.put(
                "/v1/users/me/browse-destination",
                headers=headers,
                json={"destination_id": lisbon["id"]},
            )
        )
        me = _ok(client.post("/v1/users/me/onboarding/complete", headers=headers))
        assert me["onboarding_completed"] is True
        assert me["browse_destination"]["id"] == lisbon["id"]

        # 3. The feed starts at the chosen destination, with stories from it and its neighbourhoods.
        feed = _ok(client.get("/v1/feed", headers={**headers, "Accept-Language": "fr"}))
        assert_matches_contract(feed, "FeedPage")
        assert feed["context"]["source"] == "selected"
        assert feed["context"]["destination"]["id"] == lisbon["id"]
        assert feed["context"]["destination"]["name"] == "Lisbonne"  # localized
        bodies = [post["body"] for post in feed["data"]]
        assert any("pastéis de nata" in body for body in bodies)
        assert any("Alfama" in body for body in bodies)
        assert {post["primary_destination"]["path"] for post in feed["data"]} <= {
            "portugal/lisbon",
            "portugal/lisbon/alfama",
        }

        # 4. Reacting works from the first session (no further setup needed).
        first = feed["data"][0]["id"]
        reacted = client.post(
            f"/v1/posts/{first}/reactions", headers=headers, json={"reaction": "helpful"}
        )
        assert _ok(reacted)["counts"]["reactions"] >= 1

        # 5. With PostGIS, Nearby follows the device to its city instead (FEED-001/002).
        if db_scalar(app.db_url, "SELECT to_regclass('destination_boundaries') IS NOT NULL"):
            nearby = _ok(
                client.get(
                    "/v1/feed",
                    headers=headers,
                    params={"tab": "nearby", "near": "-22.9711,-43.1822", "radius_km": 10},
                )
            )
            assert nearby["context"]["source"] == "gps"
            assert nearby["context"]["destination"]["path"] == "brazil/rio-de-janeiro"
            assert all(
                post["primary_destination"]["path"].startswith("brazil/rio-de-janeiro")
                for post in nearby["data"]
            )
    finally:
        db_scalar(app.db_url, f"DELETE FROM users WHERE id = '{EDITORS}' RETURNING 1")  # noqa: S608
