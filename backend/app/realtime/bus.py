"""Realtime fanout (docs/06 §5.3, ADR-0023): one channel per user.

Publishers name the users to tell, so membership is decided when the event is produced and a
removed member simply stops receiving. ``MemoryBus`` serves a single process (development, tests,
one gateway); ``RedisBus`` uses pub/sub channels ``rt:user:{id}`` across processes, and
``PostgresBus`` uses ``LISTEN``/``NOTIFY`` where there is no Redis. Events are
JSON-safe dicts ``{"type": <server frame type>, "data": {...}}``. Delivery is best effort: the
database is the record and clients catch up by ``seq``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)

BUFFER_FRAMES = 1000  # docs/06 §10: server send buffer per connection


def _backpressure() -> dict[str, Any]:
    return {
        "type": "sync.required",
        "data": {"reason": "backpressure", "full_resync": True, "conversations": []},
    }


class Subscription(Protocol):
    async def get(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class RealtimeBus(Protocol):
    async def publish(self, user_ids: Sequence[uuid.UUID], event: Mapping[str, Any]) -> None: ...

    async def subscribe(self, user_id: uuid.UUID) -> Subscription: ...


class _MemorySubscription:
    def __init__(self, bus: MemoryBus, user_id: uuid.UUID) -> None:
        self._bus = bus
        self.user_id = user_id
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def offer(self, event: dict[str, Any]) -> None:
        if self._queue.qsize() >= BUFFER_FRAMES:
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait(_backpressure())
            return
        self._queue.put_nowait(event)

    async def get(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        self._bus.drop(self)


class MemoryBus:
    def __init__(self) -> None:
        self._subscriptions: dict[uuid.UUID, set[_MemorySubscription]] = defaultdict(set)

    async def publish(self, user_ids: Sequence[uuid.UUID], event: Mapping[str, Any]) -> None:
        self.deliver(user_ids, event)

    def deliver(self, user_ids: Sequence[uuid.UUID], event: Mapping[str, Any]) -> None:
        """Hand an event to this process's subscribers (synchronous: safe from callbacks)."""
        encoded = json.dumps(event, default=str)
        for user in set(user_ids):
            for subscription in list(self._subscriptions.get(user, ())):
                subscription.offer(json.loads(encoded))  # each connection gets its own copy

    def deliver_to_all(self, event: Mapping[str, Any]) -> None:
        self.deliver(list(self._subscriptions), event)

    async def subscribe(self, user_id: uuid.UUID) -> Subscription:
        subscription = _MemorySubscription(self, user_id)
        self._subscriptions[user_id].add(subscription)
        return subscription

    def drop(self, subscription: _MemorySubscription) -> None:
        subscribers = self._subscriptions.get(subscription.user_id)
        if subscribers is not None:
            subscribers.discard(subscription)
            if not subscribers:
                del self._subscriptions[subscription.user_id]


def _channel(user_id: uuid.UUID) -> str:
    return f"rt:user:{user_id}"


class _RedisSubscription:
    def __init__(self, pubsub: PubSub) -> None:
        self._pubsub = pubsub

    async def get(self) -> dict[str, Any]:
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
            if message is not None and message.get("type") == "message":
                event: dict[str, Any] = json.loads(message["data"])
                return event

    async def close(self) -> None:
        await self._pubsub.unsubscribe()
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]


class RedisBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, user_ids: Sequence[uuid.UUID], event: Mapping[str, Any]) -> None:
        encoded = json.dumps(event, default=str)
        for user in set(user_ids):
            await self._redis.publish(_channel(user), encoded)

    async def subscribe(self, user_id: uuid.UUID) -> Subscription:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(_channel(user_id))
        return _RedisSubscription(pubsub)


PG_CHANNEL = "tb_realtime"
# NOTIFY payloads are limited to 8000 bytes; large recipient lists are split across notifications.
_PG_PAYLOAD_LIMIT = 7000
_PG_USERS_PER_NOTIFY = 100


def _server_recovered() -> dict[str, Any]:
    return {
        "type": "sync.required",
        "data": {"reason": "server_recovered", "full_resync": True, "conversations": []},
    }


class PostgresBus:
    """Cross-process fanout over PostgreSQL ``LISTEN``/``NOTIFY`` without Redis (ADR-0033).

    Each process keeps its own subscribers (``MemoryBus``) and one listening connection. A publish
    is delivered to local subscribers at once and sent through ``pg_notify`` for the other
    processes (the API instances and the worker); a process ignores its own notifications by
    origin. ``LISTEN`` needs a session (a direct connection or a session pooler, never a
    transaction pooler). When the listening connection drops, it reconnects with backoff and tells
    every local subscriber to resync, since events may have been missed meanwhile.
    """

    def __init__(
        self,
        *,
        publish_engine: Any,
        listen_engine: Any,
        reconnect_seconds: tuple[float, float] = (1.0, 30.0),
    ) -> None:
        self._local = MemoryBus()
        self._origin = uuid.uuid4().hex
        self._publish_engine = publish_engine
        self._listen_engine = listen_engine
        self._reconnect = reconnect_seconds
        self._listener: asyncio.Task[None] | None = None
        self._listening = asyncio.Event()

    async def publish(self, user_ids: Sequence[uuid.UUID], event: Mapping[str, Any]) -> None:
        users = sorted({str(user) for user in user_ids})
        if not users:
            return
        self._local.deliver([uuid.UUID(u) for u in users], event)
        payloads = []
        for start in range(0, len(users), _PG_USERS_PER_NOTIFY):
            payload = json.dumps(
                {"o": self._origin, "u": users[start : start + _PG_USERS_PER_NOTIFY], "e": event},
                default=str,
                separators=(",", ":"),
            )
            if len(payload.encode()) > _PG_PAYLOAD_LIMIT:
                # Too big to carry: the other processes' subscribers catch up instead.
                payload = json.dumps(
                    {
                        "o": self._origin,
                        "u": users[start : start + _PG_USERS_PER_NOTIFY],
                        "e": _server_recovered(),
                    },
                    separators=(",", ":"),
                )
            payloads.append(payload)
        from sqlalchemy import text

        async with self._publish_engine.connect() as connection:
            for payload in payloads:
                await connection.execute(
                    text("SELECT pg_notify(:channel, :payload)"),
                    {"channel": PG_CHANNEL, "payload": payload},
                )
            await connection.commit()

    async def subscribe(self, user_id: uuid.UUID) -> Subscription:
        self.start()
        return await self._local.subscribe(user_id)

    def start(self) -> None:
        if self._listener is None or self._listener.done():
            self._listener = asyncio.create_task(self._listen(), name="realtime-pg-listener")

    async def wait_listening(self) -> None:
        """Until the listening connection is up (tests and readiness)."""
        self.start()
        await self._listening.wait()

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            message = json.loads(payload)
            if message.get("o") == self._origin:
                return
            users = [uuid.UUID(str(u)) for u in message.get("u") or []]
            event = message.get("e")
        except (ValueError, TypeError, AttributeError):
            return
        if isinstance(event, dict) and users:
            self._local.deliver(users, event)

    async def _listen(self) -> None:
        delay, cap = self._reconnect
        recovered = False
        while True:
            try:
                async with self._listen_engine.connect() as connection:
                    raw = await connection.get_raw_connection()
                    driver = raw.driver_connection
                    lost = asyncio.Event()
                    driver.add_termination_listener(_setter(lost))
                    await driver.add_listener(PG_CHANNEL, self._on_notify)
                    self._listening.set()
                    if recovered:
                        self._local.deliver_to_all(_server_recovered())
                    delay = self._reconnect[0]
                    while not lost.is_set():
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(lost.wait(), timeout=30.0)
                        if not lost.is_set():
                            await driver.execute("SELECT 1")  # keeps poolers from idling it out
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("realtime_pg_listener_lost", exc_info=True)
            self._listening.clear()
            recovered = True
            await asyncio.sleep(delay)
            delay = min(cap, delay * 2)


def _setter(event: asyncio.Event) -> Any:
    """A connection-termination callback that sets ``event``."""

    def callback(_connection: Any) -> None:
        event.set()

    return callback
