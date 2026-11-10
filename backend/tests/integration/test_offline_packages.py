"""Offline packages: build, license, signed manifest, tokenized download (BL-4.08; OFF-001,
OFF-004, OFF-005)."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.guides.offline import verify_manifest
from app.modules.guides.packages import build_guide_package
from app.modules.guides.seeding import DEFAULT_FILE, load_content, read_document
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import store  # noqa: F401 - dev billing app fixture
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _premium
from tests.integration.test_guides import _guides
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _destination, _problem, _user
from tests.integration.test_trips import _create as _create_trip

pytestmark = pytest.mark.integration

DEVICE = "device-0001-abcd"


@pytest.fixture(autouse=True)
def _fresh(store: LiveApp) -> Iterator[None]:  # noqa: F811
    clear = (
        "WITH l AS (DELETE FROM offline_package_licenses RETURNING 1), "
        "o AS (DELETE FROM offline_packages RETURNING 1), "
        "g AS (DELETE FROM destination_guides RETURNING 1), "
        "h AS (UPDATE destinations SET has_guides = false WHERE has_guides RETURNING 1) "
        "SELECT (SELECT count(*) FROM l) + (SELECT count(*) FROM o) "
        "+ (SELECT count(*) FROM h) + count(*) FROM g"
    )
    db_scalar(store.db_url, clear)
    yield
    db_scalar(store.db_url, clear)


def _build(live: LiveApp, document: dict[str, Any], locales: tuple[str, ...]) -> dict[str, int]:
    storage = live.client.app.state.media_storage  # type: ignore[attr-defined]

    async def run() -> dict[str, int]:
        engine = create_async_engine(live.db_url)
        try:
            async with async_sessionmaker(engine)() as session, session.begin():
                await load_content(session, document, live.clock.now())
                destination = await session.scalar(
                    text("SELECT id FROM destinations WHERE slug = :s"), {"s": "lisbon-pt"}
                )
                versions = {}
                for locale in locales:
                    package = await build_guide_package(
                        session,
                        storage,
                        destination_id=destination,
                        locale=locale,
                        now=live.clock.now(),
                    )
                    assert package is not None
                    versions[locale] = package.version
                return versions
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _packages(live: LiveApp, token: str) -> dict[str, Any]:
    response = live.client.get(
        f"/v1/destinations/{_destination(live, 'portugal/lisbon')}/offline-packages",
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    for item in response.json()["data"]:
        assert_matches_contract(item, "OfflinePackageSummary")
    return {p["locale"]: p for p in response.json()["data"]}


def _license(live: LiveApp, token: str, package_id: str, device: str = DEVICE) -> Any:
    return live.client.post(
        f"/v1/offline-packages/{package_id}/licenses",
        headers=_auth(token),
        json={"device_id": device},
    )


def _manifest_key(live: LiveApp) -> str:
    config = live.client.get(
        "/v1/client-config", params={"platform": "ios", "app_version": "1.0.0"}
    ).json()
    [key] = config["offline_manifest_keys"]
    return str(key["public_key"])


def _fetch(live: LiveApp, base_url: str, file: str) -> Any:
    redirect = live.client.get(urlsplit(base_url).path + file, follow_redirects=False)
    if redirect.status_code != 307:
        return redirect
    return live.client.get(urlsplit(redirect.headers["location"]).path)


@pytest.mark.req("OFF-001", "OFF-004")
def test_license_verify_and_download_a_package(store: LiveApp) -> None:  # noqa: F811
    assert _build(store, read_document(DEFAULT_FILE), ("en", "pt-BR")) == {"en": 1, "pt-BR": 1}
    token, _ = _user(store)  # free plan: one offline package
    packages = _packages(store, token)
    english, portuguese = packages["en"], packages["pt-BR"]
    assert english["tier"] == "free"
    assert english["entitled"] is True

    granted = _license(store, token, english["id"])
    assert granted.status_code == 201, granted.text
    assert_matches_contract(granted.json(), "OfflinePackageLicense")
    license_ = granted.json()
    manifest = license_["manifest"]
    assert verify_manifest(manifest, _manifest_key(store))  # what the app checks
    assert license_["quota"]["used"] == 1
    assert license_["quota"]["limit"] == 1
    tampered = {**manifest, "version": 99}
    assert not verify_manifest(tampered, _manifest_key(store))

    # Every file matches its manifest hash.
    for entry in manifest["files"]:
        response = _fetch(store, license_["download"]["base_url"], entry["path"])
        assert response.status_code == 200, entry
        assert hashlib.sha256(response.content).hexdigest() == entry["sha256"]
        assert len(response.content) == entry["bytes"]
    assert _fetch(store, license_["download"]["base_url"], "nope.json").status_code == 404
    forged = license_["download"]["base_url"].replace(
        "/v1/offline-downloads/", "/v1/offline-downloads/x"
    )
    assert _fetch(store, forged, "index.json").status_code == 404

    again = _license(store, token, english["id"])  # idempotent and free
    assert again.json()["id"] == license_["id"]
    assert again.json()["quota"]["used"] == 1
    denied = _problem(_license(store, token, portuguese["id"]), 409, "quota_exceeded")
    assert denied["feature_key"] == "offline.packages"

    mine = store.client.get("/v1/users/me/offline-packages", headers=_auth(token)).json()
    assert [entry["package"]["id"] for entry in mine["data"]] == [english["id"]]
    signed = store.client.get(
        f"/v1/offline-packages/{english['id']}/manifest", headers=_auth(token)
    ).json()
    assert_matches_contract(signed, "OfflineManifest")
    assert verify_manifest(signed, _manifest_key(store))

    released = store.client.delete(
        f"/v1/offline-packages/{english['id']}/licenses/{license_['id']}", headers=_auth(token)
    )
    assert released.status_code == 204
    gone = _fetch(store, license_["download"]["base_url"], "index.json")
    assert gone.status_code == 404  # released licenses stop downloading
    assert _license(store, token, portuguese["id"]).status_code == 201  # quota freed


@pytest.mark.req("DISC-011", "TRIP-001", "OFF-001", "NFR-007", "NFR-010")
def test_the_travel_guide_works_without_ever_enabling_discovery(store: LiveApp) -> None:  # noqa: F811
    _build(store, read_document(DEFAULT_FILE), ("en",))
    token, user_id = _user(store)
    privacy = store.client.get("/v1/users/me/privacy", headers=_auth(token)).json()
    assert privacy["discovery_enabled"] is False  # never turned on

    trip = _create_trip(store, token)
    assert trip.status_code == 201, trip.text
    [guide] = _guides(store, **{"Accept-Language": "en"})
    assert store.client.get(f"/v1/guides/{guide['id']}", headers=_auth(token)).status_code == 200
    granted = _license(store, token, _packages(store, token)["en"]["id"])
    assert granted.status_code == 201, granted.text
    index = _fetch(store, granted.json()["download"]["base_url"], "index.json")
    assert index.status_code == 200

    # Nothing about the traveller became discoverable along the way.
    traces = db_scalar(
        store.db_url,
        "SELECT (SELECT count(*) FROM traveler_discovery_sessions WHERE user_id = :u) "
        "+ (SELECT count(*) FROM consent_records WHERE user_id = :u "
        "AND consent_type = 'traveler_discovery')",
        u=uuid.UUID(user_id),
    )
    assert traces == 0


@pytest.mark.req("OFF-001", "OFF-005")
def test_updates_replace_old_licenses_and_expired_content_disappears(
    store: LiveApp,  # noqa: F811
) -> None:
    document = read_document(DEFAULT_FILE)
    _build(store, document, ("en",))
    token, _ = _user(store)
    first = _packages(store, token)["en"]
    granted = _license(store, token, first["id"]).json()

    assert _build(store, document, ("en",)) == {"en": 1}  # unchanged content: same version
    changed = copy.deepcopy(document)
    for guide in changed["guides"]:
        guide["version"] = 2
        guide["summary"] += " Updated."
    assert _build(store, changed, ("en",)) == {"en": 2}
    second = _packages(store, token)["en"]
    assert second["version"] == 2
    update = _license(store, token, second["id"])
    assert update.status_code == 201, update.text  # the new version replaces the old license
    assert update.json()["quota"]["used"] == 1
    old = _fetch(store, granted["download"]["base_url"], "index.json")
    assert old.status_code == 404

    db_scalar(
        store.db_url,
        "UPDATE offline_packages SET license_expires_at = now() - interval '1 minute' "
        "WHERE id = :i RETURNING 1",
        i=uuid.UUID(second["id"]),
    )
    assert "en" not in _packages(store, token)
    _problem(_license(store, token, second["id"]), 404, "not_found")
    expired = _fetch(store, update.json()["download"]["base_url"], "index.json")
    assert expired.status_code == 404


@pytest.mark.req("OFF-004")
def test_premium_packages_need_premium(store: LiveApp) -> None:  # noqa: F811
    document = read_document(DEFAULT_FILE)
    document["guides"] = [dict(document["guides"][0], tier="premium")]
    _build(store, document, ("en",))
    free, _ = _user(store)
    package = _packages(store, free)["en"]
    assert (package["tier"], package["entitled"]) == ("premium", False)
    _problem(_license(store, free, package["id"]), 403, "entitlement_required")
    _problem(
        store.client.get(f"/v1/offline-packages/{package['id']}/manifest", headers=_auth(free)),
        403,
        "entitlement_required",
    )
    premium, _, _ = _premium(store)
    granted = _license(store, premium, package["id"])
    assert granted.status_code == 201, granted.text
    assert granted.json()["quota"]["limit"] == 15
