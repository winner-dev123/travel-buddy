"""Editorial media: credit, verified rights and destination covers (DEST-007)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_media import _finalize, _media_app, _request, _upload
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _destination, _problem, _tick, _user
from tests.unit.test_media_processing import jpeg_with_gps

pytestmark = [pytest.mark.integration, pytest.mark.req("DEST-007")]

CREDIT = {
    "text": "Photo by Ana Souza",
    "license": "CC BY-SA 4.0",
    "url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
}


@pytest.fixture
def media(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
    yield from _media_app(catalog, "local")


def _ready_editorial(live: LiveApp, token: str, **body: Any) -> str:
    media_id = _upload(
        live, token, jpeg_with_gps(), purpose="editorial", attribution=CREDIT, **body
    )
    assert _finalize(live, token, media_id).status_code == 202
    _tick(live)
    return media_id


def _rights(live: LiveApp, token: str, media_id: str, **body: Any) -> Any:
    return live.client.post(f"/v1/admin/media/{media_id}/rights", headers=_admin(token), json=body)


def test_only_content_staff_upload_editorial_media_with_a_credit(media: LiveApp) -> None:
    staff, _ = _staff(media, "admin")
    member, _ = _user(media)
    data = jpeg_with_gps()
    _problem(
        _request(media, member, data, purpose="editorial", attribution=CREDIT), 403, "forbidden"
    )
    missing = _request(media, staff, data, purpose="editorial")
    _problem(missing, 422, "validation_failed")
    assert missing.json()["errors"][0]["field"] == "attribution"
    stray = _request(media, member, data, purpose="post", attribution=CREDIT)
    _problem(stray, 422, "validation_failed")
    assert stray.json()["errors"][0]["code"] == "not_allowed"
    # Moderators manage reports, not content: no editorial uploads.
    moderator, _ = _staff(media, "moderator")
    _problem(
        _request(media, moderator, data, purpose="editorial", attribution=CREDIT), 403, "forbidden"
    )


@pytest.mark.req("ADM-004", "ADM-007", "ADM-009")
def test_a_cover_needs_verified_rights_and_disappears_when_revoked(media: LiveApp) -> None:
    staff, staff_id = _staff(media, "admin")
    member, _ = _user(media)
    destination = _destination(media, "portugal/lisbon")
    url = f"/v1/admin/destinations/{destination}"
    db_scalar(
        media.db_url,
        "DELETE FROM outbox_events WHERE event_type = 'destination.updated' "
        "AND aggregate_id = :d RETURNING 1",
        d=uuid.UUID(destination),
    )
    try:
        cover = _ready_editorial(media, staff, alt_text="Tram 28 in Alfama")
        unverified = media.client.patch(url, headers=_admin(staff), json={"cover_media_id": cover})
        _problem(unverified, 422, "validation_failed")
        assert unverified.json()["errors"][0]["code"] == "rights_not_verified"

        # Members cannot verify rights; staff do it with a justification, audited.
        _problem(
            media.client.post(
                f"/v1/admin/media/{cover}/rights", headers=_auth(member), json={"verified": True}
            ),
            403,
            "forbidden",
        )
        verified = _rights(media, staff, cover, verified=True)
        assert verified.status_code == 200, verified.text
        assert_matches_contract(verified.json(), "EditorialMedia")
        assert verified.json()["rights_verified_at"] is not None
        assert verified.json()["attribution"] == CREDIT
        # The platform owns it now: it no longer depends on the uploader's account.
        owner = db_scalar(
            media.db_url,
            "SELECT coalesce(owner_id::text, 'platform') || ':' || rights_verified_by::text "
            "FROM media_assets WHERE id = :m",
            m=uuid.UUID(cover),
        )
        assert owner == f"platform:{staff_id}"

        set_cover = media.client.patch(url, headers=_admin(staff), json={"cover_media_id": cover})
        assert set_cover.status_code == 200, set_cover.text
        assert_matches_contract(set_cover.json(), "Destination")
        public = media.client.get(f"/v1/destinations/{destination}")
        assert public.status_code == 200
        shown = public.json()["cover"]
        assert shown["id"] == cover
        assert shown["status"] == "ready"
        assert shown["attribution"] == CREDIT
        assert shown["alt_text"] == "Tram 28 in Alfama"
        # Editorial renditions do not carry the uploader's id in their public URL.
        assert "/e/" in shown["url"]
        assert staff_id not in shown["url"]
        lisbon_in_search = media.client.get("/v1/destinations/search", params={"q": "Lisbon"})
        hits = [d for d in lisbon_in_search.json()["data"] if d["id"] == destination]
        assert hits
        assert hits[0]["cover"]["id"] == cover

        # A corrected credit is shown at once; revoking hides the cover everywhere.
        corrected = _rights(
            media, staff, cover, verified=True, attribution={**CREDIT, "text": "Photo: Ana S."}
        )
        assert corrected.json()["attribution"]["text"] == "Photo: Ana S."
        revoked = _rights(media, staff, cover, verified=False)
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["rights_verified_at"] is None
        # A takedown deletes the stored renditions: their URLs may be cached anywhere.
        assert revoked.json()["status"] == "deleted"
        assert revoked.json()["ref"] is None
        queued = db_scalar(
            media.db_url,
            "SELECT count(*) FROM asynchronous_jobs WHERE kind = 'media.delete_objects' "
            "AND payload->>'public_keys' LIKE :m",
            m=f"%{cover}%",
        )
        assert queued == 1
        _problem(_rights(media, staff, cover, verified=True), 409, "conflict")
        assert media.client.get(f"/v1/destinations/{destination}").json()["cover"] is None

        audits = db_scalar(
            media.db_url,
            "SELECT string_agg(action, '|' ORDER BY action) FROM audit_logs WHERE resource_id = :m",
            m=cover,
        )
        assert audits == "media.rights_revoked|media.rights_verified|media.rights_verified"
        # Cached web pages are purged on the cover change and on each rights change (SAFE-012).
        events = db_scalar(
            media.db_url,
            "SELECT count(*) FROM outbox_events WHERE event_type = 'destination.updated' "
            "AND aggregate_id = :d AND payload->'changed' = '[\"cover\"]'::jsonb",
            d=uuid.UUID(destination),
        )
        assert events == 3  # set, corrected credit, revoked

        # User media can never become a cover; null removes the cover.
        post_media = _upload(media, staff, jpeg_with_gps(), purpose="post")
        wrong = media.client.patch(url, headers=_admin(staff), json={"cover_media_id": post_media})
        _problem(wrong, 422, "validation_failed")
        assert wrong.json()["errors"][0]["code"] == "not_editorial"
        pending = _upload(media, staff, jpeg_with_gps(), purpose="editorial", attribution=CREDIT)
        not_ready = media.client.patch(url, headers=_admin(staff), json={"cover_media_id": pending})
        assert not_ready.json()["errors"][0]["code"] == "not_ready"
        # Rights are verified only once the image is processed (the uploader still owns it).
        _problem(_rights(media, staff, pending, verified=True), 409, "conflict")
        cleared = media.client.patch(url, headers=_admin(staff), json={"cover_media_id": None})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["cover"] is None
        _problem(_rights(media, staff, post_media, verified=True), 404, "not_found")
    finally:  # the seeded catalog is shared by other tests
        db_scalar(
            media.db_url,
            "UPDATE destinations SET cover_media_id = NULL WHERE id = :d RETURNING 1",
            d=uuid.UUID(destination),
        )
