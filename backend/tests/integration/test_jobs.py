"""Durable jobs, the outbox relay and web cache webhooks against PostgreSQL (BL-1.09, BL-1.25)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import AppEnv
from app.core.time import FixedClock
from app.main import create_app
from app.modules.platform.service import (
    EventRouter,
    Job,
    JobRunner,
    PermanentJobError,
    enqueue,
    record_event,
)
from app.modules.web_cache.config import WebCacheSettings
from app.modules.web_cache.domain import signature_header
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import db_scalar
from tests.integration.test_identity_flows import _auth, _id_token, _register

pytestmark = pytest.mark.integration

CRON = "c" * 40
WEBHOOK_SECRET = "w" * 40
WEBHOOK_URL = "https://web.test/api/revalidate"


def _execute(url: str, sql: str) -> None:
    async def run() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
        finally:
            await engine.dispose()

    asyncio.run(run())


def _reset(url: str) -> None:
    _execute(url, "TRUNCATE outbox_events, asynchronous_jobs")


async def _with_db(
    url: str, work: Callable[[async_sessionmaker[AsyncSession]], Awaitable[Any]]
) -> Any:
    engine = create_async_engine(url)
    try:
        return await work(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def _job_row(url: str, kind: str) -> dict[str, Any]:
    async def read(maker: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
        async with maker() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT status, attempts, run_at, last_error, locked_by "
                        "FROM asynchronous_jobs WHERE kind = :k"
                    ),
                    {"k": kind},
                )
            ).one()
            return dict(row._mapping)

    result: dict[str, Any] = asyncio.run(_with_db(url, read))
    return result


def _run_tick(
    url: str,
    handlers: dict[str, Callable[[Job], Awaitable[None]]],
    router: EventRouter | None = None,
    setup: Callable[[AsyncSession], Awaitable[None]] | None = None,
) -> dict[str, int]:
    async def work(maker: async_sessionmaker[AsyncSession]) -> dict[str, int]:
        if setup is not None:
            async with maker() as session, session.begin():
                await setup(session)
        runner = JobRunner(sessionmaker=maker, router=router or EventRouter(), handlers=handlers)
        return (await runner.tick(budget_seconds=5)).as_dict()

    result: dict[str, int] = asyncio.run(_with_db(url, work))
    return result


# ─────────────────────────────────── queue ───────────────────────────────────


def test_dedupe_key_allows_one_active_job(schema_db_url: str) -> None:
    _reset(schema_db_url)

    async def work(maker: async_sessionmaker[AsyncSession]) -> list[bool]:
        async with maker() as session, session.begin():
            first = await enqueue(session, queue="default", kind="k", payload={}, dedupe_key="d1")
            second = await enqueue(session, queue="default", kind="k", payload={}, dedupe_key="d1")
            other = await enqueue(session, queue="default", kind="k", payload={}, dedupe_key="d2")
        return [first, second, other]

    assert asyncio.run(_with_db(schema_db_url, work)) == [True, False, True]


def test_successful_job_completes(schema_db_url: str) -> None:
    _reset(schema_db_url)
    seen: list[dict[str, Any]] = []

    async def handler(job: Job) -> None:
        seen.append(dict(job.payload))

    async def setup(session: AsyncSession) -> None:
        await enqueue(session, queue="default", kind="ok", payload={"n": 1})

    result = _run_tick(schema_db_url, {"ok": handler}, setup=setup)
    assert result["succeeded"] == 1
    assert seen == [{"n": 1}]
    row = _job_row(schema_db_url, "ok")
    assert row["status"] == "succeeded"
    assert row["locked_by"] is None


def test_failing_job_is_retried_with_backoff(schema_db_url: str) -> None:
    _reset(schema_db_url)

    async def handler(_job: Job) -> None:
        raise RuntimeError("receiver down")

    async def setup(session: AsyncSession) -> None:
        await enqueue(session, queue="default", kind="flaky", payload={})

    result = _run_tick(schema_db_url, {"flaky": handler}, setup=setup)
    assert result["retried"] == 1
    row = _job_row(schema_db_url, "flaky")
    assert row["status"] == "queued"
    assert row["attempts"] == 1
    assert "receiver down" in row["last_error"]
    delay = db_scalar(
        schema_db_url,
        "SELECT extract(epoch FROM run_at - now()) FROM asynchronous_jobs WHERE kind = 'flaky'",
    )
    assert 10 <= float(delay) <= 15  # type: ignore[arg-type]
    # Not due yet: an immediate second tick does nothing.
    assert _run_tick(schema_db_url, {"flaky": handler})["retried"] == 0


@pytest.mark.parametrize(
    ("kind", "max_attempts"),
    [("permanent", 10), ("exhausted", 1), ("unregistered", 10)],
)
def test_jobs_go_dead(schema_db_url: str, kind: str, max_attempts: int) -> None:
    _reset(schema_db_url)

    async def permanent(_job: Job) -> None:
        raise PermanentJobError("signature rejected")

    async def failing(_job: Job) -> None:
        raise RuntimeError("still down")

    async def setup(session: AsyncSession) -> None:
        await enqueue(session, queue="default", kind=kind, payload={}, max_attempts=max_attempts)

    handlers = {"permanent": permanent, "exhausted": failing}
    result = _run_tick(schema_db_url, handlers, setup=setup)
    assert result["dead"] == 1
    assert _job_row(schema_db_url, kind)["status"] == "dead"


def test_jobs_abandoned_by_a_crashed_worker_are_recovered(schema_db_url: str) -> None:
    _reset(schema_db_url)
    ran: list[str] = []

    async def handler(job: Job) -> None:
        ran.append(job.kind)

    async def setup(session: AsyncSession) -> None:
        await enqueue(session, queue="default", kind="orphan", payload={})
        await session.execute(
            text(
                "UPDATE asynchronous_jobs SET status = 'running', locked_by = 'dead-worker', "
                "locked_at = now() - interval '10 minutes' WHERE kind = 'orphan'"
            )
        )

    result = _run_tick(schema_db_url, {"orphan": handler}, setup=setup)
    assert result["recovered"] == 1
    assert ran == ["orphan"]


def test_relay_turns_events_into_jobs_exactly_once(schema_db_url: str) -> None:
    _reset(schema_db_url)
    router = EventRouter()
    router.subscribe("thing.happened", queue="default", kind="react")
    router.subscribe("thing.happened", queue="default", kind="ignored", when=lambda d: False)
    payloads: list[dict[str, Any]] = []

    async def react(job: Job) -> None:
        payloads.append(dict(job.payload))

    async def setup(session: AsyncSession) -> None:
        record_event(
            session,
            aggregate_type="thing",
            aggregate_id=uuid.uuid4(),
            event_type="thing.happened",
            payload={"x": 1},
        )

    result = _run_tick(schema_db_url, {"react": react}, router=router, setup=setup)
    assert result["relayed"] == 1
    assert result["succeeded"] == 1
    assert payloads[0]["event_type"] == "thing.happened"
    assert payloads[0]["data"] == {"x": 1}
    published = db_scalar(
        schema_db_url, "SELECT count(*) FROM outbox_events WHERE published_at IS NOT NULL"
    )
    assert published == 1
    # A second tick relays nothing new.
    assert _run_tick(schema_db_url, {"react": react}, router=router)["relayed"] == 0
    assert db_scalar(schema_db_url, "SELECT count(*) FROM asynchronous_jobs") == 1


# ─────────────────────────────── web cache webhooks (end to end) ───────────────────────────────


@dataclass
class WebhookApp:
    client: TestClient
    clock: FixedClock
    db_url: str
    received: list[httpx.Request]


def _webhook_app(schema_db_url: str, *, inline: bool) -> Iterator[WebhookApp]:
    _execute(schema_db_url, "TRUNCATE users CASCADE")
    _reset(schema_db_url)
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    received: list[httpx.Request] = []

    def web(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(204)

    async def ok() -> bool:
        return True

    app = create_app(
        make_settings(
            database_url=schema_db_url,
            dev_idp_enabled=True,
            cron_secret=SecretStr(CRON),
            jobs_inline_after_response=inline,
        ),
        identity_settings=make_identity_settings(),
        web_cache_settings=WebCacheSettings(  # type: ignore[call-arg]
            _env_file=None,
            app_env=AppEnv.TEST,
            web_revalidate_url=WEBHOOK_URL,
            web_revalidate_secret=SecretStr(WEBHOOK_SECRET),
        ),
        readiness_checks={"db": ok},
        clock=clock,
        http_transport=httpx.MockTransport(web),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield WebhookApp(client=client, clock=clock, db_url=schema_db_url, received=received)


@pytest.fixture
def webhook_app(schema_db_url: str) -> Iterator[WebhookApp]:
    yield from _webhook_app(schema_db_url, inline=False)


@pytest.fixture
def inline_webhook_app(schema_db_url: str) -> Iterator[WebhookApp]:
    yield from _webhook_app(schema_db_url, inline=True)


def _signed_in(app: WebhookApp) -> tuple[str, str]:
    response = _register(app, _id_token(app))  # type: ignore[arg-type]
    assert response.status_code == 201, response.text
    body = response.json()
    return str(body["tokens"]["access_token"]), str(body["user"]["profile"]["handle"])


def _assert_signed(request: httpx.Request) -> dict[str, Any]:
    header = request.headers["X-TB-Signature"]
    timestamp = int(header.split(",")[0].removeprefix("t="))
    assert header == signature_header(WEBHOOK_SECRET.encode(), timestamp, request.content)
    payload: dict[str, Any] = json.loads(request.content)
    return payload


@pytest.mark.req("SAFE-012", "PROF-008")
def test_indexing_change_reaches_the_web_via_the_cron_tick(webhook_app: WebhookApp) -> None:
    token, handle = _signed_in(webhook_app)
    response = webhook_app.client.patch(
        "/v1/users/me/privacy", headers=_auth(token), json={"search_engine_indexing": True}
    )
    assert response.status_code == 200, response.text
    assert webhook_app.received == []  # nothing sent until a tick runs

    tick = webhook_app.client.get(
        "/internal/jobs/tick", headers={"Authorization": f"Bearer {CRON}"}
    )
    assert tick.status_code == 200, tick.text
    assert_matches_contract(tick.json(), "JobTickResult")
    # >= 1: the first tick in a fresh database also runs the daily retention purges (BL-1.18).
    assert tick.json()["data"]["succeeded"] >= 1

    [request] = webhook_app.received
    payload = _assert_signed(request)
    assert payload["reason"] == "indexing_consent_changed"
    assert payload["tags"] == [f"profile:{handle}", "stories", "sitemap"]
    event_id = db_scalar(
        webhook_app.db_url,
        "SELECT id::text FROM outbox_events WHERE event_type = 'privacy.updated'",
    )
    assert payload["event_id"] == event_id


@pytest.mark.req("SAFE-012")
def test_handle_change_is_pushed_right_after_the_response(inline_webhook_app: WebhookApp) -> None:
    token, old_handle = _signed_in(inline_webhook_app)
    new_handle = f"new_{uuid.uuid4().hex[:8]}"
    response = inline_webhook_app.client.patch(
        "/v1/users/me", headers=_auth(token), json={"handle": new_handle, "bio": "Hi"}
    )
    assert response.status_code == 200, response.text
    [request] = inline_webhook_app.received
    payload = _assert_signed(request)
    assert payload["reason"] == "profile_visibility_changed"
    assert payload["tags"] == [
        f"profile:{new_handle}",
        f"profile:{old_handle}",
        "stories",
        "sitemap",
    ]


def test_ordinary_edits_send_no_webhook(inline_webhook_app: WebhookApp) -> None:
    token, _ = _signed_in(inline_webhook_app)
    response = inline_webhook_app.client.patch(
        "/v1/users/me", headers=_auth(token), json={"bio": "Only the bio changed"}
    )
    assert response.status_code == 200
    assert inline_webhook_app.received == []


@pytest.mark.security
def test_tick_endpoint_requires_the_cron_secret(webhook_app: WebhookApp) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {CRON}"}):
        response = webhook_app.client.post("/internal/jobs/tick", headers=headers)
        assert response.status_code == 401, headers
        assert_matches_contract(response.json(), "Problem")


@pytest.mark.security
def test_tick_endpoint_is_absent_without_a_cron_secret(live_app: Any) -> None:
    response = live_app.client.get("/internal/jobs/tick", headers={"Authorization": "Bearer x"})
    assert response.status_code == 404


def test_worker_once_processes_due_jobs(schema_db_url: str) -> None:
    """``python -m app.worker --once`` relays and runs jobs, then exits cleanly."""
    import os
    import subprocess
    import sys

    from tests.conftest import BACKEND_ROOT

    _reset(schema_db_url)

    async def setup(maker: async_sessionmaker[AsyncSession]) -> None:
        async with maker() as session, session.begin():
            await enqueue(session, queue="default", kind="no.handler", payload={})

    asyncio.run(_with_db(schema_db_url, setup))
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": schema_db_url,
        "REDIS_URL": "",
        "LOG_JSON": "false",
        "WEB_REVALIDATE_URL": "",
    }
    completed = subprocess.run(
        [sys.executable, "-m", "app.worker", "--once"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    # The job had no handler, so the worker dead-lettered it instead of looping on it.
    assert _job_row(schema_db_url, "no.handler")["status"] == "dead"
