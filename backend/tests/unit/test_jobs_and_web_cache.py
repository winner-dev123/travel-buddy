"""Job backoff, web cache revalidation rules, webhook signing and delivery (BL-1.09/1.25)."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import AppEnv
from app.core.time import FixedClock
from app.modules.platform.service import EventRouter, Job, PermanentJobError, backoff
from app.modules.web_cache import service as web_cache
from app.modules.web_cache.config import WebCacheSettings
from app.modules.web_cache.domain import revalidation_for, signature_header

SECRET = "s" * 40
URL = "https://web.example/api/revalidate"


def _settings(**overrides: object) -> WebCacheSettings:
    values: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "web_revalidate_url": URL,
        "web_revalidate_secret": SecretStr(SECRET),
    }
    values.update(overrides)
    return WebCacheSettings(_env_file=None, **values)  # type: ignore[call-arg]


def test_backoff_doubles_to_a_cap_and_spans_about_an_hour() -> None:
    delays = [backoff(n) for n in range(1, 10)]
    assert delays[:3] == [timedelta(seconds=15), timedelta(seconds=30), timedelta(seconds=60)]
    assert max(delays) == timedelta(minutes=15)
    assert timedelta(minutes=55) <= sum(delays, timedelta()) <= timedelta(minutes=70)
    with pytest.raises(ValueError, match="1-based"):
        backoff(0)


@pytest.mark.req("SAFE-012")
@pytest.mark.parametrize(
    ("event_type", "data", "expected"),
    [
        (
            "profile.updated",
            {"handle": "ana.new", "previous_handle": "ana.old", "changed": ["handle"]},
            (
                "profile_visibility_changed",
                ("profile:ana.new", "profile:ana.old", "stories", "sitemap"),
            ),
        ),
        (
            "profile.updated",
            {"handle": "ana", "changed": ["account_visibility", "bio"]},
            ("profile_visibility_changed", ("profile:ana", "stories", "sitemap")),
        ),
        ("profile.updated", {"handle": "ana", "changed": ["bio", "display_name"]}, None),
        (
            "privacy.updated",
            {"handle": "ana", "changed": ["search_engine_indexing"]},
            ("indexing_consent_changed", ("profile:ana", "stories", "sitemap")),
        ),
        (
            "privacy.updated",
            {"handle": "ana", "changed": ["profile_visibility", "search_engine_indexing"]},
            ("profile_visibility_changed", ("profile:ana", "stories", "sitemap")),
        ),
        ("discovery.disabled", {"user_id": "x"}, None),
        ("privacy.updated", {"handle": "ana", "changed": "not-a-list"}, None),
    ],
)
def test_revalidation_rules(
    event_type: str, data: dict[str, object], expected: tuple[str, tuple[str, ...]] | None
) -> None:
    decision = revalidation_for(event_type, data)
    if expected is None:
        assert decision is None
    else:
        assert decision is not None
        assert (decision.reason, decision.tags) == expected


@pytest.mark.security
def test_signature_matches_the_receiver_algorithm() -> None:
    body = b'{"event_id":"e"}'
    header = signature_header(b"secret", 1_700_000_000, body)
    expected = hmac.new(b"secret", b"1700000000." + body, hashlib.sha256).hexdigest()
    assert header == f"t=1700000000,v1={expected}"


@pytest.mark.security
def test_settings_require_a_strong_secret_and_https_outside_dev() -> None:
    assert not WebCacheSettings(_env_file=None, app_env=AppEnv.TEST).enabled  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="WEB_REVALIDATE_SECRET"):
        _settings(web_revalidate_secret=SecretStr("short"))
    with pytest.raises(ValidationError, match="https"):
        _settings(app_env=AppEnv.STAGING, web_revalidate_url="http://web.example/api/revalidate")


def test_subscriptions_only_when_enabled_and_relevant() -> None:
    router = EventRouter()
    web_cache.subscribe(router, WebCacheSettings(_env_file=None, app_env=AppEnv.TEST))  # type: ignore[call-arg]
    assert router.subscriptions_for("privacy.updated") == []

    router = EventRouter()
    web_cache.subscribe(router, _settings())
    [subscription] = router.subscriptions_for("privacy.updated")
    assert subscription.when({"handle": "a.b", "changed": ["search_engine_indexing"]})
    assert not subscription.when({"handle": "a.b", "changed": ["read_receipts_enabled"]})


def _job(data: dict[str, object] | None = None) -> Job:
    return Job(
        id=uuid.uuid4(),
        queue="default",
        kind=web_cache.JOB_KIND,
        payload={
            "event_id": "0190f5c2-0000-7000-8000-000000000001",
            "event_type": "privacy.updated",
            "occurred_at": "2026-11-09T12:00:00+00:00",
            "data": data or {"handle": "ana", "changed": ["search_engine_indexing"]},
        },
        attempts=1,
        max_attempts=10,
        request_id=None,
    )


async def _deliver(status: int, captured: list[httpx.Request]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status)

    clock = FixedClock(datetime(2026, 11, 9, 12, 0, 5, tzinfo=UTC))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await web_cache.make_handler(_settings(), client, clock)(_job())


@pytest.mark.req("SAFE-012")
async def test_delivery_sends_a_signed_contract_body() -> None:
    captured: list[httpx.Request] = []
    await _deliver(204, captured)
    [request] = captured
    assert str(request.url) == URL
    body = request.content
    assert json.loads(body) == {
        "event_id": "0190f5c2-0000-7000-8000-000000000001",
        "occurred_at": "2026-11-09T12:00:00+00:00",
        "reason": "indexing_consent_changed",
        "tags": ["profile:ana", "stories", "sitemap"],
    }
    timestamp = int(datetime(2026, 11, 9, 12, 0, 5, tzinfo=UTC).timestamp())
    assert request.headers["X-TB-Signature"] == signature_header(SECRET.encode(), timestamp, body)


@pytest.mark.parametrize("status", [401, 400, 404])
async def test_rejections_are_permanent(status: int) -> None:
    with pytest.raises(PermanentJobError):
        await _deliver(status, [])


@pytest.mark.parametrize("status", [500, 502, 429])
async def test_server_errors_and_throttling_are_retried(status: int) -> None:
    with pytest.raises(RuntimeError, match=str(status)):
        await _deliver(status, [])


async def test_irrelevant_jobs_send_nothing() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        handler = web_cache.make_handler(_settings(), client, FixedClock(datetime.now(tz=UTC)))
        await handler(_job({"handle": "ana", "changed": ["read_receipts_enabled"]}))
    assert captured == []
