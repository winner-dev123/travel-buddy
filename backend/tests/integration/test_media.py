"""Media uploads end to end against the in-process store (BL-1.08; POST-004, SAFE-004,
T-MED-01/04)."""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr

from app.core.config import AppEnv
from app.core.time import FixedClock
from app.main import create_app
from app.modules.media.config import MediaSettings
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, _truncate_users, db_scalar
from tests.integration.test_identity_flows import _auth
from tests.integration.test_messaging import _connect
from tests.integration.test_posts import CRON, _problem, _tick, _user
from tests.unit.test_media_processing import jpeg_with_gps

pytestmark = [pytest.mark.integration, pytest.mark.req("POST-004", "SAFE-004")]


def _media_app(
    db_url: str, storage: str, flags: dict[str, bool] | None = None
) -> Iterator[LiveApp]:
    _truncate_users(db_url)
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))

    async def ok() -> bool:
        return True

    app = create_app(
        make_settings(
            database_url=db_url,
            dev_idp_enabled=True,
            cron_secret=SecretStr(CRON),
            feature_flags=flags or {},
        ),
        identity_settings=make_identity_settings(),
        media_settings=MediaSettings(
            _env_file=None,  # type: ignore[call-arg]
            app_env=AppEnv.TEST,
            media_storage=storage,  # type: ignore[arg-type]
            media_local_base_url="http://testserver",
        ),
        readiness_checks={"db": ok},
        clock=clock,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=db_url)


@pytest.fixture
def media(schema_db_url: str) -> Iterator[LiveApp]:
    yield from _media_app(schema_db_url, "local")


def _request(live: LiveApp, token: str, data: bytes, key: str | None = None, **body: Any) -> Any:
    payload = {
        "purpose": "post",
        "mime_type": "image/jpeg",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "alt_text": "Sunset over the river",
        **body,
    }
    return live.client.post(
        "/v1/media/uploads",
        headers={**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())},
        json=payload,
    )


def _upload(live: LiveApp, token: str, data: bytes, **body: Any) -> str:
    created = _request(live, token, body.pop("declared", data), **body)
    assert created.status_code == 201, created.text
    target = created.json()["upload"]
    put = live.client.put(target["url"], content=data, headers=target["headers"])
    assert put.status_code == 200, put.text
    return str(created.json()["media_id"])


def _asset(live: LiveApp, token: str, media_id: str) -> dict[str, Any]:
    response = live.client.get(f"/v1/media/{media_id}", headers=_auth(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_contract(body, "MediaAsset")
    return body


def _finalize(live: LiveApp, token: str, media_id: str) -> Any:
    return live.client.post(f"/v1/media/{media_id}/finalize", headers=_auth(token))


def test_upload_finalize_and_serve_metadata_free_variants(media: LiveApp) -> None:
    token, _ = _user(media)
    data = jpeg_with_gps()
    key = str(uuid.uuid4())
    created = _request(media, token, data, key)
    assert created.status_code == 201, created.text
    assert_matches_contract(created.json(), "MediaUpload")
    replay = _request(media, token, data, key)
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json()["media_id"] == created.json()["media_id"]
    media_id = created.json()["media_id"]
    target = created.json()["upload"]
    assert target["method"] == "PUT"
    put = media.client.put(target["url"], content=data, headers=target["headers"])
    assert put.status_code == 200, put.text
    assert _asset(media, token, media_id)["status"] == "pending_upload"

    finalized = _finalize(media, token, media_id)
    assert finalized.status_code == 202, finalized.text
    assert finalized.json()["status"] == "scanning"
    assert finalized.json()["ref"]["status"] == "processing"
    _tick(media)

    asset = _asset(media, token, media_id)
    assert asset["status"] == "ready"
    assert (asset["width"], asset["height"]) == (1000, 2000)  # EXIF orientation applied
    ref = asset["ref"]
    assert (ref["status"], ref["kind"], ref["alt_text"]) == (
        "ready",
        "image",
        "Sunset over the river",
    )
    served = media.client.get(ref["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert "immutable" in served.headers["cache-control"]
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.size == (1000, 2000)
        assert not image.getexif()  # GPS and camera data are gone
    assert _finalize(media, token, media_id).status_code == 202  # idempotent


@pytest.mark.security
def test_media_is_private_to_its_owner_and_must_be_uploaded_first(media: LiveApp) -> None:
    owner, _ = _user(media)
    other, _ = _user(media)
    data = jpeg_with_gps(64, 64)
    created = _request(media, owner, data).json()
    _problem(_finalize(media, owner, created["media_id"]), 409, "conflict")
    _problem(
        media.client.get(f"/v1/media/{created['media_id']}", headers=_auth(other)), 404, "not_found"
    )
    _problem(_finalize(media, other, created["media_id"]), 404, "not_found")
    # The presigned URL accepts exactly the declared type and size.
    target = created["upload"]
    wrong_size = media.client.put(target["url"], content=data + b"x", headers=target["headers"])
    assert wrong_size.status_code == 403
    wrong_type = media.client.put(
        target["url"], content=data, headers={"Content-Type": "image/png"}
    )
    assert wrong_type.status_code == 403


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"mime_type": "image/heic"}, 415, "unsupported_media_type"),
        ({"mime_type": "video/mp4"}, 415, "unsupported_media_type"),
        ({"purpose": "avatar", "mime_type": "video/mp4"}, 415, "unsupported_media_type"),
        ({"purpose": "avatar", "bytes": 10 * 1024 * 1024 + 1}, 413, "payload_too_large"),
        ({"purpose": "post", "bytes": 25 * 1024 * 1024 + 1}, 413, "payload_too_large"),
        ({"sha256": "nothex"}, 422, "validation_failed"),
    ],
)
@pytest.mark.security
def test_type_and_size_limits_per_purpose(
    media: LiveApp, body: dict[str, Any], status: int, code: str
) -> None:
    token, _ = _user(media)
    _problem(_request(media, token, b"\xff\xd8\xff\xe0", **body), status, code)


@pytest.mark.req("POST-004")
def test_video_uploads_wait_for_the_post_video_flag(schema_db_url: str) -> None:
    for live in _media_app(schema_db_url, "local", {"post_video": False}):
        token, _ = _user(live)
        refused = _request(live, token, b"\x00\x00\x00\x18ftypmp42", mime_type="video/mp4")
        _problem(refused, 403, "feature_disabled")
        assert refused.json()["feature_key"] == "post_video"
        photo = _request(live, token, b"\xff\xd8\xff\xe0")
        assert photo.status_code == 201, photo.text


def test_unverified_accounts_cannot_upload(media: LiveApp) -> None:
    token, _ = _user(media, verified=False)
    _problem(_request(media, token, jpeg_with_gps(32, 32)), 403, "email_unverified")


@pytest.mark.security
@pytest.mark.parametrize(
    ("declared_body", "reason"),
    [
        ({"mime_type": "image/png"}, "type_mismatch"),
        ({"tamper_hash": True}, "hash_mismatch"),
    ],
)
def test_content_that_differs_from_its_declaration_is_rejected(
    media: LiveApp, declared_body: dict[str, Any], reason: str
) -> None:
    token, _ = _user(media)
    data = jpeg_with_gps(64, 64)
    body = dict(declared_body)
    if body.pop("tamper_hash", False):
        body["sha256"] = hashlib.sha256(b"something else").hexdigest()
    media_id = _upload(media, token, data, **body)
    assert _finalize(media, token, media_id).status_code == 202
    _tick(media)
    asset = _asset(media, token, media_id)
    assert (asset["status"], asset["rejection_reason"]) == ("rejected", reason)
    assert asset["ref"]["status"] == "unavailable"
    assert asset["ref"]["url"] is None


@pytest.fixture
def no_storage(schema_db_url: str) -> Iterator[LiveApp]:
    yield from _media_app(schema_db_url, "disabled")


def test_uploads_answer_503_without_storage(no_storage: LiveApp) -> None:
    token, _ = _user(no_storage)
    _problem(_request(no_storage, token, jpeg_with_gps(16, 16)), 503, "service_unavailable")


@pytest.mark.req("AUTH-010", "POST-004")
def test_account_erasure_deletes_stored_media(media: LiveApp) -> None:
    token, user_id = _user(media)
    media_id = _upload(media, token, jpeg_with_gps(400, 300))
    _finalize(media, token, media_id)
    _tick(media)
    storage = media.client.app.state.media_storage  # type: ignore[attr-defined]
    owned = [key for key in storage.public if key.startswith(f"m/{user_id}/")]
    assert owned  # variants were written
    deletion = media.client.post(
        "/v1/users/me/deletion",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={"confirm": True},
    )
    assert deletion.status_code == 202, deletion.text
    db_scalar(
        media.db_url,
        "UPDATE users SET deletion_requested_at = now() - interval '31 days' "
        "WHERE id = :u RETURNING 1",
        u=uuid.UUID(user_id),
    )
    db_scalar(
        media.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' RETURNING 1",
    )
    _tick(media)
    _tick(media)
    assert not [key for key in storage.public if key.startswith(f"m/{user_id}/")]


# ─────────────────────────────── photos on posts ───────────────────────────────


def _photo_post(live: LiveApp, token: str, media_ids: list[str], **body: Any) -> Any:
    payload = {
        "kind": "photo",
        "body": "Golden hour at the viewpoint",
        "visibility": "public",
        "location_precision": "none",
        "media_ids": media_ids,
        **body,
    }
    return live.client.post(
        "/v1/posts",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json=payload,
    )


@pytest.mark.req("POST-001", "POST-004")
def test_photo_posts_show_a_placeholder_until_media_is_ready(media: LiveApp) -> None:
    token, _ = _user(media)
    first = _upload(media, token, jpeg_with_gps(600, 400))
    second = _upload(media, token, jpeg_with_gps(500, 500, orientation=1))
    for media_id in (first, second):
        _finalize(media, token, media_id)
    created = _photo_post(media, token, [second, first])
    assert created.status_code == 201, created.text
    post = created.json()
    assert_matches_contract(post, "Post")
    assert [m["id"] for m in post["media"]] == [second, first]  # caller's order
    assert {m["status"] for m in post["media"]} == {"processing"}
    _tick(media)
    shown = media.client.get(f"/v1/posts/{post['id']}", headers=_auth(token)).json()
    assert [(m["status"], m["url"] is not None) for m in shown["media"]] == [
        ("ready", True),
        ("ready", True),
    ]
    public = media.client.get(f"/v1/public/posts/{post['id']}")
    assert public.status_code == 200
    assert len(public.json()["media"]) == 2


@pytest.mark.security
def test_only_your_own_uploaded_post_media_can_be_attached(media: LiveApp) -> None:
    owner, _ = _user(media)
    other, _ = _user(media)
    theirs = _upload(media, other, jpeg_with_gps(64, 64))
    _finalize(media, other, theirs)
    _problem(_photo_post(media, owner, [theirs]), 422, "validation_failed")
    unfinished = _upload(media, owner, jpeg_with_gps(64, 64))  # never finalized
    _problem(_photo_post(media, owner, [unfinished]), 422, "validation_failed")
    _problem(_photo_post(media, owner, [str(uuid.uuid4())]), 422, "validation_failed")
    mine = _upload(media, owner, jpeg_with_gps(64, 64))
    _finalize(media, owner, mine)
    _problem(_photo_post(media, owner, [mine, mine]), 422, "validation_failed")
    avatar = _upload(media, owner, jpeg_with_gps(64, 64), purpose="avatar")
    _finalize(media, owner, avatar)
    _problem(_photo_post(media, owner, [avatar]), 422, "validation_failed")
    _problem(_photo_post(media, owner, []), 422, "validation_failed")  # photo kind needs media


@pytest.mark.req("POST-004", "SAFE-009")
def test_hard_deleting_a_post_removes_its_stored_photos(media: LiveApp) -> None:
    token, user_id = _user(media)
    media_id = _upload(media, token, jpeg_with_gps(300, 200))
    _finalize(media, token, media_id)
    _tick(media)
    post = _photo_post(media, token, [media_id]).json()
    storage = media.client.app.state.media_storage  # type: ignore[attr-defined]
    assert any(key.startswith(f"m/{user_id}/{media_id}/") for key in storage.public)
    media.client.delete(f"/v1/posts/{post['id']}", headers=_auth(token))
    db_scalar(
        media.db_url,
        "UPDATE posts SET deleted_at = now() - interval '31 days' WHERE id = :p RETURNING 1",
        p=uuid.UUID(post["id"]),
    )
    db_scalar(
        media.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' RETURNING 1",
    )
    _tick(media)
    _tick(media)
    assert not any(key.startswith(f"m/{user_id}/{media_id}/") for key in storage.public)
    assert (
        db_scalar(
            media.db_url, "SELECT count(*) FROM media_assets WHERE id = :m", m=uuid.UUID(media_id)
        )
        == 0
    )


# ─────────────────────────────── avatars ───────────────────────────────


@pytest.mark.req("PROF-001", "POST-004")
def test_avatars_appear_everywhere_and_replacing_one_erases_the_old(media: LiveApp) -> None:
    token, user_id = _user(media)
    first = _upload(media, token, jpeg_with_gps(512, 512, orientation=1), purpose="avatar")
    _finalize(media, token, first)
    _tick(media)
    set_avatar = media.client.patch(
        "/v1/users/me", headers=_auth(token), json={"avatar_media_id": first}
    )
    assert set_avatar.status_code == 200, set_avatar.text
    me = media.client.get("/v1/users/me", headers=_auth(token)).json()
    assert_matches_contract(me, "Me")
    assert me["profile"]["avatar"]["id"] == first
    assert me["profile"]["avatar"]["status"] == "ready"

    post = media.client.post(
        "/v1/posts",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "kind": "tip",
            "body": "Bring a jacket",
            "visibility": "public",
            "location_precision": "none",
        },
    ).json()
    assert post["author"]["avatar"]["id"] == first
    viewer, _ = _user(media)
    profile = media.client.get(f"/v1/users/{user_id}", headers=_auth(viewer)).json()
    assert_matches_contract(profile, "PublicProfile")
    assert profile["avatar"]["id"] == first

    second = _upload(media, token, jpeg_with_gps(256, 256, orientation=1), purpose="avatar")
    _finalize(media, token, second)
    media.client.patch("/v1/users/me", headers=_auth(token), json={"avatar_media_id": second})
    _tick(media)
    storage = media.client.app.state.media_storage  # type: ignore[attr-defined]
    assert not any(key.startswith(f"m/{user_id}/{first}/") for key in storage.public)
    assert (
        db_scalar(
            media.db_url, "SELECT count(*) FROM media_assets WHERE id = :m", m=uuid.UUID(first)
        )
        == 0
    )

    photo = _upload(media, token, jpeg_with_gps(64, 64))  # post purpose
    _finalize(media, token, photo)
    _problem(
        media.client.patch("/v1/users/me", headers=_auth(token), json={"avatar_media_id": photo}),
        422,
        "validation_failed",
    )
    cleared = media.client.patch(
        "/v1/users/me", headers=_auth(token), json={"avatar_media_id": None}
    )
    assert cleared.status_code == 200
    assert (
        media.client.get("/v1/users/me", headers=_auth(token)).json()["profile"]["avatar"] is None
    )


@pytest.mark.security
@pytest.mark.req("DM-002")
def test_message_photos_are_private_and_served_through_short_lived_urls(media: LiveApp) -> None:
    ana, ana_id = _user(media)
    bo, bo_id = _user(media)
    _connect(media, ana_id, bo_id)
    conversation = media.client.post(
        "/v1/conversations", headers=_auth(ana), json={"kind": "direct", "user_id": bo_id}
    ).json()["id"]
    media_id = _upload(media, ana, jpeg_with_gps(), purpose="message")
    assert _finalize(media, ana, media_id).status_code == 202
    _tick(media)

    sent = media.client.post(
        f"/v1/conversations/{conversation}/messages",
        headers={**_auth(ana), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "client_message_id": str(uuid.uuid4()),
            "kind": "image",
            "attachment_media_ids": [media_id],
        },
    )
    assert sent.status_code == 201, sent.text
    history = media.client.get(
        f"/v1/conversations/{conversation}/messages", headers=_auth(bo)
    ).json()
    [attachment] = history["data"][0]["attachments"]
    assert attachment["status"] == "ready"
    assert "/_dev/storage/private/" in attachment["url"]
    assert attachment["url_expires_at"] is not None
    served = media.client.get(attachment["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert "private" in served.headers["cache-control"]

    # Nothing reaches the public bucket, and a tampered or expired URL is refused.
    assert not any(key.startswith(f"m/{ana_id}/{media_id}") for key in _local(media).public)
    assert media.client.get(attachment["url"][:-4] + "beef").status_code == 403
    media.clock.set(media.clock.now() + timedelta(minutes=6))
    assert media.client.get(attachment["url"]).status_code == 403

    # Deleting the message erases the stored photo.
    message_id = sent.json()["id"]
    deleted = media.client.delete(
        f"/v1/conversations/{conversation}/messages/{message_id}", headers=_auth(ana)
    )
    assert deleted.status_code == 204
    _tick(media)
    assert not any(media_id in key for key in _local(media).private)


def _local(live: LiveApp) -> Any:
    storage = live.client.app.state.media_storage  # type: ignore[attr-defined]
    return storage
