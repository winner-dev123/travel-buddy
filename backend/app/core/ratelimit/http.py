"""HTTP integration: per-route classes, client identity, enforcement and ``RateLimit-*`` headers.

A route's class comes from ``openapi_extra={"x-rate-limit-class": ...}`` (declared with
``rate_limited()``), otherwise ``/v1/admin/*`` → ``admin``, health and internal routes → ``none``,
``GET`` → ``read`` and other methods → ``write``. A contract test checks every implemented route
against the contract's ``x-rate-limit-class``.

Client IP: the web BFF calls the API from shared egress IPs, so it forwards the browser's IP in
``X-TB-Client-IP``, trusted only together with the shared ``X-TB-Forwarding-Secret``. Otherwise the
edge's ``X-Real-IP``/``X-Forwarded-For`` are used when proxy headers are trusted (Vercel overwrites
them), else the socket peer. IPv6 addresses are counted per /64.
"""

from __future__ import annotations

import hmac
import ipaddress
from typing import Any

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import AppError, ErrorCode
from app.core.ratelimit.limiter import Decision, RateLimiter
from app.core.ratelimit.policy import Bucket, RateClass
from app.core.ratelimit.policy import Scope as LimitScope

RATE_CLASS_KEY = "x-rate-limit-class"
BUCKET_KEY = "x-rate-limit-bucket"
STATE_KEY = "rate_limit"
CLIENT_IP_HEADER = "x-tb-client-ip"
FORWARDING_SECRET_HEADER = "x-tb-forwarding-secret"  # noqa: S105 - header name, not a secret


def rate_limited(rate_class: str, *, bucket: str | None = None) -> dict[str, Any]:
    """``openapi_extra`` for a route whose class is not the method default."""
    extra: dict[str, Any] = {RATE_CLASS_KEY: RateClass(rate_class).value}
    if bucket is not None:
        extra[BUCKET_KEY] = bucket
    return extra


def route_rate_class(route: APIRoute, method: str) -> tuple[RateClass, str | None]:
    extra = route.openapi_extra or {}
    if RATE_CLASS_KEY in extra:
        return RateClass(extra[RATE_CLASS_KEY]), extra.get(BUCKET_KEY)
    if route.path.startswith("/v1/admin/"):
        return RateClass.ADMIN, None
    if route.path.startswith(("/health/", "/internal/")):
        return RateClass.NONE, None
    return (RateClass.READ if method in ("GET", "HEAD") else RateClass.WRITE), None


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def client_ip(request: Request) -> str:
    settings = request.app.state.settings
    secret = settings.client_ip_forwarding_secret
    if secret is not None:
        presented = request.headers.get(FORWARDING_SECRET_HEADER, "")
        if presented and hmac.compare_digest(
            presented.encode(), secret.get_secret_value().encode()
        ):
            forwarded = _valid_ip(request.headers.get(CLIENT_IP_HEADER))
            if forwarded:
                return forwarded
    if settings.trust_proxy_headers:
        edge = _valid_ip(request.headers.get("x-real-ip"))
        if edge is None:
            first = (request.headers.get("x-forwarded-for") or "").split(",")[0]
            edge = _valid_ip(first)
        if edge:
            return edge
    peer = request.client.host if request.client else None
    return _valid_ip(peer) or "unknown"


def _token_claims(request: Request) -> tuple[str, str] | None:
    """(user id, session id) from a valid bearer token, without failing the request."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        claims = request.app.state.access_tokens.verify(token.strip())
    except AppError:
        return None  # the route's own authentication rejects it
    return str(claims.user_id), str(claims.session_id)


def _subject(request: Request, bucket: Bucket, route: APIRoute) -> str | None:
    """Who the request counts against; ``None`` leaves the check to the owning service."""
    if bucket.scope is LimitScope.USER:
        claims = _token_claims(request)
        return f"u:{claims[0]}" if claims else f"ip:{client_ip(request)}"
    if bucket.scope is LimitScope.KEY:
        if bucket.rate_class is RateClass.WEBHOOK:
            return f"route:{route.path}"  # per provider (signatures are verified first)
        claims = _token_claims(request)
        # Per session when signed in; otherwise the service applies it once it knows the key
        # (refresh: the session behind the refresh token).
        return f"s:{claims[1]}" if claims else None
    return f"ip:{client_ip(request)}"


async def enforce_rate_limit(connection: HTTPConnection) -> None:
    """App-wide dependency: runs before each route's own dependencies (authentication included).
    WebSocket routes pass through: the realtime gateway limits per frame (docs/06 §10)."""
    if not isinstance(connection, Request):
        return
    request = connection
    limiter: RateLimiter | None = request.app.state.rate_limiter
    route = request.scope.get("route")
    if limiter is None or not isinstance(route, APIRoute):
        return
    rate_class, bucket_name = route_rate_class(route, request.method)
    if rate_class is RateClass.NONE:
        return
    bucket = limiter.policy.bucket(bucket_name or rate_class.value)
    subject = _subject(request, bucket, route)
    if subject is None:
        return
    decision = await limiter.check(bucket, subject)
    request.state.rate_limit = decision
    if not decision.allowed:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "Too many requests. Slow down and try again later.",
            headers=decision.headers(),
        )


class RateLimitHeadersMiddleware:
    """Adds ``RateLimit-Limit/Remaining/Reset`` to every response of a rate-limited route."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state: dict[str, Any] = scope.setdefault("state", {})

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                decision = state.get(STATE_KEY)
                if isinstance(decision, Decision):
                    headers = MutableHeaders(scope=message)
                    for name, value in decision.headers().items():
                        if name.lower() not in headers:
                            headers[name] = value
            await send(message)

        await self.app(scope, receive, send_wrapper)
