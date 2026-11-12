"""PostgreSQL LISTEN/NOTIFY fanout across processes (ADR-0033)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.core.db import Database
from app.realtime.bus import PostgresBus

pytestmark = pytest.mark.integration


def _bus(url: str) -> tuple[PostgresBus, list[Database]]:
    publisher, listener = Database(url, pool_size=1), Database(url, pool_size=1, max_overflow=0)
    return (
        PostgresBus(
            publish_engine=publisher.engine,
            listen_engine=listener.engine,
            reconnect_seconds=(0.05, 0.2),
        ),
        [publisher, listener],
    )


async def _next(subscription: Any, seconds: float = 5.0) -> dict[str, Any]:
    event: dict[str, Any] = await asyncio.wait_for(subscription.get(), seconds)
    return event


async def _nothing(subscription: Any, seconds: float = 0.4) -> bool:
    try:
        await asyncio.wait_for(subscription.get(), seconds)
    except TimeoutError:
        return True
    return False


def test_events_cross_processes_once(schema_db_url: str) -> None:
    async def scenario() -> None:
        api, api_dbs = _bus(schema_db_url)
        worker, worker_dbs = _bus(schema_db_url)
        ana, bo = uuid.uuid4(), uuid.uuid4()
        try:
            ana_socket = await api.subscribe(ana)
            await api.wait_listening()
            # From another process (the worker): delivered through NOTIFY.
            event = {"type": "notification.new", "data": {"notification_id": str(uuid.uuid4())}}
            await worker.publish([ana], event)
            assert await _next(ana_socket) == event
            # From the same process: delivered locally, and its own NOTIFY is ignored.
            typing = {"type": "typing", "data": {"state": "started"}}
            await api.publish([ana, bo], typing)
            assert await _next(ana_socket) == typing
            assert await _nothing(ana_socket)
            # Only the users named.
            await worker.publish([bo], {"type": "typing", "data": {}})
            assert await _nothing(ana_socket)
        finally:
            for bus, dbs in ((api, api_dbs), (worker, worker_dbs)):
                await bus.close()
                for db in dbs:
                    await db.dispose()

    asyncio.run(scenario())


def test_large_recipient_lists_are_split(schema_db_url: str) -> None:
    async def scenario() -> None:
        api, api_dbs = _bus(schema_db_url)
        worker, worker_dbs = _bus(schema_db_url)
        members = [uuid.uuid4() for _ in range(250)]
        try:
            last = await api.subscribe(members[-1])
            first = await api.subscribe(members[0])
            await api.wait_listening()
            event = {"type": "message.new", "data": {"conversation_id": str(uuid.uuid4())}}
            await worker.publish(members, event)
            assert await _next(first) == event
            assert await _next(last) == event
        finally:
            for bus, dbs in ((api, api_dbs), (worker, worker_dbs)):
                await bus.close()
                for db in dbs:
                    await db.dispose()

    asyncio.run(scenario())


def test_auto_picks_postgres_without_redis() -> None:
    from app.core.config import AppEnv, Settings

    def resolved(**values: object) -> str:
        defaults: dict[str, object] = {
            "app_env": AppEnv.STAGING,
            "redis_url": "",
            "realtime_bus": "auto",
            "database_transaction_pooler": False,
        }
        return Settings.model_construct(**{**defaults, **values}).resolved_realtime_bus

    assert resolved() == "postgres"
    assert resolved(redis_url="redis://cache:6379/0") == "redis"
    assert resolved(database_transaction_pooler=True) == "memory"  # can't LISTEN
    assert resolved(app_env=AppEnv.TEST) == "memory"
    assert resolved(realtime_bus="memory") == "memory"
