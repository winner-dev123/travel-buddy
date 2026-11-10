"""Push delivery (BL-3.06; NOTIF-002..004, DM-009).

Every new notification queues one ``notifications.push`` job. The job pushes to the recipient's
live devices unless the notification was already read, push is off for its type, or the
recipient's quiet hours are on (the in-app notification stays either way). Title and body are
rendered in the recipient's language with the same templates as the notification center, so a
push never carries a message body or a location (NOTIF-004). Providers that report a device as
gone get it disabled.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity import service as identity
from app.modules.notifications.domain import in_quiet_hours, render
from app.modules.notifications.models import Notification
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles

logger = logging.getLogger(__name__)

JOB_KIND = "notifications.push"
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_BATCH = 100


@dataclass(frozen=True, slots=True)
class PushMessage:
    title: str
    body: str
    data: dict[str, Any]
    collapse_key: str | None = None


class PushSender(Protocol):
    async def send(
        self, targets: Sequence[identity.PushTarget], message: PushMessage
    ) -> set[uuid.UUID]:
        """Deliver; returns the targets the provider reported as gone."""
        ...


@dataclass
class RecordingPushSender:
    """Development and tests: keeps pushes in memory, nothing leaves the process."""

    sent: list[tuple[identity.PushTarget, PushMessage]] = field(default_factory=list)
    gone: set[str] = field(default_factory=set)  # tokens to report as unregistered

    async def send(
        self, targets: Sequence[identity.PushTarget], message: PushMessage
    ) -> set[uuid.UUID]:
        self.sent.extend((target, message) for target in targets)
        return {t.id for t in targets if t.token in self.gone}


class ExpoPushSender:
    """The Expo push service (works with Expo push tokens on iOS and Android). FCM, APNs and Web
    Push targets are skipped until their adapters land (Web Push: BL-3.16)."""

    def __init__(self, http: httpx.AsyncClient, access_token: str | None = None) -> None:
        self._http = http
        self._access_token = access_token

    async def send(
        self, targets: Sequence[identity.PushTarget], message: PushMessage
    ) -> set[uuid.UUID]:
        expo = [t for t in targets if t.provider == "expo"]
        gone: set[uuid.UUID] = set()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        for start in range(0, len(expo), EXPO_BATCH):
            batch = expo[start : start + EXPO_BATCH]
            payload = [
                {
                    "to": target.token,
                    "title": message.title,
                    "body": message.body,
                    "data": message.data,
                    "sound": "default",
                    **({"collapseId": message.collapse_key} if message.collapse_key else {}),
                }
                for target in batch
            ]
            response = await self._http.post(
                EXPO_PUSH_URL, json=payload, headers=headers, timeout=10.0
            )
            if response.status_code >= 500:
                raise RuntimeError(f"Expo push answered {response.status_code}")  # retried
            if response.status_code != 200:
                logger.warning("expo_push_rejected", extra={"status": response.status_code})
                continue
            tickets = response.json().get("data") or []
            for target, ticket in zip(batch, tickets, strict=False):
                details = ticket.get("details") or {}
                if (
                    ticket.get("status") == "error"
                    and details.get("error") == "DeviceNotRegistered"
                ):
                    gone.add(target.id)
        return gone


def _quiet(context: profiles.PushContext, now: datetime) -> bool:
    if context.quiet_hours is None:
        return False
    try:
        local = now.astimezone(ZoneInfo(context.time_zone))
    except ZoneInfoNotFoundError:
        local = now
    return in_quiet_hours(local.hour * 60 + local.minute, *context.quiet_hours)


def _data(notification: Notification) -> dict[str, Any]:
    """Routing data for the app: IDs only (NOTIF-004)."""
    data: dict[str, Any] = {
        "notification_id": str(notification.id),
        "type": notification.type,
    }
    if notification.entity_type and notification.entity_id:
        data["entity_type"] = notification.entity_type
        data["entity_id"] = str(notification.entity_id)
    return data


async def deliver(
    session: AsyncSession,
    sender: PushSender,
    cipher: identity.PushTokenCipher,
    notification_id: uuid.UUID,
    *,
    now: datetime,
) -> int:
    """Push one notification; returns how many devices it was sent to."""
    notification = await session.get(Notification, notification_id)
    if notification is None or notification.read_at is not None or notification.pushed_at:
        return 0
    user = notification.user_id
    if not await profiles.wants_notification(session, user, notification.type, "push"):
        return 0
    context = await profiles.push_context(session, user)
    if context is None or _quiet(context, now):
        return 0
    targets = await identity.push_targets(session, cipher, user)
    if not targets:
        return 0
    actor = None
    if notification.actor_id is not None:
        found = (await profiles.authors(session, [notification.actor_id])).get(
            notification.actor_id
        )
        actor = found.display_name if found else None
    title, body = render(
        notification.type, notification.payload, actor=actor, locale=context.ui_locale
    )
    collapse = f"{notification.type}:{notification.entity_id}" if notification.entity_id else None
    gone = await sender.send(
        targets,
        PushMessage(title=title, body=body, data=_data(notification), collapse_key=collapse),
    )
    await identity.disable_push_targets(session, list(gone))
    await session.execute(
        update(Notification).where(Notification.id == notification.id).values(pushed_at=now)
    )
    return len(targets) - len(gone)


def make_handler(
    sessionmaker: async_sessionmaker[AsyncSession],
    sender: PushSender | None,
    cipher: identity.PushTokenCipher,
) -> platform.JobHandler:
    async def handle(job: platform.Job) -> None:
        if sender is None:
            return
        async with sessionmaker() as session, session.begin():
            await deliver(
                session,
                sender,
                cipher,
                uuid.UUID(str(job.payload["notification_id"])),
                now=datetime.now(tz=UTC),
            )

    return handle
