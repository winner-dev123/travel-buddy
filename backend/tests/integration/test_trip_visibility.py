"""Who can read a trip: connections, group members, blocks (BL-4.04; TRIP-001, TRIP-005)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp
from tests.integration.test_billing import store  # noqa: F401 - dev billing app fixture
from tests.integration.test_connections import _send
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _group, _join, _premium
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _user
from tests.integration.test_trips import _create, _trip, _write

pytestmark = pytest.mark.integration


def _read(live: LiveApp, token: str, trip_id: str) -> Any:
    return live.client.get(f"/v1/trips/{trip_id}", headers=_auth(token))


def _connect(live: LiveApp, a: str, b: str, b_id: str) -> None:
    sent = _send(live, a, b_id)
    assert sent.status_code == 201, sent.text
    accepted = live.client.post(
        f"/v1/connections/requests/{sent.json()['id']}/accept", headers=_auth(b)
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.req("TRIP-005", "SAFE-001")
def test_connection_trips_are_visible_to_connections_only(store: LiveApp) -> None:  # noqa: F811
    owner, owner_id = _user(store)
    friend, friend_id = _user(store)
    stranger, _ = _user(store)
    _connect(store, friend, owner, owner_id)
    trip = _trip(store, owner, visibility="connections")
    assert _read(store, friend, trip["id"]).status_code == 200
    _problem(_read(store, stranger, trip["id"]), 404, "not_found")
    # Reading is not editing.
    _problem(
        _write(
            store, friend, "patch", f"/v1/trips/{trip['id']}", trip["version"], {"title": "Mine"}
        ),
        403,
        "forbidden",
    )
    # A public trip still hides from someone the owner blocked.
    public = _trip(store, owner, visibility="public")
    assert _read(store, stranger, public["id"]).status_code == 200
    blocked = store.client.put(f"/v1/users/{friend_id}/block", headers=_auth(owner))
    assert blocked.status_code in (200, 204), blocked.text
    _problem(_read(store, friend, public["id"]), 404, "not_found")
    _problem(_read(store, friend, trip["id"]), 404, "not_found")


@pytest.mark.req("TRIP-005", "GRP-001")
def test_group_trips_are_shared_with_the_group(store: LiveApp) -> None:  # noqa: F811
    owner, _, _ = _premium(store)
    group = _group(store, owner)
    member, _ = _join(store, owner, group["id"])
    outsider, _ = _user(store)
    trip = _trip(store, owner, visibility="group", group_id=group["id"])
    assert trip["group_id"] == group["id"]
    assert _read(store, member, trip["id"]).status_code == 200
    _problem(_read(store, outsider, trip["id"]), 404, "not_found")
    _problem(_create(store, owner, visibility="group"), 422, "validation_failed")
    # Only a group you belong to.
    _problem(
        _create(store, outsider, visibility="group", group_id=group["id"]), 422, "validation_failed"
    )
    # Moving the trip back to private takes it away from the group.
    updated = _write(
        store, owner, "patch", f"/v1/trips/{trip['id']}", trip["version"], {"visibility": "private"}
    )
    assert updated.status_code == 200, updated.text
    _problem(_read(store, member, trip["id"]), 404, "not_found")


def _share(live: LiveApp, token: str, trip_id: str, user_id: str, role: str) -> Any:
    return live.client.put(
        f"/v1/trips/{trip_id}/collaborators/{user_id}", headers=_auth(token), json={"role": role}
    )


@pytest.mark.req("TRIP-005")
def test_owners_share_private_trips_with_connections_and_group_members(
    store: LiveApp,  # noqa: F811
) -> None:
    owner, owner_id = _premium(store)[:2]
    friend, friend_id = _user(store)
    _, stranger_id = _user(store)
    _connect(store, friend, owner, owner_id)
    trip = _trip(store, owner)  # private
    shared = _share(store, owner, trip["id"], friend_id, "editor")
    assert shared.status_code == 200, shared.text
    assert_matches_contract(shared.json(), "Trip")
    assert [(c["user"]["id"], c["role"]) for c in shared.json()["collaborators"]] == [
        (friend_id, "editor")
    ]
    edited = _write(
        store,
        friend,
        "patch",
        f"/v1/trips/{trip['id']}",
        shared.json()["version"],
        {"title": "Ours"},
    )
    assert edited.status_code == 200, edited.text
    _problem(_share(store, owner, trip["id"], stranger_id, "viewer"), 403, "connection_required")
    _problem(_share(store, friend, trip["id"], stranger_id, "viewer"), 403, "forbidden")
    _problem(_share(store, owner, trip["id"], owner_id, "viewer"), 422, "validation_failed")

    viewer = _share(store, owner, trip["id"], friend_id, "viewer").json()
    _problem(
        _write(
            store, friend, "patch", f"/v1/trips/{trip['id']}", viewer["version"], {"title": "x"}
        ),
        403,
        "forbidden",
    )
    left = store.client.delete(
        f"/v1/trips/{trip['id']}/collaborators/{friend_id}", headers=_auth(friend)
    )
    assert left.status_code == 204, left.text
    _problem(_read(store, friend, trip["id"]), 404, "not_found")

    # Members of the trip's group can be added without being connections.
    group = _group(store, owner)
    member, member_id = _join(store, owner, group["id"])
    group_trip = _trip(store, owner, group_id=group["id"])
    added = _share(store, owner, group_trip["id"], member_id, "viewer")
    assert added.status_code == 200, added.text
    assert _read(store, member, group_trip["id"]).status_code == 200
