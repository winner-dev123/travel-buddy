"""Persistence for identity (private to the module)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import (
    AdminRoleAssignment,
    AuthenticationIdentity,
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
        stmt.values(revoked_at=now, revoked_reason=reason).execution_options(
            synchronize_session=False
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
