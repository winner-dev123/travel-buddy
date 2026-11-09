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
from app.main import build_job_runner
from app.modules.identity.config import IdentitySettings
from app.modules.web_cache.config import WebCacheSettings

logger = logging.getLogger("app.worker")


async def run(*, once: bool, idle_sleep_seconds: float) -> None:
    settings = get_settings()
    configure_logging(
        level=settings.log_level, json_output=settings.log_json, service_name="travelbuddy-worker"
    )
    database = Database(
        settings.database_url,
        pool_size=min(settings.database_pool_size, 4),
        max_overflow=0,
        pool_recycle_seconds=settings.database_pool_recycle_seconds,
        transaction_pooler=settings.database_transaction_pooler,
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
