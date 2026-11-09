"""API process entry point (``uvicorn app.main:create_app --factory``)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

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
from app.modules.health.api import ReadinessCheck
from app.modules.health.api import router as health_router


def create_app(
    settings: Settings | None = None,
    *,
    readiness_checks: Mapping[str, ReadinessCheck] | None = None,
) -> FastAPI:
    """Build the API application.

    ``readiness_checks`` may be injected (tests); by default the database and Redis are checked.
    """
    settings = settings or get_settings()
    configure_logging(
        level=settings.log_level, json_output=settings.log_json, service_name=settings.service_name
    )

    database = Database(settings.database_url, pool_size=settings.database_pool_size)
    redis = create_redis(settings.redis_url)

    async def _ping_redis() -> object:
        return await redis.ping()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await redis.aclose()
            await database.dispose()

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
        else {"database": database.ping, "redis": _ping_redis}
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
    # Versioned domain routers (/v1/...) are mounted here as modules are implemented (Phase 1+).
    return app
