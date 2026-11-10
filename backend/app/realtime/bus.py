"""Realtime fanout (docs/06 §5.3, ADR-0023): one channel per user.

Publishers name the users to tell, so membership is decided when the event is produced and a
removed member simply stops receiving. ``MemoryBus`` serves a single process (development, tests,
one gateway); ``RedisBus`` uses pub/sub channels ``rt:user:{id}`` across processes. Events are
JSON-safe dicts ``{"type": <server frame type>, "data": {...}}``. Delivery is best effort: the
database is the record and clients catch up by ``seq``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

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
        encoded = json.dumps(event, default=str)
        for user in set(user_ids):
            for subscription in list(self._subscriptions.get(user, ())):
                subscription.offer(json.loads(encoded))  # each connection gets its own copy

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
