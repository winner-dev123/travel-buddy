"""BL-6.10: every flagged feature answers ``403 feature_disabled`` (with ``feature_key``) while its
flag is off, before authentication, and gets past the flag check when it is on."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.feature_flags import Flag
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings

ID = str(uuid.uuid4())

# (flag, method, path, json body) — one or more representative routes per feature.
CASES: list[tuple[Flag, str, str, dict[str, Any] | None]] = [
    (Flag.CONNECTIONS, "GET", "/v1/connections", None),
    (Flag.TRAVELER_DISCOVERY, "GET", "/v1/travelers/discover", None),
    (Flag.TRAVEL_GROUPS, "GET", f"/v1/groups/{ID}", None),
    (Flag.TRAVEL_GROUPS, "GET", "/v1/users/me/group-invitations", None),
    (Flag.DIRECT_MESSAGES, "POST", "/v1/conversations", {"kind": "direct", "user_id": ID}),
    (Flag.GROUP_CHALLENGES, "GET", f"/v1/challenges/{ID}", None),
    (Flag.GROUP_CHALLENGES, "GET", "/v1/users/me/rewards", None),
    (Flag.TRIPS, "GET", "/v1/trips", None),
    (Flag.TRIPS, "GET", "/v1/users/me/saved-places", None),
    (Flag.GUIDES, "GET", f"/v1/guides/{ID}", None),
    (Flag.GUIDES, "GET", f"/v1/destinations/{ID}/audio-tours", None),
    (Flag.OFFLINE_PACKAGES, "GET", "/v1/users/me/offline-packages", None),
    (Flag.OFFLINE_PACKAGES, "GET", f"/v1/offline-packages/{ID}/manifest", None),
    (Flag.OFFLINE_PACKAGES, "GET", "/v1/offline-downloads/token/manifest.json", None),
    (Flag.BILLING, "GET", "/v1/billing/products", None),
    (Flag.BILLING, "POST", "/v1/billing/checkout-sessions", {}),
    (Flag.AI_ITINERARIES, "POST", "/v1/ai/itineraries/generate", {}),
    (Flag.AI_REPLANNING, "POST", f"/v1/ai/trips/{ID}/replan", {}),
    (Flag.POST_TRANSLATION, "GET", f"/v1/posts/{ID}/translation", None),
    (Flag.GUEST_BROWSING, "GET", "/v1/public/posts", None),
    (Flag.GUEST_BROWSING, "GET", f"/v1/public/posts/{ID}", None),
]


def _client(**flags: bool) -> Iterator[TestClient]:
    async def ok() -> bool:
        return True

    app = create_app(
        make_settings(feature_flags=flags),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture(scope="module")
def all_off() -> Iterator[TestClient]:
    yield from _client(**dict.fromkeys((flag.value for flag in Flag), False))


@pytest.fixture(scope="module")
def all_on() -> Iterator[TestClient]:
    yield from _client()


def _call(client: TestClient, method: str, path: str, body: dict[str, Any] | None) -> Any:
    return client.request(method, path, json=body)


@pytest.mark.parametrize(("flag", "method", "path", "body"), CASES)
def test_disabled_feature_answers_feature_disabled(
    all_off: TestClient, flag: Flag, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = _call(all_off, method, path, body)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "feature_disabled"
    assert response.json()["feature_key"] == flag.value


@pytest.mark.parametrize(("flag", "method", "path", "body"), CASES)
def test_enabled_feature_passes_the_flag_check(
    all_on: TestClient, flag: Flag, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = _call(all_on, method, path, body)
    assert response.status_code != 403 or response.json().get("code") != "feature_disabled"


def test_conversations_stay_reachable_while_either_messaging_feature_is_on() -> None:
    for flags, expect_disabled in (
        ({"direct_messages": False, "travel_groups": False}, True),
        ({"direct_messages": False, "travel_groups": True}, False),
        ({"direct_messages": True, "travel_groups": False}, False),
    ):
        for client in _client(**flags):
            response = client.get("/v1/conversations")
            disabled = response.status_code == 403 and response.json()["code"] == "feature_disabled"
            assert disabled is expect_disabled, (flags, response.text)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/billing/entitlements"),  # everyone has the free plan
        ("POST", "/v1/billing/webhooks/stripe"),  # store notifications are never refused
        ("POST", "/v1/billing/webhooks/apple"),
        ("GET", "/v1/destinations"),  # destinations are not behind a flag
    ],
)
def test_always_open_routes_ignore_the_flags(all_off: TestClient, method: str, path: str) -> None:
    response = all_off.request(method, path, content=b"{}")
    assert not (response.status_code == 403 and response.json().get("code") == "feature_disabled")
