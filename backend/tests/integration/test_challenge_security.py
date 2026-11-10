"""Challenge security (BL-5.09; T-CHAL-01, T-CHAL-02, CHAL-005, CHAL-008): accepted answers never
reach members, and submissions are rate limited on top of attempts and cooldowns. The race on
first-correct (T-CHAL-07) is covered in test_challenges."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.ratelimit import MemoryRateLimitStore
from app.core.time import FixedClock
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings
from tests.integration.conftest import LiveApp
from tests.integration.test_billing import (
    CRON,
    _seed_products,
    store,  # noqa: F401 - dev billing app fixture
)
from tests.integration.test_challenges import _setup, _started, _submit
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _join
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem

pytestmark = [pytest.mark.integration, pytest.mark.security]

SECRET_ANSWER = "Zyzzogeton Lighthouse"
LATER_HINT = "Look past the harbour wall"


@pytest.fixture
def limited_store(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
    """The dev billing app with real (in-memory) rate limits and a tight submission budget."""

    async def ok() -> bool:
        return True

    _seed_products(catalog)
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    application = create_app(
        make_settings(
            database_url=catalog,
            dev_idp_enabled=True,
            dev_billing_enabled=True,
            cron_secret=SecretStr(CRON),
            rate_limits={"auth": "1000/60", "submission": "3/60"},
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
        rate_limit_store=MemoryRateLimitStore(),
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog)


@pytest.mark.req("CHAL-008", "T-CHAL-01")
def test_accepted_answers_never_reach_member_endpoints(store: LiveApp) -> None:  # noqa: F811
    admin, member, group = _setup(store)
    now = store.clock.now()
    cid = _started(
        store,
        admin,
        group,
        accepted_answers=[SECRET_ANSWER],
        hints=[
            {"body": "Think of the coast."},
            {"body": LATER_HINT, "release_at": (now + timedelta(days=3)).isoformat()},
        ],
    )
    wrong = _submit(store, member, cid, "The old fort")
    assert wrong.json()["evaluation_status"] == "incorrect"
    solver, _ = _join(store, admin, group)
    right = _submit(store, solver, cid, SECRET_ANSWER.lower())
    assert right.json()["evaluation_status"] == "correct"

    responses = [
        wrong,
        right,
        store.client.get(f"/v1/challenges/{cid}", headers=_auth(member)),
        store.client.get(f"/v1/groups/{group}/challenges", headers=_auth(member)),
        store.client.get(f"/v1/challenges/{cid}/hints", headers=_auth(member)),
        store.client.get(f"/v1/challenges/{cid}/results", headers=_auth(member)),
        store.client.get(f"/v1/challenges/{cid}/submissions", headers=_auth(member)),
        store.client.get(f"/v1/challenges/{cid}/teams", headers=_auth(member)),
        store.client.get(f"/v1/challenges/{cid}/disputes", headers=_auth(member)),
        store.client.get("/v1/notifications", headers=_auth(member)),
    ]
    for response in responses:
        assert response.status_code in (200, 201), (response.request.url, response.text)
        text = response.text.casefold()
        assert "zyzzogeton" not in text, response.request.url
        assert LATER_HINT.casefold() not in text, response.request.url
    # Even the manager view (which lists every hint) carries only a count of the answers: they
    # have their own audited, judge-only endpoint.
    managed = store.client.get(f"/v1/challenges/{cid}/manage", headers=_auth(admin))
    assert managed.status_code == 200, managed.text
    assert "zyzzogeton" not in managed.text.casefold()
    assert managed.json()["answer_count"] == 1
    _problem(
        store.client.get(f"/v1/challenges/{cid}/answers", headers=_auth(member)), 403, "forbidden"
    )


@pytest.mark.req("CHAL-005", "T-CHAL-02")
def test_submissions_are_rate_limited_on_top_of_attempts(limited_store: LiveApp) -> None:
    admin, member, group = _setup(limited_store)
    cid = _started(limited_store, admin, group, max_attempts=10, attempt_cooldown_seconds=0)
    for guess in ("Porto", "Sintra", "Faro"):
        assert _submit(limited_store, member, cid, guess).status_code == 201
    limited = _submit(limited_store, member, cid, "Belém Tower")
    _problem(limited, 429, "rate_limited")
    assert int(limited.headers["retry-after"]) > 0
    # Other members have their own budget.
    other, _ = _join(limited_store, admin, group)
    assert _submit(limited_store, other, cid, "Belém Tower").status_code == 201
    view = limited_store.client.get(f"/v1/challenges/{cid}", headers=_auth(member)).json()
    assert view["my_participation"]["attempts_used"] == 3  # the refused call used no attempt
