"""Group join requests (GRP-006) wait for public groups: the routes sit behind the
``group_join_requests`` flag and, while every group is private and invite-only, there is nothing
to request or review."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.time import FixedClock
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp
from tests.integration.test_billing import (
    CRON,
    _seed_products,
    store,  # noqa: F401 - dev billing app fixture
)
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_groups import _group, _join, _premium
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _user

pytestmark = pytest.mark.integration


@pytest.fixture
def flagged(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
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
            feature_flags={"group_join_requests": True},
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog)


def _ask(live: LiveApp, token: str, group_id: str) -> object:
    return live.client.post(
        f"/v1/groups/{group_id}/join-requests",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={"message": "We'll be in Lisbon the same week!"},
    )


@pytest.mark.req("GRP-006")
def test_join_requests_are_off_until_public_groups_exist(store: LiveApp) -> None:  # noqa: F811
    owner, _, _ = _premium(store)
    group = _group(store, owner)
    outsider, _ = _user(store)
    response = _ask(store, outsider, group["id"])
    _problem(response, 403, "feature_disabled")  # type: ignore[arg-type]
    listed = store.client.get(f"/v1/groups/{group['id']}/join-requests", headers=_auth(owner))
    _problem(listed, 403, "feature_disabled")


@pytest.mark.req("GRP-006", "GRP-002")
def test_with_the_flag_on_invite_only_groups_take_no_requests(flagged: LiveApp) -> None:
    owner, _, _ = _premium(flagged)
    group = _group(flagged, owner)
    member, _ = _join(flagged, owner, group["id"])
    outsider, _ = _user(flagged)
    base = f"/v1/groups/{group['id']}/join-requests"
    _problem(_ask(flagged, outsider, group["id"]), 404, "not_found")  # type: ignore[arg-type]
    listed = flagged.client.get(base, headers=_auth(owner))
    assert listed.status_code == 200, listed.text
    assert_matches_contract(listed.json(), "GroupJoinRequestPage")
    assert listed.json()["data"] == []
    _problem(flagged.client.get(base, headers=_auth(member)), 403, "forbidden")
    missing = f"{base}/{uuid.uuid4()}"
    _problem(flagged.client.post(f"{missing}/approve", headers=_auth(owner)), 404, "not_found")
    _problem(flagged.client.post(f"{missing}/reject", headers=_auth(member)), 403, "forbidden")
