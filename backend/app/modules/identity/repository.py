"""Persistence for identity (private to the module)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import (
    AdminRoleAssignment,
    AuthenticationIdentity,
    ConsentRecord,
    DevicePushToken,
    RetiredRefreshToken,
    User,
    UserSession,
)


async def find_identity(
    session: AsyncSession, issuer: str, subject: str
) -> AuthenticationIdentity | None:
    found: AuthenticationIdentity | None = await session.scalar(
        select(AuthenticationIdentity).where(
            AuthenticationIdentity.issuer == issuer, AuthenticationIdentity.subject == subject
        )
    )
    return found


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def active_roles(session: AsyncSession, user_id: uuid.UUID) -> frozenset[str]:
    rows = await session.scalars(
        select(AdminRoleAssignment.role).where(
            AdminRoleAssignment.user_id == user_id, AdminRoleAssignment.revoked_at.is_(None)
        )
    )
    return frozenset(rows)


async def session_by_current_hash(session: AsyncSession, token_hash: bytes) -> UserSession | None:
    found: UserSession | None = await session.scalar(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash).with_for_update()
    )
    return found


async def session_by_previous_hash(session: AsyncSession, token_hash: bytes) -> UserSession | None:
    found: UserSession | None = await session.scalar(
        select(UserSession)
        .where(UserSession.previous_refresh_token_hash == token_hash)
        .with_for_update()
    )
    return found


async def session_by_retired_hash(session: AsyncSession, token_hash: bytes) -> UserSession | None:
    found: UserSession | None = await session.scalar(
        select(UserSession)
        .join(RetiredRefreshToken, RetiredRefreshToken.session_id == UserSession.id)
        .where(RetiredRefreshToken.token_hash == token_hash)
        .with_for_update(of=UserSession)
    )
    return found


async def active_sessions(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> list[UserSession]:
    rows = await session.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .order_by(UserSession.last_used_at.desc())
    )
    return list(rows)


async def revoke_sessions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    reason: str,
    now: datetime,
    session_id: uuid.UUID | None = None,
) -> int:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if session_id is not None:
        stmt = stmt.where(UserSession.id == session_id)
    result = await session.execute(
        stmt.values(revoked_at=now, revoked_reason=reason)
        .returning(UserSession.id)
        .execution_options(synchronize_session=False)
    )
    revoked = list(result.scalars())
    if revoked:  # a revoked session receives no more pushes (docs/04 §3)
        await session.execute(
            delete(DevicePushToken).where(DevicePushToken.session_id.in_(revoked))
        )
    return len(revoked)


async def latest_consents(session: AsyncSession, user_id: uuid.UUID) -> list[ConsentRecord]:
    """The most recent record per consent type (the ledger itself is append-only)."""
    rows = await session.scalars(
        select(ConsentRecord)
        .where(ConsentRecord.user_id == user_id)
        .order_by(
            ConsentRecord.consent_type,
            ConsentRecord.recorded_at.desc(),
            ConsentRecord.id.desc(),
        )
        .distinct(ConsentRecord.consent_type)
    )
    return list(rows)
