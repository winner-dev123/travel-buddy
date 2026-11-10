"""Public interface of the identity module: IdP token exchange, sessions, account bootstrap.

Flows (architecture section 8, contract ``/v1/auth/*``):
* register: verify the IdP ID token → age gate → consent versions → create the user, IdP link,
  consents and default profile in ONE transaction → open a session.
* login: verify → map ``(iss, sub)`` to the user → open a session. Login during the deletion grace
  period cancels the deletion (AUTH-010).
* refresh: rotate per :func:`domain.decide_refresh`; reuse revokes the whole family (AUTH-007).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.ratelimit import RateLimiter
from app.core.security.access_tokens import AccessTokenService
from app.core.security.principal import ROLE_PERMISSIONS, Permission, PlatformRole, Principal
from app.core.time import Clock
from app.modules.billing import service as billing_service
from app.modules.destinations.schemas import DestinationSummary
from app.modules.identity import push_tokens
from app.modules.identity import repository as repo
from app.modules.identity.adapters.oidc import OidcVerifier, VerifiedIdentity
from app.modules.identity.adapters.supabase_admin import IdpAccountDeleter
from app.modules.identity.config import IdentitySettings
from app.modules.identity.domain import (
    RefreshMatch,
    RefreshOutcome,
    SessionTokenState,
    decide_refresh,
    derive_successor_token,
    device_name_from_user_agent,
    hash_token,
    is_age_eligible,
)
from app.modules.identity.models import (
    AuthenticationIdentity,
    ConsentRecord,
    ConsentSource,
    ConsentType,
    DataSubjectRequest,
    DataSubjectRequestKind,
    DataSubjectRequestStatus,
    RealtimeTicket,
    RetiredRefreshToken,
    RevokedReason,
    User,
    UserSession,
    UserStatus,
)
from app.modules.identity.push_tokens import PushTarget as PushTarget
from app.modules.identity.push_tokens import PushTokenCipher as PushTokenCipher
from app.modules.identity.schemas import (
    AccountDeletionRequest,
    AccountRestriction,
    AuthResult,
    ConsentList,
    ConsentRecordOut,
    ConsentRequest,
    DataSubjectRequestOut,
    DeviceInfo,
    LoginRequest,
    Me,
    MyAccount,
    NativePushRegistration,
    PushDeviceOut,
    RegisterRequest,
    SessionList,
    SessionOut,
    SessionTokens,
    WebPushRegistration,
)
from app.modules.media import service as media
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles_service
from app.modules.profiles.schemas import (
    Preferences,
    PrivacySettings,
    UpdateMyProfileRequest,
    UpdatePreferencesRequest,
    UpdatePrivacySettingsRequest,
)

logger = logging.getLogger(__name__)

DELETION_GRACE = timedelta(days=30)
DELETION_ROUTE = "POST /v1/users/me/deletion"
ACCOUNT_DELETIONS_JOB = "identity.account_deletions"
IDP_ACCOUNT_DELETION_JOB = "identity.delete_idp_account"

# Supplied by the composition root (location module, same layer): the user's browse destination.
BrowseDestinationProvider = Callable[
    [AsyncSession, uuid.UUID, Sequence[str]], Awaitable[DestinationSummary | None]
]
# Supplied by the composition root (trust_safety, same layer): active restrictions (SAFE-013).
RestrictionsProvider = Callable[
    [AsyncSession, uuid.UUID, datetime], Awaitable[list[AccountRestriction]]
]


@dataclass(frozen=True, slots=True)
class LegalRequirements:
    """What registration currently requires (served to clients via GET /v1/client-config)."""

    terms_version: str
    privacy_version: str
    minimum_age: int


class IdentityService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        verifier: OidcVerifier,
        access_tokens: AccessTokenService,
        settings: IdentitySettings,
        clock: Clock,
        browse_destination: BrowseDestinationProvider | None = None,
        limiter: RateLimiter | None = None,
        restrictions: RestrictionsProvider | None = None,
        quota_usage: billing_service.QuotaUsage | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._limiter = limiter
        self._restrictions = restrictions
        self._quota_usage = quota_usage
        self._browse_destination = browse_destination
        self._verifier = verifier
        self._access_tokens = access_tokens
        self._settings = settings
        self._clock = clock
        self._derivation_key = settings.refresh_token_derivation_key.get_secret_value().encode()
        self._push_cipher = push_cipher(settings)

    def legal_requirements(self) -> LegalRequirements:
        return LegalRequirements(
            terms_version=self._settings.terms_version,
            privacy_version=self._settings.privacy_version,
            minimum_age=self._settings.minimum_age,
        )

    async def _limit(self, bucket: str, subject: str) -> None:
        # On top of the per-IP ``auth`` limit: 20/h per IdP subject, 60/h refreshes per session.
        if self._limiter is not None:
            await self._limiter.enforce(bucket, subject)

    # ─────────────────────────────── register / login ───────────────────────────────

    async def register(self, request: RegisterRequest, *, user_agent: str | None) -> AuthResult:
        identity = await self._verifier.verify(request.id_token, expected_nonce=request.nonce)
        await self._limit("auth_subject", f"{identity.issuer}|{identity.subject}")
        now = self._clock.now()
        try:
            eligible = is_age_eligible(request.birth_date, now.date(), self._settings.minimum_age)
        except ValueError as exc:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "birth_date cannot be in the future.",
                errors=[FieldError(field="/birth_date", code="in_future", message=str(exc))],
            ) from exc
        if not eligible:
            # Nothing is stored for under-age attempts (AUTH-008).
            raise AppError(
                ErrorCode.AGE_RESTRICTED,
                f"You must be at least {self._settings.minimum_age} to use Travel Buddy.",
            )
        if (
            request.accepted_terms_version != self._settings.terms_version
            or request.accepted_privacy_version != self._settings.privacy_version
        ):
            raise AppError(
                ErrorCode.CONSENT_REQUIRED,
                "Please review and accept the current terms and privacy policy.",
                extensions={
                    "terms_version": self._settings.terms_version,
                    "privacy_version": self._settings.privacy_version,
                },
            )

        async with self._sessionmaker() as session, session.begin():
            if await repo.find_identity(session, identity.issuer, identity.subject):
                raise AppError(
                    ErrorCode.CONFLICT, "An account already exists for this sign-in. Use login."
                )
            if identity.email and await self._email_in_use(session, identity.email):
                raise AppError(
                    ErrorCode.CONFLICT,
                    "This email is already registered. Sign in with the method you used before.",
                )
            user = User(
                status=UserStatus.ACTIVE,
                email=identity.email,
                email_verified_at=now if identity.email_verified else None,
                birth_year=request.birth_date.year,  # the full date is never stored
                age_assured_at=now,
                primary_locale=request.locale,
            )
            session.add(user)
            await session.flush()
            session.add(
                AuthenticationIdentity(
                    user_id=user.id,
                    issuer=identity.issuer,
                    subject=identity.subject,
                    method=identity.method,
                    email_at_link=identity.email,
                    last_used_at=now,
                )
            )
            for consent_type, version in (
                (ConsentType.TERMS, request.accepted_terms_version),
                (ConsentType.PRIVACY_POLICY, request.accepted_privacy_version),
            ):
                session.add(
                    ConsentRecord(
                        user_id=user.id,
                        consent_type=consent_type,
                        version=version,
                        granted=True,
                        source=ConsentSource.ONBOARDING,
                        recorded_at=now,
                    )
                )
            await profiles_service.create_default_profile(
                session, user_id=user.id, idp_name=identity.name, locale=request.locale
            )
            tokens = await self._open_session(
                session, user, identity, request.client, request.device, user_agent
            )
            me = await self._compose_me(session, user)
        return AuthResult(tokens=tokens, user=me, is_new_user=True)

    async def login(self, request: LoginRequest, *, user_agent: str | None) -> AuthResult:
        identity = await self._verifier.verify(request.id_token, expected_nonce=request.nonce)
        await self._limit("auth_subject", f"{identity.issuer}|{identity.subject}")
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            link = await repo.find_identity(session, identity.issuer, identity.subject)
            user = await repo.get_user(session, link.user_id) if link else None
            if (
                link is None
                or user is None
                or user.status
                in (
                    UserStatus.DELETED,
                    UserStatus.DEACTIVATED,
                )
            ):
                raise AppError(ErrorCode.NOT_FOUND, "No account for this sign-in. Register first.")
            if (
                user.status == UserStatus.SUSPENDED
                and user.suspended_until is not None
                and user.suspended_until <= now
            ):
                user.status = UserStatus.ACTIVE  # a temporary suspension has ended
                user.suspended_until = None
            if user.status == UserStatus.SUSPENDED:
                raise AppError(ErrorCode.ACCOUNT_SUSPENDED, "This account is suspended.")
            if user.status == UserStatus.PENDING_DELETION:
                await _cancel_deletion(session, user)  # signing in cancels it (AUTH-010)
            if identity.email_verified and user.email_verified_at is None:
                user.email_verified_at = now
            link.last_used_at = now
            tokens = await self._open_session(
                session, user, identity, request.client, request.device, user_agent
            )
            me = await self._compose_me(session, user)
        return AuthResult(tokens=tokens, user=me, is_new_user=False)

    async def _email_in_use(self, session: AsyncSession, email: str) -> bool:
        found = await session.scalar(
            select(User.id).where(User.email == email, User.status != UserStatus.DELETED)
        )
        return found is not None

    async def _open_session(
        self,
        session: AsyncSession,
        user: User,
        identity: VerifiedIdentity,
        client: str,
        device: DeviceInfo | None,
        user_agent: str | None,
    ) -> SessionTokens:
        now = self._clock.now()
        raw = secrets.token_urlsafe(32)
        expires_at = now + timedelta(days=self._settings.refresh_token_ttl_days)
        device_name = (device.device_name if device else None) or device_name_from_user_agent(
            user_agent
        )
        record = UserSession(
            user_id=user.id,
            refresh_token_hash=hash_token(raw),
            platform=client,
            device_id=device.device_id if device else None,
            device_name=device_name,
            app_version=device.app_version if device else None,
            amr=sorted(identity.amr),
            auth_time=identity.auth_time,
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
        )
        session.add(record)
        await session.flush()
        return await self._tokens(session, user, record, raw)

    async def _tokens(
        self, session: AsyncSession, user: User, record: UserSession, raw_refresh: str
    ) -> SessionTokens:
        roles = await repo.active_roles(session, user.id)
        access, access_expires_at = self._access_tokens.issue(
            user_id=user.id,
            session_id=record.id,
            roles=roles,
            amr=frozenset(record.amr or []),
            auth_time=record.auth_time,
            email_verified=user.email_verified_at is not None,
            age_assured=user.age_assured_at is not None,
        )
        return SessionTokens(
            access_token=access,
            access_token_expires_at=access_expires_at,
            refresh_token=raw_refresh,
            refresh_token_expires_at=record.expires_at,
            session_id=record.id,
        )

    # ─────────────────────────────────── refresh ───────────────────────────────────

    async def refresh(self, raw: str) -> SessionTokens:
        token_hash = hash_token(raw)
        now = self._clock.now()
        leeway = timedelta(seconds=self._settings.refresh_reuse_leeway_seconds)
        reuse_detected = False
        async with self._sessionmaker() as session, session.begin():
            match, record = RefreshMatch.NONE, None
            for candidate_match, finder in (
                (RefreshMatch.CURRENT, repo.session_by_current_hash),
                (RefreshMatch.PREVIOUS, repo.session_by_previous_hash),
                (RefreshMatch.RETIRED, repo.session_by_retired_hash),
            ):
                record = await finder(session, token_hash)
                if record is not None:
                    match = candidate_match
                    break
            if record is not None:  # raising here rolls back before anything rotates
                await self._limit("auth_refresh", f"session:{record.id}")
            state = (
                SessionTokenState(
                    revoked=record.revoked_at is not None,
                    expires_at=record.expires_at,
                    rotated_at=record.rotated_at,
                )
                if record is not None
                else None
            )
            outcome = decide_refresh(match, state, now=now, leeway=leeway)
            user = await repo.get_user(session, record.user_id) if record is not None else None
            if record is not None and (user is None or user.status != UserStatus.ACTIVE):
                outcome = RefreshOutcome.REVOKED

            if outcome is RefreshOutcome.REUSE_DETECTED and record is not None:
                record.revoked_at = now
                record.revoked_reason = RevokedReason.REUSE_DETECTED
                reuse_detected = True  # committed below; raise after the transaction ends
            elif outcome is RefreshOutcome.ROTATE and record is not None and user is not None:
                successor = derive_successor_token(raw, self._derivation_key)
                session.add(
                    RetiredRefreshToken(token_hash=token_hash, session_id=record.id, retired_at=now)
                )
                record.previous_refresh_token_hash = token_hash
                record.refresh_token_hash = hash_token(successor)
                record.rotated_at = now
                record.refresh_generation += 1
                record.expires_at = now + timedelta(days=self._settings.refresh_token_ttl_days)
                record.last_used_at = now
                await session.flush()
                return await self._tokens(session, user, record, successor)
            elif outcome is RefreshOutcome.REPLAY_SUCCESSOR and record is not None and user:
                successor = derive_successor_token(raw, self._derivation_key)
                if hash_token(successor) == record.refresh_token_hash:
                    return await self._tokens(session, user, record, successor)
                # The family moved on more than one step since: treat as reuse.
                record.revoked_at = now
                record.revoked_reason = RevokedReason.REUSE_DETECTED
                reuse_detected = True

        if reuse_detected:
            raise AppError(
                ErrorCode.REFRESH_TOKEN_REUSED,
                "This sign-in was ended for your security. Please sign in again.",
            )
        if outcome is RefreshOutcome.EXPIRED:
            raise AppError(ErrorCode.TOKEN_EXPIRED, "Your session expired. Please sign in again.")
        if outcome is RefreshOutcome.REVOKED:
            raise AppError(ErrorCode.SESSION_REVOKED, "This session was signed out.")
        raise AppError(ErrorCode.TOKEN_INVALID, "The refresh token is invalid.")

    # ─────────────────────────────── sessions & me ───────────────────────────────

    # ─────────────────────────────── account deletion (AUTH-010) ───────────────────────────────

    async def request_deletion(
        self, principal: Principal, request: AccountDeletionRequest, *, idempotency_key: uuid.UUID
    ) -> tuple[DataSubjectRequestOut, bool]:
        """Schedule deletion after the grace period. Other sessions are signed out; this one stays
        so the user can still cancel. Returns ``(request, replayed)``."""
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=DELETION_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return DataSubjectRequestOut.model_validate(replay.body), True
            user = await self._active_user(session, principal)
            if user.status == UserStatus.PENDING_DELETION:
                raise AppError(ErrorCode.CONFLICT, "Account deletion is already scheduled.")
            user.status = UserStatus.PENDING_DELETION
            user.deletion_requested_at = now
            await session.execute(
                update(UserSession)
                .where(
                    UserSession.user_id == user.id,
                    UserSession.revoked_at.is_(None),
                    UserSession.id != principal.session_id,
                )
                .values(revoked_at=now, revoked_reason=RevokedReason.ACCOUNT_DELETED)
                .execution_options(synchronize_session=False)
            )
            record = DataSubjectRequest(
                user_id=user.id,
                kind=DataSubjectRequestKind.DELETION,
                status=DataSubjectRequestStatus.RECEIVED,
                reason=request.reason,
                requested_at=now,
                scheduled_for=now + DELETION_GRACE,
            )
            session.add(record)
            await session.flush()
            platform.record_event(
                session,
                aggregate_type="user",
                aggregate_id=user.id,
                event_type="user.deletion_requested",
                payload={"user_id": str(user.id)},
            )
            out = _request_out(record)
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=202,
                body=out.model_dump(mode="json"),
            )
        return out, False

    async def cancel_deletion(self, principal: Principal) -> None:
        async with self._sessionmaker() as session, session.begin():
            user = await session.get(User, principal.user_id, with_for_update=True)
            if user is None or user.status != UserStatus.PENDING_DELETION:
                raise AppError(ErrorCode.NOT_FOUND, "No account deletion is scheduled.")
            await _cancel_deletion(session, user)

    async def logout(self, principal: Principal, *, all_sessions: bool) -> None:
        async with self._sessionmaker() as session, session.begin():
            await repo.revoke_sessions(
                session,
                user_id=principal.user_id,
                reason=RevokedReason.LOGOUT,
                now=self._clock.now(),
                session_id=None if all_sessions else principal.session_id,
            )

    async def list_sessions(self, principal: Principal) -> SessionList:
        async with self._sessionmaker() as session:
            records = await repo.active_sessions(session, principal.user_id, self._clock.now())
        return SessionList(
            data=[
                SessionOut(
                    id=r.id,
                    platform="ios"
                    if r.platform == "ios"
                    else "android"
                    if r.platform == "android"
                    else "web",
                    device_name=r.device_name,
                    app_version=r.app_version,
                    created_at=r.created_at,
                    last_used_at=r.last_used_at,
                    is_current=r.id == principal.session_id,
                )
                for r in records
            ]
        )

    async def revoke_session(self, principal: Principal, session_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            revoked = await repo.revoke_sessions(
                session,
                user_id=principal.user_id,
                reason=RevokedReason.USER_REVOKED,
                now=self._clock.now(),
                session_id=session_id,
            )
        if revoked == 0:
            raise AppError(ErrorCode.NOT_FOUND, "Session not found.")

    # ─────────────────────────────── push devices (BL-3.06) ───────────────────────────────

    async def register_push_device(
        self, principal: Principal, request: NativePushRegistration | WebPushRegistration
    ) -> PushDeviceOut:
        async with self._sessionmaker() as session, session.begin():
            if isinstance(request, WebPushRegistration):
                row = await push_tokens.register(
                    session,
                    self._push_cipher,
                    user_id=principal.user_id,
                    session_id=principal.session_id,
                    provider=request.provider,
                    device_id=request.device_id,
                    token=request.subscription.endpoint,
                    p256dh=request.subscription.keys.p256dh,
                    auth=request.subscription.keys.auth,
                )
            else:
                row = await push_tokens.register(
                    session,
                    self._push_cipher,
                    user_id=principal.user_id,
                    session_id=principal.session_id,
                    provider=request.provider,
                    device_id=request.device_id,
                    token=request.token,
                )
            return PushDeviceOut.model_validate(
                {
                    "id": row.id,
                    "provider": row.provider,
                    "device_id": row.device_id,
                    "created_at": row.created_at,
                    "last_seen_at": row.last_seen_at,
                }
            )

    async def unregister_push_device(
        self, principal: Principal, device_token_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            removed = await push_tokens.unregister(
                session, user_id=principal.user_id, device_token_id=device_token_id
            )
        if not removed:
            raise AppError(ErrorCode.NOT_FOUND, "Device not found.")

    async def get_me(self, principal: Principal) -> Me:
        async with self._sessionmaker() as session:
            user = await repo.get_user(session, principal.user_id)
            if user is None or user.status not in (UserStatus.ACTIVE, UserStatus.PENDING_DELETION):
                raise AppError(ErrorCode.UNAUTHENTICATED, "Sign in to continue.")
            return await self._compose_me(session, user)

    async def _compose_me(self, session: AsyncSession, user: User) -> Me:
        now = self._clock.now()
        roles = sorted(
            PlatformRole(r)
            for r in await repo.active_roles(session, user.id)
            if r in {role.value for role in PlatformRole}
        )
        permissions: set[Permission] = set()
        for role in roles:
            permissions |= ROLE_PERMISSIONS[role]
        bundle = await profiles_service.get_profile_bundle(session, user.id)
        usage = (
            await self._quota_usage(session, user.id, now)
            if self._quota_usage is not None
            else None
        )
        entitlements = await billing_service.get_entitlements(session, user.id, at=now, usage=usage)
        browse = (
            await self._browse_destination(session, user.id, [bundle.preferences.ui_locale])
            if self._browse_destination is not None
            else None
        )
        return Me(
            account=MyAccount(
                id=user.id,
                email=user.email,
                email_verified=user.email_verified_at is not None,
                status="pending_deletion"
                if user.status == UserStatus.PENDING_DELETION
                else "active",
                primary_locale=user.primary_locale,
                age_assured=user.age_assured_at is not None,
                deletion_scheduled_for=(
                    user.deletion_requested_at + DELETION_GRACE
                    if user.deletion_requested_at
                    else None
                ),
                created_at=user.created_at,
                restrictions=(
                    await self._restrictions(session, user.id, now)
                    if self._restrictions is not None
                    else []
                ),
            ),
            profile=bundle.profile,
            preferences=bundle.preferences,
            privacy=bundle.privacy,
            roles=roles,
            permissions=sorted(permissions),
            onboarding_completed=bundle.onboarding_completed,
            browse_destination=browse,
            entitlements=entitlements,
        )

    # ─────────────────── me: profile, preferences, privacy, consents (BL-1.04) ───────────────────

    async def _active_user(self, session: AsyncSession, principal: Principal) -> User:
        user = await repo.get_user(session, principal.user_id)
        if user is None or user.status not in (UserStatus.ACTIVE, UserStatus.PENDING_DELETION):
            raise AppError(ErrorCode.UNAUTHENTICATED, "Sign in to continue.")
        return user

    async def update_me(self, principal: Principal, request: UpdateMyProfileRequest) -> Me:
        async with self._sessionmaker() as session, session.begin():
            user = await self._active_user(session, principal)
            await profiles_service.update_profile(session, user.id, request, now=self._clock.now())
            return await self._compose_me(session, user)

    async def complete_onboarding(self, principal: Principal) -> Me:
        async with self._sessionmaker() as session, session.begin():
            user = await self._active_user(session, principal)
            await profiles_service.complete_onboarding(session, user.id, now=self._clock.now())
            return await self._compose_me(session, user)

    async def get_preferences(self, principal: Principal) -> Preferences:
        async with self._sessionmaker() as session:
            user = await self._active_user(session, principal)
            return (await profiles_service.get_profile_bundle(session, user.id)).preferences

    async def update_preferences(
        self, principal: Principal, request: UpdatePreferencesRequest
    ) -> Preferences:
        async with self._sessionmaker() as session, session.begin():
            user = await self._active_user(session, principal)
            return await profiles_service.update_preferences(session, user.id, request)

    async def get_privacy(self, principal: Principal) -> PrivacySettings:
        async with self._sessionmaker() as session:
            user = await self._active_user(session, principal)
            return (await profiles_service.get_profile_bundle(session, user.id)).privacy

    async def update_privacy(
        self, principal: Principal, request: UpdatePrivacySettingsRequest
    ) -> PrivacySettings:
        """Toggling search-engine indexing is itself a consent, recorded in the ledger."""
        async with self._sessionmaker() as session, session.begin():
            user = await self._active_user(session, principal)
            result = await profiles_service.update_privacy(session, user.id, request)
            if "search_engine_indexing" in result.changed:
                session.add(
                    ConsentRecord(
                        user_id=user.id,
                        consent_type=ConsentType.SEARCH_INDEXING,
                        version=self._settings.privacy_version,
                        granted=result.settings.search_engine_indexing,
                        source=ConsentSource.SETTINGS,
                        recorded_at=self._clock.now(),
                    )
                )
            return result.settings

    async def list_consents(self, principal: Principal) -> ConsentList:
        async with self._sessionmaker() as session:
            user = await self._active_user(session, principal)
            records = await repo.latest_consents(session, user.id)
            return ConsentList(data=[_consent_out(r) for r in records])

    async def record_consent(
        self, principal: Principal, request: ConsentRequest
    ) -> ConsentRecordOut:
        """Append to the consent ledger and mirror into privacy settings (AUTH-009, DISC-001).

        Terms and privacy policy cannot be withdrawn here (that is account deletion) and can only
        be accepted in their current version.
        """
        legal = {
            ConsentType.TERMS: self._settings.terms_version,
            ConsentType.PRIVACY_POLICY: self._settings.privacy_version,
        }
        if request.consent_type in legal:
            if not request.granted:
                raise _field_error(
                    "/granted",
                    "cannot_withdraw",
                    "To stop accepting the terms or privacy policy, delete your account.",
                )
            if request.version != legal[ConsentType(request.consent_type)]:
                raise _field_error(
                    "/version", "outdated_version", "Accept the current version of this document."
                )
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            user = await self._active_user(session, principal)
            record = ConsentRecord(
                user_id=user.id,
                consent_type=request.consent_type,
                version=request.version,
                granted=request.granted,
                source=request.source,
                recorded_at=now,
            )
            session.add(record)
            await profiles_service.apply_consent(
                session,
                user.id,
                consent_type=request.consent_type,
                granted=request.granted,
                version=request.version,
                at=now,
            )
            return _consent_out(record)


def _consent_out(record: ConsentRecord) -> ConsentRecordOut:
    return ConsentRecordOut.model_validate(
        {
            "consent_type": record.consent_type,
            "version": record.version,
            "granted": record.granted,
            "source": record.source,
            "recorded_at": record.recorded_at,
        }
    )


def _field_error(field: str, code: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code=code, message=message)],
    )


# ─────────────────────────────── staff & account administration ───────────────────────────────

ADMIN_IDLE_LIMIT = timedelta(minutes=30)  # ADM-008
ADMIN_ABSOLUTE_LIMIT = timedelta(hours=12)


@dataclass(frozen=True, slots=True)
class AccountAdminView:
    user_id: uuid.UUID
    status: str
    email: str | None
    roles: list[str]
    created_at: datetime
    last_active_on: date | None
    suspended_until: datetime | None


async def check_admin_session(
    session: AsyncSession, principal: Principal, *, now: datetime
) -> None:
    """Staff session limits on admin routes (ADM-008): 30 min idle, 12 h since authentication.
    Records the activity so the idle clock restarts."""
    record = await session.get(UserSession, principal.session_id, with_for_update=True)
    if record is None or record.revoked_at is not None or record.user_id != principal.user_id:
        raise AppError(ErrorCode.UNAUTHENTICATED, "Sign in to continue.")
    expired = now - record.auth_time > ADMIN_ABSOLUTE_LIMIT or (
        record.last_admin_activity_at is not None
        and now - record.last_admin_activity_at > ADMIN_IDLE_LIMIT
    )
    if expired:
        raise AppError(
            ErrorCode.REAUTHENTICATION_REQUIRED,
            "Your staff session timed out. Sign in again with your second factor.",
        )
    record.last_admin_activity_at = now


async def account_admin_view(session: AsyncSession, user_id: uuid.UUID) -> AccountAdminView | None:
    user = await repo.get_user(session, user_id)
    if user is None:
        return None
    return AccountAdminView(
        user_id=user.id,
        status=user.status,
        email=user.email,
        roles=sorted(await repo.active_roles(session, user.id)),
        created_at=user.created_at,
        last_active_on=user.last_active_on,
        suspended_until=user.suspended_until,
    )


async def set_account_status(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str,
    now: datetime,
    until: datetime | None = None,
) -> None:
    """Suspend, ban (deactivate) or reinstate. Leaving ``active`` revokes every session at once."""
    user = await repo.get_user(session, user_id)
    if user is None:
        raise AppError(ErrorCode.NOT_FOUND, "User not found.")
    user.status = status
    user.suspended_until = until if status == UserStatus.SUSPENDED else None
    if status != UserStatus.ACTIVE:
        await repo.revoke_sessions(session, user_id=user_id, reason=RevokedReason.ADMIN, now=now)


async def purge_expired(session: AsyncSession) -> int:
    """Sessions 90 days after revocation or expiry (retired refresh tokens cascade); ``last_ip``
    nulled after 30 days of inactivity (docs/04 §14)."""
    await session.execute(
        update(UserSession)
        .where(UserSession.last_ip.is_not(None), UserSession.last_used_at < platform.ago(days=30))
        .values(last_ip=None)
    )
    return (
        await push_tokens.purge(session)
        + await purge_realtime_tickets(session)
        + await platform.delete_batch(
            session,
            UserSession,
            or_(
                UserSession.revoked_at < platform.ago(days=90),
                UserSession.expires_at < platform.ago(days=90),
            ),
        )
    )


def push_cipher(settings: IdentitySettings) -> PushTokenCipher:
    """Encrypts push tokens with a key derived from the refresh-token secret (HKDF, own label)."""
    return PushTokenCipher(settings.refresh_token_derivation_key.get_secret_value())


async def push_targets(
    session: AsyncSession, cipher: PushTokenCipher, user_id: uuid.UUID
) -> list[PushTarget]:
    """Where to push for ``user_id`` (live sessions only), for the notifications module."""
    return await push_tokens.targets(session, cipher, user_id)


async def disable_push_targets(session: AsyncSession, ids: Sequence[uuid.UUID]) -> None:
    await push_tokens.disable(session, ids)


def _request_out(record: DataSubjectRequest) -> DataSubjectRequestOut:
    return DataSubjectRequestOut.model_validate(
        {
            "id": record.id,
            "kind": record.kind,
            "status": record.status,
            "requested_at": record.requested_at,
            "completed_at": record.completed_at,
            "scheduled_for": record.scheduled_for,
        }
    )


async def _cancel_deletion(session: AsyncSession, user: User) -> None:
    user.status = UserStatus.ACTIVE
    user.deletion_requested_at = None
    await session.execute(
        update(DataSubjectRequest)
        .where(
            DataSubjectRequest.user_id == user.id,
            DataSubjectRequest.kind == DataSubjectRequestKind.DELETION,
            DataSubjectRequest.status == DataSubjectRequestStatus.RECEIVED,
        )
        .values(status=DataSubjectRequestStatus.CANCELLED)
    )


# Runs in the deletion transaction before the ``users`` row goes (e.g. group handover).
BeforeDelete = Callable[[AsyncSession, uuid.UUID], Awaitable[None]]


async def delete_due_accounts(
    session: AsyncSession, *, limit: int = 25, before_delete: Sequence[BeforeDelete] = ()
) -> int:
    """Erase accounts whose grace period ended (the deletion saga, docs/04 §14).

    Deleting the ``users`` row cascades through every module's data (posts, comments, reactions,
    follows, blocks, notifications, sessions, consents, preferences); references kept for
    accountability become NULL or stay as bare IDs (reports, moderation history, audit log).
    The IdP account is deleted by a retryable job, and ``user.deleted`` purges cached pages.
    """
    due = (
        await session.scalars(
            select(User)
            .where(
                User.status == UserStatus.PENDING_DELETION,
                User.deletion_requested_at <= func.now() - DELETION_GRACE,
            )
            .order_by(User.deletion_requested_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for user in due:
        identities = (
            await session.scalars(
                select(AuthenticationIdentity).where(AuthenticationIdentity.user_id == user.id)
            )
        ).all()
        for link in identities:
            await platform.enqueue(
                session,
                queue="default",
                kind=IDP_ACCOUNT_DELETION_JOB,
                payload={"issuer": link.issuer, "subject": link.subject},
                dedupe_key=f"idp-delete:{link.issuer}:{link.subject}",
            )
        await media.schedule_owner_erasure(session, user.id)
        author = (await profiles_service.authors(session, [user.id])).get(user.id)
        platform.record_event(
            session,
            aggregate_type="user",
            aggregate_id=user.id,
            event_type="user.deleted",
            payload={"user_id": str(user.id), "handle": author.handle if author else None},
        )
        await session.execute(
            update(DataSubjectRequest)
            .where(
                DataSubjectRequest.user_id == user.id,
                DataSubjectRequest.kind == DataSubjectRequestKind.DELETION,
                DataSubjectRequest.status.in_(
                    [DataSubjectRequestStatus.RECEIVED, DataSubjectRequestStatus.PROCESSING]
                ),
            )
            .values(status=DataSubjectRequestStatus.COMPLETED, completed_at=func.now())
        )
        for hook in before_delete:
            await hook(session, user.id)
        await session.execute(delete(User).where(User.id == user.id))
    return len(due)


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession],
    deleter: IdpAccountDeleter | None,
    *,
    before_delete: Sequence[BeforeDelete] = (),
) -> dict[str, platform.JobHandler]:
    async def account_deletions(job: platform.Job) -> None:
        while True:
            async with sessionmaker() as session, session.begin():
                deleted = await delete_due_accounts(session, before_delete=before_delete)
            if deleted:
                logger.info("accounts deleted", extra={"count": deleted})
            if deleted < 25:
                return

    async def idp_account(job: platform.Job) -> None:
        issuer, subject = str(job.payload["issuer"]), str(job.payload["subject"])
        if deleter is None or not deleter.handles(issuer):
            logger.warning("idp_account_not_deleted", extra={"issuer": issuer})
            return
        await deleter.delete(issuer, subject)  # raising retries with backoff

    return {ACCOUNT_DELETIONS_JOB: account_deletions, IDP_ACCOUNT_DELETION_JOB: idp_account}


async def is_active(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether others may see this account (suspended, pending-deletion or deactivated: no)."""
    status = await session.scalar(select(User.status).where(User.id == user_id))
    return status == UserStatus.ACTIVE


async def active_ids(session: AsyncSession, user_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    """The given accounts that are active (visible to others)."""
    if not user_ids:
        return set()
    rows = await session.scalars(
        select(User.id).where(User.id.in_(set(user_ids)), User.status == UserStatus.ACTIVE)
    )
    return set(rows)


async def ensure_system_account(
    session: AsyncSession, *, account_id: uuid.UUID, handle: str, display_name: str, bio: str
) -> bool:
    """Create a platform-operated account (editorial content) if missing; True when created.

    It has no sign-in identity, so nobody can authenticate as it.
    """
    if await session.get(User, account_id) is not None:
        return False
    session.add(User(id=account_id, status=UserStatus.ACTIVE, primary_locale="en"))
    await session.flush()
    await profiles_service.create_system_profile(
        session, user_id=account_id, handle=handle, display_name=display_name, bio=bio
    )
    return True


async def account_created_at(session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    """When the account was created (new-account limits, CONN-005)."""
    created: datetime | None = await session.scalar(
        select(User.created_at).where(User.id == user_id)
    )
    return created


# ───────────────────────── realtime tickets (ADR-0013, BL-3.15) ─────────────────────────

REALTIME_TICKET_TTL = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class TicketGrant:
    """What a consumed ticket proves: the user, the session and the claims at minting time."""

    user_id: uuid.UUID
    session_id: uuid.UUID
    claims: dict[str, Any]
    issued_at: datetime


async def mint_realtime_ticket(
    session: AsyncSession, principal: Principal, *, now: datetime
) -> tuple[str, datetime]:
    """A 256-bit single-use ticket; only its SHA-256 is stored. Returned once."""
    ticket = secrets.token_urlsafe(32)  # 43 base64url characters
    expires_at = now + REALTIME_TICKET_TTL
    session.add(
        RealtimeTicket(
            token_hash=hashlib.sha256(ticket.encode()).digest(),
            user_id=principal.user_id,
            session_id=principal.session_id,
            claims={
                "roles": sorted(r.value for r in principal.roles),
                "email_verified": principal.email_verified,
                "age_assured": principal.age_assured,
                "amr": sorted(principal.amr),
                "auth_time": principal.auth_time.isoformat() if principal.auth_time else None,
            },
            issued_at=now,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return ticket, expires_at


async def consume_realtime_ticket(
    session: AsyncSession, ticket: str, *, now: datetime
) -> TicketGrant | None:
    """Atomically take a ticket (delete-returning, so it works once) if it is unexpired and its
    session is still live."""
    row = (
        await session.execute(
            delete(RealtimeTicket)
            .where(
                RealtimeTicket.token_hash == hashlib.sha256(ticket.encode()).digest(),
                RealtimeTicket.expires_at > now,
            )
            .returning(
                RealtimeTicket.user_id,
                RealtimeTicket.session_id,
                RealtimeTicket.claims,
                RealtimeTicket.issued_at,
            )
        )
    ).first()
    if row is None:
        return None
    live = await session.scalar(
        select(UserSession.id).where(
            UserSession.id == row[1], UserSession.revoked_at.is_(None), UserSession.expires_at > now
        )
    )
    if live is None:
        return None
    return TicketGrant(user_id=row[0], session_id=row[1], claims=dict(row[2]), issued_at=row[3])


async def purge_realtime_tickets(session: AsyncSession) -> int:
    result = await session.execute(
        delete(RealtimeTicket).where(RealtimeTicket.expires_at < func.now())
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def consent_granted(session: AsyncSession, user_id: uuid.UUID, consent_type: str) -> bool:
    """Whether the user's latest ledger record for ``consent_type`` grants it (opt-in features)."""
    return any(
        record.consent_type == consent_type and record.granted
        for record in await repo.latest_consents(session, user_id)
    )
