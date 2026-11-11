"""Worker process: ``python -m app.worker [--once]`` (architecture section 3, ADR-0004).

Loops over ``JobRunner.tick`` (relay the outbox, run due jobs). ``--once`` performs a single tick
and exits, for cron-style schedulers. Several workers may run at once (SKIP LOCKED claiming).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal

import httpx

from app.core.config import get_settings
from app.core.db import Database
from app.core.logging import configure_logging
from app.core.time import SystemClock
from app.main import (
    build_ai_provider,
    build_ai_service,
    build_billing_jobs,
    build_job_runner,
    build_media_storage,
    build_vapid,
)
from app.modules.identity.config import IdentitySettings
from app.modules.media.config import MediaSettings
from app.modules.notifications.webpush import build_sender as build_push_sender
from app.modules.web_cache.config import WebCacheSettings

logger = logging.getLogger("app.worker")


async def run(*, once: bool, idle_sleep_seconds: float) -> None:
    settings = get_settings()
    configure_logging(
        level=settings.log_level, json_output=settings.log_json, service_name="travelbuddy-worker"
    )
    database = Database.from_settings(
        settings, pool_size=min(settings.database_pool_size, 4), max_overflow=0
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows has no add_signal_handler; Ctrl+C raises KeyboardInterrupt there instead.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    async with httpx.AsyncClient(follow_redirects=False) as http_client:
        runner = build_job_runner(
            database=database,
            web_cache_settings=WebCacheSettings(),
            identity_settings=IdentitySettings(),
            http_client=http_client,
            clock=SystemClock(),
            # In-process storage would not be shared with the API: workers need real storage.
            media_storage=(
                build_media_storage(media, http_client, SystemClock())
                if (media := MediaSettings()).resolved_storage == "s3"
                else None
            ),
            push_sender=build_push_sender(
                settings.resolved_push_provider,
                http_client,
                expo_access_token=(
                    settings.expo_access_token.get_secret_value()
                    if settings.expo_access_token
                    else None
                ),
                vapid=build_vapid(settings),
            ),
            ai=build_ai_service(settings, database, SystemClock(), build_ai_provider(settings)),
            billing=build_billing_jobs(settings, database, SystemClock(), http_client),
        )
        try:
            while not stop.is_set():
                result = await runner.tick(budget_seconds=settings.jobs_tick_budget_seconds)
                if result.relayed or result.succeeded or result.retried or result.dead:
                    logger.info("tick", extra=result.as_dict())
                if once:
                    break
                if not (result.relayed or result.succeeded or result.retried):
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), timeout=idle_sleep_seconds)
        finally:
            await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Travel Buddy job worker")
    parser.add_argument("--once", action="store_true", help="run a single tick and exit")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="seconds to wait when idle")
    args = parser.parse_args()
    asyncio.run(run(once=args.once, idle_sleep_seconds=args.idle_sleep))


if __name__ == "__main__":
    main()
