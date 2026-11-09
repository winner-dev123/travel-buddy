"""API process entry point (``uvicorn app.main:create_app --factory``)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import install_error_handlers
from app.core.feature_flags import FeatureFlags
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.pagination import CursorCodec
from app.core.redis import create_redis
from app.core.security.access_tokens import (
    AccessTokenService,
    development_signing_key,
    load_ed25519_private_key,
)
from app.core.time import Clock, SystemClock
from app.modules.client_config.api import router as client_config_router
from app.modules.health.api import ReadinessCheck
from app.modules.health.api import router as health_router
from app.modules.identity.adapters.dev_idp import DevIdentityProvider
from app.modules.identity.adapters.oidc import HttpJwksKeyProvider, IssuerConfig, OidcVerifier
from app.modules.identity.api import auth_router, dev_idp_router, me_router
from app.modules.identity.config import IdentitySettings
from app.modules.identity.service import IdentityService
from app.modules.platform.api import AfterResponseTickMiddleware, internal_router
from app.modules.platform.service import EventRouter, JobHandler, JobRunner
from app.modules.web_cache import service as web_cache_service
from app.modules.web_cache.config import WebCacheSettings

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    identity_settings: IdentitySettings | None = None,
    web_cache_settings: WebCacheSettings | None = None,
    readiness_checks: Mapping[str, ReadinessCheck] | None = None,
    clock: Clock | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the API application (composition root).

    ``readiness_checks``, ``clock`` and ``http_transport`` may be injected (tests); by default the
    database and Redis are checked, the system clock is used and HTTP goes to the network.
    """
    settings = settings or get_settings()
    identity_settings = identity_settings or IdentitySettings()
    web_cache_settings = web_cache_settings or WebCacheSettings()
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
    dev_idp = DevIdentityProvider(clock) if settings.dev_idp_enabled else None
    if dev_idp is not None:
        issuers.append(dev_idp.issuer_config())
    identity_service = IdentityService(
        sessionmaker=database.sessionmaker,
        verifier=OidcVerifier(issuers, now=lambda: clock.now().timestamp()),
        access_tokens=access_tokens,
        settings=identity_settings,
        clock=clock,
    )

    job_runner = build_job_runner(
        database=database,
        web_cache_settings=web_cache_settings,
        http_client=http_client,
        clock=clock,
    )

    app = FastAPI(
        title="Travel Buddy API",
        version=settings.service_version,
        lifespan=lifespan,
        openapi_url="/v1/openapi.json" if settings.expose_api_docs else None,
        docs_url="/v1/docs" if settings.expose_api_docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.redis = redis
    app.state.feature_flags = FeatureFlags(settings.feature_flags)
    app.state.cursor_codec = CursorCodec(
        settings.cursor_signing_key.get_secret_value().encode("utf-8"),
        ttl_seconds=settings.cursor_ttl_seconds,
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
    app.include_router(internal_router)
    if dev_idp is not None:  # absent → 404 (contract: not available in this environment)
        app.include_router(dev_idp_router)
    return app


def build_job_runner(
    *,
    database: Database,
    web_cache_settings: WebCacheSettings,
    http_client: httpx.AsyncClient,
    clock: Clock,
) -> JobRunner:
    """Event subscriptions and job handlers for every module (shared by the API and workers)."""
    router = EventRouter()
    handlers: dict[str, JobHandler] = {}
    web_cache_service.subscribe(router, web_cache_settings)
    handlers[web_cache_service.JOB_KIND] = web_cache_service.make_handler(
        web_cache_settings, http_client, clock
    )
    return JobRunner(sessionmaker=database.sessionmaker, router=router, handlers=handlers)
