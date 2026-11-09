"""API process entry point (``uvicorn app.main:create_app --factory``)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

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
from app.modules.client_config.api import router as client_config_router
from app.modules.connections import service as connections_service
from app.modules.connections.api import router as connections_router
from app.modules.destinations.api import router as destinations_router
from app.modules.destinations.service import DestinationService
from app.modules.discovery.api import router as discovery_router
from app.modules.discovery.service import DiscoveryService
from app.modules.feed import service as feed_service
from app.modules.feed.api import router as feed_router
from app.modules.feed.service import FeedService
from app.modules.health.api import ReadinessCheck
from app.modules.health.api import router as health_router
from app.modules.identity import service as identity_module
from app.modules.identity.adapters.dev_idp import DevIdentityProvider
from app.modules.identity.adapters.oidc import HttpJwksKeyProvider, IssuerConfig, OidcVerifier
from app.modules.identity.adapters.supabase_admin import build_idp_deleter
from app.modules.identity.api import auth_router, dev_idp_router, me_router
from app.modules.identity.config import IdentitySettings
from app.modules.identity.schemas import AccountRestriction
from app.modules.identity.service import IdentityService
from app.modules.location import service as location_service
from app.modules.location.api import router as location_router
from app.modules.media import service as media_service
from app.modules.media.api import router as media_router
from app.modules.media.config import MediaSettings
from app.modules.media.storage import LocalStorage, ObjectStorage, S3Storage
from app.modules.notifications import service as notifications_service
from app.modules.notifications.api import router as notifications_router
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
from app.modules.trust_safety import service as trust_safety_service
from app.modules.trust_safety.api import router as trust_safety_router
from app.modules.trust_safety.service import BlockService, ReportService
from app.modules.web_cache import service as web_cache_service
from app.modules.web_cache.config import WebCacheSettings

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

    database = Database(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_recycle_seconds=settings.database_pool_recycle_seconds,
        transaction_pooler=settings.database_transaction_pooler,
    )
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
    issuers = [
        IssuerConfig(
            issuer=trusted.issuer,
            audiences=trusted.audiences,
            algorithms=trusted.algorithms,
            keys=HttpJwksKeyProvider(str(trusted.jwks_uri), http_client),
            method=trusted.method,
        )
        for trusted in identity_settings.oidc_issuers
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
    )

    media_storage = build_media_storage(media_settings, http_client, clock)
    job_runner = build_job_runner(
        database=database,
        web_cache_settings=web_cache_settings,
        identity_settings=identity_settings,
        http_client=http_client,
        clock=clock,
        media_storage=media_storage,
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
    )
    app.state.discovery_session_service = location_service.DiscoverySessionService(
        sessionmaker=database.sessionmaker
    )
    app.state.discovery_service = DiscoveryService(sessionmaker=database.sessionmaker, clock=clock)
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
    app.state.media_service = media_service.MediaService(
        sessionmaker=database.sessionmaker,
        storage=media_storage,
        max_pending=media_settings.media_max_pending_uploads,
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
    app.add_middleware(RequestContextMiddleware, error_type_base_url=settings.error_type_base_url)

    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(client_config_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(destinations_router)
    app.include_router(location_router)
    app.include_router(social_router)
    app.include_router(trust_safety_router)
    app.include_router(feed_router)
    app.include_router(connections_router)
    app.include_router(discovery_router)
    app.include_router(notifications_router)
    app.include_router(media_router)
    app.include_router(admin_router)
    app.include_router(internal_router)
    if isinstance(media_storage, LocalStorage):  # emulates the object store (dev/test)
        app.mount(LocalStorage.MOUNT, media_storage.asgi_app())
    if dev_idp is not None:  # absent → 404 (contract: not available in this environment)
        app.include_router(dev_idp_router)
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


def build_job_runner(
    *,
    database: Database,
    web_cache_settings: WebCacheSettings,
    identity_settings: IdentitySettings,
    http_client: httpx.AsyncClient,
    clock: Clock,
    media_storage: ObjectStorage | None = None,
) -> JobRunner:
    """Event subscriptions and job handlers for every module (shared by the API and workers)."""
    router = EventRouter()
    handlers: dict[str, JobHandler] = {}
    web_cache_service.subscribe(router, web_cache_settings)
    handlers[web_cache_service.JOB_KIND] = web_cache_service.make_handler(
        web_cache_settings, http_client, clock
    )
    social_service.subscribe(router)
    handlers.update(social_service.make_handlers(database.sessionmaker))
    notifications_service.subscribe(router)
    handlers.update(notifications_service.make_handlers(database.sessionmaker))
    handlers.update(
        identity_module.make_handlers(
            database.sessionmaker, build_idp_deleter(identity_settings, http_client)
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
        "location": location_service.purge_expired,
    }
    periodic = [Periodic(f"retention.{name}", f"retention.{name}", DAILY) for name in purges]
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

    return {"post": post, "comment": comment, "user": user}
