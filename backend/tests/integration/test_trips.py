"""Trips, itineraries and offline sync end to end (BL-4.04; TRIP-001, TRIP-004, TRIP-005)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _create as _create_post
from tests.integration.test_posts import _destination, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _create(live: LiveApp, token: str, **overrides: Any) -> Any:
    body = {
        "title": "Lisbon long weekend",
        "start_date": "2026-12-04",
        "end_date": "2026-12-06",
        "destination_ids": [_destination(live, "portugal/lisbon")],
        **overrides,
    }
    return live.client.post(
        "/v1/trips", headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())}, json=body
    )


def _trip(live: LiveApp, token: str, **overrides: Any) -> dict[str, Any]:
    response = _create(live, token, **overrides)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _write(live: LiveApp, token: str, method: str, url: str, version: int, body: Any = None) -> Any:
    kwargs: dict[str, Any] = {"headers": {**_auth(token), "If-Match": f'"{version}"'}}
    if body is not None:
        kwargs["json"] = body
    return getattr(live.client, method)(url, **kwargs)


def _items(trip: dict[str, Any], day: int = 0) -> list[str]:
    return [item["title"] for item in trip["days"][day]["items"]]


@pytest.mark.req("TRIP-001")
def test_create_a_trip_with_a_day_per_date(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _user(app)
    created = _create(app, token)
    assert created.status_code == 201, created.text
    assert_matches_contract(created.json(), "Trip")
    assert created.headers["etag"] == '"1"'
    trip = created.json()
    assert trip["owner"]["id"] == user_id
    assert [d["date"] for d in trip["days"]] == ["2026-12-04", "2026-12-05", "2026-12-06"]
    assert trip["destinations"][0]["destination"]["path"] == "portugal/lisbon"
    _problem(_create(app, token, end_date="2026-12-01"), 422, "validation_failed")
    _problem(_create(app, token, visibility="group"), 422, "validation_failed")  # no group

    listed = app.client.get("/v1/trips", headers=_auth(token)).json()
    assert_matches_contract(listed, "TripSummaryPage")
    [summary] = [t for t in listed["data"] if t["id"] == trip["id"]]
    assert summary["role"] == "owner"

    stranger, _ = _user(app)
    _problem(app.client.get(f"/v1/trips/{trip['id']}", headers=_auth(stranger)), 404, "not_found")


@pytest.mark.req("TRIP-001", "TRIP-005")
def test_items_order_move_and_tombstone_with_versions(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    trip = _trip(app, token)
    tid, day0, day1 = trip["id"], trip["days"][0]["id"], trip["days"][1]["id"]
    url = f"/v1/trips/{tid}/days/{day0}/items"
    _problem(
        app.client.post(url, headers=_auth(token), json={"kind": "meal", "title": "x"}),
        428,
        "precondition_required",
    )
    _problem(
        _write(app, token, "post", url, 9, {"kind": "meal", "title": "x"}),
        412,
        "precondition_failed",
    )

    trip = _write(
        app,
        token,
        "post",
        url,
        1,
        {"kind": "meal", "title": "Pastéis de Belém", "start_time": "09:30"},
    ).json()
    trip = _write(
        app, token, "post", url, trip["version"], {"kind": "activity", "title": "Tram 28"}
    ).json()
    first = trip["days"][0]["items"][0]["id"]
    trip = _write(
        app,
        token,
        "post",
        url,
        trip["version"],
        {
            "kind": "activity",
            "title": "Alfama walk",
            "after_item_id": first,
            "duration_minutes": 90,
        },
    ).json()
    assert _items(trip) == ["Pastéis de Belém", "Alfama walk", "Tram 28"]
    assert trip["version"] == 4
    assert trip["days"][0]["items"][0]["start_time"] == "09:30"

    # Per the contract, an explicit null puts the item first; leaving the field out appends it.
    alfama = trip["days"][0]["items"][1]["id"]
    trip = _write(
        app, token, "patch", f"/v1/trips/{tid}/items/{alfama}", 4, {"after_item_id": None}
    ).json()
    assert _items(trip) == ["Alfama walk", "Pastéis de Belém", "Tram 28"]
    trip = _write(
        app,
        token,
        "post",
        url,
        trip["version"],
        {"kind": "note", "title": "Coffee", "after_item_id": None},
    ).json()
    assert _items(trip) == ["Coffee", "Alfama walk", "Pastéis de Belém", "Tram 28"]
    coffee = trip["days"][0]["items"][0]["id"]
    trip = _write(app, token, "delete", f"/v1/trips/{tid}/items/{coffee}", trip["version"]).json()
    trip = _write(
        app,
        token,
        "patch",
        f"/v1/trips/{tid}/items/{first}",
        trip["version"],
        {"after_item_id": None},
    ).json()
    assert _items(trip) == ["Pastéis de Belém", "Alfama walk", "Tram 28"]

    tram = trip["days"][0]["items"][2]["id"]
    moved = _write(
        app, token, "patch", f"/v1/trips/{tid}/items/{tram}", trip["version"], {"day_id": day1}
    )
    assert moved.status_code == 200, moved.text
    trip = moved.json()
    assert _items(trip, 0) == ["Pastéis de Belém", "Alfama walk"]
    assert _items(trip, 1) == ["Tram 28"]

    trip = _write(app, token, "delete", f"/v1/trips/{tid}/items/{first}", trip["version"]).json()
    assert _items(trip, 0) == ["Alfama walk"]
    tombstones = db_scalar(
        app.db_url,
        "SELECT count(*) FROM itinerary_items WHERE id = :i AND deleted_at IS NOT NULL",
        i=uuid.UUID(first),
    )
    assert tombstones == 1  # kept for offline sync

    trip = _write(
        app, token, "post", f"/v1/trips/{tid}/days", trip["version"], {"notes": "Sintra?"}
    ).json()
    assert [d["day_index"] for d in trip["days"]] == [0, 1, 2, 3]
    assert trip["days"][3]["date"] == "2026-12-07"
    renamed = _write(
        app, token, "patch", f"/v1/trips/{tid}", trip["version"], {"title": "Lisbon & Sintra"}
    )
    assert renamed.json()["title"] == "Lisbon & Sintra"
    assert renamed.headers["etag"] == f'"{trip["version"] + 1}"'


@pytest.mark.req("TRIP-005")
def test_public_trips_are_read_only_and_collaborators_edit(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    trip = _trip(app, token, visibility="public")
    reader, _ = _user(app)
    assert app.client.get(f"/v1/trips/{trip['id']}", headers=_auth(reader)).status_code == 200
    _problem(
        _write(app, reader, "patch", f"/v1/trips/{trip['id']}", 1, {"title": "Mine now"}),
        403,
        "forbidden",
    )
    editor, editor_id = _user(app)
    db_scalar(
        app.db_url,
        "INSERT INTO trip_collaborators (trip_id, user_id, role) "
        "VALUES (:t, :u, 'editor') RETURNING 1",
        t=uuid.UUID(trip["id"]),
        u=uuid.UUID(editor_id),
    )
    edited = _write(app, editor, "patch", f"/v1/trips/{trip['id']}", 1, {"status": "active"})
    assert edited.status_code == 200, edited.text
    assert any(c["user"]["id"] == editor_id for c in edited.json()["collaborators"])
    _problem(app.client.delete(f"/v1/trips/{trip['id']}", headers=_auth(editor)), 403, "forbidden")
    assert app.client.delete(f"/v1/trips/{trip['id']}", headers=_auth(token)).status_code == 204
    _problem(app.client.get(f"/v1/trips/{trip['id']}", headers=_auth(token)), 404, "not_found")


@pytest.mark.req("TRIP-004")
def test_offline_sync_merges_and_surfaces_conflicts(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    trip = _trip(app, token)
    tid, day0 = trip["id"], trip["days"][0]["id"]
    trip = _write(
        app,
        token,
        "post",
        f"/v1/trips/{tid}/days/{day0}/items",
        1,
        {"kind": "meal", "title": "Lunch"},
    ).json()
    lunch = trip["days"][0]["items"][0]["id"]
    base = trip["version"]
    offline_edit = datetime.now(tz=UTC) - timedelta(minutes=10)  # edited on the plane

    # Meanwhile someone renames the lunch on the server.
    trip = _write(
        app, token, "patch", f"/v1/trips/{tid}/items/{lunch}", base, {"title": "Late lunch"}
    ).json()

    new_item = str(uuid.uuid4())
    key = str(uuid.uuid4())
    payload = {
        "base_version": base,
        "operations": [
            {
                "op_id": str(uuid.uuid4()),
                "entity": "item",
                "action": "create",
                "entity_id": new_item,
                "parent_id": day0,
                "fields": {"kind": "activity", "title": "LX Factory"},
                "client_updated_at": offline_edit.isoformat(),
            },
            {
                "op_id": str(uuid.uuid4()),
                "entity": "item",
                "action": "update",
                "entity_id": lunch,
                "fields": {"title": "Seafood lunch"},
                "client_updated_at": offline_edit.isoformat(),
            },
            {
                "op_id": str(uuid.uuid4()),
                "entity": "item",
                "action": "update",
                "entity_id": new_item,
                "fields": {"title": ""},
                "client_updated_at": offline_edit.isoformat(),
            },
            {
                "op_id": str(uuid.uuid4()),
                "entity": "item",
                "action": "delete",
                "entity_id": str(uuid.uuid4()),
                "client_updated_at": offline_edit.isoformat(),
            },
        ],
    }
    synced = app.client.post(
        f"/v1/trips/{tid}/sync", headers={**_auth(token), "Idempotency-Key": key}, json=payload
    )
    assert synced.status_code == 200, synced.text
    assert_matches_contract(synced.json(), "TripSyncResult")
    result = synced.json()
    reasons = {c["reason"] for c in result["conflicts"]}
    assert reasons == {"modified_on_server", "invalid"}
    [server] = [c for c in result["conflicts"] if c["reason"] == "modified_on_server"]
    assert server["server_state"]["title"] == "Late lunch"  # the newer server write wins
    assert len(result["applied_op_ids"]) == 2  # the create and the no-op delete
    assert _items(result["trip"]) == ["Late lunch", "LX Factory"]
    assert result["trip"]["version"] == trip["version"] + 1

    replay = app.client.post(
        f"/v1/trips/{tid}/sync", headers={**_auth(token), "Idempotency-Key": key}, json=payload
    )
    assert replay.json() == result  # retried batches apply once

    # A newer offline edit wins over the server's older state.
    later = datetime.now(tz=UTC) + timedelta(minutes=1)
    newer = app.client.post(
        f"/v1/trips/{tid}/sync",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "base_version": base,
            "operations": [
                {
                    "op_id": str(uuid.uuid4()),
                    "entity": "item",
                    "action": "update",
                    "entity_id": lunch,
                    "fields": {"title": "Seafood lunch"},
                    "client_updated_at": later.isoformat(),
                },
            ],
        },
    ).json()
    assert newer["conflicts"] == []
    assert _items(newer["trip"])[0] == "Seafood lunch"


@pytest.mark.req("TRIP-006", "POST-001")
def test_publish_an_itinerary_summary_of_my_trip(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    trip = _trip(app, token)
    summary = _create_post(
        app,
        token,
        kind="itinerary_summary",
        body="Three days in Lisbon: Alfama, Belém and a day trip to Sintra.",
        trip_id=trip["id"],
        location_precision="destination",
        destination_id=_destination(app, "portugal/lisbon"),
    )
    assert summary.status_code == 201, summary.text
    assert_matches_contract(summary.json(), "Post")
    assert summary.json()["trip_id"] == trip["id"]

    stranger, _ = _user(app)
    theirs = _create_post(
        app, stranger, kind="itinerary_summary", body="Mine now", trip_id=trip["id"]
    )
    assert _problem(theirs, 422, "validation_failed")["errors"][0]["field"] == "/trip_id"
    missing = _create_post(app, token, kind="itinerary_summary", body="No trip")
    assert _problem(missing, 422, "validation_failed")["errors"][0]["field"] == "/trip_id"
