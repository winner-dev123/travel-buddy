"""Phase 3 journey (BL-3.13): connect → message, buy premium (dev store) → create a group,
invite by link → talk in the group chat."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp
from tests.integration.test_billing import MONTHLY, _verify, store  # noqa: F401
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _destination, _tick, _user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.req("DM-001", "CONN-003", "BILL-004", "GRP-001", "GRP-005", "GCHAT-001"),
]


def _ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def test_from_connection_to_group_chat(store: LiveApp) -> None:  # noqa: F811
    client = store.client
    ana, _ = _user(store)
    bo, bo_id = _user(store)

    # 1. Ana asks to connect; Bo accepts.
    request = _ok(
        client.post(
            "/v1/connections/requests",
            headers={**_auth(ana), "Idempotency-Key": str(uuid.uuid4())},
            json={"recipient_id": bo_id, "context": "profile", "note": "Fellow foodie!"},
        ),
        201,
    )
    _ok(client.post(f"/v1/connections/requests/{request['id']}/accept", headers=_auth(bo)))

    # 2. They talk in a direct conversation; Bo sees it unread, replies, reads.
    profile = _ok(client.get(f"/v1/users/{bo_id}", headers=_auth(ana)))
    assert profile["can_message"] is True
    dm = _ok(
        client.post(
            "/v1/conversations", headers=_auth(ana), json={"kind": "direct", "user_id": bo_id}
        ),
        201,
    )
    _ok(
        client.post(
            f"/v1/conversations/{dm['id']}/messages",
            headers={**_auth(ana), "Idempotency-Key": str(uuid.uuid4())},
            json={"client_message_id": str(uuid.uuid4()), "body": "Dinner in Alfama tonight?"},
        ),
        201,
    )
    [inbox] = _ok(client.get("/v1/conversations", headers=_auth(bo)))["data"]
    assert inbox["unread_count"] == 1
    _ok(
        client.post(
            f"/v1/conversations/{dm['id']}/messages",
            headers={**_auth(bo), "Idempotency-Key": str(uuid.uuid4())},
            json={"client_message_id": str(uuid.uuid4()), "body": "Yes! 8pm?"},
        ),
        201,
    )
    _ok(
        client.put(
            f"/v1/conversations/{dm['id']}/receipts",
            headers=_auth(bo),
            json={"read_through_seq": 2},
        )
    )
    _tick(store)
    assert any(
        n["type"] == "new_message"
        for n in _ok(client.get("/v1/notifications", headers=_auth(ana)))["data"]
    )

    # 3. Ana goes premium through the (dev) store and creates a group.
    purchase = _ok(_verify(store, ana, f"dev:{MONTHLY}:e2e-{uuid.uuid4().hex[:8]}"))
    assert purchase["entitlements"]["features"]["groups.create"] is True
    group = _ok(
        client.post(
            "/v1/groups",
            headers={**_auth(ana), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "name": "Alfama supper club",
                "primary_destination_id": _destination(store, "portugal/lisbon"),
                "member_capacity": 8,
            },
        ),
        201,
    )
    assert_matches_contract(group, "Group")

    # 4. Bo (free) joins with a link and both talk in the group chat.
    link = _ok(
        client.post(
            f"/v1/groups/{group['id']}/invitations", headers=_auth(ana), json={"kind": "link"}
        ),
        201,
    )
    preview = _ok(
        client.post(
            "/v1/group-invitations/preview", headers=_auth(bo), json={"token": link["token"]}
        )
    )
    assert preview["group"]["name"] == "Alfama supper club"
    _ok(
        client.post(
            "/v1/group-invitations/redeem", headers=_auth(bo), json={"token": link["token"]}
        )
    )
    chat = group["conversation_id"]
    _ok(
        client.post(
            f"/v1/groups/{group['id']}/announcements",
            headers={**_auth(ana), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "client_message_id": str(uuid.uuid4()),
                "body": "Welcome! First stop: Ti-Natércia",
            },
        ),
        201,
    )
    _ok(
        client.post(
            f"/v1/conversations/{chat}/messages",
            headers={**_auth(bo), "Idempotency-Key": str(uuid.uuid4())},
            json={"client_message_id": str(uuid.uuid4()), "body": "Can't wait 🎉"},
        ),
        201,
    )
    history = _ok(client.get(f"/v1/conversations/{chat}/messages", headers=_auth(ana)))
    assert [m["kind"] for m in history["data"]] == ["announcement", "text"]
    conversations = _ok(client.get("/v1/conversations", headers=_auth(bo)))["data"]
    assert {c["kind"] for c in conversations} == {"direct", "group"}
