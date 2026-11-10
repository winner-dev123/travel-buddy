"""Personal-data export (BL-6.03; AUTH-011, SAFE-010): request, archive, 7-day link, expiry."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _create, _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _request(live: LiveApp, token: str, key: str | None = None) -> Any:
    return live.client.post(
        "/v1/users/me/data-exports",
        headers={**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())},
    )


def _requests(live: LiveApp, token: str) -> dict[str, Any]:
    response = live.client.get("/v1/users/me/data-requests", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "DataSubjectRequestPage")
    body: dict[str, Any] = response.json()
    return body


def _archive(live: LiveApp, url: str) -> zipfile.ZipFile:
    link = live.client.get(urlparse(url).path, follow_redirects=False)
    assert link.status_code == 307, link.text
    stored = live.client.get(urlparse(link.headers["location"]).path)
    assert stored.status_code == 200, stored.text
    return zipfile.ZipFile(io.BytesIO(stored.content))


@pytest.mark.req("AUTH-011", "SAFE-010")
def test_exports_archive_my_data_without_secrets_or_others(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _user(app)
    other, other_id = _user(app)
    assert _create(app, token, body="My own tip about the tram.").status_code == 201
    assert _create(app, other, body="Someone else's secret spot.").status_code == 201

    key = str(uuid.uuid4())
    requested = _request(app, token, key)
    assert requested.status_code == 202, requested.text
    assert_matches_contract(requested.json(), "DataSubjectRequest")
    assert (requested.json()["kind"], requested.json()["status"]) == ("export", "received")
    replay = _request(app, token, key)
    assert replay.json()["id"] == requested.json()["id"]
    assert replay.headers["idempotent-replayed"] == "true"
    _problem(_request(app, token), 409, "conflict")  # one export at a time

    _tick(app)  # builds the archive
    _tick(app)  # relays "ready"
    _tick(app)  # notifications
    [export] = [r for r in _requests(app, token)["data"] if r["kind"] == "export"]
    assert export["status"] == "completed"
    assert export["download"] is not None
    with _archive(app, export["download"]["url"]) as archive:
        names = set(archive.namelist())
        assert {
            "README.txt",
            "manifest.json",
            "account.json",
            "posts.json",
            "sessions.json",
        } <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["user_id"] == user_id
        account = json.loads(archive.read("account.json"))
        assert [row["id"] for row in account] == [user_id]
        posts = json.loads(archive.read("posts.json"))
        assert [p["body"] for p in posts] == ["My own tip about the tram."]
        everything = b" ".join(archive.read(name) for name in names).decode()
    assert other_id not in everything  # nobody else's records
    assert "secret spot" not in everything
    for secret in ("refresh_token_hash", "token_hash", "ciphertext", "idempotency"):
        assert secret not in everything
    notices = app.client.get("/v1/notifications", headers=_auth(token)).json()["data"]
    assert any(n["type"] == "data_export_ready" for n in notices)

    # The link is the only key, and it dies with the archive.
    _problem(
        app.client.get("/v1/data-exports/not-a-token", follow_redirects=False), 404, "not_found"
    )
    assert _request(app, token).status_code == 202  # the next export may start
    db_scalar(
        app.db_url,
        "UPDATE data_subject_requests SET expires_at = :t WHERE id = :r RETURNING 1",
        t=app.clock.now() - timedelta(seconds=1),
        r=uuid.UUID(export["id"]),
    )
    _problem(
        app.client.get(urlparse(export["download"]["url"]).path, follow_redirects=False),
        404,
        "not_found",
    )
    db_scalar(
        app.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'identity.data_export_cleanup' RETURNING 1",
    )
    _tick(app)
    _tick(app)
    assert (
        db_scalar(
            app.db_url,
            "SELECT artifact_key FROM data_subject_requests WHERE id = :r",
            r=uuid.UUID(export["id"]),
        )
        is None
    )
    listed = [r for r in _requests(app, token)["data"] if r["id"] == export["id"]]
    assert listed[0]["download"] is None
