"""Phase 3 security tests (BL-3.12): message IDOR, cross-group leakage, subscription bypass and
invitation reuse under concurrency (threats T-AZ-*, T-BILL-*, T-GRP-*)."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from tests.integration.conftest import LiveApp
from tests.integration.test_billing import MONTHLY, _verify, store  # noqa: F401
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _group, _invite_link, _join, _premium, _redeem, _say
from tests.integration.test_identity_flows import _auth
from tests.integration.test_messaging import _pair, _sent
from tests.integration.test_posts import _problem, _user

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.mark.req("DM-001", "T-AZ-01")
def test_no_message_operation_works_on_someone_elses_conversation(store: LiveApp) -> None:  # noqa: F811
    ana, _, _, _, conversation = _pair(store)
    message = _sent(store, ana, conversation, "Private plans")
    stranger, _ = _user(store)
    base = f"/v1/conversations/{conversation}"
    item = f"{base}/messages/{message['id']}"
    attempts = [
        ("get", base, None),
        ("get", f"{base}/messages", None),
        ("put", f"{base}/receipts", {"read_through_seq": 1}),
        ("put", f"{base}/mute", {"muted_until": None}),
        ("post", f"{base}/clear", {"through_seq": 1}),
        ("get", f"{base}/pins", None),
        ("put", f"{base}/pins/{message['id']}", None),
        ("patch", item, {"body": "hijacked"}),
        ("delete", item, None),
        ("put", f"{item}/reactions/%F0%9F%91%8D", None),
        ("get", f"{base}/threads/{message['id']}", None),
    ]
    for method, url, body in attempts:
        kwargs: dict[str, Any] = {"headers": _auth(stranger)}
        if body is not None:
            kwargs["json"] = body
        response = getattr(store.client, method)(url, **kwargs)
        assert response.status_code == 404, (method, url, response.text)
    sent = store.client.post(
        f"{base}/messages",
        headers={**_auth(stranger), "Idempotency-Key": str(uuid.uuid4())},
        json={"client_message_id": str(uuid.uuid4()), "body": "let me in"},
    )
    assert sent.status_code == 404

    # A message ID from one conversation can't be reached through another the caller is in.
    cy, _, dy, _, other = _pair(store)
    del dy
    for url in (
        f"/v1/conversations/{other}/messages/{message['id']}",
        f"/v1/conversations/{other}/pins/{message['id']}",
        f"/v1/conversations/{other}/threads/{message['id']}",
    ):
        method = "delete" if "messages" in url else ("put" if "pins" in url else "get")
        assert getattr(store.client, method)(url, headers=_auth(cy)).status_code == 404, url
    reply = store.client.post(
        f"/v1/conversations/{other}/messages",
        headers={**_auth(cy), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "client_message_id": str(uuid.uuid4()),
            "body": "quoting",
            "reply_to_message_id": message["id"],
        },
    )
    _problem(reply, 422, "validation_failed")
    report = store.client.post(
        "/v1/reports",
        headers=_auth(cy),
        json={"target_type": "message", "target_id": message["id"], "reason": "spam"},
    )
    _problem(report, 404, "not_found")  # no evidence leaks to non-members


@pytest.mark.req("GCHAT-007", "T-GRP-03")
def test_groups_never_leak_into_each_other(store: LiveApp) -> None:  # noqa: F811
    owner_a, _, _ = _premium(store)
    owner_b, _, _ = _premium(store)
    group_a = _group(store, owner_a, name="Group A")
    group_b = _group(store, owner_b, name="Group B")
    secret = _say(store, owner_b, group_b["conversation_id"], "B-only plans")
    assert secret.status_code == 201
    member_a, _ = _join(store, owner_a, group_a["id"])

    for url in (
        f"/v1/groups/{group_b['id']}",
        f"/v1/groups/{group_b['id']}/members",
        f"/v1/groups/{group_b['id']}/settings",
        f"/v1/groups/{group_b['id']}/roles",
        f"/v1/conversations/{group_b['conversation_id']}",
        f"/v1/conversations/{group_b['conversation_id']}/messages",
    ):
        assert store.client.get(url, headers=_auth(member_a)).status_code == 404, url
    _problem(
        store.client.post(
            f"/v1/groups/{group_b['id']}/invitations", headers=_auth(owner_a), json={"kind": "link"}
        ),
        404,
        "not_found",
    )
    # Group B's message isn't reachable through group A's chat either.
    cross = f"/v1/conversations/{group_a['conversation_id']}/messages/{secret.json()['id']}"
    assert (
        store.client.delete(f"{cross}?reason_code=spam", headers=_auth(owner_a)).status_code == 404
    )
    listed = store.client.get("/v1/conversations", headers=_auth(member_a)).json()["data"]
    assert group_b["conversation_id"] not in {c["id"] for c in listed}


@pytest.mark.req("BILL-003", "T-BILL-01")
def test_client_asserted_premium_is_ignored(store: LiveApp) -> None:  # noqa: F811
    free, _ = _user(store)
    forged = store.client.patch(
        "/v1/users/me",
        headers=_auth(free),
        json={"entitlements": {"plan": "premium"}},
    )
    assert forged.status_code == 422  # unknown fields are rejected, never stored
    attempt = store.client.post(
        "/v1/groups",
        headers={
            **_auth(free),
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Entitlement": "groups.create",
            "X-Plan": "premium",
        },
        json={"name": "Sneaky group", "primary_destination_id": str(uuid.uuid4())},
    )
    _problem(attempt, 403, "entitlement_required")

    # A purchase another account owns unlocks nothing, even through restore.
    owner, _, transaction = _premium(store)
    del owner
    restored = store.client.post(
        "/v1/billing/purchases/restore",
        headers={**_auth(free), "Idempotency-Key": str(uuid.uuid4())},
        json={"provider": "apple", "signed_transactions": [f"dev:{MONTHLY}:{transaction}"]},
    )
    assert restored.status_code == 200
    assert restored.json()["plan"] == "free"
    _problem(_verify(store, free, f"dev:{MONTHLY}:{transaction}"), 409, "purchase_already_linked")


@pytest.mark.req("GRP-005", "GRP-012", "T-GRP-02")
def test_invitation_links_hold_under_concurrent_redemption(store: LiveApp) -> None:  # noqa: F811
    owner, _, _ = _premium(store)
    group = _group(store, owner, member_capacity=20)
    single = _invite_link(store, owner, group["id"], max_uses=1)
    racers = [_user(store)[0] for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda token: _redeem(store, token, single["token"]), racers))
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1, codes
    assert all(code == 409 for code in codes if code != 200), codes

    # Capacity holds too: two seats left, many concurrent joiners.
    small = _group(store, owner, name="Tiny trip", member_capacity=3)
    link = _invite_link(store, owner, small["id"], max_uses=10)
    joiners = [_user(store)[0] for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda token: _redeem(store, token, link["token"]), joiners))
    assert sum(r.status_code == 200 for r in results) == 2
    members = store.client.get(f"/v1/groups/{small['id']}/members", headers=_auth(owner)).json()
    assert len(members["data"]) == 3

    # A direct invitation belongs to its invitee and works once.
    invitee, invitee_id = _user(store)
    other, _ = _user(store)
    created = store.client.post(
        f"/v1/groups/{group['id']}/invitations",
        headers=_auth(owner),
        json={"kind": "direct", "invitee_user_id": invitee_id},
    ).json()
    url = f"/v1/group-invitations/{created['invitation']['id']}/accept"
    _problem(store.client.post(url, headers=_auth(other)), 404, "not_found")
    assert store.client.post(url, headers=_auth(invitee)).status_code == 200
    _problem(store.client.post(url, headers=_auth(invitee)), 409, "invitation_invalid")
