"""Destination guides and audio tours (BL-4.07; GUIDE-004, GUIDE-005, GUIDE-006)."""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.guides.seeding import DEFAULT_FILE, SeedResult, load_content, read_document
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import store  # noqa: F401 - dev billing app fixture
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _premium
from tests.integration.test_identity_flows import _auth
from tests.integration.test_places import _document as _places_document
from tests.integration.test_places import _ingest, _place_id
from tests.integration.test_posts import _destination, _problem, _user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _fresh(store: LiveApp) -> Iterator[None]:  # noqa: F811
    clear = (
        "WITH s AS (DELETE FROM audio_tour_stops RETURNING 1), "
        "t AS (DELETE FROM audio_tours RETURNING 1), "
        "g AS (DELETE FROM destination_guides RETURNING 1), "
        "p AS (DELETE FROM places RETURNING 1), "
        "h AS (UPDATE destinations SET has_guides = false WHERE has_guides RETURNING 1) "
        "SELECT (SELECT count(*) FROM s) + (SELECT count(*) FROM t) "
        "+ (SELECT count(*) FROM g) + (SELECT count(*) FROM h) + count(*) FROM p"
    )
    db_scalar(store.db_url, clear)
    yield
    db_scalar(store.db_url, clear)


def _load(live: LiveApp, document: dict[str, Any]) -> SeedResult:
    async def run() -> SeedResult:
        engine = create_async_engine(live.db_url)
        try:
            async with async_sessionmaker(engine)() as session, session.begin():
                return await load_content(session, document, live.clock.now())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _guides(live: LiveApp, headers: dict[str, str] | None = None, **extra: str) -> list[Any]:
    response = live.client.get(
        f"/v1/destinations/{_destination(live, 'portugal/lisbon')}/guides",
        headers={**(headers or {}), **extra},
    )
    assert response.status_code == 200, response.text
    for item in response.json()["data"]:
        assert_matches_contract(item, "GuideSummary")
    data: list[Any] = response.json()["data"]
    return data


def _premium_guide(tier: str = "premium", slug: str = "lisbon-insider") -> dict[str, Any]:
    document = read_document(DEFAULT_FILE)
    guide = copy.deepcopy(document["guides"][0])
    guide.update({"slug": slug, "tier": tier, "title": f"Lisbon {tier}"})
    return {"guides": [guide]}


@pytest.mark.req("GUIDE-004", "GUIDE-006")
def test_free_guides_are_public_localized_and_structured(store: LiveApp) -> None:  # noqa: F811
    assert _load(store, read_document(DEFAULT_FILE)) == SeedResult(guides=2, audio_tours=0)
    [english] = _guides(store, **{"Accept-Language": "en"})
    [portuguese] = _guides(store, **{"Accept-Language": "pt-BR"})
    assert english["title"] == "Lisbon essentials"
    assert portuguese["title"] == "Lisboa essencial"
    assert english["entitled"] is True  # free, even anonymously
    lisbon = store.client.get(f"/v1/destinations/{_destination(store, 'portugal/lisbon')}").json()
    assert lisbon["has_guides"] is True

    guide = store.client.get(f"/v1/guides/{english['id']}")
    assert guide.status_code == 200, guide.text
    assert_matches_contract(guide.json(), "Guide")
    body = guide.json()
    assert body["destination"]["path"] == "portugal/lisbon"
    assert body["content_license"] == "travelbuddy-editorial"
    faq = next(s for s in body["sections"] if s["kind"] == "faq")
    assert len(faq["faq_items"]) == 3
    assert faq["faq_items"][0]["question"] == "Is Lisbon a walkable city?"

    # A new version retires the old one; expired rights stop serving.
    updated = read_document(DEFAULT_FILE)
    for item in updated["guides"]:
        item["version"] = 2
        item["title"] = item["title"] + " (2027)"
    _load(store, updated)
    [current] = _guides(store, **{"Accept-Language": "en"})
    assert current["version"] == 2
    _problem(store.client.get(f"/v1/guides/{english['id']}"), 404, "not_found")
    db_scalar(
        store.db_url,
        "UPDATE destination_guides SET rights_expire_at = now() - interval '1 day' "
        "WHERE id = :i RETURNING 1",
        i=uuid.UUID(current["id"]),
    )
    _problem(store.client.get(f"/v1/guides/{current['id']}"), 404, "not_found")
    _problem(store.client.get(f"/v1/destinations/{uuid.uuid4()}/guides"), 404, "not_found")


def test_sections_are_validated_before_anything_is_published(store: LiveApp) -> None:  # noqa: F811
    broken = _premium_guide()
    broken["guides"][0]["sections"].append({"id": "x", "kind": "faq", "heading": "Empty FAQ"})
    with pytest.raises(ValueError, match="faq_items"):
        _load(store, broken)
    assert db_scalar(store.db_url, "SELECT count(*) FROM destination_guides") == 0


@pytest.mark.req("GUIDE-004")
def test_premium_and_purchasable_guides_need_an_entitlement(store: LiveApp) -> None:  # noqa: F811
    _load(store, _premium_guide("premium"))
    _load(store, _premium_guide("purchasable", slug="lisbon-food-walk"))
    rows = {g["tier"]: g for g in _guides(store)}
    premium, purchasable = rows["premium"], rows["purchasable"]
    assert premium["entitled"] is False
    _problem(store.client.get(f"/v1/guides/{premium['id']}"), 401, "unauthenticated")

    free_token, free_id = _user(store)
    locked = _problem(
        store.client.get(f"/v1/guides/{premium['id']}", headers=_auth(free_token)),
        403,
        "entitlement_required",
    )
    assert locked["entitlement"] == "guides.premium"
    # Buying one guide unlocks that guide only.
    db_scalar(
        store.db_url,
        "INSERT INTO subscription_entitlements (id, user_id, entitlement_key, source_type, "
        "source_id, starts_at) VALUES (:id, :u, :k, 'admin_grant', :s, now() - interval '1 hour') "
        "RETURNING 1",
        id=uuid.uuid4(),
        u=uuid.UUID(free_id),
        k=f"content:guide:{purchasable['id']}",
        s=uuid.uuid4(),
    )
    bought = store.client.get(f"/v1/guides/{purchasable['id']}", headers=_auth(free_token))
    assert bought.status_code == 200, bought.text
    _problem(
        store.client.get(f"/v1/guides/{premium['id']}", headers=_auth(free_token)),
        403,
        "entitlement_required",
    )

    premium_token, _, _ = _premium(store)
    assert all(g["entitled"] for g in _guides(store, _auth(premium_token)))
    ok = store.client.get(f"/v1/guides/{premium['id']}", headers=_auth(premium_token))
    assert ok.status_code == 200, ok.text


@pytest.mark.req("GUIDE-005")
def test_audio_tours_list_stops_with_on_device_geofences(store: LiveApp) -> None:  # noqa: F811
    _ingest(store, _places_document())
    owner, owner_id = _user(store)
    audio = uuid.uuid4()
    db_scalar(
        store.db_url,
        "INSERT INTO media_assets (id, owner_id, purpose, status, mime_type, bytes, sha256, "
        "duration_ms, quarantine_key, variants) VALUES (:id, :o, 'post', 'ready', 'audio/mpeg', "
        "1000, 'x', 180000, 'q', CAST(:v AS jsonb)) RETURNING 1",
        id=audio,
        o=uuid.UUID(owner_id),
        v='[{"url": "https://cdn.example.org/tower.mp3", "key": "tower.mp3"}]',
    )
    _load(
        store,
        {
            "audio_tours": [
                {
                    "destination": "portugal/lisbon",
                    "slug": "belem-walk",
                    "locale": "en",
                    "tier": "premium",
                    "title": "Belém by the river",
                    "description": "Monuments of the Age of Discovery.",
                    "content_license": "travelbuddy-editorial",
                    "stops": [
                        {
                            "place_id": _place_id(store, "belem-tower"),
                            "audio_media_id": str(audio),
                            "title": "The tower",
                            "transcript": "Built to guard the river.",
                            "trigger_radius_m": 40,
                            "duration_s": 180,
                        }
                    ],
                }
            ]
        },
    )
    lisbon = _destination(store, "portugal/lisbon")
    listing = store.client.get(f"/v1/destinations/{lisbon}/audio-tours").json()["data"]
    [summary] = listing
    assert_matches_contract(summary, "AudioTourSummary")
    assert (summary["stop_count"], summary["total_duration_s"], summary["entitled"]) == (
        1,
        180,
        False,
    )
    _problem(store.client.get(f"/v1/audio-tours/{summary['id']}"), 401, "unauthenticated")
    _problem(
        store.client.get(f"/v1/audio-tours/{summary['id']}", headers=_auth(owner)),
        403,
        "entitlement_required",
    )
    token, _, _ = _premium(store)
    tour = store.client.get(f"/v1/audio-tours/{summary['id']}", headers=_auth(token))
    assert tour.status_code == 200, tour.text
    assert_matches_contract(tour.json(), "AudioTour")
    [stop] = tour.json()["stops"]
    assert stop["trigger_radius_m"] == 40
    assert stop["place"]["category"] == "attraction"
    assert stop["audio"]["kind"] == "audio"
    assert stop["audio"]["url"] == "https://cdn.example.org/tower.mp3"
    assert stop["audio"]["duration_ms"] == 180000
