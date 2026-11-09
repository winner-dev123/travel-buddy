"""Rate limiting (BL-1.15; SAFE-005, NFR-006): sliding-window maths, policy, settings, client IP,
failure modes and the HTTP behaviour (headers, 429, Retry-After)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.core.config import AppEnv, Settings
from app.core.errors import AppError, ErrorCode
from app.core.ratelimit import (
    Limit,
    MemoryRateLimitStore,
    RateLimiter,
    RatePolicy,
    StoreUnavailableError,
    WindowHit,
    evaluate,
)
from app.core.ratelimit.policy import parse_limits
from app.core.time import FixedClock
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings

pytestmark = pytest.mark.req("SAFE-005", "NFR-006")

T0 = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)  # a multiple of every window used below


# ─────────────────────────────── sliding window ───────────────────────────────


def test_requests_within_the_limit_are_allowed_with_remaining_quota() -> None:
    decision = evaluate(Limit(10, 60), current=4, previous=0, elapsed=15)
    assert decision.allowed
    assert decision.remaining == 6
    assert decision.reset_seconds == 45


def test_the_previous_window_counts_with_a_decaying_weight() -> None:
    # 75% of the previous window still overlaps: 8 x 0.75 + 3 = 9 <= 10.
    assert evaluate(Limit(10, 60), current=3, previous=8, elapsed=15).allowed
    # Same counts later in the window weigh less... and earlier they weigh more.
    assert not evaluate(Limit(10, 60), current=3, previous=10, elapsed=5).allowed


def test_rejection_reports_how_long_to_wait() -> None:
    full = evaluate(Limit(10, 60), current=11, previous=0, elapsed=20)
    assert not full.allowed
    assert full.remaining == 0
    assert 40 <= full.retry_after_seconds <= 60 + 40
    decaying = evaluate(Limit(10, 60), current=2, previous=20, elapsed=10)
    assert not decaying.allowed
    # Allowed again once 20 x (1 - t/60) + 2 <= 9, i.e. t >= 39 s → about 29 s from now.
    assert 25 <= decaying.retry_after_seconds <= 31
    assert decaying.headers()["Retry-After"] == str(decaying.retry_after_seconds)


def test_limits_are_parsed_and_overrides_are_validated() -> None:
    assert parse_limits("20/86400, 5/60") == (Limit(20, 86400), Limit(5, 60))
    policy = RatePolicy.build({"write": "200/60"})
    assert policy.bucket("write").limits == (Limit(200, 60),)
    assert policy.bucket("reports").limits == (Limit(20, 86400),)
    assert policy.bucket("reports").fails_closed
    assert not policy.bucket("read").fails_closed
    with pytest.raises(ValueError, match="unknown rate limit bucket"):
        RatePolicy.build({"nope": "1/60"})
    with pytest.raises(ValueError, match="invalid rate limit"):
        parse_limits("ten per minute")


# ─────────────────────────────── settings ───────────────────────────────


def test_store_selection_follows_the_environment() -> None:
    assert make_settings().resolved_rate_limit_store == "disabled"
    assert make_settings(app_env=AppEnv.DEVELOPMENT).resolved_rate_limit_store == "memory"
    assert make_settings(rate_limit_store="memory").resolved_rate_limit_store == "memory"


def _production(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnv.STAGING,
        "cursor_signing_key": SecretStr("x" * 40),
        "platform_jwt_private_key": SecretStr("unused-in-this-test"),
    }
    values.update(overrides)
    return make_settings(**values)


def test_production_uses_redis_when_configured_otherwise_postgres() -> None:
    assert _production().resolved_rate_limit_store == "redis"
    no_redis = _production(redis_url="")
    assert no_redis.resolved_rate_limit_store == "postgres"


@pytest.mark.security
@pytest.mark.parametrize("store", ["memory", "disabled"])
def test_production_rejects_unshared_or_missing_rate_limiting(store: str) -> None:
    with pytest.raises(ValidationError, match="RATE_LIMIT_STORE"):
        _production(rate_limit_store=store)


def test_invalid_rate_limit_overrides_fail_at_boot() -> None:
    with pytest.raises(ValidationError, match="unknown rate limit bucket"):
        make_settings(rate_limits={"everything": "1/60"})


def test_proxy_headers_are_trusted_on_vercel_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not make_settings().trusts_proxy_headers
    monkeypatch.setenv("VERCEL", "1")
    assert make_settings().trusts_proxy_headers
    assert not make_settings(trust_proxy_headers=False).trusts_proxy_headers


# ─────────────────────────────── limiter & failure modes ───────────────────────────────


def test_limiter_counts_per_subject_and_frees_up_as_windows_pass() -> None:
    clock = FixedClock(T0)
    limiter = RateLimiter(MemoryRateLimitStore(), RatePolicy.build({"write": "3/60"}), clock)
    bucket = limiter.policy.bucket("write")

    async def burst(subject: str, n: int) -> list[bool]:
        return [(await limiter.check(bucket, subject)).allowed for _ in range(n)]

    assert asyncio.run(burst("u:a", 4)) == [True, True, True, False]
    assert asyncio.run(burst("u:b", 1)) == [True]  # other subjects are unaffected
    clock.set(T0 + timedelta(seconds=150))  # two windows later nothing carries over
    assert asyncio.run(burst("u:a", 3)) == [True, True, True]


class _DownStore:
    async def hit(self, hits: Sequence[WindowHit]) -> list[tuple[int, int]]:
        raise StoreUnavailableError("connection refused")


def test_open_classes_let_requests_through_when_the_store_is_down() -> None:
    limiter = RateLimiter(_DownStore(), RatePolicy.build(), FixedClock(T0))
    assert asyncio.run(limiter.check(limiter.policy.bucket("read"), "u:a")).allowed


@pytest.mark.security
def test_closed_classes_reject_requests_when_the_store_is_down() -> None:
    limiter = RateLimiter(_DownStore(), RatePolicy.build(), FixedClock(T0))
    with pytest.raises(AppError) as caught:
        asyncio.run(limiter.check(limiter.policy.bucket("auth"), "ip:203.0.113.9"))
    assert caught.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert caught.value.headers["Retry-After"] == "5"


def test_enforce_raises_rate_limited_with_headers() -> None:
    limiter = RateLimiter(
        MemoryRateLimitStore(), RatePolicy.build({"auth_subject": "1/3600"}), FixedClock(T0)
    )
    asyncio.run(limiter.enforce("auth_subject", "iss|sub"))
    with pytest.raises(AppError) as caught:
        asyncio.run(limiter.enforce("auth_subject", "iss|sub"))
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert {"Retry-After", "RateLimit-Limit", "RateLimit-Remaining"} <= set(caught.value.headers)


# ─────────────────────────────── HTTP ───────────────────────────────


async def _ok() -> bool:
    return True


def _app(**settings: object) -> FastAPI:
    return create_app(
        make_settings(rate_limit_store="memory", **settings),
        identity_settings=make_identity_settings(),
        readiness_checks={"database": _ok},
        clock=FixedClock(T0),
    )


CONFIG = ("/v1/client-config", {"platform": "web", "app_version": "0.1.0"})


def test_responses_carry_rate_limit_headers_and_429_has_retry_after() -> None:
    with TestClient(_app(rate_limits={"read": "2/60"})) as client:
        first = client.get(CONFIG[0], params=CONFIG[1])
        assert first.status_code == 200
        assert first.headers["RateLimit-Limit"] == "2"
        assert first.headers["RateLimit-Remaining"] == "1"
        assert int(first.headers["RateLimit-Reset"]) == 60
        client.get(CONFIG[0], params=CONFIG[1])
        limited = client.get(CONFIG[0], params=CONFIG[1])
        assert limited.status_code == 429
        assert limited.headers["content-type"].startswith("application/problem+json")
        assert limited.json()["code"] == "rate_limited"
        assert int(limited.headers["Retry-After"]) >= 1
        assert limited.headers["RateLimit-Remaining"] == "0"


def test_health_probes_are_never_limited() -> None:
    with TestClient(_app(rate_limits={"read": "1/60"})) as client:
        for _ in range(3):
            response = client.get("/health/live")
            assert response.status_code == 200
            assert "RateLimit-Limit" not in response.headers


def test_limits_run_before_authentication() -> None:
    with TestClient(_app(rate_limits={"read": "1/60"})) as client:
        assert client.get("/v1/users/me").status_code == 401
        assert client.get("/v1/users/me").status_code == 429


def _ip_of(client: TestClient, **headers: str) -> int:
    """Hits a guest route (per-IP, limit 1) and returns the status of a second hit."""
    client.get("/v1/client-config", params=CONFIG[1], headers=headers)
    return client.get("/v1/client-config", params=CONFIG[1], headers=headers).status_code


@pytest.mark.security
def test_forwarded_client_ip_is_trusted_only_with_the_shared_secret() -> None:
    secret = "s" * 40
    app = _app(rate_limits={"read": "1/60"}, client_ip_forwarding_secret=SecretStr(secret))
    with TestClient(app) as client:
        trusted = {"X-TB-Forwarding-Secret": secret}
        assert _ip_of(client, **trusted, **{"X-TB-Client-IP": "198.51.100.1"}) == 429
        # A different browser behind the BFF has its own quota...
        ok = client.get(
            CONFIG[0], params=CONFIG[1], headers={**trusted, "X-TB-Client-IP": "198.51.100.2"}
        )
        assert ok.status_code == 200
        # ...but without the secret the header is ignored (the socket peer's quota applies).
        assert _ip_of(client, **{"X-TB-Client-IP": "198.51.100.3"}) == 429
        spoofed = client.get(
            CONFIG[0],
            params=CONFIG[1],
            headers={"X-TB-Forwarding-Secret": "wrong", "X-TB-Client-IP": "198.51.100.4"},
        )
        assert spoofed.status_code == 429


@pytest.mark.security
def test_edge_headers_are_used_only_when_trusted_and_ipv6_counts_per_64() -> None:
    with TestClient(_app(rate_limits={"read": "1/60"}, trust_proxy_headers=True)) as client:
        assert _ip_of(client, **{"X-Forwarded-For": "2001:db8:1:2::1, 10.0.0.1"}) == 429
        same_prefix = client.get(
            CONFIG[0], params=CONFIG[1], headers={"X-Real-IP": "2001:db8:1:2:ffff::9"}
        )
        assert same_prefix.status_code == 429
        other = client.get(CONFIG[0], params=CONFIG[1], headers={"X-Real-IP": "203.0.113.7"})
        assert other.status_code == 200
    with TestClient(_app(rate_limits={"read": "1/60"})) as client:
        client.get(CONFIG[0], params=CONFIG[1], headers={"X-Real-IP": "203.0.113.8"})
        ignored = client.get(CONFIG[0], params=CONFIG[1], headers={"X-Real-IP": "203.0.113.9"})
        assert ignored.status_code == 429
