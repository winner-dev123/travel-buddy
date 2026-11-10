"""AI itinerary generation end to end (BL-4.02; AI-001, AI-002, AI-003, AI-007, AI-008, AI-009,
TRIP-001). Runs on the deterministic fake provider the test environment selects."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

from app.modules.ai_assistant.provider import FakeAIProvider, ProviderError
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _destination, _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

GENERATE = "/v1/ai/itineraries/generate"


@pytest.fixture(autouse=True)
def _fresh_generations(app: LiveApp) -> Iterator[None]:  # noqa: F811
    """The shared catalog database keeps rows between tests: breaker and budget rows, or a
    pending generation, must not leak into the next test."""
    clear = "WITH gone AS (DELETE FROM ai_generations RETURNING 1) SELECT count(*) FROM gone"
    db_scalar(app.db_url, clear)
    yield
    db_scalar(app.db_url, clear)


def _generate(live: LiveApp, token: str, key: str | None = None, **overrides: Any) -> Any:
    body = {
        "destination_id": _destination(live, "portugal/lisbon"),
        "start_date": "2026-12-04",
        "end_date": "2026-12-06",
        "interests": ["food", "viewpoints"],
        "travel_styles": ["culture"],
        "pace": "moderate",
        "party": {"adults": 2},
        **overrides,
    }
    headers = {**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())}
    return live.client.post(GENERATE, headers={**headers, "Accept-Language": "pt-BR"}, json=body)


def _accepted(live: LiveApp, token: str, **overrides: Any) -> dict[str, Any]:
    response = _generate(live, token, **overrides)
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def _poll(live: LiveApp, token: str, generation_id: str) -> dict[str, Any]:
    response = live.client.get(f"/v1/ai/generations/{generation_id}", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "AIGeneration")
    body: dict[str, Any] = response.json()
    return body


def _fake(live: LiveApp) -> FakeAIProvider:
    provider = live.client.app.state.ai_provider  # type: ignore[attr-defined]
    assert isinstance(provider, FakeAIProvider)
    return provider


def _row(live: LiveApp, generation_id: str, column: str) -> object:
    return db_scalar(
        live.db_url,
        f"SELECT {column} FROM ai_generations WHERE id = :i",  # noqa: S608 - fixed column names
        i=uuid.UUID(generation_id),
    )


def _insert(live: LiveApp, *, status: str, cost: int = 0, user_id: str | None = None) -> None:
    now = live.clock.now()
    db_scalar(
        live.db_url,
        "INSERT INTO ai_generations (id, user_id, feature, provider, model, prompt_version, status,"
        " cost_micros, created_at, completed_at) VALUES (:id, :u, 'itinerary_generate', 'fake',"
        " 'fake', 'itinerary.v1', :s, :c, :t, :t) RETURNING 1",
        id=uuid.uuid4(),
        u=uuid.UUID(user_id) if user_id else None,
        s=status,
        c=cost,
        t=now,
    )


@pytest.mark.req("AI-001", "AI-002", "AI-003", "AI-007", "AI-008", "AI-009")
def test_generate_poll_and_get_a_validated_grounded_proposal(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _user(app)
    key = str(uuid.uuid4())
    created = _generate(app, token, key)
    assert created.status_code == 202, created.text
    assert_matches_contract(created.json(), "AIGeneration")
    generation = created.json()
    assert created.headers["location"] == f"/v1/ai/generations/{generation['id']}"
    assert generation["status"] == "pending"
    assert generation["quota"]["used"] == 1
    assert generation["quota"]["limit"] == 5  # free plan
    assert _generate(app, token, key).json() == generation  # idempotent retry
    assert _poll(app, token, generation["id"])["status"] == "pending"

    _tick(app)  # relay the request event, run the generation
    done = _poll(app, token, generation["id"])
    assert done["status"] == "succeeded", done
    assert done["completed_at"] is not None
    assert done["error"] is None
    proposal = done["result"]
    itinerary = proposal["itinerary"]
    assert [d["date"] for d in itinerary["days"]] == ["2026-12-04", "2026-12-05", "2026-12-06"]
    assert itinerary["destination"]["path"] == "portugal/lisbon"
    assert itinerary["time_zone"] == "Europe/Lisbon"
    assert proposal["disclaimer"].startswith("As sugestões da IA")  # Accept-Language pt-BR
    assert proposal["prompt_version"] == "itinerary.v1"
    item = itinerary["days"][0]["items"][0]
    assert item["unverified"] is True  # no catalog places yet (BL-4.01)
    assert [s["kind"] for s in item["source_attribution"]] == ["ai_general_knowledge"]

    # Telemetry without the prompt or the request (AI-008, AI-009).
    assert _row(app, generation["id"], "params") is None
    assert _row(app, generation["id"], "status") == "succeeded"
    assert int(str(_row(app, generation["id"], "input_tokens"))) > 0
    assert int(str(_row(app, generation["id"], "cost_micros"))) > 0
    assert _row(app, generation["id"], "attempts") == 1
    prompt = _fake(app).calls[-1]
    assert "pt-BR" in prompt.user
    assert user_id not in prompt.user

    _tick(app)  # the completion event becomes a notification
    notifications = app.client.get("/v1/notifications", headers=_auth(token)).json()["data"]
    assert any(n["type"] == "ai_generation_ready" for n in notifications)
    entitlements = app.client.get("/v1/billing/entitlements", headers=_auth(token)).json()
    assert entitlements["quotas"]["ai.itinerary_generations"]["used"] == 1

    stranger, _ = _user(app)
    _problem(
        app.client.get(f"/v1/ai/generations/{generation['id']}", headers=_auth(stranger)),
        404,
        "not_found",
    )


@pytest.mark.req("AI-002", "AI-003", "TRIP-001")
def test_apply_a_proposal_to_a_trip(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    generation = _accepted(app, token)
    _tick(app)
    trip = app.client.post(
        "/v1/trips",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "title": "Lisbon",
            "start_date": "2026-12-04",
            "end_date": "2026-12-06",
            "destination_ids": [_destination(app, "portugal/lisbon")],
        },
    ).json()
    url = f"/v1/trips/{trip['id']}/apply-itinerary"
    body = {"generation_id": generation["id"], "mode": "replace", "day_indexes": [0, 1]}
    _problem(app.client.post(url, headers=_auth(token), json=body), 428, "precondition_required")
    missing = {"generation_id": str(uuid.uuid4()), "mode": "merge"}
    _problem(
        app.client.post(url, headers={**_auth(token), "If-Match": '"1"'}, json=missing),
        404,
        "not_found",
    )

    applied = app.client.post(url, headers={**_auth(token), "If-Match": '"1"'}, json=body)
    assert applied.status_code == 200, applied.text
    assert_matches_contract(applied.json(), "Trip")
    trip = applied.json()
    assert trip["origin"] == "ai_assisted"
    assert trip["version"] == 2
    day0, day1, day2 = trip["days"]
    assert len(day0["items"]) == 3
    assert len(day1["items"]) == 3
    assert day2["items"] == []  # not selected
    item = day0["items"][0]
    assert item["origin"] == "ai"
    assert item["unverified"] is True
    assert item["start_time"] == "09:00"
    assert 0 < item["ai_confidence"] <= 1

    merged = app.client.post(
        url,
        headers={**_auth(token), "If-Match": '"2"'},
        json={"generation_id": generation["id"], "mode": "merge", "day_indexes": [0]},
    ).json()
    assert len(merged["days"][0]["items"]) == 6
    replaced = app.client.post(
        url,
        headers={**_auth(token), "If-Match": '"3"'},
        json={"generation_id": generation["id"], "mode": "replace", "day_indexes": [0]},
    ).json()
    assert len(replaced["days"][0]["items"]) == 3  # older items became sync tombstones

    other, _ = _user(app)
    _problem(
        app.client.post(
            f"/v1/trips/{trip['id']}/apply-itinerary",
            headers={**_auth(other), "If-Match": '"4"'},
            json=body,
        ),
        404,
        "not_found",
    )


@pytest.mark.req("AI-009")
def test_requests_are_validated_and_quota_limited(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _user(app)
    _problem(_generate(app, token, end_date="2026-12-30"), 422, "validation_failed")  # > 21 days
    _problem(_generate(app, token, end_date="2026-12-01"), 422, "validation_failed")
    _problem(_generate(app, token, destination_id=str(uuid.uuid4())), 422, "validation_failed")
    _problem(_generate(app, token, interests=["food", "Food"]), 422, "validation_failed")

    for _ in range(4):
        _insert(app, status="succeeded", user_id=user_id)
    _insert(app, status="validation_failed", user_id=user_id)  # failures are free
    last = _accepted(app, token)
    assert last["quota"] == {**last["quota"], "used": 5, "limit": 5}
    denied = _problem(_generate(app, token), 409, "quota_exceeded")
    assert denied["feature_key"] == "ai.itinerary_generations"
    recorded = db_scalar(
        app.db_url,
        "SELECT count(*) FROM ai_generations WHERE user_id = :u AND status = 'quota_exceeded'",
        u=uuid.UUID(user_id),
    )
    assert recorded == 1


@pytest.mark.req("AI-002")
def test_invalid_output_is_repaired_once_then_fails_typed(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    fake = _fake(app)

    fake.script('{"days": [], "warnings": [], "confidence": 0.5}')  # then the normal answer
    repaired = _accepted(app, token)
    _tick(app)
    assert _poll(app, token, repaired["id"])["status"] == "succeeded"
    assert _row(app, repaired["id"], "attempts") == 2
    assert "failed these checks" in (fake.calls[-1].feedback or "")

    fake.script(
        "not json",
        '{"days": [{"day_index": 5, "theme": null, "items": []}], '
        '"warnings": [], "confidence": 0.5}',
    )
    broken = _accepted(app, token)
    _tick(app)
    failed = _poll(app, token, broken["id"])
    assert failed["status"] == "failed"
    assert failed["result"] is None
    assert failed["error"]["code"] == "ai_output_invalid"
    assert failed["error"]["status"] == 502
    assert _row(app, broken["id"], "status") == "validation_failed"
    errors = _row(app, broken["id"], "validation_errors")
    assert isinstance(errors, list)
    assert any("day_index" in e for e in errors)
    assert failed["quota"]["used"] == 1  # only the repaired one counts

    fake.script("refuse")
    refused = _accepted(app, token)
    _tick(app)
    assert _poll(app, token, refused["id"])["error"]["code"] == "ai_output_invalid"
    assert _row(app, refused["id"], "status") == "refused"

    fake.script(ProviderError("overloaded", retryable=True, status=529))
    down = _accepted(app, token)
    _tick(app)
    assert _poll(app, token, down["id"])["error"]["code"] == "ai_unavailable"
    assert _row(app, down["id"], "status") == "provider_error"


@pytest.mark.req("AI-009")
def test_circuit_breakers_refuse_new_work(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    accepted = _accepted(app, token)

    for _ in range(5):  # five provider failures in a row, within the cooldown
        _insert(app, status="provider_error")
    busy = _problem(_generate(app, token), 503, "ai_unavailable")
    assert busy["detail"]
    _tick(app)  # work accepted before the breaker opened is closed, not sent
    assert _poll(app, token, accepted["id"])["error"]["code"] == "ai_unavailable"
    assert _row(app, accepted["id"], "status") == "unavailable"

    app.clock.set(app.clock.now() + timedelta(minutes=3))  # the cooldown passed: closed again
    assert _generate(app, token).status_code == 202

    _insert(app, status="succeeded", cost=25_000_000)  # today's budget (25 USD) is spent
    _problem(_generate(app, token), 503, "ai_unavailable")


@pytest.mark.req("AI-009")
def test_a_stuck_generation_fails_instead_of_pending_forever(app: LiveApp) -> None:  # noqa: F811
    token, _ = _user(app)
    stuck = _accepted(app, token)
    db_scalar(  # the job never ran (a crashed worker), and half an hour passed
        app.db_url,
        "UPDATE ai_generations SET created_at = created_at - interval '31 minutes' "
        "WHERE id = :i RETURNING 1",
        i=uuid.UUID(stuck["id"]),
    )
    failed = _poll(app, token, stuck["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "ai_unavailable"
    _tick(app)  # the late job leaves the closed generation alone
    assert _row(app, stuck["id"], "status") == "provider_error"
