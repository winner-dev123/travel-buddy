"""API process entry point (``uvicorn app.main:create_app --factory``)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import install_error_handlers
from app.core.feature_flags import FeatureFlags
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.pagination import CursorCodec
from app.core.ratelimit import (
    MemoryRateLimitStore,
    RateLimiter,
    RateLimitHeadersMiddleware,
    RateLimitStore,
    RatePolicy,
    RedisRateLimitStore,
    enforce_rate_limit,
)
from app.core.redis import create_redis
from app.core.security.access_tokens import (
    AccessTokenService,
    development_signing_key,
    load_ed25519_private_key,
)
from app.core.time import Clock, SystemClock
from app.modules.admin.api import router as admin_router
from app.modules.admin.service import AdminService
from app.modules.ai_assistant import service as ai_service
from app.modules.ai_assistant.api import posts_router as translation_router
from app.modules.ai_assistant.api import router as ai_router
from app.modules.ai_assistant.provider import (
    AIProvider,
    AITask,
    AnthropicProvider,
    FakeAIProvider,
    TaskConfig,
)
from app.modules.billing import service as billing_service
from app.modules.billing.api import dev_router as dev_billing_router
from app.modules.billing.api import router as billing_router
from app.modules.billing.apple import AppleJWSVerifier, AppleStoreProvider
from app.modules.billing.google import (
    GoogleCerts,
    GooglePlayApi,
    GooglePlayProvider,
    PushVerifier,
    ServiceAccount,
)
from app.modules.billing.providers import BillingProvider, DevBillingProvider, UnconfiguredStore
from app.modules.billing.stripe import StripeClient
from app.modules.challenges import service as challenges_service
from app.modules.challenges.api import router as challenges_router
from app.modules.client_config.api import router as client_config_router
from app.modules.connections import service as connections_service
from app.modules.connections.api import router as connections_router
from app.modules.destinations.api import places_router
from app.modules.destinations.api import router as destinations_router
from app.modules.destinations.service import DestinationService, PlaceService
from app.modules.discovery import signals as abuse_signals
from app.modules.discovery.api import router as discovery_router
from app.modules.discovery.service import DiscoveryService
from app.modules.feed import service as feed_service
from app.modules.feed.api import router as feed_router
from app.modules.feed.service import FeedService
from app.modules.groups import service as groups_service
from app.modules.groups.api import invitations_router as group_invitations_router
from app.modules.groups.api import router as groups_router
from app.modules.guides import packages as offline_packages
from app.modules.guides import service as guides_service
from app.modules.guides.api import router as guides_router
from app.modules.guides.offline import DownloadTokens, ManifestSigner, development_manifest_key
from app.modules.guides.packages import OfflinePackageService
from app.modules.guides.service import GuideService
from app.modules.health.api import ReadinessCheck
from app.modules.health.api import router as health_router
from app.modules.identity import exports as data_exports
from app.modules.identity import service as identity_module
from app.modules.identity.adapters.dev_idp import DevIdentityProvider
from app.modules.identity.adapters.firebase import FirebaseAccountCheck, firebase_project
from app.modules.identity.adapters.idp_deletion import build_idp_deleter
from app.modules.identity.adapters.oidc import HttpJwksKeyProvider, IssuerConfig, OidcVerifier
from app.modules.identity.api import auth_router, dev_idp_router, exports_router, me_router
from app.modules.identity.config import IdentitySettings
from app.modules.identity.schemas import AccountRestriction
from app.modules.identity.service import IdentityService
from app.modules.location import service as location_service
from app.modules.location.api import router as location_router
from app.modules.media import service as media_service
from app.modules.media.api import router as media_router
from app.modules.media.config import MediaSettings
from app.modules.media.storage import LocalStorage, ObjectStorage, S3Storage
from app.modules.messaging import service as messaging_service
from app.modules.messaging.api import router as messaging_router
from app.modules.notifications import service as notifications_service
from app.modules.notifications.api import router as notifications_router
from app.modules.notifications.push import PushSender
from app.modules.notifications.webpush import Vapid
from app.modules.notifications.webpush import build_sender as build_push_sender
from app.modules.platform.api import AfterResponseTickMiddleware, internal_router
from app.modules.platform.service import (
    DAILY,
    EventRouter,
    JobHandler,
    JobRunner,
    Periodic,
    PostgresRateLimitStore,
    purge_platform,
    retention_handler,
)
from app.modules.profiles import service as profiles_service
from app.modules.social import service as social_service
from app.modules.social.api import router as social_router
from app.modules.social.follows import FollowService
from app.modules.social.interactions import InteractionService
from app.modules.social.profile_view import PublicProfileService
from app.modules.social.public import PublicPostService
from app.modules.trips import service as trips_service
from app.modules.trips.api import router as trips_router
from app.modules.trips.api import saved_places_router
from app.modules.trips.saved_places import SavedPlaceService
from app.modules.trust_safety import service as trust_safety_service
from app.modules.trust_safety.api import router as trust_safety_router
from app.modules.trust_safety.service import BlockService, ReportService
from app.modules.web_cache import service as web_cache_service
from app.modules.web_cache.config import WebCacheSettings
from app.realtime.bus import MemoryBus, RealtimeBus, RedisBus
from app.realtime.gateway import router as realtime_router
from app.realtime.tickets import router as realtime_tickets_router

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    identity_settings: IdentitySettings | None = None,
    web_cache_settings: WebCacheSettings | None = None,
    media_settings: MediaSettings | None = None,
    readiness_checks: Mapping[str, ReadinessCheck] | None = None,
    clock: Clock | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
    rate_limit_store: RateLimitStore | None = None,
) -> FastAPI:
    """Build the API application (composition root).

    ``readiness_checks``, ``clock``, ``http_transport`` and ``rate_limit_store`` may be injected
    (tests); by default the database and Redis are checked, the system clock is used, HTTP goes to
    the network and the rate-limit store follows ``RATE_LIMIT_STORE``.
    """
    settings = settings or get_settings()
    identity_settings = identity_settings or IdentitySettings()
    web_cache_settings = web_cache_settings or WebCacheSettings()
    media_settings = media_settings or MediaSettings()
    clock = clock or SystemClock()
    configure_logging(
        level=settings.log_level, json_output=settings.log_json, service_name=settings.service_name
    )

    database = Database.from_settings(settings)
    redis = create_redis(settings.redis_url) if settings.redis_url else None
    http_client = httpx.AsyncClient(follow_redirects=False, transport=http_transport)

    async def _ping_redis() -> object:
        assert redis is not None
        return await redis.ping()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await http_client.aclose()
            if redis is not None:
                await redis.aclose()
            await database.dispose()

    if settings.platform_jwt_private_key is not None:
        signing_key = load_ed25519_private_key(settings.platform_jwt_private_key.get_secret_value())
    else:  # only reachable in development/test (settings guard)
        logger.warning("using the development-only platform JWT signing key")
        signing_key = development_signing_key()
    access_tokens = AccessTokenService(
        signing_key,
        key_id=settings.platform_jwt_key_id,
        ttl=timedelta(seconds=settings.access_token_ttl_seconds),
        clock=clock,
    )
    firebase_check = (
        FirebaseAccountCheck(identity_settings.firebase_web_api_key, http_client)
        if identity_settings.firebase_web_api_key
        else None
    )
    issuers = [
        IssuerConfig(
            issuer=trusted.issuer,
            audiences=trusted.audiences,
            algorithms=trusted.algorithms,
            keys=HttpJwksKeyProvider(str(trusted.jwks_uri), http_client),
            method=trusted.method,
            account_check=firebase_check if firebase_project(trusted.issuer) else None,
        )
        for trusted in identity_settings.trusted_issuers
    ]
    rate_limiter = build_rate_limiter(
        settings, database=database, redis=redis, clock=clock, store=rate_limit_store
    )
    dev_idp = DevIdentityProvider(clock) if settings.dev_idp_enabled else None
    if dev_idp is not None:
        issuers.append(dev_idp.issuer_config())
    identity_service = IdentityService(
        sessionmaker=database.sessionmaker,
        verifier=OidcVerifier(issuers, now=lambda: clock.now().timestamp()),
        access_tokens=access_tokens,
        settings=identity_settings,
        clock=clock,
        browse_destination=location_service.browse_destination_summary,
        limiter=rate_limiter,
        restrictions=account_restrictions,
        quota_usage=quota_usage,
    )

    media_storage = build_media_storage(media_settings, http_client, clock)
    web_push_vapid = build_vapid(settings)
    push_sender = build_push_sender(
        settings.resolved_push_provider,
        http_client,
        expo_access_token=(
            settings.expo_access_token.get_secret_value() if settings.expo_access_token else None
        ),
        vapid=web_push_vapid,
    )
    ai_provider = build_ai_provider(settings)
    ai = build_ai_service(settings, database, clock, ai_provider)
    job_runner = build_job_runner(
        database=database,
        web_cache_settings=web_cache_settings,
        identity_settings=identity_settings,
        http_client=http_client,
        clock=clock,
        media_storage=media_storage,
        push_sender=push_sender,
        ai=ai,
    )

    app = FastAPI(
        title="Travel Buddy API",
        version=settings.service_version,
        lifespan=lifespan,
        openapi_url="/v1/openapi.json" if settings.expose_api_docs else None,
        docs_url="/v1/docs" if settings.expose_api_docs else None,
        redoc_url=None,
        # Runs before every route's own dependencies, so floods are rejected before any work.
        dependencies=[Depends(enforce_rate_limit)],
    )
    app.state.settings = settings
    app.state.rate_limiter = rate_limiter
    app.state.database = database
    app.state.redis = redis
    app.state.feature_flags = FeatureFlags(settings.feature_flags)
    cursor_codec = CursorCodec(
        settings.cursor_signing_key.get_secret_value().encode("utf-8"),
        ttl_seconds=settings.cursor_ttl_seconds,
    )
    app.state.cursor_codec = cursor_codec
    app.state.destination_service = DestinationService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec
    )
    app.state.place_service = PlaceService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec, clock=clock
    )
    app.state.location_service = location_service.LocationService(
        sessionmaker=database.sessionmaker
    )
    app.state.post_service = social_service.PostService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec
    )
    app.state.interaction_service = InteractionService(
        sessionmaker=database.sessionmaker,
        cursors=cursor_codec,
        public_site_url=settings.public_site_url,
    )
    app.state.follow_service = FollowService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec
    )
    app.state.public_post_service = PublicPostService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec
    )
    app.state.public_profile_service = PublicProfileService(
        sessionmaker=database.sessionmaker,
        clock=clock,
        relationship=connections_service.relationship_between,
        relationship_detail=connections_service.relationship_detail,
        cursors=cursor_codec,
    )
    app.state.discovery_session_service = location_service.DiscoverySessionService(
        sessionmaker=database.sessionmaker
    )
    app.state.discovery_service = DiscoveryService(sessionmaker=database.sessionmaker, clock=clock)
    # Group co-members share a context for connection requests (groups sit above connections).
    connections_service.add_shared_context(groups_service.share_active_group)
    # Itinerary summaries reference the author's own trips (trips sit beside social).
    social_service.set_trip_check(trips_service.owns_trip)
    app.state.connection_service = connections_service.ConnectionService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec, clock=clock
    )
    app.state.feed_service = FeedService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec, clock=clock
    )
    block_service = BlockService(
        sessionmaker=database.sessionmaker,
        cursors=cursor_codec,
        on_block=[social_service.remove_follows_between, connections_service.end_between],
    )
    app.state.block_service = block_service
    app.state.report_service = ReportService(
        sessionmaker=database.sessionmaker,
        blocks=block_service,
        providers=evidence_providers(),
    )
    app.state.media_storage = media_storage
    app.state.push_sender = push_sender
    app.state.web_push_vapid = web_push_vapid
    app.state.media_service = media_service.MediaService(
        sessionmaker=database.sessionmaker,
        storage=media_storage,
        max_pending=media_settings.media_max_pending_uploads,
    )
    app.state.trip_service = trips_service.TripService(
        sessionmaker=database.sessionmaker,
        cursors=cursor_codec,
        clock=clock,
        plans=itinerary_plan,
        audience=TripAudience(clock),
    )
    app.state.guide_service = GuideService(sessionmaker=database.sessionmaker, clock=clock)
    app.state.data_export_service = data_exports.DataExportService(
        sessionmaker=database.sessionmaker,
        clock=clock,
        cursors=cursor_codec,
        tokens=data_exports.ExportTokens(
            settings.cursor_signing_key.get_secret_value().encode("utf-8")
        ),
        storage=media_storage,
    )
    app.state.challenge_service = challenges_service.ChallengeService(
        sessionmaker=database.sessionmaker,
        clock=clock,
        cursors=cursor_codec,
        # Discount codes at rest: a key derived (own HKDF label) from the server secret.
        cipher=challenges_service.RewardSecretCipher(
            identity_settings.refresh_token_derivation_key.get_secret_value()
        ),
    )
    app.state.offline_package_service = OfflinePackageService(
        sessionmaker=database.sessionmaker,
        clock=clock,
        storage=media_storage,
        signer=build_manifest_signer(settings),
        tokens=DownloadTokens(settings.cursor_signing_key.get_secret_value().encode("utf-8")),
    )
    app.state.saved_place_service = SavedPlaceService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec, clock=clock
    )
    app.state.ai_provider = ai_provider
    app.state.ai_service = ai
    apple_verifier = build_apple_verifier(settings)
    google_play, google_push = build_google_play(settings, http_client)
    app.state.billing_service = billing_service.BillingService(
        sessionmaker=database.sessionmaker,
        clock=clock,
        stripe=StripeClient(
            http_client,
            secret_key=(
                settings.stripe_secret_key.get_secret_value()
                if settings.stripe_secret_key
                else None
            ),
            webhook_secret=(
                settings.stripe_webhook_secret.get_secret_value()
                if settings.stripe_webhook_secret
                else None
            ),
            api_base=settings.stripe_api_base,
        ),
        web_origin=settings.public_site_url,
        usage=quota_usage,
        providers=billing_providers(settings, apple_verifier, google_play),
        apple=apple_verifier,
        google=google_play,
        google_push=google_push,
    )
    realtime_bus = build_realtime_bus(settings, redis)
    app.state.realtime_bus = realtime_bus
    app.state.messaging_service = messaging_service.MessagingService(
        sessionmaker=database.sessionmaker,
        cursors=cursor_codec,
        publish=realtime_bus.publish,
        sign=media_service.private_signer(media_storage),
        group_policy=group_chat_policy,
        flags=app.state.feature_flags,
    )
    app.state.group_service = groups_service.GroupService(
        sessionmaker=database.sessionmaker,
        clock=clock,
        cursors=cursor_codec,
        chat=GroupChatRooms(),
        announce=app.state.messaging_service.announce,
        public_site_url=settings.public_site_url,
        publish=realtime_bus.publish,
    )
    app.state.notification_service = notifications_service.NotificationService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec
    )
    app.state.admin_service = AdminService(
        sessionmaker=database.sessionmaker, cursors=cursor_codec, clock=clock
    )
    app.state.readiness_checks = (
        dict(readiness_checks)
        if readiness_checks is not None
        else {"database": database.ping, **({"redis": _ping_redis} if redis else {})}
    )
    app.state.clock = clock
    app.state.access_tokens = access_tokens
    app.state.identity_service = identity_service
    app.state.dev_idp = dev_idp
    app.state.job_runner = job_runner

    if settings.jobs_inline_after_response:
        app.add_middleware(
            AfterResponseTickMiddleware,
            runner=job_runner,
            budget_seconds=settings.jobs_inline_budget_seconds,
        )

    app.add_middleware(RateLimitHeadersMiddleware)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Accept-Language",
                "Idempotency-Key",
                "If-Match",
                "X-Request-ID",
            ],
            expose_headers=[
                "X-Request-ID",
                "RateLimit-Limit",
                "RateLimit-Remaining",
                "RateLimit-Reset",
                "Retry-After",
            ],
        )
    # Outermost: every response (including CORS preflight and errors) carries X-Request-ID.
    app.add_middleware(
        RequestContextMiddleware,
        error_type_base_url=settings.error_type_base_url,
        hsts=settings.is_production_like,
    )

    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(client_config_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(exports_router)
    app.include_router(destinations_router)
    app.include_router(places_router)
    app.include_router(location_router)
    app.include_router(social_router)
    app.include_router(trust_safety_router)
    app.include_router(feed_router)
    app.include_router(connections_router)
    app.include_router(discovery_router)
    app.include_router(notifications_router)
    app.include_router(messaging_router)
    app.include_router(billing_router)
    app.include_router(groups_router)
    app.include_router(trips_router)
    app.include_router(saved_places_router)
    app.include_router(guides_router)
    app.include_router(challenges_router)
    app.include_router(ai_router)
    app.include_router(translation_router)
    app.include_router(group_invitations_router)
    app.include_router(realtime_router)
    app.include_router(realtime_tickets_router)
    app.include_router(media_router)
    app.include_router(admin_router)
    app.include_router(internal_router)
    if isinstance(media_storage, LocalStorage):  # emulates the object store (dev/test)
        app.mount(LocalStorage.MOUNT, media_storage.asgi_app())
    if dev_idp is not None:  # absent → 404 (contract: not available in this environment)
        app.include_router(dev_idp_router)
    if settings.dev_billing_enabled:  # refused outside development/test by Settings
        app.include_router(dev_billing_router)
    return app


def build_media_storage(
    settings: MediaSettings, http_client: httpx.AsyncClient, clock: Clock
) -> ObjectStorage | None:
    """Object storage for ``MEDIA_STORAGE`` (``None``: uploads answer 503)."""
    kind = settings.resolved_storage
    if kind == "local":
        return LocalStorage(base_url=settings.media_local_base_url, clock=clock)
    if kind == "s3":
        assert settings.media_s3_endpoint is not None  # validated by MediaSettings
        assert settings.media_s3_access_key_id is not None
        assert settings.media_s3_secret_access_key is not None
        return S3Storage(
            endpoint=str(settings.media_s3_endpoint),
            region=settings.media_s3_region,
            access_key=settings.media_s3_access_key_id.get_secret_value(),
            secret=settings.media_s3_secret_access_key.get_secret_value(),
            quarantine_bucket=settings.media_quarantine_bucket,
            public_bucket=settings.media_public_bucket,
            private_bucket=settings.media_private_bucket,
            public_base_url=str(settings.media_public_base_url),
            http=http_client,
            clock=clock,
        )
    return None


def build_rate_limiter(
    settings: Settings,
    *,
    database: Database,
    redis: Redis | None,
    clock: Clock,
    store: RateLimitStore | None = None,
) -> RateLimiter | None:
    """The limiter for ``RATE_LIMIT_STORE`` (``None`` when disabled, i.e. in tests by default)."""
    policy = RatePolicy.build(settings.rate_limits)
    if store is not None:
        return RateLimiter(store, policy, clock)
    kind = settings.resolved_rate_limit_store
    if kind == "disabled":
        return None
    if kind == "memory":
        return RateLimiter(MemoryRateLimitStore(), policy, clock)
    if kind == "redis":
        if redis is None:
            raise RuntimeError("RATE_LIMIT_STORE=redis needs REDIS_URL")
        return RateLimiter(RedisRateLimitStore(redis), policy, clock)
    return RateLimiter(PostgresRateLimitStore(database.sessionmaker), policy, clock)


def build_apple_verifier(settings: Settings) -> AppleJWSVerifier | None:
    """App Store signed data needs the bundle id and the pinned Apple root (BL-6.01)."""
    if not settings.apple_bundle_id or not settings.apple_root_ca_sha256:
        return None
    return AppleJWSVerifier(
        root_fingerprints=settings.apple_root_ca_sha256.split(","),
        bundle_id=settings.apple_bundle_id,
    )


def build_google_play(
    settings: Settings, http_client: httpx.AsyncClient
) -> tuple[GooglePlayProvider | None, PushVerifier | None]:
    """Play purchases need the package name and a service account key; RTDN pushes also need
    the push subscription's audience and service account (BL-6.01)."""
    key = settings.google_play_service_account_json
    if not settings.google_play_package_name or key is None:
        return None, None
    api = GooglePlayApi(
        ServiceAccount.from_json(key.get_secret_value()),
        settings.google_play_package_name,
        http_client,
    )
    push = None
    if settings.google_pubsub_audience and settings.google_pubsub_service_account:
        push = PushVerifier(
            GoogleCerts(http_client),
            audience=settings.google_pubsub_audience,
            service_account=settings.google_pubsub_service_account,
        )
    return GooglePlayProvider(api, settings.google_play_package_name), push


def billing_providers(
    settings: Settings, apple: AppleJWSVerifier | None, google: GooglePlayProvider | None = None
) -> dict[str, BillingProvider]:
    if settings.dev_billing_enabled:
        return {"apple": DevBillingProvider(), "google": DevBillingProvider()}
    return {
        "apple": AppleStoreProvider(apple) if apple else UnconfiguredStore("the App Store"),
        "google": google if google else UnconfiguredStore("Google Play"),
    }


# Personal-data export (BL-6.03): every module that keeps personal data exports its own part.
DATA_EXPORTERS: tuple[data_exports.Exporter, ...] = (
    identity_module.export_user_data,
    profiles_service.export_user_data,
    social_service.export_user_data,
    feed_service.export_user_data,
    connections_service.export_user_data,
    messaging_service.export_user_data,
    groups_service.export_user_data,
    trips_service.export_user_data,
    location_service.export_user_data,
    billing_service.export_user_data,
    ai_service.export_user_data,
    challenges_service.export_user_data,
    trust_safety_service.export_user_data,
    media_service.export_user_data,
    notifications_service.export_user_data,
    guides_service.export_user_data,
)


class TripAudience:
    """Connections and group membership for trip visibility (trips, same layer; TRIP-005)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def connected(
        self, session: AsyncSession, owner_id: uuid.UUID, viewer_id: uuid.UUID
    ) -> bool:
        return viewer_id in await connections_service.connected_ids(session, owner_id, [viewer_id])

    async def in_group(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        access = await groups_service.member_access(
            session, group_id, user_id, now=self._clock.now()
        )
        return access is not None


class GroupChatRooms:
    """Group chat rooms live in messaging; groups (same layer) reaches them through this."""

    async def create(
        self, session: AsyncSession, group_id: uuid.UUID, owner_id: uuid.UUID
    ) -> uuid.UUID:
        return await messaging_service.create_group_conversation(session, group_id, owner_id)

    async def add_member(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        from_join: bool,
    ) -> None:
        await messaging_service.add_group_member(
            session, conversation_id, user_id, from_join=from_join
        )

    async def remove_member(
        self, session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await messaging_service.remove_group_member(session, conversation_id, user_id)


def challenge_answer_judge(
    ai: ai_service.AIService | None,
) -> challenges_service.AnswerJudge | None:
    """The AI judge for ``ai_assisted`` challenges (ai_assistant → challenges, same layer)."""
    if ai is None:
        return None

    async def judge(
        *,
        user_id: uuid.UUID | None,
        title: str,
        description: str,
        accepted_answers: Sequence[str],
        answer: str,
    ) -> challenges_service.AIVerdict | None:
        verdict = await ai.judge_answer(
            user_id=user_id,
            title=title,
            description=description,
            accepted_answers=accepted_answers,
            answer=answer,
        )
        if verdict is None:
            return None
        return challenges_service.AIVerdict(
            matches=verdict.matches, confidence=verdict.confidence, rationale=verdict.rationale
        )

    return judge


async def group_chat_policy(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> groups_service.ChatPolicy:
    """Send rights in a group chat come from the group (groups → messaging, same layer)."""
    return await groups_service.chat_policy(session, group_id, user_id, now=now)


def build_manifest_signer(settings: Settings) -> ManifestSigner | None:
    """Signs offline package manifests (BL-4.08); a development key outside staging/production."""
    if settings.offline_manifest_private_key is not None:
        key = load_ed25519_private_key(settings.offline_manifest_private_key.get_secret_value())
        return ManifestSigner(key, settings.offline_manifest_key_id)
    if settings.app_env.allows_dev_adapters:
        return ManifestSigner(development_manifest_key(), "dev-offline")
    return None


async def quota_usage(
    session: AsyncSession, user_id: uuid.UUID, at: datetime
) -> dict[billing_service.Quota, int]:
    """Current usage of every metered quota, from the modules that own the rows."""
    return {
        **await ai_service.quota_usage(session, user_id, at),
        **await offline_packages.quota_usage(session, user_id, at),
        **await groups_service.quota_usage(session, user_id, at),
    }


def build_ai_provider(settings: Settings) -> AIProvider | None:
    """The AI adapter for this environment (BL-4.02, ADR-0024); ``None`` = unavailable (503)."""
    resolved = settings.resolved_ai_provider
    if resolved == "anthropic" and settings.anthropic_api_key is not None:
        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=settings.anthropic_base_url,
            refusal_fallback=settings.ai_refusal_fallback,
        )
    if resolved == "fake":
        return FakeAIProvider()
    return None


def build_ai_service(
    settings: Settings, database: Database, clock: Clock, provider: AIProvider | None
) -> ai_service.AIService:
    itinerary = TaskConfig(
        model=settings.ai_itinerary_model,
        max_tokens=settings.ai_itinerary_max_tokens,
        effort=settings.ai_itinerary_effort,
        timeout_seconds=settings.ai_timeout_seconds,
    )
    return ai_service.AIService(
        sessionmaker=database.sessionmaker,
        clock=clock,
        provider=provider,
        tasks={
            AITask.ITINERARY_GENERATE: itinerary,
            AITask.TRIP_REPLAN: itinerary,
            AITask.POST_TRANSLATE: TaskConfig(
                model=settings.ai_translation_model,
                max_tokens=8000,
                effort=settings.ai_translation_effort,
                timeout_seconds=min(settings.ai_timeout_seconds, 60.0),
            ),
            AITask.CHALLENGE_JUDGE: TaskConfig(
                model=settings.ai_judge_model,
                max_tokens=2048,
                effort=settings.ai_judge_effort,
                timeout_seconds=min(settings.ai_timeout_seconds, 60.0),
            ),
        },
        policy=ai_service.SpendPolicy(
            daily_budget_micros=round(settings.ai_daily_budget_usd * 1_000_000),
            breaker_failures=settings.ai_breaker_failures,
            breaker_cooldown=timedelta(seconds=settings.ai_breaker_cooldown_seconds),
        ),
        problem_base_url=settings.error_type_base_url,
    )


async def itinerary_plan(
    session: AsyncSession, user_id: uuid.UUID, generation_id: uuid.UUID
) -> trips_service.ItineraryPlan | None:
    """An AI proposal as the trips module applies it (ai_assistant -> trips; AI-002)."""
    proposal = await ai_service.proposal_for(session, user_id, generation_id)
    if proposal is None:
        return None
    return trips_service.ItineraryPlan(
        generation_id=generation_id,
        days=tuple(
            trips_service.PlannedDay(
                day_index=day["day_index"],
                date=date.fromisoformat(day["date"]),
                items=tuple(
                    trips_service.PlannedItem(
                        kind=item["kind"],
                        title=item["title"],
                        notes=item["description"] or None,
                        place_id=uuid.UUID(item["place_id"]) if item["place_id"] else None,
                        start_time=item["suggested_start_time"],
                        duration_minutes=item["estimated_duration_minutes"],
                        confidence=item["confidence"],
                        unverified=item["unverified"],
                        source_attribution=tuple(item["source_attribution"]),
                        data_freshness_at=(
                            datetime.fromisoformat(item["place_data_freshness_at"])
                            if item.get("place_data_freshness_at")
                            else None
                        ),
                    )
                    for item in day["items"]
                ),
            )
            for day in proposal["itinerary"]["days"]
        ),
    )


def build_vapid(settings: Settings) -> Vapid | None:
    """The Web Push application server key, when configured (BL-3.16)."""
    if settings.web_push_vapid_private_key is None:
        return None
    return Vapid(
        settings.web_push_vapid_private_key.get_secret_value(), settings.web_push_vapid_subject
    )


def build_realtime_bus(settings: Settings, redis: Redis | None) -> RealtimeBus:
    """Realtime fanout (ADR-0023): Redis pub/sub across processes, or in-process."""
    if settings.resolved_realtime_bus == "redis":
        if redis is None:
            raise RuntimeError("REALTIME_BUS=redis needs REDIS_URL")
        return RedisBus(redis)
    return MemoryBus()


def build_job_runner(
    *,
    database: Database,
    web_cache_settings: WebCacheSettings,
    identity_settings: IdentitySettings,
    http_client: httpx.AsyncClient,
    clock: Clock,
    media_storage: ObjectStorage | None = None,
    push_sender: PushSender | None = None,
    ai: ai_service.AIService | None = None,
) -> JobRunner:
    """Event subscriptions and job handlers for every module (shared by the API and workers)."""
    router = EventRouter()
    handlers: dict[str, JobHandler] = {}
    if ai is not None:
        ai_service.subscribe(router)
        handlers.update(ai_service.make_handlers(ai))
    web_cache_service.subscribe(router, web_cache_settings)
    handlers[web_cache_service.JOB_KIND] = web_cache_service.make_handler(
        web_cache_settings, http_client, clock
    )
    social_service.subscribe(router)
    handlers.update(social_service.make_handlers(database.sessionmaker))
    notifications_service.subscribe(router)
    handlers.update(
        notifications_service.make_handlers(
            database.sessionmaker,
            push_sender=push_sender,
            push_cipher=identity_module.push_cipher(identity_settings),
        )
    )
    handlers.update(
        identity_module.make_handlers(
            database.sessionmaker,
            build_idp_deleter(identity_settings, http_client),
            before_delete=[groups_service.hand_over_owned_groups],
        )
    )
    handlers.update(abuse_signals.make_handlers(database.sessionmaker))
    handlers.update(groups_service.make_handlers(database.sessionmaker, clock))
    challenges_service.subscribe(router)
    handlers.update(
        data_exports.make_export_handlers(
            database.sessionmaker, clock, media_storage, DATA_EXPORTERS
        )
    )
    handlers.update(
        challenges_service.make_handlers(
            database.sessionmaker, clock, judge=challenge_answer_judge(ai)
        )
    )
    handlers.update(
        media_service.make_handlers(
            database.sessionmaker, media_storage, media_service.NoopScanner()
        )
    )
    # Daily retention purges, one per module that owns data with a retention rule (BL-1.18).
    purges = {
        "platform": purge_platform,
        "identity": identity_module.purge_expired,
        "social": social_service.purge_expired,
        "trust_safety": trust_safety_service.purge_expired,
        "feed": feed_service.purge_expired,
        "notifications": notifications_service.purge_expired,
        "media": media_service.purge_expired,
        "connections": connections_service.purge_expired,
        "messaging": messaging_service.purge_expired,
        "billing": billing_service.purge_expired,
        "groups": groups_service.purge_expired,
        "trips": trips_service.purge_expired,
        "ai_assistant": ai_service.purge_expired,
        "offline_packages": offline_packages.purge_expired,
        "location": location_service.purge_expired,
    }
    periodic = [Periodic(f"retention.{name}", f"retention.{name}", DAILY) for name in purges]
    periodic.append(Periodic(abuse_signals.JOB_KIND, abuse_signals.JOB_KIND, timedelta(hours=1)))
    # Export archives go once their 7-day link has expired (BL-6.03).
    periodic.append(Periodic(data_exports.CLEANUP_JOB, data_exports.CLEANUP_JOB, DAILY))
    # Challenges start and close on time (CHAL-003); reads also apply due moves lazily.
    periodic.append(
        Periodic(
            challenges_service.LIFECYCLE_JOB,
            challenges_service.LIFECYCLE_JOB,
            timedelta(minutes=5),
        )
    )
    periodic.append(
        Periodic(
            groups_service.PREMIUM_WATCH_JOB,
            groups_service.PREMIUM_WATCH_JOB,
            timedelta(hours=6),
        )
    )
    # Accounts whose 30-day grace ended are erased within the hour (AUTH-010: 30 + 7 days).
    periodic.append(
        Periodic(
            identity_module.ACCOUNT_DELETIONS_JOB,
            identity_module.ACCOUNT_DELETIONS_JOB,
            timedelta(hours=1),
        )
    )
    handlers.update(
        {
            f"retention.{name}": retention_handler(database.sessionmaker, purge, name=name)
            for name, purge in purges.items()
        }
    )
    return JobRunner(
        sessionmaker=database.sessionmaker, router=router, handlers=handlers, periodic=periodic
    )


async def account_restrictions(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> list[AccountRestriction]:
    """Active restrictions for ``Me`` (trust_safety → identity, same layer; SAFE-013). Every
    platform restriction can be appealed through support until in-app appeals exist."""
    return [
        AccountRestriction.model_validate(
            {"kind": r.kind, "reason_code": r.reason_code, "until": r.until, "appealable": True}
        )
        for r in await trust_safety_service.active_restrictions(session, user_id, now=now)
    ]


def evidence_providers() -> dict[str, trust_safety_service.EvidenceProvider]:
    """Report evidence per target type, supplied by the modules that own the content."""

    async def post(
        session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
    ) -> trust_safety_service.Evidence | None:
        found = await social_service.post_evidence(session, target_id, reporter_id)
        return trust_safety_service.Evidence(*found) if found else None

    async def comment(
        session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
    ) -> trust_safety_service.Evidence | None:
        found = await social_service.comment_evidence(session, target_id, reporter_id)
        return trust_safety_service.Evidence(*found) if found else None

    async def user(
        session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
    ) -> trust_safety_service.Evidence | None:
        snapshot = await profiles_service.user_evidence(session, target_id)
        return trust_safety_service.Evidence(target_id, snapshot) if snapshot else None

    async def message(
        session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
    ) -> trust_safety_service.Evidence | None:
        found = await messaging_service.message_evidence(session, target_id, reporter_id)
        return trust_safety_service.Evidence(*found) if found else None

    async def group(
        session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
    ) -> trust_safety_service.Evidence | None:
        found = await groups_service.group_evidence(session, target_id, reporter_id)
        return trust_safety_service.Evidence(*found) if found else None

    return {
        "post": post,
        "comment": comment,
        "user": user,
        "message": message,
        "group": group,
    }
