"""Challenge results: winners, publication, badges, reward review and fulfillment, disputes
(BL-5.06, BL-5.07; CHAL-010..012, CHAL-014..016)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import store  # noqa: F401 - dev billing app fixture
from tests.integration.test_challenges import _create, _judge, _setup, _started, _submit
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _join
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _problem, _tick

pytestmark = pytest.mark.integration

CODE = "TOUR10-BELEM"


def _results(live: LiveApp, token: str, challenge_id: str) -> dict[str, Any]:
    response = live.client.get(f"/v1/challenges/{challenge_id}/results", headers=_auth(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _publish(live: LiveApp, token: str, challenge_id: str) -> Any:
    return live.client.post(f"/v1/challenges/{challenge_id}/results/publish", headers=_auth(token))


def _winner(live: LiveApp, token: str, challenge_id: str, winner_id: str, action: str) -> Any:
    return live.client.post(
        f"/v1/challenges/{challenge_id}/winners/{winner_id}/{action}",
        headers=_auth(token),
        json={"note": "Checked by the judges"},
    )


@pytest.mark.req("CHAL-011", "CHAL-012", "CHAL-014", "CHAL-015")
def test_publishing_results_awards_badges_and_starts_fulfillment(store: LiveApp) -> None:  # noqa: F811
    admin, _, group = _setup(store)
    first, first_id = _join(store, admin, group)
    second, second_id = _join(store, admin, group)
    third, third_id = _join(store, admin, group)
    badge = {
        "reward_type": "badge",
        "title": "Explorer",
        "badge_key": "explorer",
        "quantity": 2,
        "fulfillment_owner": "platform",
    }
    discount = {
        "reward_type": "discount_code",
        "title": "10% off a tour",
        "sponsor_name": "Partner Tours",
        "quantity": 1,
        "eligibility_rules": "One per traveller; adults only.",
        "fulfillment_owner": "sponsor",
    }
    view = _create(
        store,
        admin,
        group,
        winner_policy="first_n_correct",
        max_winners=2,
        rewards=[badge, discount],
    ).json()
    cid = view["id"]
    [reward_id] = [r["id"] for r in view["reward_details"] if r["reward_type"] == "discount_code"]

    # Platform review (CHAL-014): staff only, with a justification.
    staff, _ = _staff(store)
    review = f"/v1/admin/challenge-rewards/{reward_id}/review"
    _problem(
        store.client.post(review, headers=_auth(first), json={"decision": "approved"}),
        403,
        "forbidden",
    )
    reviewed = store.client.post(
        review, headers=_admin(staff), json={"decision": "approved", "note": "Terms checked"}
    )
    assert reviewed.status_code == 200, reviewed.text
    assert_matches_contract(reviewed.json(), "ChallengeReward")
    assert reviewed.json()["review_status"] == "approved"
    published = store.client.post(
        f"/v1/challenges/{cid}/publish", headers={**_auth(admin), "If-Match": '"1"'}
    )
    assert published.status_code == 200, published.text
    store.clock.set(store.clock.now() + timedelta(minutes=5))
    assert _submit(store, first, cid, "Belém Tower").json()["is_provisional_winner"] is True
    assert _submit(store, second, cid, "Torre de Belém").json()["is_provisional_winner"] is True
    assert _submit(store, third, cid, "Sintra").json()["evaluation_status"] == "incorrect"
    assert _results(store, third, cid)["winners"] == []  # nothing public before publication

    done = _publish(store, admin, cid)
    assert done.status_code == 200, done.text
    assert_matches_contract(done.json(), "ChallengeResults")
    assert (done.json()["published"], done.json()["status"]) == (True, "completed")
    public = _results(store, third, cid)
    assert [(w["user"]["id"], w["rank"], w["status"]) for w in public["winners"]] == [
        (first_id, 1, "confirmed"),
        (second_id, 2, "confirmed"),
    ]
    _problem(_publish(store, admin, cid), 409, "conflict")
    [late] = store.client.get(
        f"/v1/challenges/{cid}/submissions",
        headers=_auth(admin),
        params={"scope": "all", "evaluation_status": "incorrect"},
    ).json()["data"]
    _problem(_judge(store, admin, cid, late["id"], "correct"), 409, "conflict")  # final

    # Badges: both winners, nobody else (CHAL-012).
    for user_id in (first_id, second_id):
        owned = store.client.get(f"/v1/users/{user_id}/badges", headers=_auth(third)).json()
        [entry] = owned["data"]
        assert_matches_contract(entry, "UserBadge")
        assert (entry["badge"]["key"], entry["source_id"]) == ("explorer", cid)
    own = store.client.get(f"/v1/users/{third_id}/badges", headers=_auth(third))
    assert own.json()["data"] == []

    # Fulfillment of the discount for the top winner (CHAL-015).
    page = store.client.get(f"/v1/challenges/{cid}/fulfillments", headers=_auth(admin))
    assert_matches_contract(page.json(), "RewardFulfillmentPage")
    [fulfillment] = page.json()["data"]
    assert (fulfillment["recipient"]["id"], fulfillment["status"]) == (first_id, "pending")
    _problem(
        store.client.get(f"/v1/challenges/{cid}/fulfillments", headers=_auth(first)),
        403,
        "forbidden",
    )
    move = f"/v1/challenges/{cid}/fulfillments/{fulfillment['id']}/transitions"
    _problem(
        store.client.post(move, headers=_auth(admin), json={"to_status": "delivered"}),
        409,
        "conflict",
    )
    _problem(
        store.client.post(move, headers=_auth(admin), json={"to_status": "issued"}),
        422,
        "validation_failed",
    )
    _problem(
        store.client.post(move, headers=_auth(first), json={"to_status": "issued", "secret": "X"}),
        403,
        "forbidden",
    )
    issued = store.client.post(
        move,
        headers=_auth(admin),
        json={"to_status": "issued", "secret": CODE, "note": "Sent by the sponsor"},
    )
    assert issued.status_code == 200, issued.text
    assert_matches_contract(issued.json(), "RewardFulfillment")
    assert CODE not in issued.text
    mine = store.client.get("/v1/users/me/rewards", headers=_auth(first))
    assert mine.headers["cache-control"] == "no-store"
    assert_matches_contract(mine.json(), "MyRewardPage")
    [reward] = mine.json()["data"]
    assert (reward["secret"], reward["status"], reward["challenge"]["id"]) == (CODE, "issued", cid)
    assert store.client.get("/v1/users/me/rewards", headers=_auth(second)).json()["data"] == []
    stored = db_scalar(
        store.db_url,
        "SELECT secret_ciphertext FROM reward_fulfillments WHERE id = :f",
        f=uuid.UUID(fulfillment["id"]),
    )
    assert isinstance(stored, bytes)
    assert CODE.encode() not in stored
    audit = db_scalar(
        store.db_url,
        "SELECT string_agg(metadata::text, ' ') FROM audit_logs "
        "WHERE action = 'challenge.fulfillment_transitioned' AND resource_id = :f",
        f=fulfillment["id"],
    )
    assert isinstance(audit, str)
    assert CODE not in audit
    delivered = store.client.post(move, headers=_auth(admin), json={"to_status": "delivered"})
    assert delivered.json()["status"] == "delivered"

    _tick(store)  # relays the results and reward events
    _tick(store)  # notifications
    titles = {
        n["title"]
        for n in store.client.get("/v1/notifications", headers=_auth(first)).json()["data"]
        if n["type"] == "challenge_result" and n["entity_id"] == cid
    }
    assert len(titles) == 2  # results published, and the reward issued (in the user's locale)


@pytest.mark.req("CHAL-010", "CHAL-016")
def test_judges_pick_admin_selects_winners_after_disputes(store: LiveApp) -> None:  # noqa: F811
    admin, _, group = _setup(store)
    alice, alice_id = _join(store, admin, group)
    bruno, bruno_id = _join(store, admin, group)
    bystander, _ = _join(store, admin, group)
    cid = _started(
        store,
        admin,
        group,
        validation_method="admin_review",
        winner_policy="admin_selects",
        max_winners=1,
    )
    mine = _submit(store, alice, cid, "Belém Tower").json()
    theirs = _submit(store, bruno, cid, "Torre de Belém").json()
    assert theirs["is_provisional_winner"] is False
    _judge(store, admin, cid, mine["submission_id"], "correct")
    _judge(store, admin, cid, theirs["submission_id"], "correct")
    candidates = {w["user"]["id"]: w for w in _results(store, admin, cid)["winners"]}
    assert set(candidates) == {alice_id, bruno_id}

    url = f"/v1/challenges/{cid}/disputes"
    reason = "My answer came in first and is just as correct."
    _problem(
        store.client.post(url, headers=_auth(bystander), json={"reason": reason}), 403, "forbidden"
    )
    _problem(
        store.client.post(
            url,
            headers=_auth(bruno),
            json={"reason": reason, "submission_id": mine["submission_id"]},
        ),
        404,
        "not_found",
    )
    raised = store.client.post(
        url, headers=_auth(bruno), json={"reason": reason, "submission_id": theirs["submission_id"]}
    )
    assert raised.status_code == 201, raised.text
    assert_matches_contract(raised.json(), "ChallengeDispute")
    _problem(_publish(store, admin, cid), 409, "conflict")  # an open dispute holds the results
    assert store.client.get(url, headers=_auth(alice)).json()["data"] == []
    listed = store.client.get(url, headers=_auth(admin))
    assert_matches_contract(listed.json(), "ChallengeDisputePage")
    assert [d["raised_by"]["id"] for d in listed.json()["data"]] == [bruno_id]
    resolve = f"{url}/{raised.json()['id']}/resolve"
    note = {"status": "rejected", "resolution_note": "Both are correct; the judges pick one."}
    _problem(store.client.post(resolve, headers=_auth(bruno), json=note), 403, "forbidden")
    resolved = store.client.post(resolve, headers=_auth(admin), json=note)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "rejected"
    _problem(store.client.post(resolve, headers=_auth(admin), json=note), 409, "conflict")

    picked = _winner(store, admin, cid, candidates[alice_id]["id"], "confirm")
    assert picked.status_code == 200, picked.text
    assert_matches_contract(picked.json(), "ChallengeWinner")
    assert (picked.json()["status"], picked.json()["determined_by"]) == ("confirmed", "admin")
    _problem(_winner(store, admin, cid, candidates[bruno_id]["id"], "confirm"), 409, "conflict")
    _problem(_winner(store, alice, cid, candidates[bruno_id]["id"], "confirm"), 403, "forbidden")

    assert _publish(store, admin, cid).status_code == 200
    assert [w["user"]["id"] for w in _results(store, bystander, cid)["winners"]] == [alice_id]
    statuses = {w["user"]["id"]: w["status"] for w in _results(store, admin, cid)["winners"]}
    assert statuses == {alice_id: "confirmed", bruno_id: "revoked"}


@pytest.mark.req("CHAL-010")
def test_revoking_a_winner_moves_the_next_answer_up(store: LiveApp) -> None:  # noqa: F811
    admin, _, group = _setup(store)
    first, first_id = _join(store, admin, group)
    second, second_id = _join(store, admin, group)
    cid = _started(store, admin, group)
    _submit(store, first, cid, "Belém Tower")
    _submit(store, second, cid, "Belém Tower")
    [winner] = _results(store, admin, cid)["winners"]
    assert winner["user"]["id"] == first_id
    revoked = _winner(store, admin, cid, winner["id"], "revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    after = {
        w["user"]["id"]: (w["status"], w["rank"]) for w in _results(store, admin, cid)["winners"]
    }
    assert after == {first_id: ("revoked", 1), second_id: ("provisional", 1)}
    _problem(_winner(store, admin, cid, winner["id"], "confirm"), 409, "conflict")
