"""Group challenges: authoring, prize policy, lifecycle, member views, submissions and winners
(BL-5.01..5.03; CHAL-001..003, CHAL-005, CHAL-006, CHAL-008..011, CHAL-013, CHAL-014)."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import store  # noqa: F401 - dev billing app fixture
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _group, _join, _premium
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _tick, _user

pytestmark = pytest.mark.integration


def _body(live: LiveApp, **overrides: Any) -> dict[str, Any]:
    now = live.clock.now()
    body: dict[str, Any] = {
        "kind": "riddle",
        "title": "Where is the tower?",
        "description": "I guard the river mouth and saw the caravels leave. Name me.",
        "solving_mode": "individual",
        "validation_method": "exact",
        "accepted_answers": ["Torre de Belém", "Belém Tower", "torre de belem!"],
        "normalization": {"strip_articles": ["en", "pt-BR"]},
        "hints": [
            {"body": "Think Manueline."},
            {"body": "It is in Belém.", "release_at": (now + timedelta(hours=1)).isoformat()},
        ],
        "starts_at": (now + timedelta(minutes=2)).isoformat(),
        "ends_at": (now + timedelta(days=1)).isoformat(),
        "max_attempts": 3,
        "winner_policy": "first_correct",
        "prize_description": "Bragging rights and the Explorer badge",
        "rewards": [
            {
                "reward_type": "badge",
                "title": "Explorer",
                "badge_key": "explorer",
                "quantity": 1,
                "fulfillment_owner": "platform",
            }
        ],
        **overrides,
    }
    return body


def _create(live: LiveApp, token: str, group_id: str, **overrides: Any) -> Any:
    return live.client.post(
        f"/v1/groups/{group_id}/challenges",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json=_body(live, **overrides),
    )


def _lifecycle(live: LiveApp) -> None:
    """Run the lifecycle job now (periodic tasks follow the database clock) and relay events."""
    db_scalar(
        live.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'challenges.lifecycle' RETURNING 1",
    )
    _tick(live)  # enqueues and runs the lifecycle job
    _tick(live)  # relays its events
    _tick(live)  # notifications


def _submit(
    live: LiveApp, token: str, challenge_id: str, answer: str, key: str | None = None
) -> Any:
    return live.client.post(
        f"/v1/challenges/{challenge_id}/submissions",
        headers={**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())},
        json={"answer": answer},
    )


def _started(live: LiveApp, admin: str, group_id: str, **overrides: Any) -> str:
    """A published challenge that has started; returns its id."""
    view = _create(live, admin, group_id, **overrides).json()
    published = live.client.post(
        f"/v1/challenges/{view['id']}/publish", headers={**_auth(admin), "If-Match": '"1"'}
    )
    assert published.status_code == 200, published.text
    live.clock.set(live.clock.now() + timedelta(minutes=5))
    return str(view["id"])


def _setup(live: LiveApp) -> tuple[str, str, str]:
    """(admin token, member token, group id)."""
    admin, _, _ = _premium(live)
    group = _group(live, admin)
    member, _ = _join(live, admin, group["id"])
    return admin, member, group["id"]


@pytest.mark.req("CHAL-001", "CHAL-002", "CHAL-006", "CHAL-008")
def test_admins_create_drafts_that_never_expose_answers(store: LiveApp) -> None:  # noqa: F811
    admin, member, group = _setup(store)
    created = _create(store, admin, group)
    assert created.status_code == 201, created.text
    assert_matches_contract(created.json(), "ChallengeManagerView")
    view = created.json()
    assert created.headers["etag"] == '"1"'
    assert view["status"] == "draft"
    assert view["answer_count"] == 2  # "torre de belem!" normalizes to an existing answer
    assert "accepted_answers" not in created.text
    assert "Torre de Bel" not in created.text
    assert len(view["all_hints"]) == 2
    assert view["reward_details"][0]["badge"]["key"] == "explorer"

    # Drafts are invisible to members; managing needs the permission.
    _problem(
        store.client.get(f"/v1/challenges/{view['id']}", headers=_auth(member)), 404, "not_found"
    )
    listed = store.client.get(f"/v1/groups/{group}/challenges", headers=_auth(member)).json()
    assert listed["data"] == []
    _problem(_create(store, member, group), 403, "forbidden")
    outsider, _ = _user(store)
    _problem(_create(store, outsider, group), 404, "not_found")


@pytest.mark.req("CHAL-002", "CHAL-013")
def test_invalid_configs_and_prohibited_prizes_are_rejected(store: LiveApp) -> None:  # noqa: F811
    admin, _, group = _setup(store)
    now = store.clock.now()
    _problem(
        _create(store, admin, group, ends_at=(now + timedelta(minutes=1)).isoformat()),
        422,
        "validation_failed",
    )
    _problem(_create(store, admin, group, accepted_answers=None), 422, "validation_failed")
    _problem(_create(store, admin, group, max_attempts=50), 422, "validation_failed")
    _problem(
        _create(store, admin, group, prize_description="Win $50 in cash"),
        422,
        "reward_not_permitted",
    )
    _problem(
        _create(
            store,
            admin,
            group,
            rewards=[
                {
                    "reward_type": "promotional",
                    "title": "Raffle for a city tour",
                    "quantity": 1,
                    "eligibility_rules": "Adults only",
                    "fulfillment_owner": "sponsor",
                }
            ],
        ),
        422,
        "reward_not_permitted",
    )
    # Admin-reviewed riddles may omit answers.
    assert (
        _create(
            store, admin, group, validation_method="admin_review", accepted_answers=None
        ).status_code
        == 201
    )


@pytest.mark.req("CHAL-003", "CHAL-014", "CHAL-008")
def test_publish_review_gate_scheduler_and_hint_release(store: LiveApp) -> None:  # noqa: F811
    admin, member, group = _setup(store)
    discount = {
        "reward_type": "discount_code",
        "title": "10% off a tour",
        "sponsor_name": "Partner Tours",
        "quantity": 3,
        "eligibility_rules": "One per traveller; adults only.",
        "fulfillment_owner": "sponsor",
    }
    view = _create(store, admin, group, rewards=[discount]).json()
    url = f"/v1/challenges/{view['id']}"
    _problem(
        store.client.post(f"{url}/publish", headers=_auth(admin)), 428, "precondition_required"
    )
    blocked = store.client.post(f"{url}/publish", headers={**_auth(admin), "If-Match": '"1"'})
    _problem(blocked, 409, "conflict")  # the discount awaits platform review
    db_scalar(
        store.db_url,
        "UPDATE challenge_rewards SET review_status = 'approved' "
        "WHERE challenge_id = :c RETURNING 1",
        c=uuid.UUID(view["id"]),
    )
    published = store.client.post(f"{url}/publish", headers={**_auth(admin), "If-Match": '"1"'})
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "scheduled"

    before = store.client.get(url, headers=_auth(member))
    assert_matches_contract(before.json(), "Challenge")
    assert before.json()["hints"] == []  # nothing before the start
    assert before.json()["my_participation"] is None

    store.clock.set(store.clock.now() + timedelta(minutes=5))
    _lifecycle(store)
    assert (
        db_scalar(
            store.db_url,
            "SELECT status FROM group_challenges WHERE id = :c",
            c=uuid.UUID(view["id"]),
        )
        == "active"
    )
    started = store.client.get("/v1/notifications", headers=_auth(member)).json()["data"]
    assert any(n["type"] == "challenge_started" for n in started)

    live = store.client.get(url, headers=_auth(member)).json()
    assert live["status"] == "active"
    assert [h["body"] for h in live["hints"]] == ["Think Manueline."]  # the second is later
    hints = store.client.get(f"{url}/hints", headers=_auth(member)).json()["data"]
    assert len(hints) == 1
    managed = store.client.get(f"{url}/manage", headers=_auth(admin)).json()
    assert len(managed["all_hints"]) == 2
    _problem(store.client.get(f"{url}/manage", headers=_auth(member)), 403, "forbidden")

    # After the start only the end may be extended.
    version = managed["version"]
    locked = store.client.patch(
        url, headers={**_auth(admin), "If-Match": f'"{version}"'}, json={"title": "New title"}
    )
    _problem(locked, 409, "challenge_locked")
    later = (store.clock.now() + timedelta(days=2)).isoformat()
    extended = store.client.patch(
        url, headers={**_auth(admin), "If-Match": f'"{version}"'}, json={"ends_at": later}
    )
    assert extended.status_code == 200, extended.text
    assert extended.json()["rules_version"] == managed["rules_version"] + 1

    cancelled = store.client.post(
        f"{url}/cancel", headers=_auth(admin), json={"reason": "Venue closed for works"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    _tick(store)
    _tick(store)
    results = store.client.get("/v1/notifications", headers=_auth(member)).json()["data"]
    assert any(n["type"] == "challenge_result" for n in results)
    _problem(
        store.client.post(f"{url}/cancel", headers=_auth(admin), json={"reason": "Again"}),
        409,
        "conflict",
    )


@pytest.mark.req("CHAL-001")
def test_drafts_edit_freely_and_members_list_published(store: LiveApp) -> None:  # noqa: F811
    admin, member, group = _setup(store)
    view = _create(store, admin, group).json()
    url = f"/v1/challenges/{view['id']}"
    edited = store.client.patch(
        url,
        headers={**_auth(admin), "If-Match": '"1"'},
        json={"title": "Which tower?", "accepted_answers": ["Torre de Belém"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["answer_count"] == 1
    assert edited.json()["version"] == 2
    _problem(
        store.client.patch(url, headers={**_auth(admin), "If-Match": '"1"'}, json={"title": "Old"}),
        412,
        "precondition_failed",
    )
    store.client.post(f"{url}/publish", headers={**_auth(admin), "If-Match": '"2"'})
    listed = store.client.get(f"/v1/groups/{group}/challenges", headers=_auth(member))
    assert_matches_contract(listed.json(), "ChallengePage")
    assert [c["title"] for c in listed.json()["data"]] == ["Which tower?"]
    managers = store.client.get(
        f"/v1/groups/{group}/challenges", headers=_auth(admin), params={"status": "draft"}
    ).json()
    assert managers["data"] == []


@pytest.mark.req("CHAL-005", "CHAL-006", "CHAL-009", "T-CHAL-02")
def test_submissions_enforce_window_attempts_cooldown_and_idempotency(
    store: LiveApp,  # noqa: F811
) -> None:
    admin, member, group = _setup(store)
    view = _create(store, admin, group).json()
    cid = view["id"]
    store.client.post(f"/v1/challenges/{cid}/publish", headers={**_auth(admin), "If-Match": '"1"'})
    _problem(_submit(store, member, cid, "Belém Tower"), 409, "challenge_not_active")
    store.clock.set(store.clock.now() + timedelta(minutes=5))

    key = str(uuid.uuid4())
    wrong = _submit(store, member, cid, "Jerónimos", key=key)
    assert wrong.status_code == 201, wrong.text
    assert_matches_contract(wrong.json(), "SubmissionResult")
    result = wrong.json()
    assert result["evaluation_status"] == "incorrect"
    assert (result["attempt_no"], result["attempts_remaining"]) == (1, 2)
    assert result["is_provisional_winner"] is False
    assert result["next_attempt_at"] is not None
    assert "Torre" not in wrong.text  # nothing about the answer comes back

    replay = _submit(store, member, cid, "Jerónimos", key=key)
    assert replay.status_code == 201
    assert replay.json()["submission_id"] == result["submission_id"]
    _problem(_submit(store, member, cid, "Belém Tower", key=key), 409, "idempotency_key_reused")
    cooling = _submit(store, member, cid, "Belém Tower")
    _problem(cooling, 409, "attempt_cooldown")
    assert cooling.headers["retry-after"] == "30"
    _problem(_submit(store, member, cid, "!!!"), 422, "validation_failed")  # costs no attempt

    store.clock.set(store.clock.now() + timedelta(seconds=31))
    correct = _submit(store, member, cid, "  torre de BELEM ").json()
    assert correct["evaluation_status"] == "correct"
    assert correct["attempt_no"] == 2
    assert correct["is_provisional_winner"] is True
    assert correct["next_attempt_at"] is None
    store.clock.set(store.clock.now() + timedelta(seconds=31))
    _problem(_submit(store, member, cid, "Belém Tower"), 409, "conflict")  # already solved

    other, _ = _join(store, admin, group)
    for answer in ("Lisbon", "Porto", "Sintra"):
        assert _submit(store, other, cid, answer).json()["evaluation_status"] == "incorrect"
        store.clock.set(store.clock.now() + timedelta(seconds=31))
    _problem(_submit(store, other, cid, "Belém Tower"), 409, "attempts_exhausted")
    me = store.client.get(f"/v1/challenges/{cid}", headers=_auth(other)).json()
    assert me["my_participation"]["attempts_used"] == 3
    assert me["my_participation"]["attempts_remaining"] == 0

    url = f"/v1/challenges/{cid}/submissions"
    mine = store.client.get(url, headers=_auth(member))
    assert_matches_contract(mine.json(), "ChallengeSubmissionPage")
    assert [s["evaluation_status"] for s in mine.json()["data"]] == ["incorrect", "correct"]
    assert all(s["ai_rationale"] is None for s in mine.json()["data"])
    _problem(
        store.client.get(url, headers=_auth(member), params={"scope": "all"}), 403, "forbidden"
    )
    first = store.client.get(url, headers=_auth(admin), params={"scope": "all", "limit": 3}).json()
    assert len(first["data"]) == 3
    rest = store.client.get(
        url,
        headers=_auth(admin),
        params={"scope": "all", "limit": 3, "cursor": first["page"]["next_cursor"]},
    ).json()
    assert len(rest["data"]) == 2
    assert rest["page"]["next_cursor"] is None
    solved = store.client.get(
        url, headers=_auth(admin), params={"scope": "all", "evaluation_status": "correct"}
    ).json()
    assert [s["submitted_by"]["id"] for s in solved["data"]] == [
        correct_owner["submitted_by"]["id"] for correct_owner in mine.json()["data"][1:]
    ]

    late, _ = _join(store, admin, group)
    db_scalar(  # end the challenge without letting the access tokens expire
        store.db_url,
        "UPDATE group_challenges SET ends_at = :t WHERE id = :c RETURNING 1",
        t=store.clock.now() - timedelta(seconds=1),
        c=uuid.UUID(cid),
    )
    _problem(_submit(store, late, cid, "Belém Tower"), 409, "challenge_not_active")


@pytest.mark.req("CHAL-009", "CHAL-010", "CHAL-011", "T-CHAL-07")
def test_first_n_correct_is_decided_once_under_concurrency(store: LiveApp) -> None:  # noqa: F811
    admin, _, group = _setup(store)
    racers = [_join(store, admin, group)[0] for _ in range(5)]
    cid = _started(store, admin, group, winner_policy="first_n_correct", max_winners=2)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda token: _submit(store, token, cid, "Belém Tower"), racers))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert {r.json()["evaluation_status"] for r in results} == {"correct"}
    ids = sorted(r.json()["submission_id"] for r in results)
    won = sorted(r.json()["submission_id"] for r in results if r.json()["is_provisional_winner"])
    # Submissions to a challenge are serialized, so the winners are the two earliest (UUIDv7).
    assert won == ids[:2]

    judged = store.client.get(f"/v1/challenges/{cid}/results", headers=_auth(admin))
    assert_matches_contract(judged.json(), "ChallengeResults")
    assert [w["rank"] for w in judged.json()["winners"]] == [1, 2]
    assert {w["status"] for w in judged.json()["winners"]} == {"provisional"}
    assert judged.json()["participant_count"] == 5
    # Members see winners only once results are published (CHAL-011).
    seen = store.client.get(f"/v1/challenges/{cid}/results", headers=_auth(racers[0])).json()
    assert seen["published"] is False
    assert seen["winners"] == []


@pytest.mark.req("CHAL-006", "CHAL-007", "CHAL-010")
def test_review_methods_wait_and_admin_selects_picks_no_one(store: LiveApp) -> None:  # noqa: F811
    admin, member, group = _setup(store)
    reviewed = _started(store, admin, group, validation_method="admin_review")
    pending = _submit(store, member, reviewed, "Belém Tower").json()
    assert pending["evaluation_status"] == "pending"
    assert pending["is_provisional_winner"] is False
    managed = store.client.get(f"/v1/challenges/{reviewed}/manage", headers=_auth(admin)).json()
    assert (managed["pending_review_count"], managed["participant_count"]) == (1, 1)

    assisted = _started(store, admin, group, validation_method="ai_assisted")
    matched = _submit(store, member, assisted, "torre de belem").json()
    assert matched["evaluation_status"] == "correct"
    other, _ = _join(store, admin, group)
    loose = _submit(store, other, assisted, "the old fort by the river in Lisbon").json()
    assert loose["evaluation_status"] == "pending"  # waits for the AI judge

    chosen = _started(store, admin, group, winner_policy="admin_selects")
    picked = _submit(store, member, chosen, "Belém Tower").json()
    assert picked["evaluation_status"] == "correct"
    assert picked["is_provisional_winner"] is False
    results = store.client.get(f"/v1/challenges/{chosen}/results", headers=_auth(admin)).json()
    assert results["winners"] == []
