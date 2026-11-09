"""Rate limiting against real stores and real flows (BL-1.15; SAFE-005, NFR-006, T-AUTH-11)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.ratelimit import MemoryRateLimitStore, RedisRateLimitStore, WindowHit
from app.core.redis import create_redis
from app.core.time import FixedClock
from app.main import create_app
from app.modules.platform.service import PostgresRateLimitStore
from tests.conftest import make_identity_settings, make_settings
from tests.integration.conftest import LiveApp, _truncate_users
from tests.integration.test_identity_flows import _auth, _id_token, _register

pytestmark = [pytest.mark.integration, pytest.mark.req("SAFE-005", "NFR-006")]


def _hits(key: str, window_start: int) -> list[WindowHit]:
    return [WindowHit(key=key, window_start=window_start, window_seconds=60)]


def test_postgres_store_counts_current_and_previous_windows(schema_db_url: str) -> None:
    key = f"rl:test:{uuid.uuid4()}"

    async def run() -> list[list[tuple[int, int]]]:
        engine = create_async_engine(schema_db_url)
        store = PostgresRateLimitStore(async_sessionmaker(engine), prune_every=3)
        try:
            return [
                await store.hit(_hits(key, 600)),
                await store.hit(_hits(key, 600)),
                await store.hit(_hits(key, 660)),  # also prunes expired rows (3rd call)
                await store.hit(_hits(f"{key}:other", 660)),
            ]
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == [[(1, 0)], [(2, 0)], [(1, 2)], [(1, 0)]]


def test_redis_store_counts_current_and_previous_windows(test_redis_url: str) -> None:
    key = f"rl:test:{uuid.uuid4()}"

    async def run() -> list[list[tuple[int, int]]]:
        redis = create_redis(test_redis_url)
        store = RedisRateLimitStore(redis)
        try:
            return [
                await store.hit(_hits(key, 600)),
                await store.hit(_hits(key, 600)),
                await store.hit(_hits(key, 660)),
            ]
        finally:
            await redis.aclose()

    assert asyncio.run(run()) == [[(1, 0)], [(2, 0)], [(1, 2)]]


@pytest.fixture
def limited(schema_db_url: str) -> Iterator[LiveApp]:
    """A live app with tight per-subject, per-session and report limits."""
    _truncate_users(schema_db_url)
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))

    async def ok() -> bool:
        return True

    app = create_app(
        make_settings(
            database_url=schema_db_url,
            dev_idp_enabled=True,
            rate_limits={
                "auth": "1000/60",  # dev IdP mints count per IP; not under test here
                "auth_subject": "2/3600",
                "auth_refresh": "2/3600",
                "reports": "1/86400",
            },
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
        rate_limit_store=MemoryRateLimitStore(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=schema_db_url)


def _login(live: LiveApp, sub: str, email: str) -> Any:
    return live.client.post(
        "/v1/auth/login",
        json={"id_token": _id_token(live, sub=sub, email=email), "client": "web"},
    )


@pytest.mark.security
def test_sign_ins_are_limited_per_idp_subject(limited: LiveApp) -> None:
    sub, email = f"user-{uuid.uuid4()}", f"{uuid.uuid4().hex[:10]}@example.com"
    assert _register(limited, _id_token(limited, sub=sub, email=email)).status_code == 201
    first = _login(limited, sub, email)
    assert first.status_code == 200
    blocked = _login(limited, sub, email)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) > 60
    # Another account from the same client is unaffected.
    other = _register(limited, _id_token(limited))
    assert other.status_code == 201


@pytest.mark.security
def test_refreshes_are_limited_per_session(limited: LiveApp) -> None:
    registered = _register(limited, _id_token(limited)).json()
    token = registered["tokens"]["refresh_token"]
    for _ in range(2):
        rotated = limited.client.post("/v1/auth/refresh", json={"refresh_token": token})
        assert rotated.status_code == 200, rotated.text
        token = rotated.json()["refresh_token"]
    blocked = limited.client.post("/v1/auth/refresh", json={"refresh_token": token})
    assert blocked.status_code == 429
    # Nothing rotated on the rejected attempt: the same token works once the windows pass.
    limited.clock.set(limited.clock.now() + timedelta(hours=2))
    later = limited.client.post("/v1/auth/refresh", json={"refresh_token": token})
    assert later.status_code == 200, later.text


@pytest.mark.req("SAFE-002")
def test_reports_have_their_own_daily_bucket(limited: LiveApp) -> None:
    reporter = _register(limited, _id_token(limited)).json()["tokens"]["access_token"]
    targets = [_register(limited, _id_token(limited)).json()["user"]["account"]["id"] for _ in "ab"]
    first = limited.client.post(
        "/v1/reports",
        headers=_auth(reporter),
        json={"target_type": "user", "target_id": targets[0], "reason": "spam"},
    )
    assert first.status_code == 202, first.text
    second = limited.client.post(
        "/v1/reports",
        headers=_auth(reporter),
        json={"target_type": "user", "target_id": targets[1], "reason": "spam"},
    )
    assert second.status_code == 429
    assert second.headers["RateLimit-Limit"] == "1"
