"""Public interface of the identity module: IdP token exchange, sessions, account bootstrap.

Flows (architecture section 8, contract ``/v1/auth/*``):
* register: verify the IdP ID token → age gate → consent versions → create the user, IdP link,
  consents and default profile in ONE transaction → open a session.
* login: verify → map ``(iss, sub)`` to the user → open a session. Login during the deletion grace
  period cancels the deletion (AUTH-010).
* refresh: rotate per :func:`domain.decide_refresh`; reuse revokes the whole family (AUTH-007).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.ratelimit import RateLimiter
from app.core.security.access_tokens import AccessTokenService
from app.core.security.principal import ROLE_PERMISSIONS, Permission, PlatformRole, Principal
from app.core.time import Clock
from app.modules.billing import service as billing_service
from app.modules.destinations.schemas import DestinationSummary
from app.modules.identity import repository as repo
from app.modules.identity.adapters.oidc import OidcVerifier, VerifiedIdentity
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
    RetiredRefreshToken,
    RevokedReason,
    User,
    UserSession,
    UserStatus,
)
from app.modules.identity.schemas import (
    AuthResult,
    ConsentList,
    ConsentRecordOut,
    ConsentRequest,
    DeviceInfo,
    LoginRequest,
    Me,
    MyAccount,
    RegisterRequest,
    SessionList,
    SessionOut,
    SessionTokens,
)
from app.modules.profiles import service as profiles_service
from app.modules.profiles.schemas import (
    Preferences,
    PrivacySettings,
    UpdateMyProfileRequest,
    UpdatePreferencesRequest,
    UpdatePrivacySettingsRequest,
)

DELETION_GRACE = timedelta(days=30)

# Supplied by the composition root (location module, same layer): the user's browse destination.
BrowseDestinationProvider = Callable[
    [AsyncSession, uuid.UUID, Sequence[str]], Awaitable[DestinationSummary | None]
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
    ) -> None:
        self._sessionmaker = sessionmaker
        self._limiter = limiter
        self._browse_destination = browse_destination
        self._verifier = verifier
        self._access_tokens = access_tokens
        self._settings = settings
        self._clock = clock
        self._derivation_key = settings.refresh_token_derivation_key.get_secret_value().encode()

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
                user.status = UserStatus.ACTIVE  # signing in cancels the deletion (AUTH-010)
                user.deletion_requested_at = None
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
        entitlements = await billing_service.get_entitlements(session, user.id, at=now)
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
