"""Abuse signals (SAFE-011, BL-2.07): an hourly job files automated reports for staff review.

Signals (each filed once while its report is open; thresholds sit above normal use):
- ``mass_connection_requests``: 15+ requests in 24 h with at least half declined (spam);
- ``mass_reports``: 10+ reports filed in 24 h (weaponised reporting);
- ``destination_hopping``: discovery started in 4+ different cities in 24 h (T-LOC-03).
Reports go to the moderation queue with the counts as evidence; nothing is enforced
automatically.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.connections import service as connections
from app.modules.location import service as location
from app.modules.platform import service as platform
from app.modules.trust_safety import service as trust_safety

logger = logging.getLogger(__name__)

JOB_KIND = "safety.abuse_signals"
WINDOW_HOURS = 24
MASS_REQUESTS = 15
MASS_REPORTS = 10
HOPPING_CITIES = 4


async def detect(session: AsyncSession) -> int:
    """File reports for new signals; returns how many were filed."""
    filed = 0
    for user, (sent, declined) in (
        await connections.request_stats_since(session, hours=WINDOW_HOURS, at_least=MASS_REQUESTS)
    ).items():
        if declined * 2 >= sent:
            filed += await trust_safety.file_system_report(
                session,
                user_id=user,
                reason="spam",
                signal="mass_connection_requests",
                evidence={"window_hours": WINDOW_HOURS, "sent": sent, "declined": declined},
            )
    for user, count in (
        await trust_safety.reports_filed_since(session, hours=WINDOW_HOURS, at_least=MASS_REPORTS)
    ).items():
        filed += await trust_safety.file_system_report(
            session,
            user_id=user,
            reason="other",
            signal="mass_reports",
            evidence={"window_hours": WINDOW_HOURS, "reports": count},
        )
    for user, (starts, cities) in (
        await location.session_hops_since(
            session, hours=WINDOW_HOURS, at_least_cities=HOPPING_CITIES
        )
    ).items():
        filed += await trust_safety.file_system_report(
            session,
            user_id=user,
            reason="other",
            signal="destination_hopping",
            evidence={"window_hours": WINDOW_HOURS, "starts": starts, "cities": cities},
        )
    return filed


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> dict[str, platform.JobHandler]:
    async def handle(job: platform.Job) -> None:
        async with sessionmaker() as session, session.begin():
            filed = await detect(session)
        if filed:
            logger.warning("abuse signals filed", extra={"count": filed})

    return {JOB_KIND: handle}
