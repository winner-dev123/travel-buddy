"""Premium replanning of an existing trip (BL-4.05; AI-005, AI-007, AI-008)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_billing import store  # noqa: F401 - dev billing app fixture
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _premium
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _destination, _problem, _tick, _user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _fresh(store: LiveApp) -> Iterator[None]:  # noqa: F811
    clear = "WITH a AS (DELETE FROM ai_generations RETURNING 1) SELECT count(*) FROM a"
    db_scalar(store.db_url, clear)
    yield
    db_scalar(store.db_url, clear)


def _trip(live: LiveApp, token: str) -> dict[str, Any]:
    trip = live.client.post(
        "/v1/trips",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "title": "Lisbon",
            "start_date": "2026-12-04",
            "end_date": "2026-12-06",
            "destination_ids": [_destination(live, "portugal/lisbon")],
        },
    ).json()
    url = f"/v1/trips/{trip['id']}/days/{trip['days'][0]['id']}/items"
    for version, (title, at) in enumerate([("Fado night", "21:00"), ("Tram 28", "10:00")], 1):
        trip = live.client.post(
            url,
            headers={**_auth(token), "If-Match": f'"{version}"'},
            json={"kind": "activity", "title": title, "start_time": at, "duration_minutes": 60},
        ).json()
    return dict(trip)


def _replan(live: LiveApp, token: str, trip_id: str, **body: Any) -> Any:
    return live.client.post(
        f"/v1/ai/trips/{trip_id}/replan",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={"instruction": "It will rain on the first day", **body},
    )


@pytest.mark.req("AI-005", "AI-008")
def test_premium_travellers_replan_chosen_days_and_apply_the_proposal(
    store: LiveApp,  # noqa: F811
) -> None:
    token, _, _ = _premium(store)
    trip = _trip(store, token)
    tram = next(i for i in trip["days"][0]["items"] if i["title"] == "Tram 28")

    accepted = _replan(
        store,
        token,
        trip["id"],
        base_version=trip["version"],
        day_indexes=[0],
        constraints={"keep_item_ids": [tram["id"]], "avoid_categories": ["viewpoint"]},
    )
    assert accepted.status_code == 202, accepted.text
    assert_matches_contract(accepted.json(), "AIGeneration")
    generation = accepted.json()
    assert generation["feature"] == "trip_replan"
    assert generation["quota"] == {**generation["quota"], "used": 1, "limit": 60}

    _tick(store)
    done = store.client.get(f"/v1/ai/generations/{generation['id']}", headers=_auth(token))
    assert_matches_contract(done.json(), "AIGeneration")
    assert done.json()["status"] == "succeeded", done.json()
    [day] = done.json()["result"]["itinerary"]["days"]  # only the requested day
    assert day["day_index"] == 0
    titles = [item["title"] for item in day["items"]]
    assert "Tram 28" in titles  # kept unchanged
    assert "Fado night" not in titles
    assert all(item["category"] != "viewpoint" for item in day["items"])
    prompt = store.client.app.state.ai_provider.calls[-1]  # type: ignore[attr-defined]
    assert "It will rain on the first day" in prompt.user
    assert "Fado night" in prompt.user  # the current plan is the context
    assert '"days_to_replan": [0]' in prompt.user
    assert _row_params(store, generation["id"]) is None  # cleared once answered

    # Nothing changed yet; applying replaces day 0 only.
    unchanged = store.client.get(f"/v1/trips/{trip['id']}", headers=_auth(token)).json()
    assert unchanged["version"] == trip["version"]
    applied = store.client.post(
        f"/v1/trips/{trip['id']}/apply-itinerary",
        headers={**_auth(token), "If-Match": f'"{trip["version"]}"'},
        json={"generation_id": generation["id"], "mode": "replace", "day_indexes": [0]},
    )
    assert applied.status_code == 200, applied.text
    new_titles = [i["title"] for i in applied.json()["days"][0]["items"]]
    assert "Tram 28" in new_titles
    assert "Fado night" not in new_titles


def _row_params(live: LiveApp, generation_id: str) -> object:
    return db_scalar(
        live.db_url, "SELECT params FROM ai_generations WHERE id = :i", i=uuid.UUID(generation_id)
    )


@pytest.mark.req("AI-005")
def test_replanning_is_premium_current_and_scoped_to_the_trip(store: LiveApp) -> None:  # noqa: F811
    free, _ = _user(store)
    free_trip = _trip(store, free)
    denied = _problem(
        _replan(store, free, free_trip["id"], base_version=free_trip["version"]),
        403,
        "entitlement_required",
    )
    assert denied["entitlement"] == "ai.trip_replan"

    token, _, _ = _premium(store)
    trip = _trip(store, token)
    _problem(_replan(store, token, trip["id"], base_version=1), 409, "conflict")  # stale
    _problem(
        _replan(store, token, trip["id"], base_version=trip["version"], day_indexes=[7]),
        422,
        "validation_failed",
    )
    _problem(
        _replan(
            store,
            token,
            trip["id"],
            base_version=trip["version"],
            constraints={"keep_item_ids": [str(uuid.uuid4())]},
        ),
        422,
        "validation_failed",
    )
    _problem(
        _replan(store, token, trip["id"], base_version=trip["version"], instruction="x"),
        422,
        "validation_failed",
    )
    # Someone else's private trip does not exist for them.
    _problem(_replan(store, free, trip["id"], base_version=trip["version"]), 404, "not_found")

    everything = _replan(store, token, trip["id"], base_version=trip["version"])
    assert everything.status_code == 202, everything.text
    _tick(store)
    result = store.client.get(
        f"/v1/ai/generations/{everything.json()['id']}", headers=_auth(token)
    ).json()
    assert [d["day_index"] for d in result["result"]["itinerary"]["days"]] == [0, 1, 2]
