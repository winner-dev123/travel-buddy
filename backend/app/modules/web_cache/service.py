"""Public interface of the web_cache module: subscriptions and the signed webhook job (BL-1.25).

Delivery is at-least-once with the queue's backoff (10 attempts over about an hour). The outbox
``event_id`` is sent as the webhook's ``event_id``, so the receiver deduplicates retries.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from app.core.time import Clock
from app.modules.platform.service import EventRouter, Job, JobHandler, PermanentJobError
from app.modules.web_cache.config import WebCacheSettings
from app.modules.web_cache.domain import revalidation_for, signature_header

logger = logging.getLogger(__name__)

JOB_KIND = "web_cache.revalidate"
QUEUE = "default"
_EVENT_TYPES = (
    "destination.updated",
    "profile.updated",
    "privacy.updated",
    "user.deleted",
    "post.published",
    "post.updated",
    "post.deleted",
    "post.moderated",
)
_RETRYABLE_CLIENT_ERRORS = frozenset({408, 425, 429})


def subscribe(router: EventRouter, settings: WebCacheSettings) -> None:
    """Fan relevant outbox events out to revalidation jobs (no-op while webhooks are disabled)."""
    if not settings.enabled:
        return
    for event_type in _EVENT_TYPES:
        router.subscribe(event_type, queue=QUEUE, kind=JOB_KIND, when=_affects(event_type))


def _affects(event_type: str) -> Callable[[Mapping[str, Any]], bool]:
    def check(data: Mapping[str, Any]) -> bool:
        return revalidation_for(event_type, data) is not None

    return check


def make_handler(
    settings: WebCacheSettings, http_client: httpx.AsyncClient, clock: Clock
) -> JobHandler:
    async def revalidate(job: Job) -> None:
        payload = job.payload
        data = payload.get("data")
        decision = revalidation_for(
            str(payload.get("event_type")), data if isinstance(data, dict) else {}
        )
        if decision is None:
            return  # nothing to purge any more
        secret = settings.web_revalidate_secret
        if not settings.enabled or secret is None:
            raise PermanentJobError("web revalidation is not configured")
        body = json.dumps(
            {
                "event_id": payload["event_id"],
                "occurred_at": payload["occurred_at"],
                "reason": decision.reason,
                "tags": list(decision.tags),
            },
            separators=(",", ":"),
        ).encode()
        timestamp = int(clock.now().timestamp())
        response = await http_client.post(
            settings.web_revalidate_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "TravelBuddy-Webhooks/1",
                "X-TB-Signature": signature_header(
                    secret.get_secret_value().encode(), timestamp, body
                ),
            },
            timeout=settings.web_revalidate_timeout_seconds,
        )
        if response.is_success:
            return
        status = response.status_code
        if 400 <= status < 500 and status not in _RETRYABLE_CLIENT_ERRORS:
            # 401 = signature rejected; other 4xx will not fix themselves either.
            raise PermanentJobError(f"receiver rejected the webhook with HTTP {status}")
        raise RuntimeError(f"receiver answered HTTP {status}")

    return revalidate
