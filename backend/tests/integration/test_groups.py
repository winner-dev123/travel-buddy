"""Travel groups end to end (BL-3.07..3.10; GRP-001..013, GCHAT-001..007)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import MONTHLY, _event, _verify, store  # noqa: F401
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _destination, _problem, _tick, _user

pytestmark = pytest.mark.integration


def _premium(live: LiveApp) -> tuple[str, str, str]:
    """A premium traveller: (token, user id, store transaction)."""
    token, user_id = _user(live)
    transaction = f"tx-{uuid.uuid4().hex[:10]}"
    assert _verify(live, token, f"dev:{MONTHLY}:{transaction}").status_code == 200
    return token, user_id, transaction


def _create(live: LiveApp, token: str, **overrides: Any) -> Any:
    body = {
        "name": "Lisbon food crawl",
        "description": "Pastéis, tascas and miradouros.",
        "primary_destination_id": _destination(live, "portugal/lisbon"),
        "member_capacity": 10,
        **overrides,
    }
    return live.client.post(
        "/v1/groups",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json=body,
    )


def _group(live: LiveApp, token: str, **overrides: Any) -> dict[str, Any]:
    created = _create(live, token, **overrides)
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def _invite_link(live: LiveApp, token: str, group_id: str, **body: Any) -> dict[str, Any]:
    response = live.client.post(
        f"/v1/groups/{group_id}/invitations",
        headers=_auth(token),
        json={"kind": "link", **body},
    )
    assert response.status_code == 201, response.text
    assert_matches_contract(response.json(), "CreatedGroupInvitation")
    data: dict[str, Any] = response.json()
    return data


def _redeem(live: LiveApp, token: str, link_token: str) -> Any:
    return live.client.post(
        "/v1/group-invitations/redeem", headers=_auth(token), json={"token": link_token}
    )


def _join(live: LiveApp, owner: str, group_id: str) -> tuple[str, str]:
    token, user_id = _user(live)
    link = _invite_link(live, owner, group_id, max_uses=1)
    assert _redeem(live, token, link["token"]).status_code == 200
    return token, user_id


def _say(live: LiveApp, token: str, conversation: str, body: str = "Hi all") -> Any:
    return live.client.post(
        f"/v1/conversations/{conversation}/messages",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={"client_message_id": str(uuid.uuid4()), "body": body},
    )


# ─────────────────────────────── creation ───────────────────────────────


@pytest.mark.req("GRP-001", "GRP-002", "GRP-003", "GRP-004", "GCHAT-001")
def test_only_premium_users_create_groups_and_become_owners(store: LiveApp) -> None:  # noqa: F811
    free, _ = _user(store)
    problem = _problem(_create(store, free), 403, "entitlement_required")
    assert problem["entitlement"] == "groups.create"

    owner, owner_id, _ = _premium(store)
    _problem(_create(store, owner, visibility="public"), 403, "feature_disabled")
    created = _create(store, owner)
    assert created.status_code == 201, created.text
    assert_matches_contract(created.json(), "Group")
    group = created.json()
    assert created.headers["etag"] == '"1"'
    assert created.headers["location"] == f"/v1/groups/{group['id']}"
    assert group["owner"]["id"] == owner_id
    assert group["my_membership"]["role"] == "owner"
    assert "members.invite" in group["my_membership"]["permissions"]
    assert group["premium_features_active"] is True
    assert (group["visibility"], group["join_policy"]) == ("private", "invite_only")

    # The group chat exists from the start and lists the group's name.
    conversation = store.client.get(
        f"/v1/conversations/{group['conversation_id']}", headers=_auth(owner)
    )
    assert conversation.status_code == 200
    assert conversation.json()["kind"] == "group"
    assert conversation.json()["title"] == "Lisbon food crawl"

    # Private groups are invisible to non-members.
    _problem(store.client.get(f"/v1/groups/{group['id']}", headers=_auth(free)), 404, "not_found")
    mine = store.client.get("/v1/groups", headers=_auth(owner)).json()
    assert [g["id"] for g in mine["data"]] == [group["id"]]
    assert_matches_contract(mine, "GroupPage")


@pytest.mark.req("GRP-013")
def test_owned_group_cap(store: LiveApp) -> None:  # noqa: F811
    owner, _, _ = _premium(store)
    for index in range(10):
        assert _create(store, owner, name=f"Trip number {index}").status_code == 201
    _problem(_create(store, owner, name="One too many"), 409, "quota_exceeded")
    # The subscription screen shows the same count the cap uses.
    quota = store.client.get("/v1/billing/entitlements", headers=_auth(owner)).json()["quotas"]
    assert (quota["groups.owned"]["used"], quota["groups.owned"]["limit"]) == (10, 10)


# ─────────────────────────────── joining ───────────────────────────────


@pytest.mark.req("GRP-005", "GRP-008", "GCHAT-005")
def test_direct_invitations_are_free_to_accept_and_do_not_open_dms(store: LiveApp) -> None:  # noqa: F811
    owner, owner_id, _ = _premium(store)
    group = _group(store, owner)
    guest, guest_id = _user(store)  # free account
    invited = store.client.post(
        f"/v1/groups/{group['id']}/invitations",
        headers=_auth(owner),
        json={"kind": "direct", "invitee_user_id": guest_id},
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["token"] is None
    inbox = store.client.get("/v1/users/me/group-invitations", headers=_auth(guest)).json()
    assert_matches_contract(inbox, "GroupInvitationPage")
    [invitation] = inbox["data"]
    accepted = store.client.post(
        f"/v1/group-invitations/{invitation['id']}/accept", headers=_auth(guest)
    )
    assert accepted.status_code == 200, accepted.text
    assert_matches_contract(accepted.json(), "GroupMember")
    assert accepted.json()["role"] == "member"
    assert accepted.json()["invited_by"]["id"] == owner_id

    assert _say(store, guest, group["conversation_id"]).status_code == 201
    # Sharing a group doesn't make people connections (GCHAT-005).
    dm = store.client.post(
        "/v1/conversations", headers=_auth(guest), json={"kind": "direct", "user_id": owner_id}
    )
    _problem(dm, 403, "connection_required")


@pytest.mark.req("GCHAT-002", "I18N-004")
def test_group_chat_threads_mentions_reactions_pins_and_mute(store: LiveApp) -> None:  # noqa: F811
    owner, owner_id, _ = _premium(store)
    group = _group(store, owner)
    member, _ = _join(store, owner, group["id"])
    chat = group["conversation_id"]
    url = f"/v1/conversations/{chat}"

    root = _say(store, owner, chat, "Jantar às 8? 🍷 東京の友達も来る")
    assert root.status_code == 201, root.text
    assert root.json()["body"] == "Jantar às 8? 🍷 東京の友達も来る"  # full Unicode round trip
    root_id = root.json()["id"]
    reply = store.client.post(
        f"{url}/messages",
        headers={**_auth(member), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "client_message_id": str(uuid.uuid4()),
            "body": "Count me in",
            "reply_to_message_id": root_id,
            "thread_root_id": root_id,
            "mentions": [owner_id],
        },
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["mentions"] == [owner_id]
    assert reply.json()["thread_root_id"] == root_id
    thread = store.client.get(f"{url}/threads/{root_id}", headers=_auth(owner))
    assert thread.status_code == 200, thread.text
    assert [m["id"] for m in thread.json()["data"]] == [reply.json()["id"]]

    react = f"{url}/messages/{root_id}/reactions/%F0%9F%91%8D"
    assert store.client.put(react, headers=_auth(member)).status_code == 204
    assert store.client.put(f"{url}/pins/{root_id}", headers=_auth(owner)).status_code == 204
    history = store.client.get(f"{url}/messages", headers=_auth(member)).json()["data"]
    shown = next(m for m in history if m["id"] == root_id)
    assert shown["reactions"] == [{"emoji": "👍", "count": 1, "reacted_by_me": True}]
    assert shown["pinned"] is True
    assert shown["thread_reply_count"] == 1

    muted = store.client.put(
        f"{url}/mute",
        headers=_auth(member),
        json={"muted_until": "2099-01-01T00:00:00Z", "notification_level": "mentions"},
    )
    assert muted.status_code == 200, muted.text
    assert muted.json()["notification_level"] == "mentions"


@pytest.mark.req("GRP-005", "GRP-012", "T-GRP-02")
def test_link_invitations_respect_uses_capacity_and_revocation(store: LiveApp) -> None:  # noqa: F811
    owner, _, _ = _premium(store)
    group = _group(store, owner, member_capacity=3)
    link = _invite_link(store, owner, group["id"], max_uses=5)
    assert link["url"].endswith(f"#t={link['token']}")
    first, _ = _user(store)
    preview = store.client.post(
        "/v1/group-invitations/preview", headers=_auth(first), json={"token": link["token"]}
    )
    assert preview.status_code == 200, preview.text
    assert_matches_contract(preview.json(), "GroupInvitationPreview")
    assert preview.json()["is_member"] is False
    assert _redeem(store, first, link["token"]).status_code == 200
    again = _redeem(store, first, link["token"])  # already a member: no use consumed
    assert again.status_code == 200
    second, _ = _user(store)
    assert _redeem(store, second, link["token"]).status_code == 200
    third, _ = _user(store)
    _problem(_redeem(store, third, link["token"]), 409, "group_capacity_reached")
    uses = db_scalar(
        store.db_url,
        "SELECT use_count FROM group_invitations WHERE id = :i",
        i=uuid.UUID(link["invitation"]["id"]),
    )
    assert uses == 2

    revoke = store.client.delete(
        f"/v1/groups/{group['id']}/invitations/{link['invitation']['id']}", headers=_auth(owner)
    )
    assert revoke.status_code == 204
    _problem(_redeem(store, third, link["token"]), 409, "invitation_invalid")
    _problem(_redeem(store, third, "x" * 43), 409, "invitation_invalid")


# ─────────────────────────────── roles and moderation ───────────────────────────────


@pytest.mark.req("GRP-007", "GCHAT-004", "GCHAT-007")
def test_roles_moderation_and_removal(store: LiveApp) -> None:  # noqa: F811
    owner, owner_id, _ = _premium(store)
    group = _group(store, owner)
    gid, chat = group["id"], group["conversation_id"]
    mod, mod_id = _join(store, owner, gid)
    member, member_id = _join(store, owner, gid)

    promoted = store.client.patch(
        f"/v1/groups/{gid}/members/{mod_id}", headers=_auth(owner), json={"role": "moderator"}
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "moderator"
    _problem(
        store.client.patch(
            f"/v1/groups/{gid}/members/{member_id}", headers=_auth(mod), json={"role": "admin"}
        ),
        403,
        "forbidden",
    )
    roles = store.client.get(f"/v1/groups/{gid}/roles", headers=_auth(member)).json()
    assert [r["key"] for r in roles["data"]] == ["owner", "admin", "moderator", "member"]

    # Restricted members read but can't post.
    until = (store.clock.now() + timedelta(days=1)).isoformat()
    restricted = store.client.put(
        f"/v1/groups/{gid}/members/{member_id}/restriction",
        headers=_auth(mod),
        json={"until": until, "reason_code": "spam"},
    )
    assert restricted.status_code == 200, restricted.text
    assert restricted.json()["status"] == "restricted"
    _problem(_say(store, member, chat), 403, "member_restricted")
    assert (
        store.client.get(f"/v1/conversations/{chat}/messages", headers=_auth(member)).status_code
        == 200
    )
    _problem(
        store.client.put(
            f"/v1/groups/{gid}/members/{owner_id}/restriction",
            headers=_auth(mod),
            json={"until": until},
        ),
        403,
        "forbidden",
    )
    lifted = store.client.delete(
        f"/v1/groups/{gid}/members/{member_id}/restriction", headers=_auth(mod)
    )
    assert lifted.status_code == 204
    sent = _say(store, member, chat, "Sorry about that")
    assert sent.status_code == 201

    # Moderators remove messages (with a reason) and members.
    removal = f"/v1/conversations/{chat}/messages/{sent.json()['id']}"
    _problem(store.client.delete(removal, headers=_auth(mod)), 422, "validation_failed")
    assert store.client.delete(f"{removal}?reason_code=spam", headers=_auth(mod)).status_code == 204
    [gone] = [
        m
        for m in store.client.get(
            f"/v1/conversations/{chat}/messages", headers=_auth(owner)
        ).json()["data"]
        if m["id"] == sent.json()["id"]
    ]
    assert gone["moderation_state"] == "removed_by_moderator"
    assert (
        store.client.delete(
            f"/v1/groups/{gid}/members/{member_id}?reason_code=harassment", headers=_auth(mod)
        ).status_code
        == 204
    )
    _problem(store.client.get(f"/v1/groups/{gid}", headers=_auth(member)), 404, "not_found")
    _problem(
        store.client.get(f"/v1/conversations/{chat}/messages", headers=_auth(member)),
        404,
        "not_found",
    )
    assert (
        db_scalar(
            store.db_url,
            "SELECT count(*) FROM moderation_actions WHERE scope = 'group' AND group_id = :g",
            g=uuid.UUID(gid),
        )
        == 3
    )

    # Admins-only chat; announcements still go out and can be pinned.
    settings = store.client.get(f"/v1/groups/{gid}/settings", headers=_auth(owner))
    assert settings.headers["etag"] == '"1"'
    _problem(
        store.client.patch(
            f"/v1/groups/{gid}/settings", headers=_auth(owner), json={"chat_mode": "admins_only"}
        ),
        428,
        "precondition_required",
    )
    updated = store.client.patch(
        f"/v1/groups/{gid}/settings",
        headers={**_auth(owner), "If-Match": '"1"'},
        json={"chat_mode": "admins_only"},
    )
    assert updated.status_code == 200, updated.text
    assert_matches_contract(updated.json(), "GroupSettings")
    _problem(_say(store, mod, chat), 403, "chat_admins_only")
    announcement = store.client.post(
        f"/v1/groups/{gid}/announcements",
        headers={**_auth(owner), "Idempotency-Key": str(uuid.uuid4())},
        json={"client_message_id": str(uuid.uuid4()), "body": "Meet at 7 by the tram", "pin": True},
    )
    assert announcement.status_code == 201, announcement.text
    assert_matches_contract(announcement.json(), "Message")
    assert (announcement.json()["kind"], announcement.json()["pinned"]) == ("announcement", True)
    _problem(
        store.client.post(
            f"/v1/groups/{gid}/announcements",
            headers={**_auth(mod), "Idempotency-Key": str(uuid.uuid4())},
            json={"client_message_id": str(uuid.uuid4()), "body": "Me too"},
        ),
        403,
        "forbidden",
    )


@pytest.mark.req("GRP-003", "GCHAT-006")
def test_edits_need_the_current_version_and_history_can_start_at_join(store: LiveApp) -> None:  # noqa: F811
    owner, _, _ = _premium(store)
    group = _group(store, owner)
    gid = group["id"]
    _problem(
        store.client.patch(f"/v1/groups/{gid}", headers=_auth(owner), json={"name": "New name"}),
        428,
        "precondition_required",
    )
    _problem(
        store.client.patch(
            f"/v1/groups/{gid}",
            headers={**_auth(owner), "If-Match": '"9"'},
            json={"name": "New name"},
        ),
        412,
        "precondition_failed",
    )
    renamed = store.client.patch(
        f"/v1/groups/{gid}",
        headers={**_auth(owner), "If-Match": '"1"'},
        json={"name": "Lisbon by night"},
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["version"]) == ("Lisbon by night", 2)
    assert renamed.headers["etag"] == '"2"'

    assert _say(store, owner, group["conversation_id"], "Before you joined").status_code == 201
    store.client.patch(
        f"/v1/groups/{gid}/settings",
        headers={**_auth(owner), "If-Match": '"1"'},
        json={"new_member_history": "from_join"},
    )
    late, _ = _join(store, owner, gid)
    history = store.client.get(
        f"/v1/conversations/{group['conversation_id']}/messages", headers=_auth(late)
    ).json()
    assert history["data"] == []


# ─────────────────────────────── lapse, transfer, leave, archive ───────────────────────────────


@pytest.mark.req("GRP-009", "GRP-010", "GRP-011")
def test_owner_lapse_keeps_safety_tools_and_transfer(store: LiveApp) -> None:  # noqa: F811
    owner, owner_id, transaction = _premium(store)
    group = _group(store, owner)
    gid = group["id"]
    heir, heir_id = _join(store, owner, gid)
    troll, troll_id = _join(store, owner, gid)
    assert _event(store, owner, transaction, "refunded") == "processed"  # no admin grace

    lapsed = store.client.get(f"/v1/groups/{gid}", headers=_auth(owner)).json()
    assert lapsed["premium_features_active"] is False
    assert "members.invite" not in lapsed["my_membership"]["permissions"]
    assert "members.remove" in lapsed["my_membership"]["permissions"]
    problem = _problem(
        store.client.post(
            f"/v1/groups/{gid}/invitations", headers=_auth(owner), json={"kind": "link"}
        ),
        403,
        "entitlement_required",
    )
    assert problem["entitlement"] == "members.invite"
    # Safety tools never lapse.
    assert (
        store.client.delete(
            f"/v1/groups/{gid}/members/{troll_id}", headers=_auth(owner)
        ).status_code
        == 204
    )

    # Ownership can always be transferred; the heir needs no subscription.
    _problem(store.client.post(f"/v1/groups/{gid}/leave", headers=_auth(owner)), 409, "conflict")
    offer = store.client.post(
        f"/v1/groups/{gid}/ownership-transfers", headers=_auth(owner), json={"to_user_id": heir_id}
    )
    assert offer.status_code == 201, offer.text
    assert_matches_contract(offer.json(), "OwnershipTransfer")
    # The heir finds the offer on the group; other members don't see it.
    seen = store.client.get(f"/v1/groups/{gid}", headers=_auth(heir)).json()
    assert_matches_contract(seen, "Group")
    assert seen["pending_transfer"]["id"] == offer.json()["id"]
    assert seen["pending_transfer"]["to_user"]["id"] == heir_id
    mine = store.client.get(f"/v1/groups/{gid}", headers=_auth(owner)).json()
    assert mine["pending_transfer"]["id"] == offer.json()["id"]
    accepted = store.client.post(
        f"/v1/groups/{gid}/ownership-transfers/{offer.json()['id']}/accept", headers=_auth(heir)
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    now = store.client.get(f"/v1/groups/{gid}", headers=_auth(heir)).json()
    assert now["pending_transfer"] is None  # answered
    assert now["owner"]["id"] == heir_id
    assert now["my_membership"]["role"] == "owner"
    members = store.client.get(f"/v1/groups/{gid}/members", headers=_auth(heir)).json()
    assert {m["user"]["id"]: m["role"] for m in members["data"]}[owner_id] == "admin"

    assert store.client.post(f"/v1/groups/{gid}/leave", headers=_auth(owner)).status_code == 204
    _problem(store.client.get(f"/v1/groups/{gid}", headers=_auth(owner)), 404, "not_found")

    archived = store.client.post(f"/v1/groups/{gid}/archive", headers=_auth(heir))
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    _problem(_say(store, heir, group["conversation_id"]), 403, "forbidden")  # read-only
    assert (
        store.client.get(
            f"/v1/conversations/{group['conversation_id']}/messages", headers=_auth(heir)
        ).status_code
        == 200
    )
    assert troll


@pytest.mark.req("AUTH-010", "GRP-011")
def test_erasing_an_owner_hands_groups_over_and_keeps_billing_records(store: LiveApp) -> None:  # noqa: F811
    owner, owner_id, transaction = _premium(store)
    shared = _group(store, owner, name="Shared trip")
    lonely = _group(store, owner, name="Solo plans")
    member, _ = _join(store, owner, shared["id"])
    admin, admin_id = _join(store, owner, shared["id"])
    promoted = store.client.patch(
        f"/v1/groups/{shared['id']}/members/{admin_id}",
        headers=_auth(owner),
        json={"role": "admin"},
    )
    assert promoted.status_code == 200
    requested = store.client.post(
        "/v1/users/me/deletion",
        headers={**_auth(owner), "Idempotency-Key": str(uuid.uuid4())},
        json={"confirm": True},
    )
    assert requested.status_code in (200, 201, 202), requested.text
    db_scalar(
        store.db_url,
        "UPDATE users SET deletion_requested_at = now() - interval '31 days' "
        "WHERE id = :u RETURNING 1",
        u=uuid.UUID(owner_id),
    )
    db_scalar(
        store.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' RETURNING 1",
    )
    _tick(store)
    _tick(store)
    assert (
        db_scalar(store.db_url, "SELECT count(*) FROM users WHERE id = :u", u=uuid.UUID(owner_id))
        == 0
    )

    heir = store.client.get(f"/v1/groups/{shared['id']}", headers=_auth(admin)).json()
    assert heir["owner"]["id"] == admin_id  # the longest-serving admin inherits
    assert heir["my_membership"]["role"] == "owner"
    assert store.client.get(f"/v1/groups/{shared['id']}", headers=_auth(member)).status_code == 200
    status = db_scalar(
        store.db_url,
        "SELECT status || ':' || (owner_id IS NULL) FROM travel_groups WHERE id = :g",
        g=uuid.UUID(lonely["id"]),
    )
    assert status == "archived:true"  # never deleted (GRP-011)
    kept = db_scalar(
        store.db_url,
        "SELECT count(*) FROM subscriptions WHERE original_transaction_id = :t AND user_id IS NULL",
        t=transaction,
    )
    assert kept == 1  # billing records are kept, pseudonymized


@pytest.mark.req("GCHAT-007", "SAFE-002")
def test_removed_members_are_told_at_once_and_members_can_report_groups(store: LiveApp) -> None:  # noqa: F811
    from tests.integration.test_realtime import PROTOCOL, Reader

    owner, _, _ = _premium(store)
    group = _group(store, owner)
    member, member_id = _join(store, owner, group["id"])
    outsider, _ = _user(store)
    report = {"target_type": "group", "target_id": group["id"], "reason": "scam"}
    _problem(
        store.client.post("/v1/reports", headers=_auth(outsider), json=report), 404, "not_found"
    )
    assert store.client.post("/v1/reports", headers=_auth(member), json=report).status_code == 202

    with store.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)
        reader.send("auth", {"access_token": member})
        reader.expect("auth.ok")
        removed = store.client.delete(
            f"/v1/groups/{group['id']}/members/{member_id}", headers=_auth(owner)
        )
        assert removed.status_code == 204
        frame = reader.expect("membership.changed")["data"]
        assert (frame["change"], frame["group_id"], frame["conversation_id"]) == (
            "removed",
            group["id"],
            group["conversation_id"],
        )


def _watch(live: LiveApp) -> None:
    db_scalar(
        live.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'groups.premium_watch' RETURNING 1",
    )
    _tick(live)  # creates or schedules the task
    db_scalar(
        live.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'groups.premium_watch' RETURNING 1",
    )
    _tick(live)  # runs it and relays its events
    _tick(live)  # notifications


@pytest.mark.req("GRP-009")
def test_owner_and_admins_hear_about_the_lapse_members_do_not(store: LiveApp) -> None:  # noqa: F811
    owner, _, transaction = _premium(store)
    group = _group(store, owner, name="Porto weekend")
    admin, admin_id = _join(store, owner, group["id"])
    member, _ = _join(store, owner, group["id"])
    store.client.patch(
        f"/v1/groups/{group['id']}/members/{admin_id}", headers=_auth(owner), json={"role": "admin"}
    )

    def notices(token: str) -> list[dict[str, Any]]:
        items = store.client.get("/v1/notifications", headers=_auth(token)).json()["data"]
        return [n for n in items if n["type"] == "subscription_notice"]

    _watch(store)
    assert notices(owner) == []  # premium is active

    assert _event(store, owner, transaction, "billing_retry") == "processed"
    _watch(store)
    [grace] = notices(owner)
    assert "Porto weekend" in grace["body"]
    assert grace["entity_id"] == group["id"]
    assert len(notices(admin)) == 1
    assert notices(member) == []  # the owner's billing state stays private
    _watch(store)
    assert len(notices(owner)) == 1  # once per stage

    assert _event(store, owner, transaction, "refunded") == "processed"
    _watch(store)
    assert len(notices(owner)) == 2


@pytest.mark.req("CONN-004")
def test_group_members_share_a_context_for_connection_requests(store: LiveApp) -> None:  # noqa: F811
    owner, owner_id, _ = _premium(store)
    group = _group(store, owner)
    member, member_id = _join(store, owner, group["id"])
    stranger, _ = _user(store)
    store.client.patch(
        "/v1/users/me/privacy",
        headers=_auth(owner),
        json={"connection_requests_from": "shared_context"},
    )

    def ask(token: str) -> Any:
        return store.client.post(
            "/v1/connections/requests",
            headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
            json={"recipient_id": owner_id, "context": "group", "context_ref_id": group["id"]},
        )

    _problem(ask(stranger), 403, "connection_request_not_allowed")  # no group in common
    assert ask(member).status_code == 201, "fellow members may ask"

    # Someone who left the group no longer shares it.
    leaver, leaver_id = _join(store, owner, group["id"])
    left = store.client.post(f"/v1/groups/{group['id']}/leave", headers=_auth(leaver))
    assert left.status_code == 204, left.text
    _problem(ask(leaver), 403, "connection_request_not_allowed")
    del member_id, leaver_id
